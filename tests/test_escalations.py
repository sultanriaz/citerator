from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from citerator.api import escalation_routes
from citerator.api.app import create_app
from citerator.config import Settings, get_settings
from citerator.observability import store, tracing


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
        escalation_webhook_url=None,
        enable_tracing=False,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


_HEADERS = {"X-API-Key": "secret"}


def test_create_and_fetch(client: TestClient, settings: Settings) -> None:
    payload = {
        "trace_id": "t1",
        "source": "escalated",
        "question": "Is this a PEP?",
        "passages": [
            {
                "chunk_id": "c1",
                "doc_title": "PEP Policy",
                "section_path": ["Section 1"],
                "page_start": 2,
                "page_end": 2,
                "excerpt": "A PEP is ...",
            }
        ],
        "note": "Ambiguous, needs review",
    }
    r = client.post("/escalations", json=payload, headers=_HEADERS)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["status"] == "open"
    assert row["webhook_delivered"] is False
    eid = row["id"]

    r2 = client.get(f"/escalations/{eid}", headers=_HEADERS)
    assert r2.status_code == 200
    assert r2.json()["question"] == "Is this a PEP?"


def test_webhook_failure_is_swallowed(
    client: TestClient, settings: Settings, monkeypatch
) -> None:
    settings_wh = settings.model_copy(
        update={"escalation_webhook_url": "http://example.invalid/hook"}
    )

    def boom(url, payload):
        return False, "connection refused"

    monkeypatch.setattr(escalation_routes, "_deliver_webhook", boom)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings_wh
    local = TestClient(app)

    payload = {
        "source": "flagged",
        "question": "q",
        "note": "note",
        "passages": [],
    }
    r = local.post("/escalations", json=payload, headers=_HEADERS)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["webhook_delivered"] is False
    assert body["webhook_error"] == "connection refused"

    stored = store.get_escalation(
        body["id"], db_path=settings_wh.observability_db_path
    )
    assert stored is not None
    assert stored["source"] == "flagged"
    assert stored["passages"] == []


def test_patch_status_and_validation(
    client: TestClient, settings: Settings
) -> None:
    r = client.post(
        "/escalations",
        json={
            "source": "flagged",
            "question": "q",
            "note": "n",
            "passages": [],
        },
        headers=_HEADERS,
    )
    eid = r.json()["id"]

    r2 = client.patch(
        f"/escalations/{eid}",
        json={"status": "acknowledged", "resolution_note": "in review"},
        headers=_HEADERS,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "acknowledged"
    assert r2.json()["resolution_note"] == "in review"

    r3 = client.patch(
        f"/escalations/{eid}",
        json={"status": "bogus"},
        headers=_HEADERS,
    )
    assert r3.status_code == 422


def test_list_filter_and_404(client: TestClient) -> None:
    for i in range(3):
        client.post(
            "/escalations",
            json={
                "source": "flagged",
                "question": f"q{i}",
                "note": "n",
                "passages": [],
            },
            headers=_HEADERS,
        )

    r = client.get("/escalations", headers=_HEADERS)
    assert r.status_code == 200
    assert r.json()["count"] == 3

    r2 = client.get("/escalations?status=open", headers=_HEADERS)
    assert r2.status_code == 200

    r3 = client.get("/escalations/99999", headers=_HEADERS)
    assert r3.status_code == 404


def test_every_route_requires_api_key(client: TestClient) -> None:
    assert client.post("/escalations", json={}).status_code == 401
    assert client.get("/escalations").status_code == 401
    assert client.get("/escalations/1").status_code == 401
    assert client.patch("/escalations/1", json={}).status_code == 401
