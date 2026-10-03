from __future__ import annotations

import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from citerator.config import Settings
from citerator.documents import ingest_service, jobs, registry


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    root = tmp_path / "docs"
    root.mkdir()
    db = tmp_path / "processed" / "documents.sqlite"

    s = Settings(
        documents_root=str(root),
        documents_db_path=str(db),
        embedder_kind="hash",
        sparse_kind="hash",
        embedding_model="hash",
        active_chunking_strategy="structure",
        qdrant_url=":memory:",
        max_concurrent_ingest_jobs=2,
        api_key="test",
    )
    monkeypatch.setattr(
        ingest_service, "make_client", lambda url: QdrantClient(location=":memory:")
    )
    return s


@pytest.mark.asyncio
async def test_process_file_happy_path(settings: Settings) -> None:
    src = Path(settings.documents_root) / "cdd.md"
    src.write_text(
        "# CDD Policy\n\n## Thresholds\n\nThe threshold is USD 15,000.\n",
        encoding="utf-8",
    )

    job_id = jobs.create_job("cdd.md", db_path=settings.documents_db_path)
    await ingest_service.process_file(src, settings, None, job_id)

    row = jobs.get_job(job_id, db_path=settings.documents_db_path)
    assert row["status"] == "indexed"
    assert row["doc_id"] is not None

    doc = registry.get_document(row["doc_id"], db_path=settings.documents_db_path)
    assert doc is not None
    assert doc["status"] == "indexed"
    assert doc["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_process_file_marks_failed_on_corrupt(settings: Settings) -> None:
    src = Path(settings.documents_root) / "broken.pdf"
    src.write_bytes(b"not a real pdf")

    job_id = jobs.create_job("broken.pdf", db_path=settings.documents_db_path)
    await ingest_service.process_file(src, settings, None, job_id)

    row = jobs.get_job(job_id, db_path=settings.documents_db_path)
    assert row["status"] == "failed"
    assert row["error"]


@pytest.mark.asyncio
async def test_manifest_is_parseable_by_pipeline_format(settings: Settings) -> None:
    src = Path(settings.documents_root) / "sar.md"
    src.write_text(
        "# SAR\n\n## Deadlines\n\nA SAR must be filed within 30 calendar days.\n",
        encoding="utf-8",
    )
    job_id = jobs.create_job("sar.md", db_path=settings.documents_db_path)
    await ingest_service.process_file(src, settings, None, job_id)

    from citerator.ingestion.embedding import get_embedder
    from citerator.ingestion.store import collection_name

    embedder = get_embedder("hash", "hash")
    collection = collection_name("structure", embedder.name)
    manifest_path = (
        Path(settings.documents_db_path).parent / f"manifest__{collection}.json"
    )
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "sar.md" in manifest
    entry = manifest["sar.md"]
    required = {"doc_id", "doc_hash", "signature", "chunk_count", "title", "ingested_at"}
    assert required <= set(entry.keys())
