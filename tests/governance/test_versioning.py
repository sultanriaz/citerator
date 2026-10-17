from __future__ import annotations

from citerator.governance import versioning as ver


def _row(doc_id: str, doc_hash: str, *, reason: str = "ingest") -> dict:
    return {
        "doc_id": doc_id,
        "doc_hash": doc_hash,
        "source_file": f"{doc_id}.pdf",
        "chunk_count": 10,
        "ingested_by": None,
        "version_reason": reason,
    }


def test_first_upsert_creates_version_1():
    ver._record_version_impl(_row("d1", "h1"))
    current = ver.current_version("d1")
    assert current is not None
    assert current["version"] == 1
    assert current["doc_hash"] == "h1"


def test_same_hash_does_not_create_new_version():
    ver._record_version_impl(_row("d1", "h1"))
    ver._record_version_impl(_row("d1", "h1"))
    versions = ver.list_versions("d1")
    assert len(versions) == 1


def test_new_hash_creates_new_version_and_supersedes_previous():
    ver._record_version_impl(_row("d1", "h1"))
    ver._record_version_impl(_row("d1", "h2", reason="content_updated"))

    versions = ver.list_versions("d1")
    assert len(versions) == 2
    # Newest first
    assert versions[0]["version"] == 2
    assert versions[0]["doc_hash"] == "h2"
    assert versions[1]["version"] == 1
    assert versions[1]["superseded_by_version"] == 2
    assert versions[1]["effective_to"] is not None

    current = ver.current_version("d1")
    assert current["version"] == 2


def test_is_stale_when_no_versions_returns_false():
    stale, age = ver.is_stale("nonexistent")
    assert stale is False
    assert age is None


def test_multiple_documents_independent():
    ver._record_version_impl(_row("a", "h1"))
    ver._record_version_impl(_row("b", "h1"))
    ver._record_version_impl(_row("a", "h2"))
    assert len(ver.list_versions("a")) == 2
    assert len(ver.list_versions("b")) == 1