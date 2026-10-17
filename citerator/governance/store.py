"""SQLite connection and schema for the governance database.

Separate from documents.sqlite and eval.sqlite on purpose: governance data
has different retention, backup, and access requirements. WAL mode for
concurrent reads during writes. BEGIN IMMEDIATE on the audit chain
serializes writers without blocking readers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from citerator.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_chain (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence     INTEGER NOT NULL UNIQUE,
    timestamp    TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    actor        TEXT,
    payload      TEXT NOT NULL,
    prev_hash    TEXT,
    record_hash  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_chain(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp  ON audit_chain(timestamp);

CREATE TABLE IF NOT EXISTS document_versions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id                TEXT NOT NULL,
    version               INTEGER NOT NULL,
    doc_hash              TEXT NOT NULL,
    source_file           TEXT NOT NULL,
    chunk_count           INTEGER,
    effective_from        TEXT NOT NULL,
    effective_to          TEXT,
    superseded_by_version INTEGER,
    ingested_by           TEXT,
    reason                TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE(doc_id, version)
);
CREATE INDEX IF NOT EXISTS idx_versions_doc ON document_versions(doc_id);

CREATE TABLE IF NOT EXISTS document_classification (
    doc_id              TEXT PRIMARY KEY,
    classification      TEXT NOT NULL,
    retention_days      INTEGER,
    contains_pii        INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at    TEXT,
    review_cycle_days   INTEGER,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retention_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT NOT NULL,
    action          TEXT NOT NULL,
    reason          TEXT NOT NULL,
    performed_at    TEXT NOT NULL,
    performed_by    TEXT,
    chunks_deleted  INTEGER,
    audit_sequence  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_retention_doc ON retention_actions(doc_id);
"""

ALLOWED_CLASSIFICATIONS = (
    "public",
    "internal",
    "restricted",
    "client_confidential",
)


def db_path(explicit: str | None = None) -> str:
    path = explicit or get_settings().governance_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn