from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import citerator.generation.answer as answer_module
from citerator.api.app import create_app
from citerator.config import Settings, get_settings
from citerator.generation.answer import AnswerResult
from citerator.observability import tracing


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RUNTIME_CONFIG_DB_PATH", str(tmp_path / "rt.sqlite"))
    from citerator.config import base_settings
    base_settings.cache_clear()
    tracing.reset_tracer_cache()
    yield
    base_settings.cache_clear()
    tracing.reset_tracer_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key="secret",
        observability_db_path=str(tmp_path / "obs.sqlite"),
        runtime_config_db_path=str(tmp_path / "rt.sqlite"),
        enable_tracing=False,
        rate_limit_requests_per_minute=1000,
    )


@pytest.fixture
def client(settings: Settings, monkeypatch) -> TestClient:
    def fake_answer_question(*args, **kwargs):
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
    from citerator.api import routes as routes_module
    monkeypatch.setattr(routes_module, "answer_question", fake_answer_question)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


_HEADERS = {"X-API-Key": "secret", "Content-Type": "application/json"}


def test_query_returns_trace_header_even_without_langfuse(
    client: TestClient,
) -> None:
    r = client.post(
        "/query", json={"question": "What is the threshold?"}, headers=_HEADERS
    )
    assert r.status_code == 200
    assert "x-trace-id" in {k.lower() for k in r.headers.keys()}
    tid = r.headers.get("x-trace-id") or r.headers.get("X-Trace-Id")
    assert tid and len(tid) >= 8


def test_feedback_accepts_returned_trace_id(client: TestClient) -> None:
    r = client.post(
        "/query", json={"question": "q"}, headers=_HEADERS
    )
    tid = r.headers.get("x-trace-id") or r.headers.get("X-Trace-Id")
    assert tid

    r2 = client.post(
        "/feedback",
        json={"trace_id": tid, "rating": "up"},
        headers={"X-API-Key": "secret"},
    )
    assert r2.status_code == 201


def test_non_query_route_has_no_trace_header(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    keys = {k.lower() for k in r.headers.keys()}
    assert "x-trace-id" not in keys


def test_client_supplied_trace_id_is_echoed(client: TestClient) -> None:
    r = client.post(
        "/query",
        json={"question": "q"},
        headers={**_HEADERS, "X-Trace-Id": "my-custom-id-123"},
    )
    tid = r.headers.get("x-trace-id") or r.headers.get("X-Trace-Id")
    assert tid == "my-custom-id-123"
