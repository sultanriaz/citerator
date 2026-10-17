"""Confidence scoring and banding for Citerator answers.

The pipeline produces a confidence float in [0, 1] from the top cross-encoder
rerank score, then bands it into one of three states using
settings.confidence_threshold and settings.confidence_floor.

Raw normalization is sigmoid(rerank_score). If a calibration curve has been
fitted from eval history (see citerator/evaluation/calibration.py), the
calibrated logistic function is used instead, so confidence reflects the
actual probability that the top chunk answers the question on this corpus.
Absent calibration, raw sigmoid is used, matching pre-Loop-1 behavior.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from citerator.config import Settings
from citerator.retrieval.search import RetrievedChunk


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


_coeffs_cache: dict = {"value": None, "loaded_at": 0.0, "present": False}
_COEFFS_TTL_SECONDS = 30.0


def _current_coefficients():
    """Return the active calibration coefficients, or None.

    Cached for _COEFFS_TTL_SECONDS so a refit propagates within half a
    minute. Bypass with reset_calibration_cache() for immediate effect.
    """

    now = time.time()
    if (
        _coeffs_cache["present"]
        and now - _coeffs_cache["loaded_at"] < _COEFFS_TTL_SECONDS
    ):
        return _coeffs_cache["value"]

    try:
        from citerator.evaluation.calibration import load_coefficients

        coeffs = load_coefficients()
    except Exception:
        coeffs = None

    _coeffs_cache["value"] = coeffs
    _coeffs_cache["loaded_at"] = now
    _coeffs_cache["present"] = True
    return coeffs


def reset_calibration_cache() -> None:
    """Force the next normalization to re-read coefficients from disk."""

    _coeffs_cache["value"] = None
    _coeffs_cache["loaded_at"] = 0.0
    _coeffs_cache["present"] = False


def _normalize(raw_score: float) -> float:
    """Map a raw rerank score to a confidence in [0, 1].

    Uses the fitted calibration curve if one is available; otherwise falls
    back to raw sigmoid.
    """

    coeffs = _current_coefficients()
    if coeffs is not None:
        try:
            from citerator.evaluation.calibration import apply_calibration

            return apply_calibration(raw_score, coeffs)
        except Exception:
            pass
    return _sigmoid(raw_score)


@dataclass(frozen=True)
class ConfidenceResult:
    confidence: float
    state: str
    has_candidates: bool


def score_confidence(
    reranked: list[RetrievedChunk],
    settings: Settings,
) -> ConfidenceResult:
    """Classify the top rerank score into a UI band.

    Empty retrieval returns "insufficient" without any confidence math.
    Otherwise the top candidate's rerank_score is normalized via the
    calibrated curve (or sigmoid, if not calibrated) and banded.
    """

    if not reranked:
        return ConfidenceResult(
            confidence=0.0, state="insufficient", has_candidates=False
        )

    top_score = reranked[0].rerank_score
    if top_score is None:
        top_score = 0.0

    confidence = _normalize(float(top_score))

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