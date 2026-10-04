"""SQLite-backed runtime overrides for a subset of Settings fields.

Only fields in OVERRIDABLE_FIELDS can be set. Validation runs against the
FULL merged state for cross-field rules, but per-field enum checks
(strategy, provider) run only on fields present in the partial update --
otherwise an out-of-allowlist value in the base env would block unrelated
writes.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from citerator.config import Settings, get_settings

OVERRIDABLE_FIELDS: set[str] = {
    "active_chunking_strategy",
    "top_k_retrieve",
    "top_k_rerank",
    "rerank_model",
    "confidence_threshold",
    "confidence_floor",
    "llm_provider",
    "llm_model",
    "api_key",
}

REQUIRES_REINGESTION_FIELDS: set[str] = {
    "embedding_model",
    "embedder_kind",
}

ALLOWED_CHUNKING_STRATEGIES = {"fixed", "structure", "semantic"}
ALLOWED_LLM_PROVIDERS = {"openai", "anthropic", "gemini", "google", "fake"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_overrides (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _db_path(explicit: str | None = None) -> str:
    path = explicit or get_settings().runtime_config_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_overrides(*, db_path: str | None = None) -> dict[str, Any]:
    conn = _connect(_db_path(db_path))
    try:
        rows = conn.execute(
            "SELECT key, value FROM runtime_overrides"
        ).fetchall()
    finally:
        conn.close()

    out: dict[str, Any] = {}
    for row in rows:
        try:
            out[row["key"]] = json.loads(row["value"])
        except json.JSONDecodeError:
            continue
    return out


def _validate_merged(
    base: Settings, overrides: dict[str, Any], partial: dict[str, Any]
) -> None:
    merged = base.model_dump()
    merged.update(overrides)

    if "active_chunking_strategy" in partial:
        strategy = merged.get("active_chunking_strategy")
        if strategy not in ALLOWED_CHUNKING_STRATEGIES:
            raise ValueError(
                f"active_chunking_strategy must be one of "
                f"{sorted(ALLOWED_CHUNKING_STRATEGIES)}"
            )

    if "llm_provider" in partial:
        provider = (merged.get("llm_provider") or "").lower()
        if provider and provider not in ALLOWED_LLM_PROVIDERS:
            raise ValueError(
                f"llm_provider must be one of {sorted(ALLOWED_LLM_PROVIDERS)}"
            )

    if "top_k_retrieve" in partial or "top_k_rerank" in partial:
        k_retrieve = merged.get("top_k_retrieve")
        k_rerank = merged.get("top_k_rerank")
        if isinstance(k_retrieve, int) and isinstance(k_rerank, int):
            if k_rerank > k_retrieve:
                raise ValueError("top_k_rerank must be <= top_k_retrieve")

    if "confidence_floor" in partial or "confidence_threshold" in partial:
        floor = merged.get("confidence_floor")
        threshold = merged.get("confidence_threshold")
        if isinstance(floor, (int, float)) and isinstance(threshold, (int, float)):
            if floor >= threshold:
                raise ValueError(
                    "confidence_floor must be less than confidence_threshold"
                )

    try:
        type(base).model_validate(merged)
    except Exception as exc:
        raise ValueError(f"invalid configuration: {exc}") from exc


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    if not partial:
        return get_overrides(db_path=db_path)

    for key in partial:
        if key in REQUIRES_REINGESTION_FIELDS:
            raise ValueError(
                f"{key} is not overridable at runtime -- changing it changes "
                f"the target Qdrant collection and requires re-ingestion "
                f"(Phase 2/4), not a Settings update"
            )
        if key not in OVERRIDABLE_FIELDS:
            raise ValueError(f"{key} is not overridable at runtime")

    base = get_settings()
    existing = get_overrides(db_path=db_path)
    _validate_merged(base, {**existing, **partial}, partial)

    conn = _connect(_db_path(db_path))
    try:
        for key, value in partial.items():
            conn.execute(
                """
                INSERT INTO runtime_overrides (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), _now()),
            )
        conn.commit()
    finally:
        conn.close()

    return get_overrides(db_path=db_path)


def reset_overrides(
    keys: list[str] | None = None,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    conn = _connect(_db_path(db_path))
    try:
        if keys is None:
            conn.execute("DELETE FROM runtime_overrides")
        else:
            if not keys:
                return get_overrides(db_path=db_path)
            placeholders = ",".join("?" for _ in keys)
            conn.execute(
                f"DELETE FROM runtime_overrides WHERE key IN ({placeholders})",
                keys,
            )
        conn.commit()
    finally:
        conn.close()
    return get_overrides(db_path=db_path)
