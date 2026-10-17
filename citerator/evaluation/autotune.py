"""Threshold auto-tuning for confidence gating.

Sweeps CONFIDENCE_THRESHOLD across a range, scores each candidate against
the labelled question set, and returns the one that maximizes a weighted
objective. Uses ONLY retrieval + rerank + confidence banding -- no LLM
calls, no Ragas, no eval runs. Fast enough to run on every deploy.

Objective (weighted sum of three components, each in [0, 1]):

    safety_refuse_pct      fraction of out_of_corpus questions that end
                           in state=insufficient. Must be ~1.0 in
                           production; failing this means the pipeline
                           answered when it should have refused.
    safety_escalate_pct    fraction of underspecified questions that do
                           NOT end in state=confident. A confident answer
                           to a vague question is a specific kind of harm.
    answer_rate            fraction of lookup/multi_document questions
                           that DO end in state=confident. This is the
                           "usefulness" side of the tradeoff; without it
                           the optimal threshold is trivially 0.99.

Default weights (0.40 / 0.30 / 0.30) prioritise safety, then balance
escalation and coverage. Override with AutotuneConfig if your priorities
differ.

The confidence banding here uses the same _normalize() as production, so a
fitted calibration (Loop 1) is respected -- the threshold that wins here
is the threshold that wins on real queries.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class AutotuneConfig:
    min_threshold: float = 0.30
    max_threshold: float = 0.95
    step: float = 0.02
    weight_safety_refuse: float = 0.40
    weight_safety_escalate: float = 0.30
    weight_answer_rate: float = 0.30
    min_safety_refuse: float = 1.00   # hard floor -- results below are rejected
    min_safety_escalate: float = 0.60
    confidence_floor: float = 0.15


@dataclass
class ThresholdResult:
    threshold: float
    safety_refuse_pct: float
    safety_escalate_pct: float
    answer_rate: float
    score: float
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class AutotuneResult:
    best: ThresholdResult
    sweep: list[ThresholdResult]
    evaluated_at: str
    question_count: int
    config: dict[str, Any]
    notes: list[str] = field(default_factory=list)


def _classify(question_state: str, category: str, expected: str) -> str:
    """Reduce (state, category) to a scoring bucket."""

    if category == "out_of_corpus" or expected == "refuse":
        return "out_of_corpus"
    if category == "underspecified" or expected == "clarify_or_escalate":
        return "underspecified"
    return "answer"


def _score_at_threshold(
    per_question: list[dict[str, Any]],
    threshold: float,
    floor: float,
) -> ThresholdResult:
    """Re-band cached (raw_score, category, expected) rows under a candidate
    threshold and compute the three components plus the weighted objective."""

    from citerator.retrieval.confidence import _normalize

    buckets = {"out_of_corpus": [], "underspecified": [], "answer": []}

    for row in per_question:
        confidence = _normalize(row["raw_score"])
        if confidence >= threshold:
            state = "confident"
        elif confidence >= floor:
            state = "low_confidence"
        else:
            state = "insufficient"
        buckets[row["bucket"]].append(state)

    def frac(states: list[str], predicate) -> float:
        if not states:
            return 1.0  # empty category = vacuously satisfied
        return sum(1 for s in states if predicate(s)) / len(states)

    safety_refuse = frac(buckets["out_of_corpus"], lambda s: s == "insufficient")
    safety_escalate = frac(buckets["underspecified"], lambda s: s != "confident")
    answer_rate = frac(buckets["answer"], lambda s: s == "confident")

    score = (
        0.40 * safety_refuse
        + 0.30 * safety_escalate
        + 0.30 * answer_rate
    )

    return ThresholdResult(
        threshold=threshold,
        safety_refuse_pct=safety_refuse,
        safety_escalate_pct=safety_escalate,
        answer_rate=answer_rate,
        score=score,
        counts={
            "out_of_corpus": len(buckets["out_of_corpus"]),
            "underspecified": len(buckets["underspecified"]),
            "answer": len(buckets["answer"]),
        },
    )


def _collect_raw_scores(settings: Any) -> list[dict[str, Any]]:
    """Run retrieval + rerank for each question, return rows for the sweep.

    No LLM, no Ragas. Warm cache: ~1-2s per question on CPU.
    """

    from citerator.evaluation.questions import load_questions
    from citerator.ingestion.embedding import get_embedder, get_sparse_embedder
    from citerator.ingestion.store import make_client
    from citerator.retrieval.rerank import CrossEncoderReranker, rerank
    from citerator.retrieval.search import search

    questions = load_questions(Path(settings.eval_questions_path))
    embedder = get_embedder(
        settings.embedder_kind, settings.embedding_model or None
    )
    sparse = get_sparse_embedder(settings.sparse_kind)
    client = make_client(settings.qdrant_url)
    reranker = CrossEncoderReranker(settings.rerank_model)

    rows: list[dict[str, Any]] = []
    for q in questions:
        try:
            candidates = search(
                q.question,
                settings,
                client=client,
                embedder=embedder,
                sparse_embedder=sparse,
            )
            reranked = rerank(
                q.question, candidates, settings, reranker=reranker
            )
            raw_score = (
                float(reranked[0].rerank_score)
                if reranked and reranked[0].rerank_score is not None
                else -20.0
            )
            rows.append(
                {
                    "question": q.question,
                    "raw_score": raw_score,
                    "bucket": _classify(
                        q.category, q.category, q.expected_behavior
                    ),
                    "category": q.category,
                }
            )
        except Exception as exc:
            logger.warning(
                "autotune_score_failed",
                question=q.question,
                error=str(exc),
            )
    return rows


def autotune(
    settings: Any,
    config: AutotuneConfig | None = None,
    *,
    apply: bool = False,
) -> AutotuneResult:
    """Sweep confidence thresholds, return the best, optionally persist it."""

    cfg = config or AutotuneConfig()
    if config is None:
        try:
            cfg = AutotuneConfig(
                min_threshold=cfg.min_threshold,
                max_threshold=cfg.max_threshold,
                step=cfg.step,
                weight_safety_refuse=cfg.weight_safety_refuse,
                weight_safety_escalate=cfg.weight_safety_escalate,
                weight_answer_rate=cfg.weight_answer_rate,
                min_safety_refuse=cfg.min_safety_refuse,
                min_safety_escalate=cfg.min_safety_escalate,
                confidence_floor=getattr(settings, "confidence_floor", cfg.confidence_floor),
            )
        except Exception:
            pass
    per_question = _collect_raw_scores(settings)
    if not per_question:
        raise ValueError("no questions scored; check the eval question set")

    thresholds: list[float] = []
    t = cfg.min_threshold
    while t <= cfg.max_threshold + 1e-9:
        thresholds.append(round(t, 4))
        t += cfg.step

    sweep: list[ThresholdResult] = []
    notes: list[str] = []

    for threshold in thresholds:
        r = _score_at_threshold(per_question, threshold, cfg.confidence_floor)
        r.score = (
            cfg.weight_safety_refuse * r.safety_refuse_pct
            + cfg.weight_safety_escalate * r.safety_escalate_pct
            + cfg.weight_answer_rate * r.answer_rate
        )
        sweep.append(r)

    # Apply the hard floors first. If no threshold satisfies them, take the
    # best-scoring threshold that gets closest, and record why.
    eligible = [
        r
        for r in sweep
        if r.safety_refuse_pct >= cfg.min_safety_refuse
        and r.safety_escalate_pct >= cfg.min_safety_escalate
    ]

    if not eligible:
        best = max(sweep, key=lambda r: r.score)
        notes.append(
            "No threshold satisfied both safety floors "
            f"(refuse >= {cfg.min_safety_refuse:.2f}, "
            f"escalate >= {cfg.min_safety_escalate:.2f}). "
            "Fell back to raw weighted score. Add harder eval questions "
            "or review calibration."
        )
    else:
        best = max(eligible, key=lambda r: r.score)

    result = AutotuneResult(
        best=best,
        sweep=sweep,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        question_count=len(per_question),
        config=asdict(cfg),
        notes=notes,
    )

    if apply:
        from citerator.runtime_config import overrides as overrides_store

        overrides_store.set_overrides(
            {"confidence_threshold": best.threshold}
        )
        logger.info(
            "autotune_applied",
            threshold=best.threshold,
            score=round(best.score, 4),
            safety_refuse=round(best.safety_refuse_pct, 3),
            safety_escalate=round(best.safety_escalate_pct, 3),
            answer_rate=round(best.answer_rate, 3),
        )

    return result


def save_report(
    result: AutotuneResult, path: Path | None = None
) -> Path:
    p = path or Path("data/processed/autotune.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "best": asdict(result.best),
                "sweep": [asdict(r) for r in result.sweep],
                "evaluated_at": result.evaluated_at,
                "question_count": result.question_count,
                "config": result.config,
                "notes": result.notes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return p


if __name__ == "__main__":
    import argparse

    from citerator.config import get_settings

    parser = argparse.ArgumentParser(
        description="Auto-tune confidence_threshold against the eval set."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the winning threshold through runtime overrides.",
    )
    parser.add_argument("--min", type=float, default=0.30)
    parser.add_argument("--max", type=float, default=0.95)
    parser.add_argument("--step", type=float, default=0.02)
    args = parser.parse_args()

    _settings = get_settings()
    cfg = AutotuneConfig(
        min_threshold=args.min,
        max_threshold=args.max,
        step=args.step,
        confidence_floor=_settings.confidence_floor,
    )
    result = autotune(get_settings(), cfg, apply=args.apply)
    report_path = save_report(result)

    b = result.best
    print()
    print(f"Best threshold      = {b.threshold:.2f}")
    print(f"  score             = {b.score:.4f}")
    print(f"  safety_refuse     = {b.safety_refuse_pct:.3f}")
    print(f"  safety_escalate   = {b.safety_escalate_pct:.3f}")
    print(f"  answer_rate       = {b.answer_rate:.3f}")
    print(f"  evaluated over {result.question_count} questions")
    if args.apply:
        print("  -> persisted via runtime_config; effective immediately")
    else:
        print("  (dry run -- pass --apply to persist)")
    print(f"Report: {report_path.as_posix()}")
    for note in result.notes:
        print(f"  note: {note}")