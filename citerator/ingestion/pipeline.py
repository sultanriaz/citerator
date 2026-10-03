"""Ingestion pipeline: folder of documents -> chunks -> embeddings -> Qdrant, plus a run report.

    python -m citerator.ingestion.pipeline --input data/raw --strategy structure --embedder bge

Properties:
  * Idempotent: unchanged files (same content hash AND same pipeline settings) are skipped.
    Changed files are re-indexed: old points are deleted by doc_id, new ones upserted.
  * Deterministic: chunk IDs are UUIDv5 of (doc, chunker, params, index); re-runs overwrite.
  * Observable: every run writes a JSON report (stats, warnings, per-document status).
  * Resumable: the manifest is saved after each document, so a crash loses at most one.
  * One bad file never stops the run; failures are reported and the exit code is non-zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .chunking import chunk_document, make_chunker
from .embedding import CachedEmbedder, get_embedder, get_sparse_embedder
from .loaders import discover_files, doc_id_for, file_sha256, load_document
from .models import Chunk
from .stats import compute_stats, format_stats
from .store import ChunkStore, collection_name, make_client, slug
from .tokens import get_tokenizer

log = logging.getLogger("citerator.pipeline")

TOKEN_SAFETY_MARGIN = 64  # room for the breadcrumb prefix and tokenizer approximation


@dataclass
class IngestConfig:
    input_dir: Path = Path("data/raw")
    strategy: str = "structure"  # fixed | structure | semantic
    embedder: str = "bge"  # bge | openai | hash
    embedding_model: str | None = None
    sparse: str = "bm25"  # bm25 | hash | none
    qdrant_url: str = "http://localhost:6333"
    collection: str | None = None
    max_tokens: int = 400
    min_tokens: int | None = None
    overlap_ratio: float | None = None
    breakpoint_percentile: float | None = None
    force: bool = False
    dry_run: bool = False
    prune: bool = False
    use_cache: bool = True
    price_per_million_tokens: float | None = None
    report_dir: Path = Path("eval/results")
    processed_dir: Path = Path("data/processed")


# --------------------------------------------------------------------------- manifest


def _load_manifest(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Manifest %s unreadable (%s); starting fresh", path, exc)
    return {}


def _save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _signature(chunker, embedder, sparse, tokenizer) -> str:
    blob = json.dumps(
        {
            "chunker": chunker.name,
            "params": chunker.params,
            "embedder": embedder.name,
            "sparse": getattr(sparse, "name", None),
            "tokenizer": tokenizer.name,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- run


def run_ingestion(cfg: IngestConfig, embedder=None, sparse=None, client=None) -> dict:
    """Run the pipeline and return the report dict. Pass embedder/sparse/client to inject fakes."""
    t_start = time.time()
    run_ts = datetime.now(timezone.utc)
    input_dir = Path(cfg.input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input folder not found: {input_dir}")
    files = discover_files(input_dir)
    if not files:
        raise FileNotFoundError(f"no supported documents (.pdf .md .html) found in {input_dir}")

    base_embedder = embedder or get_embedder(cfg.embedder, cfg.embedding_model)
    if sparse is None:
        sparse = get_sparse_embedder(cfg.sparse)
    cached = None
    if cfg.use_cache and not isinstance(base_embedder, CachedEmbedder):
        cached = CachedEmbedder(base_embedder, Path(cfg.processed_dir) / "embedding_cache.sqlite")
    emb = cached or base_embedder

    if cfg.max_tokens > emb.max_tokens - TOKEN_SAFETY_MARGIN:
        raise ValueError(
            f"max_tokens={cfg.max_tokens} is too close to the {emb.name} input limit ({emb.max_tokens}); "
            f"use at most {emb.max_tokens - TOKEN_SAFETY_MARGIN}. Longer text would be silently truncated."
        )

    tokenizer = get_tokenizer(emb.tokenizer_name)
    chunker = make_chunker(
        cfg.strategy,
        tokenizer,
        embedder=emb,
        max_tokens=cfg.max_tokens,
        min_tokens=cfg.min_tokens,
        overlap_ratio=cfg.overlap_ratio,
        breakpoint_percentile=cfg.breakpoint_percentile,
    )
    collection = cfg.collection or collection_name(cfg.strategy, emb.name)
    signature = _signature(chunker, emb, sparse, tokenizer)
    manifest_path = Path(cfg.processed_dir) / f"manifest__{collection}.json"
    manifest = _load_manifest(manifest_path)

    store = None
    if not cfg.dry_run:
        client = client or make_client(cfg.qdrant_url)
        store = ChunkStore(client, collection, emb.dim, sparse=sparse is not None)
        store.ensure_collection()

    log.info("collection=%s strategy=%s embedder=%s tokenizer=%s%s", collection, cfg.strategy, emb.name,
             tokenizer.name, "" if tokenizer.exact else " (APPROXIMATE token counts)")

    doc_reports: list[dict] = []
    all_chunks: list[Chunk] = []
    for path in files:
        rel = path.relative_to(input_dir).as_posix()
        t0 = time.time()
        report = {"file": rel, "status": "indexed", "chunks": 0, "warnings": [], "seconds": 0.0}
        try:
            doc_hash = file_sha256(path)
            entry = manifest.get(rel)
            if entry and entry.get("doc_hash") == doc_hash and entry.get("signature") == signature and not cfg.force:
                report.update(status="skipped", chunks=entry.get("chunk_count", 0))
                doc_reports.append(report)
                continue

            doc = load_document(path, input_dir)
            report["warnings"] = list(doc.warnings)
            chunks = chunk_document(doc, chunker, tokenizer)
            report["chunks"] = len(chunks)
            report["title"] = doc.title

            if not chunks:
                report["status"] = "empty"
                if store is not None:
                    store.delete_doc(doc.doc_id)
                    manifest.pop(rel, None)
                    _save_manifest(manifest_path, manifest)
            else:
                all_chunks += chunks
                if store is None:
                    report["status"] = "dry_run"
                else:
                    dense = emb.embed_documents([c.embed_text for c in chunks])
                    sparse_vecs = sparse.embed_documents([c.embed_text for c in chunks]) if sparse else None
                    store.delete_doc(doc.doc_id)  # remove stale points from an older version
                    store.upsert(chunks, dense, sparse_vecs, emb.name, run_ts)
                    manifest[rel] = {
                        "doc_id": doc.doc_id,
                        "doc_hash": doc_hash,
                        "signature": signature,
                        "chunk_count": len(chunks),
                        "title": doc.title,
                        "ingested_at": run_ts.isoformat(),
                    }
                    _save_manifest(manifest_path, manifest)
        except Exception as exc:  # one bad file must not stop the run
            log.exception("failed to ingest %s", rel)
            report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            report["seconds"] = round(time.time() - t0, 2)
        if report["status"] != "skipped":
            doc_reports.append(report)

    pruned: list[str] = []
    if cfg.prune and store is not None:
        on_disk = {p.relative_to(input_dir).as_posix() for p in files}
        for rel in sorted(set(manifest) - on_disk):
            store.delete_doc(manifest[rel].get("doc_id") or doc_id_for(rel))
            manifest.pop(rel)
            pruned.append(rel)
        if pruned:
            _save_manifest(manifest_path, manifest)

    stats = compute_stats(all_chunks, model_max_tokens=emb.max_tokens)
    counts = {s: sum(d["status"] == s for d in doc_reports) for s in ("indexed", "skipped", "empty", "failed", "dry_run")}
    report = {
        "run_id": run_ts.strftime("%Y%m%dT%H%M%SZ"),
        "timestamp": run_ts.isoformat(),
        "config": {
            "strategy": cfg.strategy,
            "chunker_params": chunker.params,
            "embedder": emb.name,
            "embedding_dim": emb.dim,
            "sparse": getattr(sparse, "name", None),
            "tokenizer": tokenizer.name,
            "tokenizer_exact": tokenizer.exact,
            "collection": collection,
            "dry_run": cfg.dry_run,
            "force": cfg.force,
        },
        "documents": counts | {"total": len(doc_reports)},
        "stats_note": "stats cover documents processed in this run (skipped documents are excluded)",
        "stats": stats,
        "chunk_token_counts": [c.token_count for c in all_chunks],
        "embedding": {
            "cache_hits": getattr(cached, "hits", None),
            "cache_misses": getattr(cached, "misses", None),
            "tokens_to_embed": stats.get("embed_tokens_total", 0),
            "estimated_cost_usd": (
                round(stats.get("embed_tokens_total", 0) / 1e6 * cfg.price_per_million_tokens, 4)
                if cfg.price_per_million_tokens is not None
                else None
            ),
        },
        "pruned": pruned,
        "per_document": doc_reports,
        "points_in_collection": store.count() if store is not None else None,
        "seconds": round(time.time() - t_start, 2),
    }

    report_dir = Path(cfg.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ingest_{report['run_id']}_{slug(cfg.strategy)}_{slug(emb.name)}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    if cached is not None:
        cached.close()
    return report


# --------------------------------------------------------------------------- CLI


def _print_summary(report: dict) -> None:
    cfg = report["config"]
    docs = report["documents"]
    print()
    print(f"Run {report['run_id']}  strategy={cfg['strategy']}  embedder={cfg['embedder']}  "
          f"collection={cfg['collection']}{'  [DRY RUN]' if cfg['dry_run'] else ''}")
    print(f"Documents: {docs['total']} processed  (indexed={docs['indexed']} skipped={docs['skipped']} "
          f"empty={docs['empty']} failed={docs['failed']} dry_run={docs['dry_run']})")
    print(report["stats_note"])
    print(format_stats(report["stats"]))
    emb = report["embedding"]
    if emb["cache_hits"] is not None:
        print(f"  embedding cache hits/misses  {emb['cache_hits']} / {emb['cache_misses']}")
    if emb["estimated_cost_usd"] is not None:
        print(f"  estimated embedding cost     ${emb['estimated_cost_usd']}")
    if not cfg["tokenizer_exact"]:
        print("  NOTE: token counts are approximate (real tokenizer unavailable)")
    problems = [d for d in report["per_document"] if d["warnings"] or d["status"] == "failed"]
    if problems:
        print("\nWarnings:")
        for d in problems:
            for w in d["warnings"]:
                print(f"  {d['file']}: {w}")
            if d["status"] == "failed":
                print(f"  {d['file']}: FAILED - {d.get('error')}")
    if report["pruned"]:
        print(f"\nPruned from index (deleted on disk): {', '.join(report['pruned'])}")
    print(f"\nReport: {report['report_path']}  ({report['seconds']}s)")


def build_parser() -> argparse.ArgumentParser:
    from citerator.config import get_settings

    s = get_settings()
    p = argparse.ArgumentParser(prog="python -m citerator.ingestion.pipeline", description=__doc__.split("\n\n")[0])
    p.add_argument("--input", default="data/raw", help="folder with .pdf/.md/.html documents (default: data/raw)")
    p.add_argument("--strategy", choices=["fixed", "structure", "semantic"], default="structure")
    p.add_argument("--embedder", choices=["bge", "openai", "hash"], default="bge")
    p.add_argument("--embedding-model", default=None, help=f"model name (bge default: {s.embedding_model})")
    p.add_argument("--sparse", choices=["bm25", "hash", "none"], default="bm25", help="sparse vectors for hybrid search")
    p.add_argument("--qdrant-url", default=s.qdrant_url, help="http URL, ':memory:' or a local folder")
    p.add_argument("--collection", default=None, help="override the auto-generated collection name")
    p.add_argument("--max-tokens", type=int, default=400)
    p.add_argument("--min-tokens", type=int, default=None, help="structure/semantic minimum chunk size")
    p.add_argument("--overlap", type=float, default=None, dest="overlap_ratio", help="fixed: overlap ratio, e.g. 0.12")
    p.add_argument("--breakpoint-percentile", type=float, default=None, help="semantic: split threshold percentile")
    p.add_argument("--force", action="store_true", help="re-index every file even if unchanged")
    p.add_argument("--dry-run", action="store_true", help="load + chunk + stats only; no embeddings, no Qdrant writes")
    p.add_argument("--prune", action="store_true", help="remove from the index documents deleted from disk")
    p.add_argument("--no-cache", action="store_true", help="disable the on-disk embedding cache")
    p.add_argument("--price-per-million", type=float, default=None, dest="price_per_million_tokens",
                   help="USD per 1M embedding tokens (for the cost estimate; check current API pricing)")
    p.add_argument("--report-dir", default="eval/results")
    p.add_argument("--processed-dir", default="data/processed")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = IngestConfig(
        input_dir=Path(args.input), strategy=args.strategy, embedder=args.embedder,
        embedding_model=args.embedding_model, sparse=args.sparse, qdrant_url=args.qdrant_url,
        collection=args.collection, max_tokens=args.max_tokens, min_tokens=args.min_tokens,
        overlap_ratio=args.overlap_ratio, breakpoint_percentile=args.breakpoint_percentile,
        force=args.force, dry_run=args.dry_run, prune=args.prune, use_cache=not args.no_cache,
        price_per_million_tokens=args.price_per_million_tokens,
        report_dir=Path(args.report_dir), processed_dir=Path(args.processed_dir),
    )
    try:
        report = run_ingestion(cfg)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print_summary(report)
    return 1 if report["documents"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
