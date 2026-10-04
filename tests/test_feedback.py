from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from citerator.api.app import create_app
from citerator.config import Settings, get_settings
from citerator.observability import store, tracing
from citerator.observability.tracing import FakeTracer


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
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


_HEADERS = {"X-API-Key": "secret"}


def test_feedback_persists_row(client: TestClient, settings: Settings) -> None:
    r = client.post(
        "/feedback",
        json={"trace_id": "t1", "rating": "up", "comment": "spot on"},
        headers=_HEADERS,
    )
    assert r.status_code == 201, r.text
    assert r.json()["trace_id"] == "t1"
    assert r.json()["rating"] == "up"

    rows = store.list_feedback(db_path=settings.observability_db_path)
    assert len(rows) == 1
    assert rows[0]["comment"] == "spot on"


def test_feedback_forwards_score_when_tracer_is_not_null(
    client: TestClient, settings: Settings, monkeypatch
) -> None:
    fake = FakeTracer()
    monkeypatch.setattr(tracing, "_tracer_singleton", fake)

    r = client.post(
        "/feedback",
        json={"trace_id": "tX", "rating": "down"},
        headers=_HEADERS,
    )
    assert r.status_code == 201

    assert len(fake.scores) == 1
    assert fake.scores[0]["value"] == 0.0
    assert fake.scores[0]["trace_id"] == "tX"


def test_feedback_rejects_missing_api_key(client: TestClient) -> None:
    r = client.post(
        "/feedback", json={"trace_id": "t1", "rating": "up"}
    )
    assert r.status_code == 401


def test_feedback_rejects_invalid_rating(client: TestClient) -> None:
    r = client.post(
        "/feedback",
        json={"trace_id": "t1", "rating": "meh"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
