from __future__ import annotations

import pytest

from citerator.governance import erasure as erasure_mod


@pytest.fixture
def fake_qdrant(monkeypatch):
    """Replace the Qdrant client with an in-memory stand-in."""

    class FakePoint:
        def __init__(self, pid, payload):
            self.id = pid
            self.payload = payload

    class FakeClient:
        def __init__(self):
            self.points = [
                FakePoint(
                    "p1",
                    {
                        "chunk_id": "c1",
                        "doc_id": "d1",
                        "source_file": "a.pdf",
                        "text": "Mr. John Smith filed a report",
                    },
                ),
                FakePoint(
                    "p2",
                    {
                        "chunk_id": "c2",
                        "doc_id": "d2",
                        "source_file": "b.pdf",
                        "text": "Unrelated content about thresholds",
                    },
                ),
            ]
            self.deleted_selectors = []

        def collection_exists(self, name):
            return True

        def scroll(self, **kwargs):
            return (self.points, None)

        def delete(self, *, collection_name, points_selector, wait):
            self.deleted_selectors.append(points_selector)

    client = FakeClient()

    monkeypatch.setattr(
        "citerator.ingestion.store.make_client", lambda url: client
    )
    monkeypatch.setattr(
        "citerator.ingestion.embedding.get_embedder",
        lambda kind, name=None: type("E", (), {"name": "test", "dim": 8})(),
    )
    monkeypatch.setattr(
        "citerator.ingestion.store.collection_name",
        lambda strategy, name: "test_collection",
    )
    return client


def test_find_matches_finds_by_substring(fake_qdrant):
    matches, _, _ = erasure_mod.find_matches("john smith")
    assert len(matches) == 1
    assert matches[0].chunk_id == "c1"


def test_dry_run_does_not_delete(fake_qdrant):
    result = erasure_mod.erase("john smith", dry_run=True)
    assert result.dry_run is True
    assert result.matched_chunks == 1
    assert result.deleted_chunks == 0
    assert fake_qdrant.deleted_selectors == []


def test_live_run_deletes_matches(fake_qdrant):
    result = erasure_mod.erase("john smith", dry_run=False)
    assert result.dry_run is False
    assert result.deleted_chunks == 1
    assert len(fake_qdrant.deleted_selectors) == 1


def test_no_matches_is_a_noop(fake_qdrant):
    result = erasure_mod.erase("nonexistent-subject", dry_run=False)
    assert result.matched_chunks == 0
    assert result.deleted_chunks == 0
    assert fake_qdrant.deleted_selectors == []


def test_audit_chain_does_not_store_raw_subject():
    """The audit chain is tamper-evident and may be exported. Storing the
    raw subject would defeat the erasure."""
    from citerator.governance import audit

    audit.append(
        "erasure.dry_run",
        {"subject_hash": erasure_mod._hash_subject("john smith")},
    )
    records = audit.list_records(event_type="erasure.dry_run")
    assert records
    import json
    text = json.dumps(records[0].payload)
    assert "john smith" not in text.lower()