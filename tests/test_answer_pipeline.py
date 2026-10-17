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


def test_insufficient_evidence_provides_fallback_and_zero_citations(monkeypatch) -> None:
    # Insufficient confidence: low score candidate below floor
    chunk = _chunk("c_low", "Unrelated noise", rerank_score=-10.0)
    fake_llm = FakeLLMClient()

    monkeypatch.setattr(answer_module, "search", lambda *args, **kwargs: [chunk])
    monkeypatch.setattr(answer_module, "rerank", lambda *args, **kwargs: [chunk])

    result = answer_module.answer_question("What is the tax rate?", _settings(), llm_client=fake_llm)

    assert result.state == "insufficient"
    assert result.answer is None
    assert result.citations == [], "Must have zero fabricated citations on insufficient evidence"
    assert len(result.related_passages) == 1
    assert result.escalation_draft is not None
    assert "Insufficient confidence to answer automatically" in result.escalation_draft["suggested_note"]
    assert fake_llm.invoked is False, "LLM must never be called on insufficient evidence"


def test_grounded_answer_includes_verified_citations(monkeypatch) -> None:
    chunk = _chunk(
        "c1",
        "Customer due diligence must be conducted for transactions exceeding $10,000.",
        rerank_score=3.5,
    )
    fake_llm = FakeLLMClient(
        response_text="Customer due diligence is required for transactions exceeding $10,000 [1]."
    )

    monkeypatch.setattr(answer_module, "search", lambda *args, **kwargs: [chunk])
    monkeypatch.setattr(answer_module, "rerank", lambda *args, **kwargs: [chunk])

    result = answer_module.answer_question("What is the CDD threshold?", _settings(), llm_client=fake_llm)

    assert result.state == "confident"
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == "c1"
    assert result.citations[0].support_score is not None
    assert result.citations[0].support_score >= 0.5


def test_hallucinated_citation_in_llm_response_is_stripped(monkeypatch) -> None:
    chunk = _chunk(
        "c1",
        "Staff must attend annual AML compliance training.",
        rerank_score=3.5,
    )
    # LLM hallucinates a claim completely unsupported by the chunk
    fake_llm = FakeLLMClient(
        response_text="Willful non-compliance leads to 20 years in federal prison [1]."
    )

    monkeypatch.setattr(answer_module, "search", lambda *args, **kwargs: [chunk])
    monkeypatch.setattr(answer_module, "rerank", lambda *args, **kwargs: [chunk])

    result = answer_module.answer_question("What is the training requirement?", _settings(), llm_client=fake_llm)

    assert result.state == "confident"
    # The citation marker exists in LLM text, but since chunk does not support the claim, it is stripped
    assert len(result.citations) == 0, "Hallucinated citation was not stripped!"