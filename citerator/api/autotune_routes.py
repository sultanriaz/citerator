"""Threshold auto-tune endpoint.

Exposes the Loop 2 sweeper over HTTP so the Settings screen can offer a
"Find best threshold" button without a redeploy. Dry-run by default;
pass ?apply=true to persist through runtime overrides.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from citerator.api.deps import require_api_key
from citerator.config import Settings, get_settings
from citerator.evaluation import autotune as autotune_module
from citerator.evaluation.autotune import AutotuneConfig

router = APIRouter(prefix="/settings/pipeline", tags=["autotune"])


class ThresholdResultModel(BaseModel):
    threshold: float
    safety_refuse_pct: float
    safety_escalate_pct: float
    answer_rate: float
    score: float
    counts: dict[str, int]


class AutotuneResponse(BaseModel):
    best: ThresholdResultModel
    sweep: list[ThresholdResultModel]
    evaluated_at: str
    question_count: int
    config: dict[str, Any]
    notes: list[str]
    applied: bool


def _to_model(r) -> ThresholdResultModel:
    return ThresholdResultModel(
        threshold=r.threshold,
        safety_refuse_pct=r.safety_refuse_pct,
        safety_escalate_pct=r.safety_escalate_pct,
        answer_rate=r.answer_rate,
        score=r.score,
        counts=r.counts,
    )


@router.post("/autotune", response_model=AutotuneResponse)
def run_autotune(
    apply: bool = Query(False, description="Persist the winning threshold."),
    min_threshold: float = Query(0.30, ge=0.0, le=1.0),
    max_threshold: float = Query(0.95, ge=0.0, le=1.0),
    step: float = Query(0.02, gt=0.0, le=0.2),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> AutotuneResponse:
    if min_threshold >= max_threshold:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "min_threshold must be < max_threshold",
        )

    cfg = AutotuneConfig(
        min_threshold=min_threshold,
        max_threshold=max_threshold,
        step=step,
        confidence_floor=settings.confidence_floor,
    )
    try:
        result = autotune_module.autotune(settings, cfg, apply=apply)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Autotune failed: {exc}",
        ) from exc

    autotune_module.save_report(result)

    return AutotuneResponse(
        best=_to_model(result.best),
        sweep=[_to_model(r) for r in result.sweep],
        evaluated_at=result.evaluated_at,
        question_count=result.question_count,
        config=result.config,
        notes=result.notes,
        applied=apply,
    )


@router.get("/autotune/latest")
def get_latest_autotune(
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    """Return the most recent autotune report, or 404 if none exists."""

    path = autotune_module.Path("data/processed/autotune.json")
    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No autotune report yet"
        )
    import json

    return json.loads(path.read_text(encoding="utf-8"))