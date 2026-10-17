"""Data classification and retention enforcement.

Every document carries a classification (public / internal / restricted /
client_confidential) and a retention window in days. Retention is what
turns "we store documents" into "we store documents for exactly as long as
policy permits, and can prove when we removed them."

Purge is a two-phase operation: dry_run returns what would be deleted and
why, then a live run performs the deletions and writes an audit record.
Nothing is ever deleted without both a reason and an audit entry.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from citerator.config import get_settings
from citerator.governance import audit
from citerator.governance.store import ALLOWED_CLASSIFICATIONS, connect

logger = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_default(doc_id: str, conn) -> None:
    exists = conn.execute(
        "SELECT 1 FROM document_classification WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if exists:
        return
    s = get_settings()
    conn.execute(
        """
        INSERT INTO document_classification
        (doc_id, classification, retention_days, contains_pii,
         last_reviewed_at, review_cycle_days, updated_at)
        VALUES (?, ?, ?, 0, NULL, ?, ?)
        """,
        (
            doc_id,
            s.document_default_classification,
            s.document_default_retention_days,
            s.document_review_cycle_days,
            _now(),
        ),
    )


def get(doc_id: str) -> dict[str, Any] | None:
    s = get_settings()
    conn = connect(s.governance_db_path)
    try:
        _ensure_default(doc_id, conn)
        row = conn.execute(
            "SELECT * FROM document_classification WHERE doc_id = ?", (doc_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    out = dict(row)
    out["contains_pii"] = bool(out["contains_pii"])
    return out


def set_classification(
    doc_id: str,
    *,
    classification: str,
    retention_days: int | None,
    contains_pii: bool,
    review_cycle_days: int | None,
    actor: str | None = None,
) -> dict[str, Any]:
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise ValueError(
            f"classification must be one of {sorted(ALLOWED_CLASSIFICATIONS)}"
        )
    if retention_days is not None and retention_days < 1:
        raise ValueError("retention_days must be positive or null")

    s = get_settings()
    conn = connect(s.governance_db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.execute(
            "SELECT * FROM document_classification WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        conn.execute(
            """
            INSERT INTO document_classification
            (doc_id, classification, retention_days, contains_pii,
             last_reviewed_at, review_cycle_days, updated_at)
            VALUES (?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                classification    = excluded.classification,
                retention_days    = excluded.retention_days,
                contains_pii      = excluded.contains_pii,
                review_cycle_days = excluded.review_cycle_days,
                updated_at        = excluded.updated_at
            """,
            (
                doc_id,
                classification,
                retention_days,
                1 if contains_pii else 0,
                review_cycle_days,
                _now(),
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

    audit.append(
        "document.classification.changed",
        {
            "doc_id": doc_id,
            "before": dict(before) if before else None,
            "after": {
                "classification": classification,
                "retention_days": retention_days,
                "contains_pii": contains_pii,
                "review_cycle_days": review_cycle_days,
            },
        },
        actor=actor,
    )
    result = get(doc_id)
    return result or {}


def mark_reviewed(doc_id: str, *, actor: str | None = None) -> None:
    s = get_settings()
    conn = connect(s.governance_db_path)
    try:
        _ensure_default(doc_id, conn)
        conn.execute(
            "UPDATE document_classification SET last_reviewed_at = ?, updated_at = ? WHERE doc_id = ?",
            (_now(), _now(), doc_id),
        )
    finally:
        conn.close()
    audit.append(
        "document.reviewed",
        {"doc_id": doc_id},
        actor=actor,
    )


def documents_due_for_retention(
    *, registry_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return documents whose retention window has expired."""

    now = datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []
    for row in registry_rows:
        doc_id = row.get("doc_id")
        if not doc_id:
            continue
        cls = get(doc_id)
        if not cls:
            continue
        retention = cls.get("retention_days")
        if retention is None:
            continue
        indexed_at = row.get("indexed_at") or row.get("updated_at")
        if not indexed_at:
            continue
        try:
            anchor = datetime.fromisoformat(indexed_at)
        except Exception:
            continue
        age_days = (now - anchor).days
        if age_days >= retention:
            due.append(
                {
                    "doc_id": doc_id,
                    "source_file": row.get("source_file"),
                    "retention_days": retention,
                    "age_days": age_days,
                    "classification": cls.get("classification"),
                }
            )
    return due