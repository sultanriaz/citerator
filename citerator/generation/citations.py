"""Citation parsing and validation for generated answers."""

from __future__ import annotations

import re

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


def parse_citations(answer: str, chunks: list[RetrievedChunk]) -> list[Citation]:
    """Map valid ``[n]`` markers to chunks.

    Out-of-range markers are dropped and logged. The function never raises for a
    malformed citation marker.
    """

    citations: list[Citation] = []
    seen: set[int] = set()

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

        seen.add(marker)
        chunk = chunks[marker - 1]
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