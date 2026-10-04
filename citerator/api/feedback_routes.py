"""Feedback endpoint for the Ask screen's thumbs up/down.

Feedback rows are stored unconditionally, even for an unrecognized
trace_id. This project keeps no query log to validate against; the frontend
is the source of truth for what it showed the user. If a real tracer is
configured, feedback is also forwarded as a Langfuse score on the original
trace, so it appears in the Langfuse UI alongside the span timings.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from citerator.api.deps import require_api_key
from citerator.config import Settings, get_settings
from citerator.observability import store
from citerator.observability.logging_config import _is_dev  # noqa: F401  (imported for parity, unused here)
from citerator.observability.tracing import NullTracer, get_tracer

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: Literal["up", "down"]
    comment: str | None = None


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(
    request: FeedbackRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict:
    if not request.trace_id.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "trace_id is required")

    row = store.add_feedback(
        trace_id=request.trace_id,
        rating=request.rating,
        comment=request.comment,
        db_path=settings.observability_db_path,
    )

    tracer = get_tracer(settings)
    if not isinstance(tracer, NullTracer):
        try:
            tracer.score(
                request.trace_id,
                name="user_feedback",
                value=1.0 if request.rating == "up" else 0.0,
                comment=request.comment,
            )
        except Exception:
            pass

    return row


@router.get("/feedback")
def list_feedback(
    trace_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict:
    rows = store.list_feedback(
        trace_id=trace_id,
        limit=limit,
        offset=offset,
        db_path=settings.observability_db_path,
    )
    return {"feedback": rows, "count": len(rows)}
