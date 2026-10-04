"""Escalation endpoints backing the Ask screen's "Flag for review" and
"Escalate to a human" actions.

Records are always persisted. Webhook delivery is a single best-effort POST
with no retries; failures are captured in webhook_delivered / webhook_error
fields and never surface as a 500 to the caller. This matches the
"never silently swallow, but never break the primary request" convention:
the failure is visible in stored state and in a structlog warning.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from citerator.api.deps import require_api_key
from citerator.config import Settings, get_settings
from citerator.observability import store

import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/escalations", tags=["escalations"])

_ALLOWED_STATUSES = {"open", "acknowledged", "resolved"}


class Passage(BaseModel):
    chunk_id: str | None = None
    doc_title: str | None = None
    section_path: list[str] | None = None
    page_start: int | None = None
    page_end: int | None = None
    excerpt: str | None = None


class EscalationRequest(BaseModel):
    trace_id: str | None = None
    source: Literal["escalated", "flagged"]
    question: str
    passages: list[Passage] = Field(default_factory=list)
    note: str


class EscalationUpdate(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]
    resolution_note: str | None = None


def _deliver_webhook(url: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        import httpx

        response = httpx.post(url, json=payload, timeout=10.0)
        if 200 <= response.status_code < 300:
            return True, None
        return False, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)[:200]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_escalation(
    request: EscalationRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict:
    passages_payload = [p.model_dump() for p in request.passages]

    delivered = False
    webhook_error: str | None = None
    if settings.escalation_webhook_url:
        delivered, webhook_error = _deliver_webhook(
            settings.escalation_webhook_url,
            {
                "source": request.source,
                "trace_id": request.trace_id,
                "question": request.question,
                "note": request.note,
                "passages": passages_payload,
            },
        )
        if not delivered:
            logger.warning(
                "escalation_webhook_failed",
                url=settings.escalation_webhook_url,
                error=webhook_error,
            )

    escalation_id = store.create_escalation(
        trace_id=request.trace_id,
        source=request.source,
        question=request.question,
        passages=passages_payload,
        note=request.note,
        status="open",
        webhook_delivered=delivered,
        webhook_error=webhook_error,
        db_path=settings.observability_db_path,
    )

    row = store.get_escalation(
        escalation_id, db_path=settings.observability_db_path
    )
    if row is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "escalation was created but could not be read back",
        )
    return row


@router.get("")
def list_escalations(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict:
    if status_filter is not None and status_filter not in _ALLOWED_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of {sorted(_ALLOWED_STATUSES)}",
        )
    rows = store.list_escalations(
        status=status_filter,
        limit=limit,
        offset=offset,
        db_path=settings.observability_db_path,
    )
    return {"escalations": rows, "count": len(rows)}


@router.get("/{escalation_id}")
def get_escalation(
    escalation_id: int,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict:
    row = store.get_escalation(
        escalation_id, db_path=settings.observability_db_path
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escalation not found")
    return row


@router.patch("/{escalation_id}")
def update_escalation(
    escalation_id: int,
    request: EscalationUpdate,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict:
    row = store.update_escalation_status(
        escalation_id,
        request.status,
        request.resolution_note,
        db_path=settings.observability_db_path,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escalation not found")
    return row
