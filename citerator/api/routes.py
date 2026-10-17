"""HTTP routes for Citerator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from citerator.api.deps import require_api_key
from citerator.api.schemas import HealthResponse, QueryRequest
from citerator.config import Settings, get_settings
from citerator.generation.answer import AnswerResult, answer_question
from citerator.ingestion.store import make_client
from citerator.retrieval.confidence import ConfidenceResult
from citerator.retrieval.search import RetrievalFilters, RetrievedChunk

router = APIRouter()


def _build_answer_result(
    *,
    question: str,
    settings: Settings,
    confidence: ConfidenceResult,
    reranked: list[RetrievedChunk],
    answer_text: str | None,
    citations: list,
    tokens: dict[str, int | None] | None,
    latency: dict[str, float],
    retrieval_details_enabled: bool,
) -> AnswerResult:
    escalation_draft = None
    related: list[RetrievedChunk] = []
    if confidence.state == "insufficient":
        related = reranked[: settings.top_k_rerank]
        escalation_draft = {
            "question": question,
            "passages": [p.model_dump() for p in related],
            "suggested_note": (
                "Insufficient confidence to answer automatically; "
                "route to a compliance reviewer."
            ),
        }
    elif confidence.state == "low_confidence":
        escalation_draft = {
            "question": question,
            "passages": [p.model_dump() for p in reranked],
            "suggested_note": (
                "Low confidence answer; verify citations before relying on it."
            ),
        }

    retrieval_details = None
    if retrieval_details_enabled:
        cited_ids = {c.chunk_id for c in citations}
        retrieval_details = [
            {
                "chunk_id": c.chunk_id,
                "doc_title": c.doc_title,
                "section_path": c.section_path,
                "source_file": c.source_file,
                "dense_score": c.dense_score,
                "sparse_score": c.sparse_score,
                "fused_score": c.fused_score,
                "rerank_score": c.rerank_score,
                "used_in_answer": c.chunk_id in cited_ids,
            }
            for c in reranked
        ]

    return AnswerResult(
        state=confidence.state,
        answer=answer_text,
        confidence=confidence.confidence,
        citations=citations,
        related_passages=related if confidence.state == "insufficient" else [],
        escalation_draft=escalation_draft,
        latency_ms=latency,
        tokens=tokens,
        retrieval_details=retrieval_details,
    )


@router.post("/query", response_model=AnswerResult)
def query(
    request: QueryRequest,
    settings: Settings = Depends(get_settings),
    tenant: Any = Depends(require_api_key),
) -> AnswerResult:
    from citerator.cache import get_cache

    cache = get_cache(settings)

    tenant_id = getattr(tenant, "tenant_id", None)
    is_admin = getattr(tenant, "is_admin", False)

    if request.tenant_id and not is_admin and tenant_id and request.tenant_id != tenant_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Cross-tenant query forbidden: cannot query tenant '{request.tenant_id}'",
        )

    effective_tenant_id = request.tenant_id if (is_admin and request.tenant_id) else tenant_id

    if cache is not None and not request.show_retrieval_details:
        cached = cache.lookup(
            request.question,
            document_scope=request.document_scope,
            jurisdiction=request.jurisdiction,
            tenant=effective_tenant_id,
        )
        if cached is not None:
            try:
                return AnswerResult.model_validate(cached)
            except Exception:
                pass

    filters = None
    if request.document_scope or request.jurisdiction or effective_tenant_id:
        filters = RetrievalFilters(
            document_scope=request.document_scope,
            jurisdiction=request.jurisdiction,
            tenant_id=effective_tenant_id,
        )

    result = answer_question(
        question=request.question,
        settings=settings,
        filters=filters,
        tenant=tenant,
        show_retrieval_details=request.show_retrieval_details,
    )

    if cache is not None and not request.show_retrieval_details:
        try:
            cache.store(
                request.question,
                result.model_dump(),
                document_scope=request.document_scope,
                jurisdiction=request.jurisdiction,
                tenant=effective_tenant_id,
            )
        except Exception:
            pass

    return result


@router.post("/settings/cache/purge")
def purge_cache(
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, int]:
    from citerator.cache import get_cache

    cache = get_cache(settings)
    if cache is None:
        return {"purged": 0}
    return {"purged": cache.purge()}


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    collections: dict[str, int] = {}
    try:
        client = make_client(settings.qdrant_url)
        for collection in client.get_collections().collections:
            collections[collection.name] = client.count(collection.name).count
    except Exception:
        collections = {}

    return HealthResponse(status="ok", collections=collections)