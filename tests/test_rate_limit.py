from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from citerator.api import rate_limit
from citerator.api.app import create_app
from citerator.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "RUNTIME_CONFIG_DB_PATH", str(tmp_path / "runtime_config.sqlite")
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _settings(tmp_path: Path, rpm: int) -> Settings:
    return Settings(
        documents_root=str(tmp_path / "raw"),
        documents_db_path=str(tmp_path / "documents.sqlite"),
        eval_db_path=str(tmp_path / "eval.sqlite"),
        runtime_config_db_path=str(tmp_path / "runtime_config.sqlite"),
        api_key="secret",
        rate_limit_requests_per_minute=rpm,
    )


def test_requests_under_limit_succeed(tmp_path: Path, monkeypatch) -> None:
    s = _settings(tmp_path, rpm=5)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: s
    monkeypatch.setattr(
        rate_limit, "get_effective_settings", lambda: s
    )
    client = TestClient(app)

    for i in range(5):
        r = client.get("/documents", headers={"X-API-Key": "secret"})
        assert r.status_code == 200, f"request {i + 1} -> {r.status_code}"


def test_limit_exceeded_returns_429_with_retry_after(
    tmp_path: Path, monkeypatch
) -> None:
    s = _settings(tmp_path, rpm=3)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: s
    monkeypatch.setattr(
        rate_limit, "get_effective_settings", lambda: s
    )
    client = TestClient(app)

    for i in range(3):
        r = client.get("/documents", headers={"X-API-Key": "secret"})
        assert r.status_code == 200

    r = client.get("/documents", headers={"X-API-Key": "secret"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    body = r.json()
    assert body["error"] == "rate_limited"
    assert body["retry_after_seconds"] > 0


def test_health_is_exempt(tmp_path: Path, monkeypatch) -> None:
    s = _settings(tmp_path, rpm=1)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: s
    monkeypatch.setattr(
        rate_limit, "get_effective_settings", lambda: s
    )
    client = TestClient(app)

    for _ in range(5):
        r = client.get("/health")
        assert r.status_code == 200


def test_window_resets_counter() -> None:
    # exercise _check directly, avoiding a 60s wait
    mw = rate_limit.RateLimitMiddleware(app=None)  # type: ignore[arg-type]
    key = "test-key"

    for _ in range(3):
        allowed, _ = mw._check(key, 3)
        assert allowed

    allowed, retry = mw._check(key, 3)
    assert not allowed
    assert retry > 0

    # Force the stored window to be older than one full window
    count, window = mw._counters[key]
    mw._counters[key] = (count, window - 2 * rate_limit._WINDOW_SECONDS)

    allowed, _ = mw._check(key, 3)
    assert allowed


def test_different_keys_have_separate_buckets(
    tmp_path: Path, monkeypatch
) -> None:
    s = _settings(tmp_path, rpm=2)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: s
    monkeypatch.setattr(
        rate_limit, "get_effective_settings", lambda: s
    )
    client = TestClient(app)

    for _ in range(2):
        assert (
            client.get("/documents", headers={"X-API-Key": "aaa"}).status_code
            == 200
        )
    assert (
        client.get("/documents", headers={"X-API-Key": "aaa"}).status_code
        == 429
    )
    # Different key: fresh bucket
    assert (
        client.get("/documents", headers={"X-API-Key": "bbb"}).status_code
        == 200
    )
