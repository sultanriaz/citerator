"""Confidence scoring and banding for Citerator answers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from citerator.config import Settings
from citerator.retrieval.search import RetrievedChunk


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


@dataclass(frozen=True)
class ConfidenceResult:
    confidence: float
    state: str
    has_candidates: bool


def score_confidence(
    reranked: list[RetrievedChunk],
    settings: Settings,
) -> ConfidenceResult:
    """Normalize the top rerank score and classify it into a UI band."""

    if not reranked:
        return ConfidenceResult(confidence=0.0, state="insufficient", has_candidates=False)

    top_score = reranked[0].rerank_score
    if top_score is None:
        top_score = 0.0

    confidence = _sigmoid(float(top_score))

    if confidence >= settings.confidence_threshold:
        state = "confident"
    elif confidence >= settings.confidence_floor:
        state = "low_confidence"
    else:
        state = "insufficient"

    return ConfidenceResult(
        confidence=confidence,
        state=state,
        has_candidates=True,
    )