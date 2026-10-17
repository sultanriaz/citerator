"""Cross-encoder reranking for retrieved Citerator chunks."""

from __future__ import annotations

from typing import Any, Protocol

import structlog

from citerator.config import Settings
from citerator.retrieval.search import RetrievedChunk

logger = structlog.get_logger(__name__)


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]:
        ...


class CrossEncoderReranker:
    """Thin wrapper around sentence-transformers ``CrossEncoder``."""

    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name)

    def score(self, query: str, texts: list[str]) -> list[float]:
        pairs = [(query, text) for text in texts]
        scores = self.model.predict(pairs)
        return [float(score) for score in scores]


class FakeReranker:
    """Deterministic offline reranker for tests.

    ``scores`` maps a substring to a score. The first matching substring wins.
    Unmatched texts receive ``0.0``.
    """

    def __init__(self, scores: dict[str, float] | None = None):
        self.scores = scores or {}

    def score(self, query: str, texts: list[str]) -> list[float]:
        output: list[float] = []
        for text in texts:
            value = 0.0
            for needle, score in self.scores.items():
                if needle in text:
                    value = score
                    break
            output.append(value)
        return output


def rerank(
    query: str,
    candidates: list[RetrievedChunk],
    settings: Settings,
    reranker: Reranker | None = None,
    *,
    tenant: Any | None = None,
) -> list[RetrievedChunk]:
    """Score, sort, and truncate candidates to ``settings.top_k_rerank``."""

    if not candidates:
        return []

    # Tenant boundary authorization before reranking
    if tenant is not None:
        effective_tenant = getattr(tenant, "tenant_id", "global") or "global"
        is_admin = getattr(tenant, "is_admin", False)
        user_id = getattr(tenant, "user_id", None)
        allowed = {effective_tenant, "global"} if effective_tenant != "*" else None

        authorized_candidates: list[RetrievedChunk] = []
        for c in candidates:
            c_tenant = getattr(c, "tenant_id", "global") or "global"
            c_vis = getattr(c, "visibility", "tenant") or "tenant"
            c_owner = getattr(c, "owner_id", None)

            if not is_admin and allowed and c_tenant not in allowed:
                logger.warning(
                    "rerank_dropped_cross_tenant_candidate",
                    chunk_id=c.chunk_id,
                    chunk_tenant=c_tenant,
                    authorized_tenant=effective_tenant,
                )
                continue
            if not is_admin and c_vis == "private" and c_owner != user_id:
                logger.warning(
                    "rerank_dropped_private_candidate",
                    chunk_id=c.chunk_id,
                    owner=c_owner,
                )
                continue
            authorized_candidates.append(c)
        candidates = authorized_candidates

    if not candidates:
        return []

    reranker = reranker or CrossEncoderReranker(settings.rerank_model)
    texts = [candidate.text for candidate in candidates]
    scores = reranker.score(query, texts)

    if len(scores) != len(candidates):
        raise ValueError(
            f"Reranker returned {len(scores)} scores for {len(candidates)} candidates"
        )

    scored = list(zip(candidates, scores))
    scored.sort(key=lambda pair: pair[1], reverse=True)

    reranked = [
        candidate.model_copy(update={"rerank_score": float(score)})
        for candidate, score in scored[: settings.top_k_rerank]
    ]

    logger.info(
        "reranked",
        candidates=len(candidates),
        kept=len(reranked),
        top_score=reranked[0].rerank_score if reranked else None,
    )
    return reranked