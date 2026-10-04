from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from citerator.api import eval_routes
from citerator.api.app import create_app
from citerator.config import Settings, get_settings
from citerator.evaluation import runner, store

@pytest.fixture(autouse=True)
def _isolate_settings_cache():
    from citerator.config import base_settings
    from citerator.runtime_config import resolver

    base_settings.cache_clear()
    resolver.invalidate()
    yield
    base_settings.cache_clear()
    resolver.invalidate()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    processed = tmp_path / "processed"
    processed.mkdir()

    return Settings(
        documents_root=str(tmp_path / "raw"),
        documents_db_path=str(processed / "documents.sqlite"),
        eval_db_path=str(processed / "eval.sqlite"),
        eval_questions_path=str(tmp_path / "questions.json"),
        max_concurrent_eval_runs=1,
        api_key="secret",
        cors_origins=["*"],
        llm_provider="fake",
        embedder_kind="hash",
        sparse_kind="hash",
        embedding_model="hash",
    )


@pytest.fixture
def client(settings: Settings, monkeypatch) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    eval_routes._running_runs.clear()
    eval_routes._background_tasks.clear()
    return TestClient(app)


_HEADERS = {"X-API-Key": "secret"}


def test_every_route_requires_api_key(client: TestClient) -> None:
    assert client.post("/eval/runs", json={}).status_code == 401
    assert client.get("/eval/runs").status_code == 401
    assert client.get("/eval/latest").status_code == 401
    assert client.get("/eval/runs/compare?a=x&b=y").status_code == 401
    assert client.get("/eval/runs/anything").status_code == 401


def test_latest_404s_when_no_completed_runs(client: TestClient) -> None:
    r = client.get("/eval/latest", headers=_HEADERS)
    assert r.status_code == 404


def test_start_run_returns_immediately(
    client: TestClient, settings: Settings, monkeypatch
) -> None:
    called: dict = {"entered": False}

    async def fake_runner(run_id, run_settings, store_module, **kwargs):
        called["entered"] = True
        store_module.update_run(run_id, status="completed", db_path=settings.eval_db_path)

    monkeypatch.setattr(runner, "run_evaluation", fake_runner)

    r = client.post("/eval/runs", json={"label": "t"}, headers=_HEADERS)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["run_id"]

    deadline = time.time() + 5
    while time.time() < deadline and not called["entered"]:
        time.sleep(0.05)
    assert called["entered"] is True


def test_concurrency_limit_returns_409(
    client: TestClient, settings: Settings, monkeypatch
) -> None:
    async def slow_runner(run_id, run_settings, store_module, **kwargs):
        # Never completes; holds the _running_runs slot.
        await __import__("asyncio").sleep(10)

    monkeypatch.setattr(runner, "run_evaluation", slow_runner)

    r1 = client.post("/eval/runs", json={}, headers=_HEADERS)
    assert r1.status_code == 202

    r2 = client.post("/eval/runs", json={}, headers=_HEADERS)
    assert r2.status_code == 409


def test_latest_returns_completed_run(client: TestClient, settings: Settings) -> None:
    run_id = store.create_run(
        question_set_path="x",
        chunking_strategy="structure",
        embedder="hash",
        sparse_embedder="hash",
        rerank_model="fake",
        llm_provider="fake",
        llm_model="",
        top_k_retrieve=5,
        top_k_rerank=3,
        confidence_threshold=0.3,
        confidence_floor=0.15,
        db_path=settings.eval_db_path,
    )
    store.update_run(
        run_id,
        db_path=settings.eval_db_path,
        status="completed",
        question_count=3,
        faithfulness_mean=0.8,
        latency_p50_ms=120.0,
    )

    r = client.get("/eval/latest", headers=_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == run_id
    assert body["metrics"]["faithfulness_mean"]["value"] == 0.8
    assert body["metrics"]["faithfulness_mean"]["delta_vs_previous"] is None


def test_compare_directions(client: TestClient, settings: Settings) -> None:
    a = store.create_run(question_set_path="x", db_path=settings.eval_db_path)
    b = store.create_run(question_set_path="x", db_path=settings.eval_db_path)
    store.update_run(
        a,
        db_path=settings.eval_db_path,
        status="completed",
        faithfulness_mean=0.5,
        latency_p50_ms=200.0,
    )
    store.update_run(
        b,
        db_path=settings.eval_db_path,
        status="completed",
        faithfulness_mean=0.7,
        latency_p50_ms=150.0,
    )

    r = client.get(f"/eval/runs/compare?a={a}&b={b}", headers=_HEADERS)
    assert r.status_code == 200
    deltas = r.json()["deltas"]
    assert deltas["faithfulness_mean"]["direction"] == "higher_is_better"
    assert deltas["latency_p50_ms"]["direction"] == "lower_is_better"

