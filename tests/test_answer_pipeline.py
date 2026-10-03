from __future__ import annotations

import citerator.generation.answer as answer_module
from citerator.config import Settings
from citerator.generation.llm import FakeLLMClient
from citerator.retrieval.search import RetrievedChunk


def _chunk(chunk_id: str, text: str, rerank_score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="doc",
        doc_hash="hash",
        source_file="source.md",
        doc_title="Title",
        doc_type="policy",
        section_path=["1"],
        char_start=0,
        char_end=1,
        text=text,
        token_count=1,
        embed_token_count=1,
        chunk_index=0,
        chunker="test",
        chunker_params={},
        rerank_score=rerank_score,
    )


def _settings() -> Settings:
    return Settings(
        confidence_threshold=0.30,
        confidence_floor=0.15,
        top_k_retrieve=5,
        top_k_rerank=3,
        llm_provider="fake",
    )


def test_insufficient_does_not_call_llm(monkeypatch) -> None:
    fake_llm = FakeLLMClient()

    monkeypatch.setattr(answer_module, "search", lambda *args, **kwargs: [])
    monkeypatch.setattr(answer_module, "rerank", lambda *args, **kwargs: [])

    result = answer_module.answer_question("question", _settings(), llm_client=fake_llm)

    assert result.state == "insufficient"
    assert result.answer is None
    assert fake_llm.invoked is False


def test_confident_generates_and_parses_citations(monkeypatch) -> None:
    chunk = _chunk("c1", "alpha text", rerank_score=3.0)
    fake_llm = FakeLLMClient()

    monkeypatch.setattr(answer_module, "search", lambda *args, **kwargs: [chunk])
    monkeypatch.setattr(answer_module, "rerank", lambda *args, **kwargs: [chunk])

    result = answer_module.answer_question("question", _settings(), llm_client=fake_llm)

    assert result.state == "confident"
    assert result.answer is not None
    assert result.citations[0].chunk_id == "c1"
    assert fake_llm.invoked is True


def test_low_confidence_generates_and_sets_escalation(monkeypatch) -> None:
    chunk = _chunk("c1", "alpha text", rerank_score=-1.0)
    fake_llm = FakeLLMClient()

    monkeypatch.setattr(answer_module, "search", lambda *args, **kwargs: [chunk])
    monkeypatch.setattr(answer_module, "rerank", lambda *args, **kwargs: [chunk])

    result = answer_module.answer_question("question", _settings(), llm_client=fake_llm)

    assert result.state == "low_confidence"
    assert result.escalation_draft is not None