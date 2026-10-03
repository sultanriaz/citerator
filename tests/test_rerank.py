from __future__ import annotations

from citerator.config import Settings
from citerator.retrieval.rerank import FakeReranker, rerank
from citerator.retrieval.search import RetrievedChunk


def _chunk(chunk_id: str, text: str) -> RetrievedChunk:
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
    )


def test_fake_reranker_ordering_is_respected() -> None:
    settings = Settings(top_k_rerank=2, rerank_model="fake")
    candidates = [
        _chunk("a", "alpha text"),
        _chunk("b", "beta text"),
        _chunk("c", "gamma text"),
    ]
    reranker = FakeReranker({"beta": 0.9, "alpha": 0.5, "gamma": 0.1})

    reranked = rerank("question", candidates, settings, reranker=reranker)

    assert [chunk.chunk_id for chunk in reranked] == ["b", "a"]
    assert reranked[0].rerank_score == 0.9