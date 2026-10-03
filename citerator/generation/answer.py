"""End-to-end orchestration for the Citerator Ask screen."""

from __future__ import annotations

import time
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from citerator.config import Settings
from citerator.generation.citations import Citation, parse_citations
from citerator.generation.llm import LLMClient, get_llm_client
from citerator.generation.prompt import build_prompt
from citerator.retrieval.confidence import score_confidence
from citerator.retrieval.rerank import Reranker, rerank
from citerator.retrieval.search import RetrievedChunk, RetrievalFilters, search

logger = structlog.get_logger(__name__)


class AnswerResult(BaseModel):
    state: Literal["confident", "low_confidence", "insufficient"]
    answer: str | None
    confidence: float
    citations: list[Citation]
    related_passages: list[RetrievedChunk]
    escalation_draft: dict[str, Any] | None
    latency_ms: dict[str, float]
    tokens: dict[str, int | None] | None
    retrieval_details: list[dict[str, Any]] | None


def _retrieval_details(
    candidates: list[RetrievedChunk],
    reranked: list[RetrievedChunk],
    citations: list[Citation],
) -> list[dict[str, Any]]:
    cited_chunk_ids = {citation.chunk_id for citation in citations}
    rerank_by_id = {chunk.chunk_id: chunk.rerank_score for chunk in reranked}

    details: list[dict[str, Any]] = []
    for chunk in candidates:
        details.append(
            {
                "chunk_id": chunk.chunk_id,
                "doc_title": chunk.doc_title,
                "section_path": chunk.section_path,
                "source_file": chunk.source_file,
                "dense_score": chunk.dense_score,
                "sparse_score": chunk.sparse_score,
                "fused_score": chunk.fused_score,
                "rerank_score": rerank_by_id.get(chunk.chunk_id, chunk.rerank_score),
                "used_in_answer": chunk.chunk_id in cited_chunk_ids,
            }
        )
    return details


def answer_question(
    question: str,
    settings: Settings,
    filters: RetrievalFilters | None = None,
    *,
    client=None,
    embedder=None,
    sparse_embedder=None,
    reranker: Reranker | None = None,
    llm_client: LLMClient | None = None,
    show_retrieval_details: bool = False,
) -> AnswerResult:
    """Run retrieval, reranking, confidence scoring, generation, and citations."""

    total_start = time.perf_counter()
    logger.info("query_start", question=question)

    retrieve_start = time.perf_counter()
    candidates = search(
        question,
        settings,
        filters=filters,
        client=client,
        embedder=embedder,
        sparse_embedder=sparse_embedder,
    )
    retrieve_ms = (time.perf_counter() - retrieve_start) * 1000.0
    logger.info(
        "query_retrieved",
        count=len(candidates),
        duration_ms=round(retrieve_ms, 2),
    )

    rerank_start = time.perf_counter()
    reranked = rerank(question, candidates, settings, reranker=reranker)
    rerank_ms = (time.perf_counter() - rerank_start) * 1000.0
    logger.info(
        "query_reranked",
        count=len(reranked),
        duration_ms=round(rerank_ms, 2),
    )

    confidence = score_confidence(reranked, settings)
    logger.info(
        "query_confidence",
        state=confidence.state,
        confidence=round(confidence.confidence, 4),
    )

    latency: dict[str, float] = {
        "retrieve": round(retrieve_ms, 2),
        "rerank": round(rerank_ms, 2),
        "generate": 0.0,
        "total": 0.0,
    }

    if confidence.state == "insufficient":
        related = reranked if reranked else candidates
        related = related[: settings.top_k_rerank]

        latency["total"] = round((time.perf_counter() - total_start) * 1000.0, 2)
        return AnswerResult(
            state="insufficient",
            answer=None,
            confidence=confidence.confidence,
            citations=[],
            related_passages=related,
            escalation_draft={
                "question": question,
                "passages": [passage.model_dump() for passage in related],
                "suggested_note": (
                    "Insufficient confidence to answer automatically; "
                    "route to a compliance reviewer."
                ),
            },
            latency_ms=latency,
            tokens=None,
            retrieval_details=_retrieval_details(candidates, reranked, [])
            if show_retrieval_details
            else None,
        )

    generate_start = time.perf_counter()
    system, user = build_prompt(question, reranked)
    llm = llm_client or get_llm_client(settings)
    response = llm.complete(system, user)
    generate_ms = (time.perf_counter() - generate_start) * 1000.0
    logger.info("query_generated", duration_ms=round(generate_ms, 2))

    citations = parse_citations(response.text, reranked)
    logger.info("query_citations_verified", citations=len(citations))

    escalation_draft = None
    if confidence.state != "confident":
        escalation_draft = {
            "question": question,
            "passages": [passage.model_dump() for passage in reranked],
            "suggested_note": (
                "Low confidence answer; verify citations before relying on it."
            ),
        }

    latency["generate"] = round(generate_ms, 2)
    latency["total"] = round((time.perf_counter() - total_start) * 1000.0, 2)

    return AnswerResult(
        state=confidence.state,
        answer=response.text,
        confidence=confidence.confidence,
        citations=citations,
        related_passages=[],
        escalation_draft=escalation_draft,
        latency_ms=latency,
        tokens={
            "input": response.input_tokens,
            "output": response.output_tokens,
        },
        retrieval_details=_retrieval_details(candidates, reranked, citations)
        if show_retrieval_details
        else None,
    )