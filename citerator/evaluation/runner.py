"""Run orchestration for the evaluation harness.

Reads the run row's per-run overrides, drives retrieval -> rerank ->
confidence -> (optional) generation -> citations -> Ragas scoring per question,
and writes both per-question results and aggregates back through the store.

Never mutates global Settings: overrides are applied via model_copy. All
errors -- at the question level and the run level -- are captured and made
queryable rather than raised out of the background task.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path
from typing import Any

import structlog

from citerator.config import Settings
from citerator.evaluation.questions import load_questions
from citerator.evaluation.ragas_scorer import (
    FakeRagasScorer,
    RagasScorer,
    RagasScores,
    RealRagasScorer,
)
from citerator.generation.citations import parse_citations
from citerator.generation.llm import LLMClient, get_llm_client
from citerator.generation.prompt import build_prompt
from citerator.ingestion.embedding import get_embedder, get_sparse_embedder
from citerator.ingestion.store import make_client
from citerator.retrieval.confidence import score_confidence
from citerator.retrieval.rerank import CrossEncoderReranker, Reranker, rerank
from citerator.retrieval.search import search

logger = structlog.get_logger(__name__)


def _apply_run_overrides(settings: Settings, run: dict[str, Any]) -> Settings:
    overrides: dict[str, Any] = {}

    if run.get("chunking_strategy"):
        overrides["active_chunking_strategy"] = run["chunking_strategy"]
    for key in (
        "top_k_retrieve",
        "top_k_rerank",
        "confidence_threshold",
        "confidence_floor",
    ):
        if run.get(key) is not None:
            overrides[key] = run[key]

    return settings.model_copy(update=overrides) if overrides else settings


def _compute_cost(
    tokens_in: int | None,
    tokens_out: int | None,
    settings: Settings,
) -> float | None:
    price_in = settings.llm_price_per_million_input_tokens
    price_out = settings.llm_price_per_million_output_tokens
    if price_in is None or price_out is None:
        return None
    if tokens_in is None and tokens_out is None:
        return None
    return (
        (tokens_in or 0) * price_in + (tokens_out or 0) * price_out
    ) / 1_000_000.0


def _mean(values: list[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return sum(kept) / len(kept) if kept else None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round(pct * (len(ordered) - 1)))
    idx = max(0, min(idx, len(ordered) - 1))
    return ordered[idx]


def _pct_passed(results: list[dict[str, Any]]) -> float | None:
    if not results:
        return None
    return 100.0 * sum(1 for r in results if r.get("passed")) / len(results)


def _compute_aggregates(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]

    refuse = [r for r in results if r.get("category") == "out_of_corpus"]
    if not refuse:
        refuse = [r for r in results if r.get("expected_behavior") == "refuse"]

    escalate = [r for r in results if r.get("category") == "underspecified"]
    if not escalate:
        escalate = [
            r for r in results if r.get("expected_behavior") == "clarify_or_escalate"
        ]

    return {
        "faithfulness_mean": _mean([r.get("faithfulness") for r in results]),
        "answer_relevancy_mean": _mean([r.get("answer_relevancy") for r in results]),
        "context_precision_mean": _mean([r.get("context_precision") for r in results]),
        "context_recall_mean": _mean([r.get("context_recall") for r in results]),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "cost_per_query_usd_mean": _mean([r.get("cost_usd") for r in results]),
        "safety_refuse_pct": _pct_passed(refuse),
        "safety_escalate_pct": _pct_passed(escalate),
    }


async def run_evaluation(
    run_id: str,
    settings: Settings,
    store,
    *,
    client=None,
    scorer: RagasScorer | None = None,
    reranker: Reranker | None = None,
    llm_client: LLMClient | None = None,
) -> None:
    """Execute a full evaluation run. Never raises out of the caller."""

    try:
        run = store.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        run_settings = _apply_run_overrides(settings, run)

        questions = load_questions(Path(run_settings.eval_questions_path))
        store.update_run(run_id, question_count=len(questions))

        scorer = scorer or RealRagasScorer(run_settings)
        reranker = reranker or CrossEncoderReranker(run_settings.rerank_model)
        llm_client = llm_client or get_llm_client(run_settings)

        embedder = get_embedder(
            run_settings.embedder_kind, run_settings.embedding_model or None
        )
        sparse = get_sparse_embedder(run_settings.sparse_kind)
        if client is None:
            client = make_client(run_settings.qdrant_url)

        logger.info(
            "eval_run_start",
            run_id=run_id,
            question_count=len(questions),
            collection_strategy=run_settings.active_chunking_strategy,
        )

        for i, q in enumerate(questions):
            started = time.perf_counter()

            try:
                candidates = search(
                    q.question,
                    run_settings,
                    client=client,
                    embedder=embedder,
                    sparse_embedder=sparse,
                )
                reranked = rerank(
                    q.question, candidates, run_settings, reranker=reranker
                )
                confidence = score_confidence(reranked, run_settings)

                answer_text: str | None = None
                tokens_in: int | None = None
                tokens_out: int | None = None
                citations: list = []

                if confidence.state != "insufficient":
                    system, user = build_prompt(q.question, reranked)
                    response = llm_client.complete(system, user)
                    answer_text = response.text
                    tokens_in = response.input_tokens
                    tokens_out = response.output_tokens
                    citations = parse_citations(answer_text, reranked)

                latency_ms = (time.perf_counter() - started) * 1000.0

                if answer_text is not None:
                    contexts = [c.text for c in reranked]
                    scores: RagasScores = scorer.score(
                        q.question, answer_text, contexts, q.ground_truth
                    )
                else:
                    scores = RagasScores(None, None, None, None)

                expected = q.expected_behavior
                if expected == "refuse":
                    passed = confidence.state == "insufficient"
                elif expected == "clarify_or_escalate":
                    passed = confidence.state != "confident"
                elif expected == "answer":
                    passed = confidence.state == "confident"
                else:
                    passed = False

                cost = _compute_cost(tokens_in, tokens_out, run_settings)

                store.add_question_result(
                    run_id,
                    question=q.question,
                    category=q.category,
                    expected_behavior=expected,
                    ground_truth=q.ground_truth,
                    state=confidence.state,
                    passed=passed,
                    faithfulness=scores.faithfulness,
                    answer_relevancy=scores.answer_relevancy,
                    context_precision=scores.context_precision,
                    context_recall=scores.context_recall,
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    answer_text=answer_text,
                    retrieved_chunk_ids=[c.chunk_id for c in reranked],
                    cited_chunk_ids=[c.chunk_id for c in citations],
                    error=None,
                )
            except Exception as exc:
                logger.warning(
                    "eval_question_failed",
                    run_id=run_id,
                    question=q.question,
                    error=str(exc),
                )
                store.add_question_result(
                    run_id,
                    question=q.question,
                    category=q.category,
                    expected_behavior=q.expected_behavior,
                    ground_truth=q.ground_truth,
                    state="insufficient",
                    passed=False,
                    error=str(exc),
                )

            store.update_run(run_id, questions_completed=i + 1)

        results = store.list_question_results(run_id)
        aggregates = _compute_aggregates(results)
        store.update_run(run_id, status="completed", **aggregates)

        logger.info("eval_run_completed", run_id=run_id, **{
            k: v for k, v in aggregates.items() if v is not None
        })

    except Exception as exc:
        logger.warning("eval_run_failed", run_id=run_id, error=str(exc))
        try:
            store.update_run(run_id, status="failed", error=str(exc))
        except Exception:
            pass
