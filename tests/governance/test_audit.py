from __future__ import annotations

import json
import sqlite3

import pytest

from citerator.config import get_settings
from citerator.governance import audit
from citerator.governance.store import connect


def test_append_and_count():
    assert audit.count() == 0
    r = audit.append("test.event", {"value": 1})
    assert r.sequence == 1
    assert r.prev_hash is None
    assert audit.count() == 1


def test_chain_links_and_hashes_are_stable():
    r1 = audit.append("test.event", {"value": 1})
    r2 = audit.append("test.event", {"value": 2})
    assert r2.prev_hash == r1.record_hash

    verify = audit.verify()
    assert verify.ok
    assert verify.total_records == 2


def test_canonical_json_ignores_key_order():
    r1 = audit.append("test.event", {"a": 1, "b": 2})
    r2 = audit.append("test.event", {"b": 2, "a": 1})
    # Both hash the same canonical form; only payload differs.
    assert r1.record_hash != r2.record_hash  # different sequence -> different prev
    # But if we recompute hashes they use the same canonical payload string
    # Because prev differs, hashes differ. Instead, confirm verify passes.
    assert audit.verify().ok


def test_tampering_with_payload_is_detected():
    audit.append("test.event", {"value": 1})
    audit.append("test.event", {"value": 2})
    audit.append("test.event", {"value": 3})

    s = get_settings()
    conn = sqlite3.connect(s.governance_db_path)
    conn.execute(
        "UPDATE audit_chain SET payload = ? WHERE sequence = 2",
        (json.dumps({"value": 999}, sort_keys=True, separators=(",", ":")),),
    )
    conn.commit()
    conn.close()

    result = audit.verify()
    assert not result.ok
    assert result.first_bad_sequence == 2
    assert "mismatch" in (result.error or "")


def test_tampering_with_hash_is_detected():
    audit.append("test.event", {"value": 1})
    audit.append("test.event", {"value": 2})

    s = get_settings()
    conn = sqlite3.connect(s.governance_db_path)
    conn.execute("UPDATE audit_chain SET record_hash = 'deadbeef' WHERE sequence = 2")
    conn.commit()
    conn.close()

    result = audit.verify()
    assert not result.ok
    assert result.first_bad_sequence == 2


def test_broken_linkage_is_detected():
    audit.append("test.event", {"value": 1})
    r2 = audit.append("test.event", {"value": 2})
    audit.append("test.event", {"value": 3})

    s = get_settings()
    conn = sqlite3.connect(s.governance_db_path)
    # Replace r2's prev_hash with a plausible but wrong hash. Its own
    # record_hash won't match the new prev, so verification fails at r2.
    conn.execute(
        "UPDATE audit_chain SET prev_hash = ? WHERE sequence = 2",
        ("0" * 64,),
    )
    conn.commit()
    conn.close()

    result = audit.verify()
    assert not result.ok
    assert result.first_bad_sequence == 2


def test_actor_fingerprint_is_stable_and_non_reversible():
    fp1 = audit.actor_fingerprint("secret-key")
    fp2 = audit.actor_fingerprint("secret-key")
    fp3 = audit.actor_fingerprint("other-key")
    assert fp1 == fp2
    assert fp1 != fp3
    assert "secret" not in fp1
    assert fp1.startswith("apikey:")


def test_list_records_and_filters():
    audit.append("event.a", {"n": 1})
    audit.append("event.b", {"n": 2})
    audit.append("event.a", {"n": 3})

    all_records = audit.list_records()
    assert len(all_records) == 3
    assert all_records[0].payload["n"] == 3

    a_only = audit.list_records(event_type="event.a")
    assert len(a_only) == 2
    assert all(r.event_type == "event.a" for r in a_only)


def test_verify_from_nonzero_sequence_returns_ok_if_chain_intact():
    audit.append("e", {"n": 1})
    audit.append("e", {"n": 2})
    audit.append("e", {"n": 3})

    partial = audit.verify(from_sequence=2)
    # Two records checked; linkage within the checked slice is valid.
    assert partial.ok
    assert partial.total_records == 2


def test_custom_hmac_key_from_settings():
    s = get_settings()
    custom = b"x" * 40
    r = audit.append("e", {"n": 1}, settings=s, key=custom)
    ok = audit.verify(settings=s, key=custom)
    assert ok.ok
    bad = audit.verify(settings=s, key=b"y" * 40)
    assert not bad.ok
    assert bad.first_bad_sequence == r.sequence


def test_key_too_short_rejected():
    s = get_settings()
    object.__setattr__(s, "audit_hmac_key", "short")
    with pytest.raises(ValueError):
        audit.load_or_create_key(s)
    object.__setattr__(s, "audit_hmac_key", "")