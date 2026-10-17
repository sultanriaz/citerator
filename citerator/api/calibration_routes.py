"""Calibration endpoint: refit confidence from eval history on demand.

Called from the Settings > Pipeline UI or from CI. Fits on the current
collection using the latest completed eval run's faithfulness labels, saves
coefficients, and invalidates the confidence module's cache so the new curve
is active on the next query.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from citerator.api.deps import require_api_key
from citerator.config import Settings, get_settings
from citerator.evaluation import calibration
from citerator.retrieval.confidence import reset_calibration_cache

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/settings/pipeline", tags=["calibration"])


@router.post("/calibrate")
def calibrate_confidence(
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    """Fit a new confidence curve from eval history.

    Requires at least 20 paired (rerank_score, faithfulness>=0.7) samples
    from the latest completed eval run. Re-runs retrieval+rerank on the
    question set (no LLM, no Ragas) to fetch the current top scores.
    """

    try:
        coeffs = calibration.fit_and_save(settings)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        logger.warning("calibration_fit_failed", error=str(exc))
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Calibration fit failed: {exc}",
        ) from exc

    reset_calibration_cache()

    return {
        "a": coeffs.a,
        "b": coeffs.b,
        "n_samples": coeffs.n_samples,
        "n_positive": coeffs.n_positive,
        "fitted_at": coeffs.fitted_at,
        "log_loss": coeffs.log_loss,
        "brier_score": coeffs.brier_score,
        "coefficients_path": calibration.DEFAULT_PATH.as_posix(),
    }


@router.get("/calibration")
def get_calibration(
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    """Return the currently-active calibration, or null if raw sigmoid is in use."""

    coeffs = calibration.load_coefficients()
    if coeffs is None:
        return {"calibrated": False}
    return {
        "calibrated": True,
        "a": coeffs.a,
        "b": coeffs.b,
        "n_samples": coeffs.n_samples,
        "n_positive": coeffs.n_positive,
        "fitted_at": coeffs.fitted_at,
        "log_loss": coeffs.log_loss,
        "brier_score": coeffs.brier_score,
    }