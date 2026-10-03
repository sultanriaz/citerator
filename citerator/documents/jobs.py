"""SQLite-backed ingestion job tracker.

Job rows persist across process restarts so upload history survives a crash.
Status transitions: queued -> parsing -> chunking -> embedding -> indexing ->
indexed. Any failure moves the job to ``failed`` with a captured error message.

Shares the SQLite file with registry.py (separate table).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from citerator.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    file_name   TEXT NOT NULL,
    status      TEXT NOT NULL,
    doc_id      TEXT,
    error       TEXT,
    warnings    TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
"""

_UPDATABLE = {"status", "doc_id", "error", "warnings", "file_name"}


def _db_path(explicit: str | None) -> str:
    path = explicit or get_settings().documents_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("warnings"), str):
        try:
            out["warnings"] = json.loads(out["warnings"])
        except json.JSONDecodeError:
            out["warnings"] = []
    return out


def create_job(file_name: str, *, db_path: str | None = None) -> str:
    job_id = str(uuid.uuid4())
    now = _now()
    conn = _connect(_db_path(db_path))
    try:
        conn.execute(
            """
            INSERT INTO jobs (job_id, file_name, status, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, ?)
            """,
            (job_id, file_name, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


def update_job(
    job_id: str,
    *,
    db_path: str | None = None,
    **fields: Any,
) -> None:
    updates: list[str] = []
    params: list[Any] = []

    for key, value in fields.items():
        if key not in _UPDATABLE:
            continue
        if key == "warnings" and not isinstance(value, str):
            value = json.dumps(value or [])
        updates.append(f"{key} = ?")
        params.append(value)

    if not updates:
        return

    updates.append("updated_at = ?")
    params.append(_now())
    params.append(job_id)

    conn = _connect(_db_path(db_path))
    try:
        conn.execute(
            f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def get_job(job_id: str, *, db_path: str | None = None) -> dict[str, Any] | None:
    conn = _connect(_db_path(db_path))
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def list_jobs(
    *,
    limit: int = 50,
    status: str | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM jobs"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    conn = _connect(_db_path(db_path))
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(row) for row in rows]
