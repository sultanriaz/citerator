from __future__ import annotations

import pytest

from citerator.governance import classification as cls_mod


def test_default_classification_applied_on_first_read():
    c = cls_mod.get("newdoc")
    assert c is not None
    assert c["classification"] == "internal"


def test_set_classification_round_trip():
    c = cls_mod.set_classification(
        "doc1",
        classification="restricted",
        retention_days=180,
        contains_pii=True,
        review_cycle_days=30,
    )
    assert c["classification"] == "restricted"
    assert c["retention_days"] == 180
    assert c["contains_pii"] is True
    assert c["review_cycle_days"] == 30


def test_set_classification_rejects_unknown_label():
    with pytest.raises(ValueError, match="classification must be one of"):
        cls_mod.set_classification(
            "doc1",
            classification="top-secret",
            retention_days=None,
            contains_pii=False,
            review_cycle_days=None,
        )


def test_set_classification_rejects_non_positive_retention():
    with pytest.raises(ValueError, match="retention_days"):
        cls_mod.set_classification(
            "doc1",
            classification="internal",
            retention_days=0,
            contains_pii=False,
            review_cycle_days=None,
        )


def test_mark_reviewed_sets_timestamp():
    cls_mod.get("doc1")
    cls_mod.mark_reviewed("doc1")
    c = cls_mod.get("doc1")
    assert c["last_reviewed_at"] is not None


def test_documents_due_for_retention():
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

    cls_mod.set_classification(
        "old-doc",
        classification="internal",
        retention_days=180,
        contains_pii=False,
        review_cycle_days=None,
    )
    cls_mod.set_classification(
        "recent-doc",
        classification="internal",
        retention_days=180,
        contains_pii=False,
        review_cycle_days=None,
    )
    cls_mod.set_classification(
        "unbounded",
        classification="internal",
        retention_days=None,
        contains_pii=False,
        review_cycle_days=None,
    )

    rows = [
        {"doc_id": "old-doc", "indexed_at": old, "source_file": "a"},
        {"doc_id": "recent-doc", "indexed_at": recent, "source_file": "b"},
        {"doc_id": "unbounded", "indexed_at": old, "source_file": "c"},
    ]
    due = cls_mod.documents_due_for_retention(registry_rows=rows)
    due_ids = {d["doc_id"] for d in due}
    assert "old-doc" in due_ids
    assert "recent-doc" not in due_ids
    assert "unbounded" not in due_ids