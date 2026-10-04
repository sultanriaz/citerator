"""SQLite-backed store for evaluation runs and per-question results.

Same pattern as documents/registry.py: raw sqlite3, CREATE TABLE IF NOT
EXISTS, parameterized queries, no ORM. Chunk text is never persisted here --
only chunk_ids; the API resolves them against Qdrant at read time.
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
CREATE TABLE IF NOT EXISTS runs (
    run_id                  TEXT PRIMARY KEY,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    status                  TEXT NOT NULL,
    label                   TEXT,
    question_set_path       TEXT,
    chunking_strategy       TEXT,
    embedder                TEXT,
    sparse_embedder         TEXT,
    rerank_model            TEXT,
    llm_provider            TEXT,
    llm_model               TEXT,
    top_k_retrieve          INTEGER,
    top_k_rerank            INTEGER,
    confidence_threshold    REAL,
    confidence_floor        REAL,
    question_count          INTEGER DEFAULT 0,
    questions_completed     INTEGER DEFAULT 0,
    error                   TEXT,
    faithfulness_mean       REAL,
    answer_relevancy_mean   REAL,
    context_precision_mean  REAL,
    context_recall_mean     REAL,
    latency_p50_ms          REAL,
    latency_p95_ms          REAL,
    cost_per_query_usd_mean REAL,
    safety_refuse_pct       REAL,
    safety_escalate_pct     REAL
);
CREATE INDEX IF NOT EXISTS idx_runs_status     ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);

CREATE TABLE IF NOT EXISTS question_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    question            TEXT NOT NULL,
    category            TEXT,
    expected_behavior   TEXT,
    ground_truth        TEXT,
    state               TEXT,
    passed              INTEGER,
    faithfulness        REAL,
    answer_relevancy    REAL,
    context_precision   REAL,
    context_recall      REAL,
    latency_ms          REAL,
    cost_usd            REAL,
    answer_text         TEXT,
    retrieved_chunk_ids TEXT,
    cited_chunk_ids     TEXT,
    error               TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_qr_run_id ON question_results(run_id);
CREATE INDEX IF NOT EXISTS idx_qr_category ON question_results(category);
"""

_RUN_UPDATABLE = {
    "status", "label", "question_set_path", "question_count", "questions_completed",
    "error", "faithfulness_mean", "answer_relevancy_mean", "context_precision_mean",
    "context_recall_mean", "latency_p50_ms", "latency_p95_ms",
    "cost_per_query_usd_mean", "safety_refuse_pct", "safety_escalate_pct",
    "chunking_strategy", "embedder", "sparse_embedder", "rerank_model",
    "llm_provider", "llm_model", "top_k_retrieve", "top_k_rerank",
    "confidence_threshold", "confidence_floor",
}

_RESULT_FIELDS = {
    "question", "category", "expected_behavior", "ground_truth", "state", "passed",
    "faithfulness", "answer_relevancy", "context_precision", "context_recall",
    "latency_ms", "cost_usd", "answer_text", "retrieved_chunk_ids",
    "cited_chunk_ids", "error",
}


def _db_path(explicit: str | None) -> str:
    path = explicit or get_settings().eval_db_path
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
    for field in ("retrieved_chunk_ids", "cited_chunk_ids"):
        if isinstance(out.get(field), str):
            try:
                out[field] = json.loads(out[field])
            except json.JSONDecodeError:
                out[field] = []
    if isinstance(out.get("passed"), int):
        out["passed"] = bool(out["passed"])
    return out


def create_run(*, db_path: str | None = None, **fields: Any) -> str:
    run_id = str(uuid.uuid4())
    now = _now()
    payload = {
        "run_id": run_id,
        "created_at": now,
        "updated_at": now,
        "status": fields.get("status", "running"),
        "label": fields.get("label"),
        "question_set_path": fields.get("question_set_path"),
        "chunking_strategy": fields.get("chunking_strategy"),
        "embedder": fields.get("embedder"),
        "sparse_embedder": fields.get("sparse_embedder"),
        "rerank_model": fields.get("rerank_model"),
        "llm_provider": fields.get("llm_provider"),
        "llm_model": fields.get("llm_model"),
        "top_k_retrieve": fields.get("top_k_retrieve"),
        "top_k_rerank": fields.get("top_k_rerank"),
        "confidence_threshold": fields.get("confidence_threshold"),
        "confidence_floor": fields.get("confidence_floor"),
        "question_count": 0,
        "questions_completed": 0,
    }

    conn = _connect(_db_path(db_path))
    try:
        cols = ", ".join(payload.keys())
        marks = ", ".join("?" for _ in payload)
        conn.execute(f"INSERT INTO runs ({cols}) VALUES ({marks})", list(payload.values()))
        conn.commit()
    finally:
        conn.close()
    return run_id


def update_run(run_id: str, *, db_path: str | None = None, **fields: Any) -> None:
    updates: list[str] = []
    params: list[Any] = []

    for key, value in fields.items():
        if key not in _RUN_UPDATABLE:
            continue
        updates.append(f"{key} = ?")
        params.append(value)

    if not updates:
        return

    updates.append("updated_at = ?")
    params.append(_now())
    params.append(run_id)

    conn = _connect(_db_path(db_path))
    try:
        conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?", params)
        conn.commit()
    finally:
        conn.close()


def get_run(run_id: str, *, db_path: str | None = None) -> dict[str, Any] | None:
    conn = _connect(_db_path(db_path))
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_runs(
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM runs"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = _connect(_db_path(db_path))
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def add_question_result(run_id: str, *, db_path: str | None = None, **fields: Any) -> int:
    payload: dict[str, Any] = {"run_id": run_id}
    for key, value in fields.items():
        if key not in _RESULT_FIELDS:
            continue
        if key in ("retrieved_chunk_ids", "cited_chunk_ids") and not isinstance(value, str):
            value = json.dumps(value or [])
        if key == "passed" and value is not None:
            value = 1 if value else 0
        payload[key] = value

    cols = ", ".join(payload.keys())
    marks = ", ".join("?" for _ in payload)

    conn = _connect(_db_path(db_path))
    try:
        cur = conn.execute(
            f"INSERT INTO question_results ({cols}) VALUES ({marks})",
            list(payload.values()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_question_results(
    run_id: str,
    *,
    category: str | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM question_results WHERE run_id = ?"
    params: list[Any] = [run_id]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY id ASC"

    conn = _connect(_db_path(db_path))
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]
