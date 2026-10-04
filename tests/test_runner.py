from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from citerator.config import Settings
from citerator.evaluation import runner, store
from citerator.evaluation.ragas_scorer import FakeRagasScorer
from citerator.generation.llm import FakeLLMClient
from citerator.ingestion.embedding import get_embedder, get_sparse_embedder
from citerator.ingestion.models import Chunk
from citerator.ingestion.store import ChunkStore, collection_name


class _QuestionReranker:
    """Scores every candidate the same, based on a per-question substring map."""

    def __init__(self, mapping: dict[str, float]):
        self.mapping = mapping

    def score(self, query: str, texts: list[str]) -> list[float]:
        score = 0.0
        for needle, value in self.mapping.items():
            if needle.lower() in query.lower():
                score = value
                break
        return [score] * len(texts)


def _make_chunk(chunk_id: str, text: str, chunk_index: int) -> Chunk:
    import uuid as _uuid

    return Chunk(
        chunk_id=str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"citerator/test/{chunk_id}")),
        doc_id="doc-1",
        doc_hash="hash-1",
        source_file="cdd_policy.md",
        doc_title="Customer Due Diligence Policy",
        doc_type="policy",
        jurisdiction="international",
        effective_date="2025-06-01",
        section_path=["Section 1"],
        page_start=None,
        page_end=None,
        char_start=0,
        char_end=len(text),
        text=text,
        embed_text=text,
        token_count=len(text.split()),
        embed_token_count=len(text.split()),
        chunk_index=chunk_index,
        chunker="structure",
        chunker_params={},
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    raw = tmp_path / "raw"
    raw.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()

    return Settings(
        documents_root=str(raw),
        documents_db_path=str(processed / "documents.sqlite"),
        eval_db_path=str(processed / "eval.sqlite"),
        eval_questions_path=str(tmp_path / "questions.json"),
        embedder_kind="hash",
        sparse_kind="hash",
        embedding_model="hash",
        active_chunking_strategy="structure",
        qdrant_url=":memory:",
        top_k_retrieve=5,
        top_k_rerank=3,
        confidence_threshold=0.30,
        confidence_floor=0.15,
        llm_provider="fake",
        rerank_model="fake",
        api_key="test",
    )


@pytest.fixture
def seeded_client(settings: Settings) -> QdrantClient:
    client = QdrantClient(location=":memory:")
    embedder = get_embedder("hash", "hash")
    sparse = get_sparse_embedder("hash")
    collection = collection_name("structure", embedder.name)

    cstore = ChunkStore(client, collection, dim=embedder.dim, sparse=True)
    cstore.ensure_collection()

    chunks = [
        _make_chunk("c1", "The threshold is USD 15,000.", 0),
        _make_chunk("c2", "Records are kept for five years.", 1),
        _make_chunk("c3", "PEP relationships require senior management approval.", 2),
    ]
    texts = [c.embed_text for c in chunks]
    dense = embedder.embed_documents(texts)
    sparse_vecs = sparse.embed_documents(texts)
    cstore.upsert(
        chunks, dense, sparse_vecs, embedder.name, datetime.now(timezone.utc)
    )
    return client


def _write_questions(path: Path, questions: list[dict]) -> None:
    path.write_text(json.dumps(questions), encoding="utf-8")


@pytest.mark.asyncio
async def test_runner_three_states_end_to_end(
    settings: Settings, seeded_client: QdrantClient
) -> None:
    questions = [
        {
            "question": "What is the CDD threshold?",
            "category": "lookup",
            "expected_behavior": "answer",
            "ground_truth": "USD 15,000",
        },
        {
            "question": "What is the tax rate in Zimbabwe?",
            "category": "out_of_corpus",
            "expected_behavior": "refuse",
            "ground_truth": None,
        },
        {
            "question": "Should I file a SAR?",
            "category": "underspecified",
            "expected_behavior": "clarify_or_escalate",
            "ground_truth": None,
        },
    ]
    _write_questions(Path(settings.eval_questions_path), questions)

    run_id = store.create_run(
        question_set_path=settings.eval_questions_path,
        chunking_strategy=settings.active_chunking_strategy,
        embedder="hash",
        sparse_embedder="hash",
        rerank_model="fake",
        llm_provider="fake",
        llm_model="",
        top_k_retrieve=settings.top_k_retrieve,
        top_k_rerank=settings.top_k_rerank,
        confidence_threshold=settings.confidence_threshold,
        confidence_floor=settings.confidence_floor,
        label="test-run",
        db_path=settings.eval_db_path,
    )

    llm = FakeLLMClient()
    scorer = FakeRagasScorer()
    reranker = _QuestionReranker(
        {"threshold": 5.0, "zimbabwe": -10.0, "should i file": -1.0}
    )

    await runner.run_evaluation(
        run_id,
        settings,
        store,
        client=seeded_client,
        scorer=scorer,
        reranker=reranker,
        llm_client=llm,
    )

    run = store.get_run(run_id, db_path=settings.eval_db_path)
    assert run["status"] == "completed"
    assert run["question_count"] == 3
    assert run["questions_completed"] == 3

    results = store.list_question_results(run_id, db_path=settings.eval_db_path)
    assert len(results) == 3

    by_question = {r["question"]: r for r in results}

    lookup = by_question["What is the CDD threshold?"]
    assert lookup["state"] == "confident"
    assert lookup["passed"] is True

    out = by_question["What is the tax rate in Zimbabwe?"]
    assert out["state"] == "insufficient"
    assert out["passed"] is True
    assert out["answer_text"] is None

    under = by_question["Should I file a SAR?"]
    assert under["state"] == "low_confidence"
    assert under["passed"] is True

    assert run["safety_refuse_pct"] == 100.0
    assert run["safety_escalate_pct"] == 100.0


@pytest.mark.asyncio
async def test_insufficient_question_never_calls_llm(
    settings: Settings, seeded_client: QdrantClient
) -> None:
    questions = [
        {
            "question": "Zimbabwe tax rate?",
            "category": "out_of_corpus",
            "expected_behavior": "refuse",
            "ground_truth": None,
        },
    ]
    _write_questions(Path(settings.eval_questions_path), questions)

    run_id = store.create_run(
        question_set_path=settings.eval_questions_path,
        chunking_strategy=settings.active_chunking_strategy,
        embedder="hash",
        sparse_embedder="hash",
        rerank_model="fake",
        llm_provider="fake",
        llm_model="",
        top_k_retrieve=settings.top_k_retrieve,
        top_k_rerank=settings.top_k_rerank,
        confidence_threshold=settings.confidence_threshold,
        confidence_floor=settings.confidence_floor,
        db_path=settings.eval_db_path,
    )

    llm = FakeLLMClient()

    class _RecordingScorer(FakeRagasScorer):
        def __init__(self):
            self.calls = 0

        def score(self, *args, **kwargs):
            self.calls += 1
            return super().score(*args, **kwargs)

    scorer = _RecordingScorer()

    await runner.run_evaluation(
        run_id,
        settings,
        store,
        client=seeded_client,
        scorer=scorer,
        reranker=_QuestionReranker({"zimbabwe": -10.0}),
        llm_client=llm,
    )

    assert llm.invoked is False
    assert scorer.calls == 0

    results = store.list_question_results(run_id, db_path=settings.eval_db_path)
    assert results[0]["state"] == "insufficient"
    assert results[0]["answer_text"] is None


@pytest.mark.asyncio
async def test_corrupt_question_does_not_crash_run(
    settings: Settings, seeded_client: QdrantClient, monkeypatch
) -> None:
    questions = [
        {
            "question": "This will ERROR inside retrieval",
            "category": "lookup",
            "expected_behavior": "answer",
            "ground_truth": "x",
        },
        {
            "question": "What is the CDD threshold?",
            "category": "lookup",
            "expected_behavior": "answer",
            "ground_truth": "USD 15,000",
        },
    ]
    _write_questions(Path(settings.eval_questions_path), questions)

    original_search = runner.search

    def patched_search(question, *args, **kwargs):
        if "ERROR" in question:
            raise RuntimeError("simulated retrieval failure")
        return original_search(question, *args, **kwargs)

    monkeypatch.setattr(runner, "search", patched_search)

    run_id = store.create_run(
        question_set_path=settings.eval_questions_path,
        chunking_strategy=settings.active_chunking_strategy,
        embedder="hash",
        sparse_embedder="hash",
        rerank_model="fake",
        llm_provider="fake",
        llm_model="",
        top_k_retrieve=settings.top_k_retrieve,
        top_k_rerank=settings.top_k_rerank,
        confidence_threshold=settings.confidence_threshold,
        confidence_floor=settings.confidence_floor,
        db_path=settings.eval_db_path,
    )

    await runner.run_evaluation(
        run_id,
        settings,
        store,
        client=seeded_client,
        scorer=FakeRagasScorer(),
        reranker=_QuestionReranker({"threshold": 5.0}),
        llm_client=FakeLLMClient(),
    )

    run = store.get_run(run_id, db_path=settings.eval_db_path)
    assert run["status"] == "completed"

    results = store.list_question_results(run_id, db_path=settings.eval_db_path)
    errored = [r for r in results if r.get("error")]
    assert len(errored) == 1
    assert "simulated retrieval failure" in errored[0]["error"]

