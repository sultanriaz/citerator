"""HTTP surface for governance: audit, versioning, classification,
retention, erasure, and control status.

All routes require the existing X-API-Key dependency. The audit chain and
control report are read-only; classification, retention, and erasure are
write operations, all of which audit their own changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from citerator.api.deps import require_api_key
from citerator.config import Settings, get_settings
from citerator.documents import registry as doc_registry
from citerator.governance import (
    audit,
    classification as cls_mod,
    controls as controls_mod,
    erasure as erasure_mod,
    versioning as ver_mod,
)

router = APIRouter(prefix="/governance", tags=["governance"])


def _actor(identity: Any) -> str:
    return audit.actor_fingerprint(identity)


class ClassificationUpdate(BaseModel):
    classification: Literal[
        "public", "internal", "restricted", "client_confidential"
    ]
    retention_days: int | None = Field(default=None, ge=1)
    contains_pii: bool = False
    review_cycle_days: int | None = Field(default=None, ge=1)


class ErasureRequest(BaseModel):
    subject: str = Field(min_length=2)
    dry_run: bool = True
    case_sensitive: bool = False
    reason: str = "gdpr_erasure_request"


@router.get("/audit")
def list_audit(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    event_type: str | None = Query(None),
    since: str | None = Query(None),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    records = audit.list_records(
        limit=limit,
        offset=offset,
        event_type=event_type,
        since=since,
        settings=settings,
    )
    return {
        "records": [
            {
                "id": r.id,
                "sequence": r.sequence,
                "timestamp": r.timestamp,
                "event_type": r.event_type,
                "actor": r.actor,
                "payload": r.payload,
                "record_hash": r.record_hash,
            }
            for r in records
        ],
        "count": len(records),
        "total": audit.count(settings=settings),
        "limit": limit,
        "offset": offset,
    }


@router.get("/audit/verify")
def verify_audit(
    from_sequence: int = Query(1, ge=1),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    result = audit.verify(settings=settings, from_sequence=from_sequence)
    return {
        "ok": result.ok,
        "total_records": result.total_records,
        "first_bad_sequence": result.first_bad_sequence,
        "error": result.error,
    }


@router.get("/audit/export")
def export_audit(
    since: str | None = Query(None),
    limit: int = Query(10_000, ge=1, le=100_000),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    records = audit.list_records(
        limit=limit, offset=0, since=since, settings=settings
    )
    records.reverse()
    verification = audit.verify(settings=settings)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "chain_verification": {
            "ok": verification.ok,
            "total_records": verification.total_records,
        },
        "records": [
            {
                "sequence": r.sequence,
                "timestamp": r.timestamp,
                "event_type": r.event_type,
                "actor": r.actor,
                "payload": r.payload,
                "prev_hash": r.prev_hash,
                "record_hash": r.record_hash,
            }
            for r in records
        ],
    }


@router.get("/documents/{doc_id}/versions")
def document_versions(
    doc_id: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    versions = ver_mod.list_versions(doc_id)
    return {"doc_id": doc_id, "versions": versions}


@router.get("/documents/{doc_id}/classification")
def get_classification(
    doc_id: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    c = cls_mod.get(doc_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No classification record")
    is_stale, age_days = ver_mod.is_stale(doc_id)
    c["review_due"] = is_stale
    c["age_days"] = age_days
    return c


@router.put("/documents/{doc_id}/classification")
def update_classification(
    doc_id: str,
    body: ClassificationUpdate,
    settings: Settings = Depends(get_settings),
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    actor = _actor(settings.api_key if False else (api_key or ""))
    try:
        updated = cls_mod.set_classification(
            doc_id,
            classification=body.classification,
            retention_days=body.retention_days,
            contains_pii=body.contains_pii,
            review_cycle_days=body.review_cycle_days,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return updated


@router.post("/documents/{doc_id}/review")
def mark_reviewed(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    actor = _actor(api_key or "")
    cls_mod.mark_reviewed(doc_id, actor=actor)
    return {"doc_id": doc_id, "reviewed_at": datetime.now(timezone.utc).isoformat()}


@router.post("/retention/due")
def retention_due(
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    docs = doc_registry.list_documents(limit=None)
    due = cls_mod.documents_due_for_retention(registry_rows=docs)
    return {"count": len(due), "documents": due}


@router.post("/retention/purge")
def retention_purge(
    dry_run: bool = Query(True),
    settings: Settings = Depends(get_settings),
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    from citerator.documents import ingest_service

    docs = doc_registry.list_documents(limit=None)
    due = cls_mod.documents_due_for_retention(registry_rows=docs)

    if dry_run:
        audit.append(
            "retention.dry_run",
            {"due_count": len(due), "doc_ids": [d["doc_id"] for d in due]},
            actor=_actor(api_key or ""),
            settings=settings,
        )
        return {"dry_run": True, "would_delete": len(due), "documents": due}

    deleted: list[str] = []
    errors: list[dict[str, str]] = []
    for d in due:
        try:
            ingest_service.delete_document(d["doc_id"], settings)
            deleted.append(d["doc_id"])
        except Exception as exc:
            errors.append({"doc_id": d["doc_id"], "error": str(exc)})

    audit.append(
        "retention.purge",
        {"deleted": deleted, "errors": errors},
        actor=_actor(api_key or ""),
        settings=settings,
    )
    return {"dry_run": False, "deleted": deleted, "errors": errors}


@router.post("/erasure")
def erasure_endpoint(
    body: ErasureRequest,
    settings: Settings = Depends(get_settings),
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        result = erasure_mod.erase(
            body.subject,
            dry_run=body.dry_run,
            case_sensitive=body.case_sensitive,
            actor=_actor(api_key or ""),
            reason=body.reason,
        )
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"erasure failed: {exc}",
        ) from exc

    return {
        "subject": result.subject,
        "dry_run": result.dry_run,
        "matched_chunks": result.matched_chunks,
        "deleted_chunks": result.deleted_chunks,
        "collections_searched": result.collections_searched,
        "truncated": result.truncated,
        "matches": [
            {
                "chunk_id": m.chunk_id,
                "doc_id": m.doc_id,
                "source_file": m.source_file,
                "excerpt": m.excerpt,
            }
            for m in result.matches
        ],
    }


@router.get("/controls")
def control_status(
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    return controls_mod.evaluate_all(settings)