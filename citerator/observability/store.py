"""SQLite persistence for feedback and escalations.

Same pattern as documents/registry.py and evaluation/store.py: raw sqlite3,
parameterized queries, CREATE TABLE IF NOT EXISTS, no ORM.

feedback rows capture the answer card's thumbs up/down per X-Trace-Id.
escalations rows capture the "Flag for review" and "Escalate to a human"
actions. Passages are stored as JSON arrays of the same lightweight shape
returned by GET /eval/runs/{id} -- chunk_id, doc_title, section_path, page
range, excerpt -- so the two endpoints render consistently in a UI.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from citerator.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    rating      TEXT NOT NULL,
    comment     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_trace ON feedback(trace_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at);

CREATE TABLE IF NOT EXISTS escalations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id            TEXT,
    source              TEXT NOT NULL,
    question            TEXT NOT NULL,
    passages            TEXT NOT NULL,
    note                TEXT NOT NULL,
    status              TEXT NOT NULL,
    resolution_note     TEXT,
    webhook_delivered   INTEGER NOT NULL DEFAULT 0,
    webhook_error       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status);
CREATE INDEX IF NOT EXISTS idx_escalations_created ON escalations(created_at);
CREATE INDEX IF NOT EXISTS idx_escalations_trace ON escalations(trace_id);
"""


def _db_path(explicit: str | None = None) -> str:
    path = explicit or get_settings().observability_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _escalation_row(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("passages"), str):
        try:
            out["passages"] = json.loads(out["passages"])
        except json.JSONDecodeError:
            out["passages"] = []
    out["webhook_delivered"] = bool(out.get("webhook_delivered"))
    return out


def add_feedback(
    trace_id: str,
    rating: str,
    comment: str | None = None,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    conn = _connect(_db_path(db_path))
    try:
        cur = conn.execute(
            """
            INSERT INTO feedback (trace_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (trace_id, rating, comment, _now()),
        )
        conn.commit()
        row_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT * FROM feedback WHERE id = ?", (row_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row)


def list_feedback(
    trace_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    *,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM feedback"
    params: list[Any] = []
    if trace_id:
        sql += " WHERE trace_id = ?"
        params.append(trace_id)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = _connect(_db_path(db_path))
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def create_escalation(
    *,
    trace_id: str | None,
    source: str,
    question: str,
    passages: list[dict[str, Any]],
    note: str,
    status: str = "open",
    webhook_delivered: bool = False,
    webhook_error: str | None = None,
    db_path: str | None = None,
) -> int:
    now = _now()
    conn = _connect(_db_path(db_path))
    try:
        cur = conn.execute(
            """
            INSERT INTO escalations (
                trace_id, source, question, passages, note, status,
                resolution_note, webhook_delivered, webhook_error,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                trace_id,
                source,
                question,
                json.dumps(passages or []),
                note,
                status,
                1 if webhook_delivered else 0,
                webhook_error,
                now,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_escalation(
    escalation_id: int, *, db_path: str | None = None
) -> dict[str, Any] | None:
    conn = _connect(_db_path(db_path))
    try:
        row = conn.execute(
            "SELECT * FROM escalations WHERE id = ?", (escalation_id,)
        ).fetchone()
    finally:
        conn.close()
    return _escalation_row(row) if row else None


def list_escalations(
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM escalations"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = _connect(_db_path(db_path))
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_escalation_row(r) for r in rows]


def update_escalation_status(
    escalation_id: int,
    status: str,
    resolution_note: str | None = None,
    *,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    conn = _connect(_db_path(db_path))
    try:
        conn.execute(
            """
            UPDATE escalations
            SET status = ?, resolution_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, resolution_note, _now(), escalation_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM escalations WHERE id = ?", (escalation_id,)
        ).fetchone()
    finally:
        conn.close()
    return _escalation_row(row) if row else None
