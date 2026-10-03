from __future__ import annotations

from citerator.generation.citations import parse_citations
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


def test_valid_citation_maps_and_out_of_range_is_dropped() -> None:
    chunks = [_chunk("a", "alpha text"), _chunk("b", "beta text")]

    citations = parse_citations("See [1] and [3].", chunks)

    assert len(citations) == 1
    assert citations[0].chunk_id == "a"
    assert citations[0].excerpt == "alpha text"