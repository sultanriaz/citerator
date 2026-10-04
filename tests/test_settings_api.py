from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from citerator.api import documents_routes, settings_routes
from citerator.api.app import create_app
from citerator.config import Settings, get_settings
from citerator.ingestion.embedding import get_embedder
from citerator.ingestion.store import ChunkStore, collection_name
from citerator.runtime_config import overrides as ov


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "RUNTIME_CONFIG_DB_PATH", str(tmp_path / "runtime_config.sqlite")
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def shared_client() -> QdrantClient:
    return QdrantClient(location=":memory:")


@pytest.fixture
def settings(tmp_path: Path, shared_client: QdrantClient, monkeypatch) -> Settings:
    s = Settings(
        documents_root=str(tmp_path / "raw"),
        documents_db_path=str(tmp_path / "documents.sqlite"),
        eval_db_path=str(tmp_path / "eval.sqlite"),
        eval_questions_path=str(tmp_path / "questions.json"),
        runtime_config_db_path=str(tmp_path / "runtime_config.sqlite"),
        embedder_kind="hash",
        sparse_kind="hash",
        embedding_model="hash",
        active_chunking_strategy="structure",
        qdrant_url=":memory:",
        api_key="secret",
        rate_limit_requests_per_minute=1000,
    )
    # Redirect Qdrant construction inside routes to the shared in-memory client.
    monkeypatch.setattr(
        documents_routes, "make_client", lambda url: shared_client
    )
    monkeypatch.setattr(
        settings_routes, "get_effective_settings", lambda: get_effective_settings()
    )
    return s


@pytest.fixture
def client(settings: Settings, shared_client: QdrantClient, monkeypatch) -> TestClient:
    from citerator.runtime_config.effective_settings import (
        get_effective_settings as _eff,
    )

    # Ensure get_effective_settings reads overrides via the same DB the test uses.
    monkeypatch.setenv(
        "RUNTIME_CONFIG_DB_PATH", settings.runtime_config_db_path
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    # Also make the override target read from the same settings object.
    monkeypatch.setattr(
        "citerator.api.app.get_effective_settings",
        lambda: settings,
        raising=False,
    )
    return TestClient(app)


_HEADERS = {"X-API-Key": "secret"}


def _seed_collection(client: QdrantClient, strategy: str) -> None:
    embedder = get_embedder("hash", "hash")
    collection = collection_name(strategy, embedder.name)
    store = ChunkStore(client, collection, dim=embedder.dim, sparse=False)
    store.ensure_collection()


def test_put_pipeline_persists_and_reads_back(
    client: TestClient, settings: Settings
) -> None:
    r = client.put(
        "/settings/pipeline",
        json={"top_k_retrieve": 30, "top_k_rerank": 6},
        headers=_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["top_k_retrieve"] == 30
    assert body["top_k_rerank"] == 6
    assert body["is_override"]["top_k_retrieve"] is True
    assert body["is_override"]["top_k_rerank"] is True
    assert body["is_override"]["confidence_threshold"] is False


def test_put_pipeline_rejects_bad_combo(client: TestClient) -> None:
    r = client.put(
        "/settings/pipeline",
        json={"confidence_floor": 0.9, "confidence_threshold": 0.4},
        headers=_HEADERS,
    )
    assert r.status_code == 422


def test_put_pipeline_rejects_missing_collection_for_new_strategy(
    client: TestClient, shared_client: QdrantClient
) -> None:
    _seed_collection(shared_client, "structure")

    r = client.put(
        "/settings/pipeline",
        json={"active_chunking_strategy": "semantic"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
    assert "no indexed documents" in r.json()["detail"]


def test_put_models_rejects_embedding_model_in_body(
    client: TestClient,
) -> None:
    r = client.put(
        "/settings/models",
        json={"embedding_model": "BAAI/bge-large-en-v1.5"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
    assert "not overridable" in r.json()["detail"]


def test_get_api_never_leaks_full_key(client: TestClient) -> None:
    r = client.get("/settings/api", headers=_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "secret" not in body["api_key_masked"]
    assert body["api_key_masked"].endswith("cret")
    assert body["api_key_masked"].startswith("*")


def test_regenerate_key_then_use_it(client: TestClient, settings: Settings) -> None:
    r = client.post("/settings/api/regenerate", headers=_HEADERS)
    assert r.status_code == 200
    new_key = r.json()["api_key"]
    assert new_key
    assert new_key != "secret"

    # Subsequent GET only returns the masked form.
    r2 = client.get("/settings/api", headers=_HEADERS)
    assert new_key not in r2.text


def test_reset_restores_default(client: TestClient, settings: Settings) -> None:
    client.put(
        "/settings/pipeline",
        json={"top_k_retrieve": 33},
        headers=_HEADERS,
    )
    r = client.post(
        "/settings/reset", json={"section": "pipeline"}, headers=_HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body["effective"]["top_k_retrieve"] == settings.top_k_retrieve


def test_preview_threshold_makes_no_llm_call(
    client: TestClient, settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    qpath = Path(settings.eval_questions_path)
    qpath.parent.mkdir(parents=True, exist_ok=True)
    import json

    qpath.write_text(
        json.dumps(
            [
                {
                    "question": "What is the CDD threshold?",
                    "category": "lookup",
                    "expected_behavior": "answer",
                    "ground_truth": "USD 15,000",
                },
                {
                    "question": "What is the capital of France?",
                    "category": "out_of_corpus",
                    "expected_behavior": "refuse",
                    "ground_truth": None,
                },
            ]
        ),
        encoding="utf-8",
    )

    called = {"llm": 0, "ragas": 0}

    def fail_llm(*args, **kwargs):
        called["llm"] += 1
        raise AssertionError("preview-threshold must not call an LLM")

    def fail_ragas(*args, **kwargs):
        called["ragas"] += 1
        raise AssertionError("preview-threshold must not call Ragas")

    monkeypatch.setattr("citerator.generation.llm.OpenAIClient.complete", fail_llm)
    monkeypatch.setattr(
        "citerator.evaluation.ragas_scorer.RealRagasScorer.score", fail_ragas
    )

    r = client.post(
        "/settings/pipeline/preview-threshold",
        json={"confidence_threshold": 0.3, "confidence_floor": 0.15},
        headers=_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert (
        body["confident"] + body["low_confidence"] + body["insufficient"] == 2
    )
    assert called["llm"] == 0
    assert called["ragas"] == 0


def test_every_settings_route_requires_api_key(client: TestClient) -> None:
    assert client.get("/settings/pipeline").status_code == 401
    assert client.put("/settings/pipeline", json={}).status_code == 401
    assert client.get("/settings/models").status_code == 401
    assert client.put("/settings/models", json={}).status_code == 401
    assert client.get("/settings/api").status_code == 401
    assert client.post("/settings/api/regenerate").status_code == 401
    assert client.post("/settings/reset", json={"section": "all"}).status_code == 401
