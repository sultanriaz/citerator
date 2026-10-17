"""SQLite-backed document registry.

One row per indexed document, keyed by ``doc_id``. Metadata only -- chunk text
always lives in Qdrant, never duplicated here. The registry shares the same
SQLite file as the job tracker (``jobs.py``); each module owns its own table.

Follows embedding.py's CachedEmbedder pattern: raw ``sqlite3``, parameterized
queries, ``CREATE TABLE IF NOT EXISTS``, no ORM.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from citerator.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id            TEXT PRIMARY KEY,
    source_file       TEXT NOT NULL,
    title             TEXT,
    doc_type          TEXT,
    jurisdiction      TEXT,
    effective_date    TEXT,
    page_count        INTEGER,
    chunk_count       INTEGER,
    doc_hash          TEXT,
    chunker           TEXT,
    chunker_params    TEXT,
    embedder          TEXT,
    sparse_embedder   TEXT,
    status            TEXT NOT NULL,
    warnings          TEXT,
    tenant_id         TEXT NOT NULL DEFAULT 'global',
    owner_id          TEXT,
    visibility        TEXT NOT NULL DEFAULT 'tenant',
    indexed_at        TEXT,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_source_file ON documents(source_file);
CREATE INDEX IF NOT EXISTS idx_documents_status      ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type    ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_tenant      ON documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_owner       ON documents(owner_id);
"""

_SORTABLE = {
    "doc_id",
    "source_file",
    "title",
    "doc_type",
    "jurisdiction",
    "effective_date",
    "chunk_count",
    "tenant_id",
    "owner_id",
    "visibility",
    "indexed_at",
    "updated_at",
}


def _db_path(explicit: str | None) -> str:
    path = explicit or get_settings().documents_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    # Automatic schema migration for existing databases
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "tenant_id" not in existing_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'global'")
    if "owner_id" not in existing_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN owner_id TEXT")
    if "visibility" not in existing_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN visibility TEXT NOT NULL DEFAULT 'tenant'")
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for field in ("chunker_params", "warnings"):
        value = out.get(field)
        if isinstance(value, str):
            try:
                out[field] = json.loads(value)
            except json.JSONDecodeError:
                out[field] = {} if field == "chunker_params" else []
    return out


_UPSERT_HOOKS: list = []


def register_upsert_hook(fn) -> None:
    """Register a callback invoked after every successful upsert.

    Governance uses this to record document versions without touching
    ingest_service. The callback receives the row dict that was written.
    Failures in a hook are logged but do not fail the upsert -- preserving
    the ingest caller's idempotency guarantee is more important than
    guaranteeing that side effects always succeed.
    """

    _UPSERT_HOOKS.append(fn)


def _fire_upsert_hooks(row: dict[str, Any]) -> None:
    if not _UPSERT_HOOKS:
        return
    import structlog

    log = structlog.get_logger(__name__)
    for fn in _UPSERT_HOOKS:
        try:
            fn(row)
        except Exception as exc:
            log.warning("registry_upsert_hook_failed", error=str(exc))


def upsert_document(row: dict[str, Any], *, db_path: str | None = None) -> None:
    payload = {
        "doc_id": row["doc_id"],
        "source_file": row["source_file"],
        "title": row.get("title"),
        "doc_type": row.get("doc_type"),
        "jurisdiction": row.get("jurisdiction"),
        "effective_date": row.get("effective_date"),
        "page_count": row.get("page_count"),
        "chunk_count": row.get("chunk_count", 0),
        "doc_hash": row.get("doc_hash"),
        "chunker": row.get("chunker"),
        "chunker_params": json.dumps(row.get("chunker_params") or {}),
        "embedder": row.get("embedder"),
        "sparse_embedder": row.get("sparse_embedder"),
        "status": row.get("status", "indexed"),
        "warnings": json.dumps(row.get("warnings") or []),
        "tenant_id": row.get("tenant_id") or "global",
        "owner_id": row.get("owner_id"),
        "visibility": row.get("visibility") or "tenant",
        "indexed_at": row.get("indexed_at") or _now(),
        "updated_at": _now(),
    }

    conn = _connect(_db_path(db_path))
    try:
        conn.execute(
            """
            INSERT INTO documents (
                doc_id, source_file, title, doc_type, jurisdiction, effective_date,
                page_count, chunk_count, doc_hash, chunker, chunker_params,
                embedder, sparse_embedder, status, warnings, tenant_id, owner_id, visibility,
                indexed_at, updated_at
            ) VALUES (
                :doc_id, :source_file, :title, :doc_type, :jurisdiction, :effective_date,
                :page_count, :chunk_count, :doc_hash, :chunker, :chunker_params,
                :embedder, :sparse_embedder, :status, :warnings, :tenant_id, :owner_id, :visibility,
                :indexed_at, :updated_at
            )
            ON CONFLICT(doc_id) DO UPDATE SET
                source_file     = excluded.source_file,
                title           = excluded.title,
                doc_type        = excluded.doc_type,
                jurisdiction    = excluded.jurisdiction,
                effective_date  = excluded.effective_date,
                page_count      = excluded.page_count,
                chunk_count     = excluded.chunk_count,
                doc_hash        = excluded.doc_hash,
                chunker         = excluded.chunker,
                chunker_params  = excluded.chunker_params,
                embedder        = excluded.embedder,
                sparse_embedder = excluded.sparse_embedder,
                status          = excluded.status,
                warnings        = excluded.warnings,
                tenant_id       = excluded.tenant_id,
                owner_id        = excluded.owner_id,
                visibility      = excluded.visibility,
                indexed_at      = excluded.indexed_at,
                updated_at      = excluded.updated_at
            """,
            payload,
        )
        conn.commit()
    finally:
        conn.close()

    _fire_upsert_hooks(payload)


def delete_document(doc_id: str, *, db_path: str | None = None) -> None:
    conn = _connect(_db_path(db_path))
    try:
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        conn.commit()
    finally:
        conn.close()


def get_document(doc_id: str, *, db_path: str | None = None) -> dict[str, Any] | None:
    conn = _connect(_db_path(db_path))
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def list_documents(
    *,
    search: str | None = None,
    doc_type: str | None = None,
    jurisdiction: str | None = None,
    status: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    is_admin: bool = False,
    include_global: bool = True,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int | None = None,
    offset: int = 0,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    if sort not in _SORTABLE:
        sort = "updated_at"
    if order.lower() not in {"asc", "desc"}:
        order = "desc"

    clauses: list[str] = []
    params: list[Any] = []

    if search:
        clauses.append("(title LIKE ? OR source_file LIKE ?)")
        needle = f"%{search}%"
        params.extend([needle, needle])
    if doc_type:
        clauses.append("doc_type = ?")
        params.append(doc_type)
    if jurisdiction:
        clauses.append("jurisdiction = ?")
        params.append(jurisdiction)
    if status:
        clauses.append("status = ?")
        params.append(status)

    if tenant_id and tenant_id != "*":
        if is_admin:
            if include_global:
                clauses.append("(tenant_id = ? OR tenant_id = 'global')")
                params.append(tenant_id)
            else:
                clauses.append("tenant_id = ?")
                params.append(tenant_id)
        else:
            if include_global:
                clauses.append("(tenant_id = ? OR tenant_id = 'global')")
                params.append(tenant_id)
            else:
                clauses.append("tenant_id = ?")
                params.append(tenant_id)

            if user_id:
                clauses.append("(visibility IN ('tenant', 'public') OR owner_id = ?)")
                params.append(user_id)
            else:
                clauses.append("visibility IN ('tenant', 'public')")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM documents {where} ORDER BY {sort} {order.upper()}"

    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

    conn = _connect(_db_path(db_path))
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(row) for row in rows]


def count_documents(*, db_path: str | None = None) -> int:
    conn = _connect(_db_path(db_path))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
    finally:
        conn.close()
