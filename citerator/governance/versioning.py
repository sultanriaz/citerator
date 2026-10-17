"""Document version tracking.

Every successful upsert of a document produces a version record. Versions
are immutable: a new ingestion that produces different content creates a
new version and marks the previous one as superseded. Ingestions that
produce identical content (same doc_hash) are no-ops -- this preserves the
idempotency that Phase 2's CLI manifest already guarantees, extended to
the governance layer.

The registry hook is the integration point. citerator/documents/registry.py
exposes register_upsert_hook(); this module registers record_version() on
import. No modification to ingest_service.py is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from citerator.config import get_settings
from citerator.governance import audit
from citerator.governance.store import connect

logger = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_version(row: dict[str, Any]) -> None:
    """Hook called after every successful registry upsert.

    Does nothing if the doc_hash is unchanged from the current version.
    Never raises -- registry hook failures are logged, not propagated, to
    preserve the caller's idempotency guarantee. The alternative (failing
    the ingest because governance could not record it) would turn a
    governance bug into a data-loss bug.
    """

    try:
        _record_version_impl(row)
    except Exception as exc:
        logger.warning(
            "version_record_failed",
            doc_id=row.get("doc_id"),
            error=str(exc),
        )


def _record_version_impl(row: dict[str, Any]) -> None:
    doc_id = row["doc_id"]
    new_hash = row.get("doc_hash") or ""
    source_file = row.get("source_file") or ""
    chunk_count = row.get("chunk_count")
    ingested_by = row.get("ingested_by")
    reason = row.get("version_reason")

    s = get_settings()
    conn = connect(s.governance_db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            """
            SELECT version, doc_hash FROM document_versions
            WHERE doc_id = ? AND superseded_by_version IS NULL
            ORDER BY version DESC LIMIT 1
            """,
            (doc_id,),
        ).fetchone()

        if current and current["doc_hash"] == new_hash:
            conn.execute("COMMIT")
            return

        next_version = (current["version"] + 1) if current else 1
        now = _now()

        if current:
            conn.execute(
                """
                UPDATE document_versions
                SET effective_to = ?, superseded_by_version = ?
                WHERE doc_id = ? AND version = ?
                """,
                (now, next_version, doc_id, current["version"]),
            )

        conn.execute(
            """
            INSERT INTO document_versions
            (doc_id, version, doc_hash, source_file, chunk_count,
             effective_from, effective_to, superseded_by_version,
             ingested_by, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
            """,
            (
                doc_id,
                next_version,
                new_hash,
                source_file,
                chunk_count,
                now,
                ingested_by,
                reason,
                now,
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
        "document.version.created",
        {
            "doc_id": doc_id,
            "version": next_version,
            "doc_hash": new_hash,
            "source_file": source_file,
            "chunk_count": chunk_count,
            "superseded_version": current["version"] if current else None,
        },
        actor=ingested_by,
    )


def list_versions(doc_id: str) -> list[dict[str, Any]]:
    s = get_settings()
    conn = connect(s.governance_db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM document_versions
            WHERE doc_id = ?
            ORDER BY version DESC
            """,
            (doc_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def current_version(doc_id: str) -> dict[str, Any] | None:
    s = get_settings()
    conn = connect(s.governance_db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM document_versions
            WHERE doc_id = ? AND superseded_by_version IS NULL
            ORDER BY version DESC LIMIT 1
            """,
            (doc_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def is_stale(doc_id: str) -> tuple[bool, int | None]:
    """Return (is_stale, days_old) for the current version of a document.

    A document is stale if the current version's effective_from is older
    than the review cycle configured for it, or the global default.
    """

    current = current_version(doc_id)
    if not current:
        return (False, None)

    s = get_settings()
    cycle = s.document_review_cycle_days
    conn = connect(s.governance_db_path)
    try:
        cls = conn.execute(
            "SELECT review_cycle_days FROM document_classification WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()
    finally:
        conn.close()
    if cls and cls["review_cycle_days"] is not None:
        cycle = cls["review_cycle_days"]

    try:
        effective = datetime.fromisoformat(current["effective_from"])
    except Exception:
        return (False, None)

    age_days = (datetime.now(timezone.utc) - effective).days
    return (age_days > cycle, age_days)