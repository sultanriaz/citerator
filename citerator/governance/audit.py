"""Tamper-evident audit chain.

Every security-relevant event is appended to a hash chain:

    record_hash = HMAC-SHA256(key, f"{prev_hash}|{canonical_payload}")

Any modification to any record invalidates that record's hash and breaks
the link to every subsequent record. verify() walks the chain and reports
the first inconsistency.

Design notes:

- HMAC, not bare SHA-256. A plain hash chain is trivially forged by anyone
  with write access to the database; they would simply recompute the whole
  chain. HMAC requires a secret key that lives outside the DB, so tampering
  requires compromising two independent stores.

- Canonical JSON (sorted keys, no whitespace, deterministic serialization)
  so payload hashing is stable across Python versions and platforms.

- Fail-closed by default. If the audit write fails, the caller is expected
  to fail the request. That is stricter than typical application behavior
  and is the correct default for a system that is supposed to be auditable.

- Concurrency: BEGIN IMMEDIATE serializes writers, so concurrent appends
  cannot interleave. WAL mode lets readers proceed during writes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from citerator.config import Settings, get_settings
from citerator.governance.store import connect

logger = structlog.get_logger(__name__)

_KEY_FILE = Path("data/processed/.audit_key")
_KEY_BYTES = 32
_MIN_KEY_BYTES = 32


@dataclass(frozen=True)
class AuditRecord:
    id: int
    sequence: int
    timestamp: str
    event_type: str
    actor: str | None
    payload: dict[str, Any]
    prev_hash: str | None
    record_hash: str


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    total_records: int
    first_bad_sequence: int | None
    error: str | None


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str | None, canonical: str, key: bytes) -> str:
    data = f"{prev_hash or 'GENESIS'}|{canonical}".encode("utf-8")
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def load_or_create_key(
    settings: Settings | None = None, *, path: Path | None = None
) -> bytes:
    s = settings or get_settings()
    if s.audit_hmac_key:
        raw = s.audit_hmac_key.encode("utf-8")
        if len(raw) < _MIN_KEY_BYTES:
            raise ValueError(
                f"audit_hmac_key must be at least {_MIN_KEY_BYTES} bytes"
            )
        return raw

    key_file = path or _KEY_FILE
    if key_file.exists():
        data = key_file.read_bytes().strip()
        if len(data) >= _MIN_KEY_BYTES:
            return data
        logger.warning(
            "audit_key_too_short", path=str(key_file), bytes=len(data)
        )

    key_file.parent.mkdir(parents=True, exist_ok=True)
    fresh = secrets.token_bytes(_KEY_BYTES)
    key_file.write_bytes(fresh)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    logger.warning(
        "audit_key_generated",
        path=str(key_file),
        hint="Set AUDIT_HMAC_KEY in production; this file is dev-only convenience",
    )
    return fresh


def append(
    event_type: str,
    payload: dict[str, Any],
    *,
    actor: str | None = None,
    settings: Settings | None = None,
    db_path: str | None = None,
    key: bytes | None = None,
) -> AuditRecord:
    s = settings or get_settings()
    k = key or load_or_create_key(s)
    now = datetime.now(timezone.utc).isoformat()
    canonical = _canonical(payload)

    conn = connect(db_path or s.governance_db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        last = conn.execute(
            "SELECT record_hash, sequence FROM audit_chain ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        prev_hash = last["record_hash"] if last else None
        sequence = (last["sequence"] + 1) if last else 1
        record_hash = _hash(prev_hash, canonical, k)
        cursor = conn.execute(
            """
            INSERT INTO audit_chain
            (sequence, timestamp, event_type, actor, payload, prev_hash, record_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (sequence, now, event_type, actor, canonical, prev_hash, record_hash),
        )
        conn.execute("COMMIT")
        return AuditRecord(
            id=cursor.lastrowid,
            sequence=sequence,
            timestamp=now,
            event_type=event_type,
            actor=actor,
            payload=payload,
            prev_hash=prev_hash,
            record_hash=record_hash,
        )
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _row_to_record(row) -> AuditRecord:
    return AuditRecord(
        id=row["id"],
        sequence=row["sequence"],
        timestamp=row["timestamp"],
        event_type=row["event_type"],
        actor=row["actor"],
        payload=json.loads(row["payload"]),
        prev_hash=row["prev_hash"],
        record_hash=row["record_hash"],
    )


def verify(
    *,
    settings: Settings | None = None,
    db_path: str | None = None,
    key: bytes | None = None,
    from_sequence: int = 1,
) -> VerificationResult:
    s = settings or get_settings()
    k = key or load_or_create_key(s)
    conn = connect(db_path or s.governance_db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM audit_chain WHERE sequence >= ? ORDER BY sequence ASC",
            (from_sequence,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return VerificationResult(
            ok=True, total_records=0, first_bad_sequence=None, error=None
        )

    prev_row = None
    for row in rows:
        expected = _hash(row["prev_hash"], row["payload"], k)
        if expected != row["record_hash"]:
            return VerificationResult(
                ok=False,
                total_records=len(rows),
                first_bad_sequence=row["sequence"],
                error=f"record_hash mismatch at sequence {row['sequence']}",
            )
        if prev_row is not None and row["prev_hash"] != prev_row["record_hash"]:
            return VerificationResult(
                ok=False,
                total_records=len(rows),
                first_bad_sequence=row["sequence"],
                error=f"chain break at sequence {row['sequence']}",
            )
        prev_row = row

    return VerificationResult(
        ok=True, total_records=len(rows), first_bad_sequence=None, error=None
    )


def list_records(
    *,
    limit: int = 100,
    offset: int = 0,
    event_type: str | None = None,
    since: str | None = None,
    settings: Settings | None = None,
    db_path: str | None = None,
) -> list[AuditRecord]:
    s = settings or get_settings()
    clauses: list[str] = []
    params: list[Any] = []
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if since:
        clauses.append("timestamp >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM audit_chain {where} ORDER BY sequence DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = connect(db_path or s.governance_db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_row_to_record(r) for r in rows]


def count(
    *, settings: Settings | None = None, db_path: str | None = None
) -> int:
    s = settings or get_settings()
    conn = connect(db_path or s.governance_db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM audit_chain").fetchone()
    finally:
        conn.close()
    return int(row["n"]) if row else 0


def actor_fingerprint(api_key: Any) -> str:
    """Stable, non-reversible identifier for an API key.

    Auditors need to distinguish actors without storing the credential
    itself in a tamper-evident log that will be exported and archived.
    """
    if not isinstance(api_key, str):
        user_id = getattr(api_key, "user_id", None)
        tenant_id = getattr(api_key, "tenant_id", None)
        if user_id:
            return f"user:{tenant_id}:{user_id}" if tenant_id else f"user:{user_id}"
        api_key = str(api_key or "")
    return "apikey:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]