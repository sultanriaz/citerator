from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from citerator.api.app import create_app
from citerator.config import Settings, get_settings


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    monkeypatch.setenv("GOVERNANCE_DB_PATH", str(tmp_path / "gov.sqlite"))
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-key-32-bytes-long-for-hmac-ok")
    monkeypatch.setenv("AUDIT_REQUIRED", "false")
    get_settings.cache_clear()
    return Settings(
        api_key="secret",
        governance_db_path=str(tmp_path / "gov.sqlite"),
        audit_hmac_key="test-key-32-bytes-long-for-hmac-ok",
        audit_required=False,
        enable_tracing=False,
        rate_limit_requests_per_minute=1000,
        runtime_config_db_path=str(tmp_path / "rt.sqlite"),
        observability_db_path=str(tmp_path / "obs.sqlite"),
        documents_db_path=str(tmp_path / "docs.sqlite"),
        eval_db_path=str(tmp_path / "eval.sqlite"),
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


_HEADERS = {"X-API-Key": "secret"}


def test_all_governance_routes_require_api_key(client: TestClient) -> None:
    probes = [
        ("GET", "/governance/audit"),
        ("GET", "/governance/audit/verify"),
        ("GET", "/governance/audit/export"),
        ("GET", "/governance/documents/abc/versions"),
        ("GET", "/governance/documents/abc/classification"),
        ("PUT", "/governance/documents/abc/classification"),
        ("POST", "/governance/documents/abc/review"),
        ("POST", "/governance/retention/due"),
        ("POST", "/governance/retention/purge"),
        ("POST", "/governance/erasure"),
        ("GET", "/governance/controls"),
    ]
    for method, path in probes:
        r = client.request(method, path, json={})
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


def test_classification_round_trip(client: TestClient) -> None:
    r = client.put(
        "/governance/documents/doc-1/classification",
        json={
            "classification": "restricted",
            "retention_days": 90,
            "contains_pii": True,
            "review_cycle_days": 30,
        },
        headers=_HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["classification"] == "restricted"

    r2 = client.get(
        "/governance/documents/doc-1/classification", headers=_HEADERS
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["retention_days"] == 90
    assert body["contains_pii"] is True
    assert "review_due" in body


def test_invalid_classification_rejected(client: TestClient) -> None:
    r = client.put(
        "/governance/documents/doc-1/classification",
        json={
            "classification": "secret",
            "retention_days": None,
            "contains_pii": False,
            "review_cycle_days": None,
        },
        headers=_HEADERS,
    )
    assert r.status_code == 422


def test_audit_endpoints(client: TestClient) -> None:
    # Generate an event via the classification change
    client.put(
        "/governance/documents/x/classification",
        json={
            "classification": "internal",
            "retention_days": None,
            "contains_pii": False,
            "review_cycle_days": None,
        },
        headers=_HEADERS,
    )

    r = client.get("/governance/audit?limit=10", headers=_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(
        rec["event_type"] == "document.classification.changed"
        for rec in body["records"]
    )

    v = client.get("/governance/audit/verify", headers=_HEADERS)
    assert v.status_code == 200
    assert v.json()["ok"] is True

    e = client.get("/governance/audit/export", headers=_HEADERS)
    assert e.status_code == 200
    assert e.json()["chain_verification"]["ok"] is True


def test_versions_endpoint_returns_empty_for_unknown_doc(client: TestClient) -> None:
    r = client.get("/governance/documents/nope/versions", headers=_HEADERS)
    assert r.status_code == 200
    assert r.json()["versions"] == []


def test_controls_endpoint(client: TestClient) -> None:
    r = client.get("/governance/controls", headers=_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "overall" in body
    assert "controls" in body
    assert "frameworks" in body
    assert body["overall"] in {"pass", "partial", "fail"}


def test_erasure_endpoint_dry_run(client: TestClient, monkeypatch) -> None:
    def fake_find(subject, case_sensitive=False):
        return ([], 0, False)

    monkeypatch.setattr(
        "citerator.governance.erasure.find_matches", fake_find
    )

    r = client.post(
        "/governance/erasure",
        json={"subject": "John Smith", "dry_run": True},
        headers=_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["matched_chunks"] == 0


def test_retention_due_endpoint(client: TestClient) -> None:
    r = client.post("/governance/retention/due", headers=_HEADERS)
    assert r.status_code == 200
    assert "count" in r.json()