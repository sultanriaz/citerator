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


def test_grounded_passage_supports_and_validates_citation() -> None:
    chunk1 = _chunk(
        "c1",
        "Under Section 314(a), financial institutions must report matching accounts within 14 calendar days.",
    )
    answer = "Financial institutions are required to report account matches within 14 calendar days [1]."

    citations = parse_citations(answer, [chunk1])
    assert len(citations) == 1
    assert citations[0].chunk_id == "c1"
    assert citations[0].support_score is not None
    assert citations[0].support_score >= 0.5
    assert "report account matches" in (citations[0].referenced_passage or "")


def test_unsupported_passage_is_rejected_as_hallucination() -> None:
    chunk1 = _chunk(
        "c1",
        "Employee parking passes must be renewed annually by the facilities department.",
    )
    # The claim has zero relevance or overlap to parking passes
    answer = "The statutory penalty for willful money laundering violations is 20 years imprisonment [1]."

    citations = parse_citations(answer, [chunk1])
    # Must be dropped as an unsupported / fabricated citation!
    assert len(citations) == 0


def test_inaccessible_cross_tenant_source_is_rejected() -> None:
    from citerator.api.deps import TenantContext

    chunk_fintech = _chunk("c_fintech", "FinTech specific compliance regulation.")
    chunk_fintech.tenant_id = "tenant_fintech"

    answer = "Per the FinTech regulation [1], audit reviews occur quarterly."
    acme_caller = TenantContext(tenant_id="tenant_acme", user_id="user_alice", is_admin=False)

    citations = parse_citations(answer, [chunk_fintech], tenant=acme_caller)
    assert len(citations) == 0, "Cross-tenant citation was not rejected!"


def test_inaccessible_private_draft_source_is_rejected() -> None:
    from citerator.api.deps import TenantContext

    chunk_private = _chunk("c_priv", "Internal confidential draft notes on investigation.")
    chunk_private.tenant_id = "tenant_acme"
    chunk_private.visibility = "private"
    chunk_private.owner_id = "user_alice"

    answer = "Internal notes indicate active investigation [1]."
    charlie_caller = TenantContext(tenant_id="tenant_acme", user_id="user_charlie", is_admin=False)
    alice_caller = TenantContext(tenant_id="tenant_acme", user_id="user_alice", is_admin=False)

    # Colleague Charlie cannot cite Alice's private draft
    charlie_citations = parse_citations(answer, [chunk_private], tenant=charlie_caller)
    assert len(charlie_citations) == 0, "Private draft citation was accessible to non-owner colleague!"

    # Owner Alice CAN cite her own private draft
    alice_citations = parse_citations(answer, [chunk_private], tenant=alice_caller)
    assert len(alice_citations) == 1
    assert alice_citations[0].chunk_id == "c_priv"


def test_refusal_response_does_not_attach_citations() -> None:
    chunk1 = _chunk("c1", "General anti-money laundering overview.")
    answer = "The available sources do not contain enough information to answer this inquiry [1]."

    citations = parse_citations(answer, [chunk1])
    assert len(citations) == 0, "Citations should not be attached to an insufficient evidence refusal statement!"