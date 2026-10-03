from __future__ import annotations

import math

from citerator.config import Settings
from citerator.retrieval.confidence import score_confidence
from citerator.retrieval.search import RetrievedChunk


def _chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        doc_id="doc",
        doc_hash="hash",
        source_file="source.md",
        doc_title="Title",
        doc_type="policy",
        section_path=["1"],
        char_start=0,
        char_end=1,
        text="text",
        token_count=1,
        embed_token_count=1,
        chunk_index=0,
        chunker="test",
        chunker_params={},
        rerank_score=score,
    )


def test_confidence_boundaries() -> None:
    settings = Settings(confidence_threshold=0.30, confidence_floor=0.15)

    threshold_logit = math.log(0.30 / 0.70)
    floor_logit = math.log(0.15 / 0.85)

    assert score_confidence([_chunk(threshold_logit)], settings).state == "confident"
    assert score_confidence([_chunk(floor_logit)], settings).state == "low_confidence"
    assert score_confidence([_chunk(floor_logit - 0.01)], settings).state == "insufficient"


def test_empty_retrieval_is_insufficient() -> None:
    settings = Settings()
    result = score_confidence([], settings)

    assert result.state == "insufficient"
    assert result.has_candidates is False
    assert result.confidence == 0.0