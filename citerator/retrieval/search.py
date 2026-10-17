"""Hybrid Qdrant retrieval for the Citerator Ask screen.

The active collection is resolved from the same naming convention used during
Phase 2 ingestion. Hybrid retrieval is performed in a single Qdrant
``query_points`` call with dense and sparse prefetches fused by RRF. If the
collection was built without sparse vectors, the function degrades to dense-only
retrieval and logs a warning instead of failing.
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from qdrant_client import QdrantClient, models

from citerator.config import Settings
from citerator.ingestion.embedding import (
    DenseEmbedder,
    SparseEmbedder,
    get_embedder,
    get_sparse_embedder,
)
from citerator.ingestion.store import DENSE, SPARSE, collection_name, make_client

logger = structlog.get_logger(__name__)


class RetrievalFilters(BaseModel):
    """Optional payload filters exposed by the Ask screen."""

    doc_id: str | None = None
    source_file: str | None = None
    doc_type: str | None = None
    jurisdiction: str | None = None
    document_scope: list[str] | None = None
    tenant_id: str | None = None
    owner_id: str | None = None


class RetrievedChunk(BaseModel):
    """A Qdrant payload plus retrieval scores.

    Payloads are produced by Phase 2 as ``Chunk.model_dump(exclude={"embed_text"})``
    plus ``embedding_model`` and ``ingested_at``. Extra fields are allowed so this
    model remains forward-compatible with additive payload changes.
    """

    model_config = ConfigDict(extra="allow")

    chunk_id: str
    doc_id: str
    doc_hash: str
    source_file: str
    doc_title: str
    doc_type: str
    jurisdiction: str | None = None
    effective_date: str | None = None
    tenant_id: str | None = "global"
    owner_id: str | None = None
    visibility: str | None = "tenant"
    section_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    char_start: int
    char_end: int
    text: str
    token_count: int
    embed_token_count: int
    chunk_index: int
    chunker: str
    chunker_params: dict[str, Any] = Field(default_factory=dict)
    embedding_model: str | None = None
    ingested_at: str | None = None

    fused_score: float | None = None
    dense_score: float | None = None
    sparse_score: float | None = None
    rank: int | None = None
    rerank_score: float | None = None


def _build_filter(
    filters: RetrievalFilters | None = None,
    tenant: Any | None = None,
) -> models.Filter | None:
    must: list[models.Condition] = []

    # 1. Enforce Tenant Boundary & Document Ownership
    if tenant is not None:
        tenant_id = getattr(tenant, "tenant_id", None) or "global"
        is_admin = getattr(tenant, "is_admin", False)
        user_id = getattr(tenant, "user_id", None)

        target_tenant = (filters and filters.tenant_id) or tenant_id
        if not is_admin or target_tenant != "*":
            must.append(
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchAny(any=[target_tenant, "global"]),
                )
            )

        if not is_admin:
            should_conds: list[models.Condition] = [
                models.FieldCondition(key="visibility", match=models.MatchValue(value="tenant")),
                models.FieldCondition(key="visibility", match=models.MatchValue(value="public")),
            ]
            if user_id:
                should_conds.append(
                    models.FieldCondition(key="owner_id", match=models.MatchValue(value=user_id))
                )
            must.append(models.Filter(should=should_conds))
    elif filters and filters.tenant_id and filters.tenant_id != "*":
        must.append(
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchAny(any=[filters.tenant_id, "global"]),
            )
        )
        must.append(
            models.FieldCondition(key="visibility", match=models.MatchAny(any=["tenant", "public"]))
        )
    else:
        # Default-deny: When tenant context is absent, only public global documents can be retrieved
        must.append(
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value="global"),
            )
        )
        must.append(
            models.FieldCondition(
                key="visibility",
                match=models.MatchValue(value="public"),
            )
        )

    # 2. Add caller filters
    if filters:
        if filters.doc_id:
            must.append(
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=filters.doc_id))
            )
        if filters.source_file:
            must.append(
                models.FieldCondition(
                    key="source_file",
                    match=models.MatchValue(value=filters.source_file),
                )
            )
        if filters.doc_type:
            must.append(
                models.FieldCondition(
                    key="doc_type",
                    match=models.MatchValue(value=filters.doc_type),
                )
            )
        if filters.jurisdiction:
            must.append(
                models.FieldCondition(
                    key="jurisdiction",
                    match=models.MatchValue(value=filters.jurisdiction),
                )
            )
        if filters.document_scope:
            must.append(
                models.FieldCondition(
                    key="source_file",
                    match=models.MatchAny(any=filters.document_scope),
                )
            )

    return models.Filter(must=must) if must else None


def _has_sparse_vectors(client: QdrantClient, collection: str) -> bool:
    info = client.get_collection(collection)
    params = info.config.params
    sparse_vectors = getattr(params, "sparse_vectors", None)
    return bool(sparse_vectors and SPARSE in sparse_vectors)


def search(
    question: str,
    settings: Settings,
    filters: RetrievalFilters | None = None,
    *,
    tenant: Any | None = None,
    client: QdrantClient | None = None,
    embedder: DenseEmbedder | None = None,
    sparse_embedder: SparseEmbedder | None = None,
) -> list[RetrievedChunk]:
    """Retrieve the top candidates for ``question``.

    Returns a list of typed ``RetrievedChunk`` objects ordered by Qdrant fusion
    score. The caller is responsible for reranking.
    """

    embedder = embedder or get_embedder(settings.embedder_kind, settings.embedding_model or None)
    collection = collection_name(settings.active_chunking_strategy, embedder.name)
    client = client or make_client(settings.qdrant_url)
    query_filter = _build_filter(filters, tenant=tenant)

    dense_vector = embedder.embed_query(question).tolist()

    sparse_embedder = sparse_embedder if sparse_embedder is not None else get_sparse_embedder(
        settings.sparse_kind
    )

    use_sparse = sparse_embedder is not None and _has_sparse_vectors(client, collection)

    if not use_sparse:
        if sparse_embedder is not None:
            logger.warning(
                "collection_has_no_sparse_vectors",
                collection=collection,
                fallback="dense_only",
            )
        response = client.query_points(
            collection_name=collection,
            query=dense_vector,
            using=DENSE,
            query_filter=query_filter,
            limit=settings.top_k_retrieve,
            with_payload=True,
        )
    else:
        sparse_vector = sparse_embedder.embed_query(question)
        prefetch = [
            models.Prefetch(
                query=dense_vector,
                using=DENSE,
                limit=settings.top_k_retrieve,
                filter=query_filter,
            ),
            models.Prefetch(
                query=models.SparseVector(
                    indices=sparse_vector.indices,
                    values=sparse_vector.values,
                ),
                using=SPARSE,
                limit=settings.top_k_retrieve,
                filter=query_filter,
            ),
        ]
        response = client.query_points(
            collection_name=collection,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=query_filter,
            limit=settings.top_k_retrieve,
            with_payload=True,
        )

    effective_tenant = getattr(tenant, "tenant_id", None) or (filters and filters.tenant_id)
    is_admin = getattr(tenant, "is_admin", False)
    user_id = getattr(tenant, "user_id", None)
    allowed_tenants = {effective_tenant, "global"} if (effective_tenant and effective_tenant != "*") else {"global"}

    chunks: list[RetrievedChunk] = []
    for rank, point in enumerate(response.points, start=1):
        payload = dict(point.payload or {})
        p_tenant = payload.get("tenant_id") or "global"
        p_vis = payload.get("visibility") or "tenant"
        p_owner = payload.get("owner_id")

        # Post-retrieval defense-in-depth: drop foreign or unauthorized private chunks
        if not is_admin and p_tenant not in allowed_tenants:
            logger.warning("dropped_cross_tenant_chunk_post_retrieval", point_id=point.id, tenant=p_tenant)
            continue
        if not is_admin and p_vis == "private" and p_owner != user_id:
            logger.warning("dropped_private_chunk_post_retrieval", point_id=point.id, owner=p_owner)
            continue

        score = float(point.score) if point.score is not None else None
        chunk = RetrievedChunk(
            **payload,
            rank=rank,
            fused_score=score,
        )
        if not use_sparse:
            chunk.dense_score = score
        chunks.append(chunk)

    return chunks