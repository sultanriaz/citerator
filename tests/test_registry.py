from __future__ import annotations

from pathlib import Path

import pytest

from citerator.documents import registry


@pytest.fixture
def db(tmp_path: Path) -> str:
    return str(tmp_path / "test.sqlite")


def _row(doc_id: str, **overrides):
    base = {
        "doc_id": doc_id,
        "source_file": f"docs/{doc_id}.md",
        "title": f"Doc {doc_id}",
        "doc_type": "policy",
        "jurisdiction": "US",
        "effective_date": "2024-01-01",
        "page_count": 3,
        "chunk_count": 5,
        "doc_hash": f"hash-{doc_id}",
        "chunker": "structure",
        "chunker_params": {"max_tokens": 400},
        "embedder": "hash",
        "sparse_embedder": "hash",
        "status": "indexed",
        "warnings": [],
    }
    base.update(overrides)
    return base


def test_upsert_get_delete_roundtrip(db: str) -> None:
    registry.upsert_document(_row("a"), db_path=db)

    got = registry.get_document("a", db_path=db)
    assert got is not None
    assert got["doc_id"] == "a"
    assert got["chunker_params"] == {"max_tokens": 400}
    assert got["status"] == "indexed"

    registry.upsert_document(_row("a", title="Updated", chunk_count=9), db_path=db)
    got = registry.get_document("a", db_path=db)
    assert got["title"] == "Updated"
    assert got["chunk_count"] == 9

    registry.delete_document("a", db_path=db)
    assert registry.get_document("a", db_path=db) is None


def test_list_filters_and_sorting(db: str) -> None:
    registry.upsert_document(_row("a", doc_type="standard", chunk_count=3), db_path=db)
    registry.upsert_document(_row("b", doc_type="policy", chunk_count=7), db_path=db)
    registry.upsert_document(
        _row("c", doc_type="policy", jurisdiction="UK", chunk_count=1), db_path=db
    )

    all_rows = registry.list_documents(db_path=db)
    assert {r["doc_id"] for r in all_rows} == {"a", "b", "c"}

    policies = registry.list_documents(doc_type="policy", db_path=db)
    assert {r["doc_id"] for r in policies} == {"b", "c"}

    uk = registry.list_documents(jurisdiction="UK", db_path=db)
    assert [r["doc_id"] for r in uk] == ["c"]

    search = registry.list_documents(search="Doc b", db_path=db)
    assert [r["doc_id"] for r in search] == ["b"]

    by_chunks = registry.list_documents(sort="chunk_count", order="asc", db_path=db)
    assert [r["doc_id"] for r in by_chunks] == ["c", "a", "b"]

    by_chunks_desc = registry.list_documents(
        sort="chunk_count", order="desc", db_path=db
    )
    assert [r["doc_id"] for r in by_chunks_desc] == ["b", "a", "c"]


def test_limit_and_offset(db: str) -> None:
    for i in range(5):
        registry.upsert_document(_row(f"d{i}", chunk_count=i), db_path=db)

    page1 = registry.list_documents(
        sort="chunk_count", order="asc", limit=2, offset=0, db_path=db
    )
    page2 = registry.list_documents(
        sort="chunk_count", order="asc", limit=2, offset=2, db_path=db
    )

    assert [r["doc_id"] for r in page1] == ["d0", "d1"]
    assert [r["doc_id"] for r in page2] == ["d2", "d3"]
