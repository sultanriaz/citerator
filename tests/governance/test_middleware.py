from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from citerator.api.app import create_app
from citerator.config import Settings, get_settings
from citerator.governance import audit


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    monkeypatch.setenv(
        "GOVERNANCE_DB_PATH", str(tmp_path / "gov.sqlite")
    )
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-key-32-bytes-long-for-hmac-ok")
    monkeypatch.setenv("AUDIT_REQUIRED", "false")
    get_settings.cache_clear()
    s = Settings(
        api_key="secret",
        observability_db_path=str(tmp_path / "obs.sqlite"),
        runtime_config_db_path=str(tmp_path / "rt.sqlite"),
        governance_db_path=str(tmp_path / "gov.sqlite"),
        audit_hmac_key="test-key-32-bytes-long-for-hmac-ok",
        audit_required=False,
        enable_tracing=False,
        rate_limit_requests_per_minute=1000,
    )
    return s


@pytest.fixture
def client(settings: Settings, monkeypatch) -> TestClient:
    import citerator.generation.answer as answer_module

    def fake_answer_question(*args, **kwargs):
        from citerator.generation.answer import AnswerResult
        return AnswerResult(
            state="confident",
            answer="ok [1]",
            confidence=0.9,
            citations=[],
            related_passages=[],
            escalation_draft=None,
            latency_ms={"total": 1.0},
            tokens=None,
            retrieval_details=None,
        )

    monkeypatch.setattr(answer_module, "answer_question", fake_answer_question)
    

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_query_creates_audit_record(client: TestClient) -> None:
    before = audit.count()
    r = client.post(
        "/query",
        json={"question": "What is the threshold?"},
        headers={"X-API-Key": "secret", "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    after = audit.count()
    assert after == before + 1

    records = audit.list_records(event_type="query", limit=1)
    assert records
    payload = records[0].payload
    assert payload["question"] == "What is the threshold?"
    assert payload["state"] == "confident"
    assert payload["path"] == "/query"


def test_unrelated_path_does_not_audit(client: TestClient) -> None:
    before = audit.count()
    r = client.get("/health")
    assert r.status_code == 200
    assert audit.count() == before


def test_chain_verifies_after_multiple_requests(client: TestClient) -> None:
    for _ in range(3):
        client.post(
            "/query",
            json={"question": "q"},
            headers={"X-API-Key": "secret", "Content-Type": "application/json"},
        )
    result = audit.verify()
    assert result.ok


def test_audit_required_returns_503_when_write_fails(
    settings: Settings, monkeypatch
) -> None:
    """Simulate a broken governance DB and confirm the middleware fails
    closed when audit_required is True."""

    import citerator.api.middleware.audit as audit_mw

    settings_with_required = settings.model_copy(update={"audit_required": True})

    def boom(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(audit_mw.audit, "append", boom)
    monkeypatch.setattr(audit_mw, "get_settings", lambda: settings_with_required)

    import citerator.generation.answer as answer_module
    from citerator.generation.answer import AnswerResult

    def fake_answer_question(*args, **kwargs):
        return AnswerResult(
            state="confident",
            answer="ok",
            confidence=0.9,
            citations=[],
            related_passages=[],
            escalation_draft=None,
            latency_ms={"total": 1.0},
            tokens=None,
            retrieval_details=None,
        )

    monkeypatch.setattr(answer_module, "answer_question", fake_answer_question)
    

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings_with_required
    c = TestClient(app)

    r = c.post(
        "/query",
        json={"question": "q"},
        headers={"X-API-Key": "secret", "Content-Type": "application/json"},
    )
    assert r.status_code == 503
    assert r.json()["error"] == "audit_write_failed"