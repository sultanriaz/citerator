import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from citerator.ingestion.embedding import HashEmbedder, HashSparseEmbedder
from citerator.ingestion.pipeline import IngestConfig, main, run_ingestion


@pytest.fixture
def client():
    return QdrantClient(location=":memory:")


def cfg(tmp_path, docs_dir, **kw) -> IngestConfig:
    base = dict(
        input_dir=docs_dir,
        strategy="structure",
        embedder="hash",
        sparse="hash",
        max_tokens=120,
        min_tokens=10,
        report_dir=tmp_path / "reports",
        processed_dir=tmp_path / "processed",
    )
    base.update(kw)
    return IngestConfig(**base)


def run(tmp_path, docs_dir, client, **kw):
    return run_ingestion(cfg(tmp_path, docs_dir, **kw), embedder=HashEmbedder(), sparse=HashSparseEmbedder(), client=client)


def all_points(client, collection):
    pts, _ = client.scroll(collection, limit=10_000, with_payload=True, with_vectors=True)
    return pts


def test_end_to_end_indexes_all_formats_with_metadata(tmp_path, docs_dir, client):
    rep = run(tmp_path, docs_dir, client)
    assert rep["documents"]["indexed"] == 3 and rep["documents"]["failed"] == 0
    coll = rep["config"]["collection"]
    assert rep["points_in_collection"] == rep["stats"]["n_chunks"] > 0

    pts = all_points(client, coll)
    by_file = {}
    for p in pts:
        by_file.setdefault(p.payload["source_file"], []).append(p)
    assert set(by_file) == {"manual.pdf", "policy.md", "faq.html"}
    pdf_pt = next(p for p in by_file["manual.pdf"] if "five years" in p.payload["text"])
    pl = pdf_pt.payload
    assert pl["page_start"] == pl["page_end"] == 3
    assert pl["section_path"][-1] == "3. Record keeping"
    assert pl["embedding_model"] == "hash-256" and pl["chunker"] == "structure"
    assert pl["doc_title"] == "ACME AML Manual" and "embed_text" not in pl
    md_pt = by_file["policy.md"][0].payload
    assert md_pt["doc_type"] == "internal_policy" and md_pt["jurisdiction"] == "PK" and md_pt["page_start"] is None
    # both named vectors are stored
    assert set(pdf_pt.vector) == {"dense", "bm25"} and len(pdf_pt.vector["dense"]) == 256


def test_rerun_is_idempotent_and_skips_unchanged(tmp_path, docs_dir, client):
    first = run(tmp_path, docs_dir, client)
    coll = first["config"]["collection"]
    ids_before = {p.id for p in all_points(client, coll)}
    second = run(tmp_path, docs_dir, client)
    assert second["documents"]["skipped"] == 3 and second["documents"]["indexed"] == 0
    assert {p.id for p in all_points(client, coll)} == ids_before
    assert second["points_in_collection"] == first["points_in_collection"]


def test_force_reindexes_without_duplicates(tmp_path, docs_dir, client):
    first = run(tmp_path, docs_dir, client)
    forced = run(tmp_path, docs_dir, client, force=True)
    assert forced["documents"]["indexed"] == 3
    assert forced["points_in_collection"] == first["points_in_collection"]


def test_changed_document_replaces_its_old_points(tmp_path, docs_dir, client):
    first = run(tmp_path, docs_dir, client)
    coll = first["config"]["collection"]
    (docs_dir / "policy.md").write_text("# Policy\n\nCompletely new short text about sanctions.", encoding="utf-8")
    second = run(tmp_path, docs_dir, client)
    assert second["documents"]["indexed"] == 1 and second["documents"]["skipped"] == 2
    md_points = [p for p in all_points(client, coll) if p.payload["source_file"] == "policy.md"]
    assert len(md_points) == 1 and "sanctions" in md_points[0].payload["text"]


def test_changing_chunk_settings_reindexes_everything(tmp_path, docs_dir, client):
    run(tmp_path, docs_dir, client)
    again = run(tmp_path, docs_dir, client, max_tokens=60)
    assert again["documents"]["indexed"] == 3 and again["documents"]["skipped"] == 0


def test_dry_run_writes_nothing_but_reports_stats(tmp_path, docs_dir, client):
    rep = run(tmp_path, docs_dir, client, dry_run=True)
    assert rep["stats"]["n_chunks"] > 0 and rep["points_in_collection"] is None
    assert client.get_collections().collections == []
    assert not list((tmp_path / "processed").glob("manifest__*.json"))
    assert Path(rep["report_path"]).exists()


def test_prune_removes_deleted_documents(tmp_path, docs_dir, client):
    first = run(tmp_path, docs_dir, client)
    coll = first["config"]["collection"]
    (docs_dir / "faq.html").unlink()
    rep = run(tmp_path, docs_dir, client, prune=True)
    assert rep["pruned"] == ["faq.html"]
    assert {p.payload["source_file"] for p in all_points(client, coll)} == {"manual.pdf", "policy.md"}


def test_one_corrupt_file_does_not_stop_the_run(tmp_path, docs_dir, client):
    (docs_dir / "broken.pdf").write_bytes(b"this is not a pdf at all")
    rep = run(tmp_path, docs_dir, client)
    assert rep["documents"]["failed"] == 1 and rep["documents"]["indexed"] == 3
    bad = next(d for d in rep["per_document"] if d["file"] == "broken.pdf")
    assert bad["status"] == "failed" and bad["error"]


def test_scanned_page_warning_reaches_the_report(tmp_path, docs_dir, client):
    rep = run(tmp_path, docs_dir, client)
    pdf = next(d for d in rep["per_document"] if d["file"] == "manual.pdf")
    assert any("page 4" in w for w in pdf["warnings"])


def test_report_file_contents(tmp_path, docs_dir, client):
    rep = run(tmp_path, docs_dir, client)
    data = json.loads(Path(rep["report_path"]).read_text())
    assert data["config"]["strategy"] == "structure" and data["config"]["tokenizer_exact"] is False
    assert len(data["chunk_token_counts"]) == data["stats"]["n_chunks"]
    assert data["stats"]["pct_over_model_limit"] == 0


@pytest.mark.parametrize("strategy", ["fixed", "semantic"])
def test_other_strategies_run_end_to_end(tmp_path, docs_dir, client, strategy):
    rep = run(tmp_path, docs_dir, client, strategy=strategy)
    assert rep["documents"]["failed"] == 0 and rep["points_in_collection"] > 0
    assert rep["config"]["collection"].startswith(f"citerator__{strategy}__")


def test_embedding_cache_is_used_on_forced_rerun(tmp_path, docs_dir, client):
    first = run(tmp_path, docs_dir, client)
    second = run(tmp_path, docs_dir, client, force=True)
    assert first["embedding"]["cache_misses"] > 0
    assert second["embedding"]["cache_misses"] == 0 and second["embedding"]["cache_hits"] > 0


def test_rejects_chunk_size_too_close_to_model_limit(tmp_path, docs_dir, client):
    class Tiny(HashEmbedder):
        max_tokens = 128

    with pytest.raises(ValueError, match="silently truncated"):
        run_ingestion(cfg(tmp_path, docs_dir, max_tokens=100), embedder=Tiny(), sparse=None, client=client)


def test_refuses_to_mix_embedding_dimensions_in_one_collection(tmp_path, docs_dir, client):
    run(tmp_path, docs_dir, client)
    with pytest.raises(RuntimeError, match="Never mix embedding models"):
        run_ingestion(
            cfg(tmp_path, docs_dir, collection="citerator__structure__hash-256"),
            embedder=HashEmbedder(dim=128), sparse=HashSparseEmbedder(), client=client,
        )


def test_missing_or_empty_input_folder(tmp_path, client):
    with pytest.raises(FileNotFoundError):
        run_ingestion(IngestConfig(input_dir=tmp_path / "nope"), embedder=HashEmbedder(), client=client)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="no supported documents"):
        run_ingestion(IngestConfig(input_dir=empty), embedder=HashEmbedder(), client=client)


def test_cli_dry_run_exit_codes(tmp_path, docs_dir, capsys):
    argv = ["--input", str(docs_dir), "--embedder", "hash", "--sparse", "none", "--dry-run",
            "--report-dir", str(tmp_path / "r"), "--processed-dir", str(tmp_path / "p"), "--max-tokens", "120"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "tokens mean / median / p95" in out and "no extractable body text" in out
    assert main(["--input", str(tmp_path / "missing"), "--embedder", "hash"]) == 2
