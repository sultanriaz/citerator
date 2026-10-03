from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from citerator.api import documents_routes
from citerator.api.app import create_app
from citerator.config import Settings, get_settings
from citerator.documents import ingest_service


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    root = tmp_path / "docs"
    root.mkdir()
    db = tmp_path / "processed" / "documents.sqlite"

    s = Settings(
        documents_root=str(root),
        documents_db_path=str(db),
        embedder_kind="hash",
        sparse_kind="hash",
        embedding_model="hash",
        active_chunking_strategy="structure",
        qdrant_url=":memory:",
        max_concurrent_ingest_jobs=2,
        api_key="secret",
        cors_origins=["*"],
        max_upload_mb=1,
    )

    shared = QdrantClient(location=":memory:")
    monkeypatch.setattr(ingest_service, "make_client", lambda url: shared)
    monkeypatch.setattr(documents_routes, "make_client", lambda url: shared)
    return s


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


_HEADERS = {"X-API-Key": "secret"}


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/documents/jobs/{job_id}", headers=_HEADERS)
        assert r.status_code == 200
        body = r.json()
        if body["status"] in {"indexed", "failed"}:
            return body
        time.sleep(0.1)
    raise AssertionError(f"Job {job_id} did not finish within {timeout}s")


def test_upload_index_and_fetch_chunks(client: TestClient) -> None:
    files = {
        "files": (
            "cdd.md",
            b"# CDD\n\n## Thresholds\n\nThreshold is USD 15,000.\n",
            "text/markdown",
        ),
    }
    r = client.post("/documents/upload", files=files, headers=_HEADERS)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["count"] == 1
    job_id = body["accepted"][0]["job_id"]

    job = _wait_for_job(client, job_id)
    assert job["status"] == "indexed"
    doc_id = job["doc_id"]

    r = client.get("/documents", headers=_HEADERS)
    assert r.status_code == 200
    assert any(d["doc_id"] == doc_id for d in r.json()["documents"])

    r = client.get(f"/documents/{doc_id}/chunks", headers=_HEADERS)
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    r = client.delete(f"/documents/{doc_id}", headers=_HEADERS)
    assert r.status_code == 204

    r = client.delete(f"/documents/{doc_id}", headers=_HEADERS)
    assert r.status_code == 204


def test_reindex_missing_doc_returns_404(client: TestClient) -> None:
    r = client.post("/documents/does-not-exist/reindex", headers=_HEADERS)
    assert r.status_code == 404


def test_all_routes_require_api_key(client: TestClient) -> None:
    probes = [
        ("GET", "/documents", None),
        ("GET", "/documents/jobs", None),
        ("GET", "/documents/chunking-strategies", None),
        ("GET", "/documents/anything", None),
        ("GET", "/documents/anything/chunks", None),
        ("DELETE", "/documents/anything", None),
        ("POST", "/documents/anything/reindex", None),
    ]
    for method, url, _ in probes:
        r = client.request(method, url)
        assert r.status_code == 401, f"{method} {url} -> {r.status_code}"


def test_wrong_extension_is_4xx(client: TestClient) -> None:
    files = {"files": ("evil.exe", b"MZ...", "application/octet-stream")}
    r = client.post("/documents/upload", files=files, headers=_HEADERS)
    assert 400 <= r.status_code < 500


def test_oversized_upload_is_413(client: TestClient, settings: Settings) -> None:
    big = b"x" * (settings.max_upload_mb * 1024 * 1024 + 1)
    files = {"files": ("big.md", big, "text/markdown")}
    r = client.post("/documents/upload", files=files, headers=_HEADERS)
    assert r.status_code == 413


def test_path_traversal_rejected(client: TestClient) -> None:
    files = {"files": ("../escape.md", b"# nope", "text/markdown")}
    r = client.post("/documents/upload", files=files, headers=_HEADERS)
    assert 400 <= r.status_code < 500
