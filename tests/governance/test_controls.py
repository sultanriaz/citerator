from __future__ import annotations

from citerator.config import get_settings
from citerator.governance import audit, controls


def test_controls_returns_all_registered_controls():
    report = controls.evaluate_all()
    ids = {c["id"] for c in report["controls"]}
    expected = {
        "audit_chain_integrity",
        "audit_chain_fresh",
        "human_oversight",
        "confidence_gating",
        "data_classification",
        "retention_policy",
        "erasure_capability",
        "model_provenance",
        "evaluation_fresh",
    }
    assert expected <= ids


def test_confidence_gating_detects_configured_floor():
    s = get_settings()
    object.__setattr__(s, "confidence_floor", 0.0)
    status, _ = controls._check_confidence_gating(s)
    assert status == "fail"

    object.__setattr__(s, "confidence_floor", 0.15)
    object.__setattr__(s, "confidence_threshold", 0.30)
    status, _ = controls._check_confidence_gating(s)
    assert status == "pass"


def test_audit_integrity_pass_and_fail_paths():
    # Empty chain -> partial
    status, _ = controls._check_audit_chain_integrity(get_settings())
    assert status in ("partial", "pass")

    audit.append("test", {"x": 1})
    status, _ = controls._check_audit_chain_integrity(get_settings())
    assert status == "pass"

    import sqlite3
    s = get_settings()
    conn = sqlite3.connect(s.governance_db_path)
    conn.execute("UPDATE audit_chain SET record_hash = 'bad' WHERE sequence = 1")
    conn.commit()
    conn.close()

    status, _ = controls._check_audit_chain_integrity(s)
    assert status == "fail"


def test_overall_status_reflects_worst():
    report = controls.evaluate_all()
    statuses = {c["status"] for c in report["controls"]}
    if "fail" in statuses:
        assert report["overall"] == "fail"
    elif "partial" in statuses:
        assert report["overall"] == "partial"
    else:
        assert report["overall"] == "pass"


def test_frameworks_bucket_is_populated():
    report = controls.evaluate_all()
    assert "EU_AI_ACT" in report["frameworks"]
    assert "ISO_42001" in report["frameworks"]
    assert "NIST_AI_RMF" in report["frameworks"]
    assert "SOC_2" in report["frameworks"]
    for fw, payload in report["frameworks"].items():
        assert "controls" in payload
        assert "summary" in payload