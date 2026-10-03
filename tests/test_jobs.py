from __future__ import annotations

from pathlib import Path

import pytest

from citerator.documents import jobs


@pytest.fixture
def db(tmp_path: Path) -> str:
    return str(tmp_path / "jobs.sqlite")


def test_create_and_get_job(db: str) -> None:
    job_id = jobs.create_job("policy.md", db_path=db)
    row = jobs.get_job(job_id, db_path=db)
    assert row is not None
    assert row["file_name"] == "policy.md"
    assert row["status"] == "queued"
    assert row["error"] is None


def test_status_transitions(db: str) -> None:
    job_id = jobs.create_job("policy.md", db_path=db)

    for status in ("parsing", "chunking", "embedding", "indexing", "indexed"):
        jobs.update_job(job_id, db_path=db, status=status)
        row = jobs.get_job(job_id, db_path=db)
        assert row["status"] == status


def test_failed_job_records_error(db: str) -> None:
    job_id = jobs.create_job("bad.pdf", db_path=db)
    jobs.update_job(job_id, db_path=db, status="failed", error="parse error")

    row = jobs.get_job(job_id, db_path=db)
    assert row["status"] == "failed"
    assert row["error"] == "parse error"


def test_list_jobs_filter_and_order(db: str) -> None:
    a = jobs.create_job("a.md", db_path=db)
    b = jobs.create_job("b.md", db_path=db)
    jobs.update_job(b, db_path=db, status="failed", error="x")

    all_rows = jobs.list_jobs(db_path=db)
    assert {r["job_id"] for r in all_rows} == {a, b}

    failed = jobs.list_jobs(status="failed", db_path=db)
    assert [r["job_id"] for r in failed] == [b]


def test_warnings_field_roundtrip(db: str) -> None:
    job_id = jobs.create_job("scan.pdf", db_path=db)
    jobs.update_job(job_id, db_path=db, status="indexed", warnings=["scanned page"])
    row = jobs.get_job(job_id, db_path=db)
    assert row["warnings"] == ["scanned page"]
