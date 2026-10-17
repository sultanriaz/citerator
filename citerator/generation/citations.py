"""Citation parsing and validation for generated answers."""

from __future__ import annotations

import re
from typing import Any

import structlog
from pydantic import BaseModel

from citerator.retrieval.search import RetrievedChunk

logger = structlog.get_logger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")


class Citation(BaseModel):
    chunk_id: str
    doc_title: str
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    source_file: str
    excerpt: str


def _excerpt(text: str, limit: int = 240) -> str:
    clean = " ".join(text.split())
    return clean[:limit] + ("..." if len(clean) > limit else "")


def parse_citations(
    answer: str,
    chunks: list[RetrievedChunk],
    *,
    tenant: Any | None = None,
) -> list[Citation]:
    """Map valid ``[n]`` markers to chunks.

    Out-of-range markers are dropped and logged. The function never raises for a
    malformed citation marker.
    """

    citations: list[Citation] = []
    seen: set[int] = set()

    effective_tenant = getattr(tenant, "tenant_id", None) if tenant else None
    is_admin = getattr(tenant, "is_admin", False) if tenant else False
    allowed = {effective_tenant, "global"} if (effective_tenant and effective_tenant != "*") else None

    for match in _CITATION_RE.finditer(answer or ""):
        marker = int(match.group(1))

        if marker in seen:
            continue
        if marker < 1 or marker > len(chunks):
            logger.warning(
                "citation_out_of_range",
                marker=marker,
                available=len(chunks),
            )
            continue

        chunk = chunks[marker - 1]
        c_tenant = getattr(chunk, "tenant_id", "global") or "global"

        # Citation resolution authorization:
        if not is_admin and allowed and c_tenant not in allowed:
            logger.warning(
                "citation_dropped_unauthorized_tenant",
                chunk_id=chunk.chunk_id,
                chunk_tenant=c_tenant,
                authorized_tenant=effective_tenant,
            )
            continue

        seen.add(marker)
        citations.append(
            Citation(
                chunk_id=chunk.chunk_id,
                doc_title=chunk.doc_title,
                section_path=list(chunk.section_path),
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                source_file=chunk.source_file,
                excerpt=_excerpt(chunk.text),
            )
        )

    return citations