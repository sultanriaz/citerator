import re

import pytest

from citerator.ingestion.chunking import (
    FixedChunker,
    SemanticChunker,
    StructureChunker,
    build_doc_text,
    chunk_document,
    make_chunker,
)
from citerator.ingestion.embedding import HashEmbedder
from citerator.ingestion.loaders import load_document
from citerator.ingestion.models import Block, Document
from citerator.ingestion.stats import compute_stats
from citerator.ingestion.tokens import RegexTokenizer

TOK = RegexTokenizer()


def make_doc(blocks, title="Test Doc") -> Document:
    return Document(doc_id="doc-1", doc_hash="h", source_file="t.md", title=title, blocks=blocks)


def words(prefix: str, n: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n)) + "."


def covered(doc: Document, chunks) -> set[int]:
    dt = build_doc_text(doc)
    cov = set()
    for c in chunks:
        cov.update(range(c.char_start, c.char_end))
    return {i for i, ch in enumerate(dt.full_text) if not ch.isspace()} - cov


# ------------------------------------------------------------------ fixed


def test_fixed_respects_max_tokens_and_covers_everything():
    doc = make_doc([Block(text=words("w", 130), kind="paragraph") for _ in range(6)])
    chunks = chunk_document(doc, FixedChunker(TOK, max_tokens=100, overlap_ratio=0.2), TOK)
    assert len(chunks) > 5
    assert all(c.token_count <= 100 for c in chunks)
    assert covered(doc, chunks) == set()


def test_fixed_overlap_is_present_and_measured():
    doc = make_doc([Block(text=words("w", 500))])
    chunks = chunk_document(doc, FixedChunker(TOK, max_tokens=100, overlap_ratio=0.2), TOK)
    stats = compute_stats(chunks)
    assert 0.1 < stats["overlap_ratio"] < 0.3
    zero = chunk_document(doc, FixedChunker(TOK, max_tokens=100, overlap_ratio=0.0), TOK)
    assert compute_stats(zero)["overlap_ratio"] == 0.0


def test_fixed_rejects_bad_overlap():
    with pytest.raises(ValueError):
        FixedChunker(TOK, overlap_ratio=1.0)


# ------------------------------------------------------------------ structure


def test_structure_never_crosses_section_boundaries():
    doc = make_doc([
        Block(text="Alpha", kind="heading", level=1),
        Block(text=words("a", 80)),
        Block(text="Beta", kind="heading", level=1),
        Block(text=words("b", 80)),
    ])
    chunks = chunk_document(doc, StructureChunker(TOK, max_tokens=200, min_tokens=20), TOK)
    assert len(chunks) == 2
    assert chunks[0].section_path == ["Alpha"] and "b0" not in chunks[0].text
    assert chunks[1].section_path == ["Beta"] and "a0" not in chunks[1].text


def test_structure_breadcrumb_is_embedded_but_not_stored():
    doc = make_doc([Block(text="Records", kind="heading", level=1), Block(text=words("r", 50))])
    (chunk,) = chunk_document(doc, StructureChunker(TOK, max_tokens=200, min_tokens=10), TOK)
    assert chunk.embed_text.startswith("Test Doc > Records")
    assert chunk.text.startswith("r0")
    assert chunk.embed_token_count > chunk.token_count


def test_structure_splits_long_sections_within_budget():
    paras = [Block(text=words(f"p{i}_", 70)) for i in range(8)]
    doc = make_doc([Block(text="Big", kind="heading", level=1), *paras])
    chunks = chunk_document(doc, StructureChunker(TOK, max_tokens=150, min_tokens=20), TOK)
    assert len(chunks) > 2
    assert all(c.token_count <= 150 for c in chunks)
    assert all(c.section_path == ["Big"] for c in chunks)
    assert covered(Document(**{**doc.model_dump(), "blocks": paras}), []) != set()  # sanity: helper works
    body_only = [b for b in doc.blocks if b.kind == "paragraph"]
    assert all(any(f"p{i}_0" in c.text for c in chunks) for i in range(len(body_only)))


def test_structure_hard_splits_a_single_giant_sentence():
    doc = make_doc([Block(text="Giant", kind="heading", level=1), Block(text=" ".join(f"x{i}" for i in range(500)))])
    chunks = chunk_document(doc, StructureChunker(TOK, max_tokens=120, min_tokens=20), TOK)
    assert len(chunks) >= 4 and all(c.token_count <= 120 for c in chunks)


def test_structure_merges_tiny_sibling_sections_keeping_inline_headings():
    doc = make_doc([
        Block(text="Parent", kind="heading", level=1),
        Block(text="First", kind="heading", level=2),
        Block(text="tiny one.", kind="paragraph"),
        Block(text="Second", kind="heading", level=2),
        Block(text="tiny two.", kind="paragraph"),
    ])
    (chunk,) = chunk_document(doc, StructureChunker(TOK, max_tokens=200, min_tokens=40), TOK)
    assert chunk.section_path == ["Parent", "First"]
    assert "Second" in chunk.text and "tiny two" in chunk.text


def test_structure_handles_document_without_headings():
    doc = make_doc([Block(text=words("n", 60)), Block(text=words("m", 60))])
    chunks = chunk_document(doc, StructureChunker(TOK, max_tokens=80, min_tokens=20), TOK)
    assert chunks and all(c.section_path == [] for c in chunks)
    assert chunks[0].embed_text.startswith("Test Doc")


# ------------------------------------------------------------------ semantic


def _topic_doc():
    sanctions = " ".join(
        f"Sanctions screening matches every customer against designated lists number {i} daily." for i in range(6)
    )
    retention = " ".join(
        f"Retention schedules keep archived transaction ledgers for years under policy {i} storage." for i in range(6)
    )
    return make_doc([Block(text=sanctions), Block(text=retention)])


def test_semantic_splits_on_topic_shift():
    doc = _topic_doc()
    chunker = SemanticChunker(TOK, HashEmbedder(), max_tokens=400, min_tokens=20, breakpoint_percentile=90, window=2)
    chunks = chunk_document(doc, chunker, TOK)
    assert len(chunks) >= 2
    assert not any("Sanctions" in c.text and "Retention" in c.text for c in chunks)
    assert covered(doc, chunks) == set()


def test_semantic_respects_max_tokens():
    doc = _topic_doc()
    chunker = SemanticChunker(TOK, HashEmbedder(), max_tokens=40, min_tokens=10)
    chunks = chunk_document(doc, chunker, TOK)
    assert all(c.token_count <= 40 for c in chunks)


def test_semantic_single_sentence_document():
    doc = make_doc([Block(text="Just one sentence here.")])
    chunks = chunk_document(doc, SemanticChunker(TOK, HashEmbedder()), TOK)
    assert len(chunks) == 1


# ------------------------------------------------------------------ shared behavior


@pytest.mark.parametrize("strategy", ["fixed", "structure", "semantic"])
def test_ids_are_deterministic_and_unique(strategy):
    doc = _topic_doc()
    mk = lambda: make_chunker(strategy, TOK, embedder=HashEmbedder(), max_tokens=60)  # noqa: E731
    a, b = chunk_document(doc, mk(), TOK), chunk_document(doc, mk(), TOK)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)


def test_ids_change_with_parameters():
    doc = _topic_doc()
    a = chunk_document(doc, FixedChunker(TOK, max_tokens=50), TOK)
    b = chunk_document(doc, FixedChunker(TOK, max_tokens=60), TOK)
    assert {c.chunk_id for c in a}.isdisjoint({c.chunk_id for c in b})


def test_empty_document_yields_no_chunks():
    assert chunk_document(make_doc([]), FixedChunker(TOK), TOK) == []


def test_page_ranges_and_section_paths_from_real_pdf(sample_pdf):
    doc = load_document(sample_pdf, sample_pdf.parent)
    chunks = chunk_document(doc, StructureChunker(TOK, max_tokens=300, min_tokens=5), TOK)
    cdd = next(c for c in chunks if "identify the customer" in c.text)
    assert (cdd.page_start, cdd.page_end) == (1, 2)  # paragraph continued onto page 2
    assert cdd.section_path[-1] == "1. Customer due diligence"
    rec = next(c for c in chunks if "five years" in c.text)
    assert rec.page_start == rec.page_end == 3
    assert all(c.source_file == "manual.pdf" for c in chunks)


def test_chunk_text_matches_character_offsets():
    doc = _topic_doc()
    dt = build_doc_text(doc)
    for c in chunk_document(doc, FixedChunker(TOK, max_tokens=50), TOK):
        assert dt.full_text[c.char_start:c.char_end] == c.text


def test_make_chunker_validation():
    with pytest.raises(ValueError):
        make_chunker("nope", TOK)
    with pytest.raises(ValueError):
        make_chunker("semantic", TOK)  # needs an embedder


def test_stats_shape():
    doc = _topic_doc()
    stats = compute_stats(chunk_document(doc, FixedChunker(TOK, max_tokens=50), TOK), model_max_tokens=512)
    for key in ("n_chunks", "tokens_mean", "tokens_median", "tokens_p95", "overlap_ratio",
                "pct_over_model_limit", "embed_tokens_total"):
        assert key in stats
    assert stats["pct_over_model_limit"] == 0
    assert compute_stats([]) == {"n_chunks": 0}
