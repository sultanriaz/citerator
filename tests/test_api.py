from __future__ import annotations

from fastapi.testclient import TestClient

from citerator.api import routes
from citerator.api.app import create_app
from citerator.config import Settings, get_settings
from citerator.generation.answer import AnswerResult


def test_query_requires_api_key_and_toggles_retrieval_details(monkeypatch) -> None:
    settings = Settings(api_key="secret", cors_origins=["*"])
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    def fake_answer_question(*args, **kwargs):
        show = kwargs.get("show_retrieval_details", False)
        return AnswerResult(
            state="confident",
            answer="ok [1]",
            confidence=0.9,
            citations=[],
            related_passages=[],
            escalation_draft=None,
            latency_ms={"total": 1.0},
            tokens=None,
            retrieval_details=[{"chunk_id": "c1"}] if show else None,
        )

    monkeypatch.setattr(routes, "answer_question", fake_answer_question)
    client = TestClient(app)

    assert client.post("/query", json={"question": "q"}).status_code == 401

    response = client.post(
        "/query",
        json={"question": "q"},
        headers={"X-API-Key": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "confident"
    assert response.json()["retrieval_details"] is None

    response = client.post(
        "/query",
        json={"question": "q", "show_retrieval_details": True},
        headers={"X-API-Key": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["retrieval_details"] == [{"chunk_id": "c1"}]


def test_health_returns_collection_counts(monkeypatch) -> None:
    settings = Settings(api_key="secret")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    class FakeCollection:
        name = "citerator__structure__hash"

    class FakeCollections:
        collections = [FakeCollection()]

    class FakeCount:
        count = 7

    class FakeClient:
        def get_collections(self):
            return FakeCollections()

        def count(self, name: str):
            return FakeCount()

    monkeypatch.setattr(routes, "make_client", lambda url: FakeClient())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["collections"]["citerator__structure__hash"] == 7