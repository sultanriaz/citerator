"""Citation parsing and validation for generated answers."""

from __future__ import annotations

import re
from typing import Any

import structlog
from pydantic import BaseModel

from citerator.retrieval.search import RetrievedChunk

logger = structlog.get_logger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")

_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "should", "shouldn't", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "wasn't", "we", "were", "weren't", "what", "when", "where", "which", "while",
    "who", "whom", "why", "with", "won't", "would", "wouldn't", "you", "your",
    "yours", "yourself", "yourselves",
    # Citation / reference meta keywords
    "see", "refer", "ref", "view", "also", "according", "stated", "source", "per",
}


class Citation(BaseModel):
    chunk_id: str
    doc_title: str
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    source_file: str
    excerpt: str
    referenced_passage: str | None = None
    support_score: float | None = None


def _excerpt(text: str, limit: int = 240) -> str:
    clean = " ".join(text.split())
    return clean[:limit] + ("..." if len(clean) > limit else "")


def extract_referenced_passage(answer: str, start_pos: int, end_pos: int) -> str:
    """Extract the sentence or clause enclosing the citation marker."""
    prefix = answer[:start_pos]
    sentence_start = -1
    for sep in [". ", ".\n", "! ", "? ", "\n"]:
        pos = prefix.rfind(sep)
        if pos != -1 and pos > sentence_start:
            sentence_start = pos + len(sep)

    start_idx = 0 if sentence_start == -1 else sentence_start

    suffix = answer[end_pos:]
    sentence_end = -1
    for sep in [". ", ".\n", "! ", "? ", "\n"]:
        pos = suffix.find(sep)
        if pos != -1 and (sentence_end == -1 or pos < sentence_end):
            sentence_end = pos + (1 if sep.startswith(".") else len(sep))

    end_idx = len(answer) if sentence_end == -1 else (end_pos + sentence_end)
    return answer[start_idx:end_idx].strip()


def check_passage_support(
    passage: str,
    chunk_text: str,
    *,
    min_token_overlap: float = 0.20,
) -> tuple[bool, float]:
    """Validate that chunk_text provides evidentiary support for the claim in passage.

    Returns (is_supported, score).
    """
    clean_p = _CITATION_RE.sub("", passage).strip()
    if not clean_p:
        return True, 1.0

    p_lower = clean_p.lower()
    c_lower = chunk_text.lower()

    # Refusal and insufficient evidence cues must never carry affirmative citations
    refusal_cues = [
        "insufficient evidence",
        "not enough information",
        "sources do not contain",
        "cannot answer",
        "cannot be determined",
        "no information provided",
        "available sources are insufficient",
    ]
    if any(cue in p_lower for cue in refusal_cues):
        return False, 0.0

    # Extract substantive content tokens
    tokens = [
        t for t in re.findall(r"\b[a-zA-Z0-9_\-\$]+\b", p_lower)
        if t not in _STOPWORDS and len(t) > 2
    ]

    if not tokens:
        # Minimalist reference like "See [1]" without specific claims
        return True, 1.0

    matched = [t for t in tokens if t in c_lower]
    score = len(matched) / len(tokens)

    # Check for specific numerical entities (e.g. $10,000, 14 days, 5 years)
    entities = re.findall(r"\b(?:\$\d+[\d,]*|\d+(?:\.\d+)?%?|\d+ (?:days|months|years))\b", p_lower)
    if entities:
        entity_matches = sum(1 for e in entities if e in c_lower)
        if entity_matches > 0:
            score = max(score, entity_matches / len(entities))
        elif len(tokens) >= 3 and score < 0.20:
            # Passage has specific numerical claims missing from chunk
            return False, score

    # Substantive claims (>= 2 content tokens) require min_token_overlap
    is_supported = score >= min_token_overlap if len(tokens) >= 2 else (len(matched) > 0)
    return is_supported, score


def parse_citations(
    answer: str,
    chunks: list[RetrievedChunk],
    *,
    tenant: Any | None = None,
    verify_support: bool = True,
    min_support_score: float = 0.20,
) -> list[Citation]:
    """Map valid ``[n]`` markers to chunks after validating existence, tenant boundaries,
    and evidentiary support for the referenced answer passage.
    """

    citations: list[Citation] = []
    seen: set[int] = set()

    effective_tenant = getattr(tenant, "tenant_id", None) if tenant else None
    is_admin = getattr(tenant, "is_admin", False) if tenant else False
    user_id = getattr(tenant, "user_id", None) if tenant else None
    allowed = {effective_tenant, "global"} if (effective_tenant and effective_tenant != "*") else None

    for match in _CITATION_RE.finditer(answer or ""):
        marker = int(match.group(1))

        if marker in seen:
            continue
        # 1. Existence check:
        if marker < 1 or marker > len(chunks):
            logger.warning(
                "citation_out_of_range",
                marker=marker,
                available=len(chunks),
            )
            continue

        chunk = chunks[marker - 1]
        c_tenant = getattr(chunk, "tenant_id", "global") or "global"
        c_vis = getattr(chunk, "visibility", "tenant") or "tenant"
        c_owner = getattr(chunk, "owner_id", None)

        # 2. Tenant boundary authorization:
        if not is_admin and allowed and c_tenant not in allowed:
            logger.warning(
                "citation_dropped_unauthorized_tenant",
                chunk_id=chunk.chunk_id,
                chunk_tenant=c_tenant,
                authorized_tenant=effective_tenant,
            )
            continue

        # 3. Private document boundary authorization:
        if not is_admin and c_vis == "private" and c_owner and c_owner != user_id:
            logger.warning(
                "citation_dropped_unauthorized_private_draft",
                chunk_id=chunk.chunk_id,
                chunk_owner=c_owner,
                caller_user=user_id,
            )
            continue

        # 4. Evidentiary support validation:
        passage = extract_referenced_passage(answer, match.start(), match.end())
        support_score = 1.0
        if verify_support:
            is_supported, support_score = check_passage_support(
                passage, chunk.text, min_token_overlap=min_support_score
            )
            if not is_supported:
                logger.warning(
                    "citation_dropped_unsupported_passage",
                    marker=marker,
                    chunk_id=chunk.chunk_id,
                    support_score=round(support_score, 3),
                    passage=passage[:100],
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
                referenced_passage=passage,
                support_score=round(support_score, 3),
            )
        )

    return citations