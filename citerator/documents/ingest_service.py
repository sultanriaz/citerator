"""Per-file ingestion service driving the Documents screen's live status.

Runs the same effective pipeline as citerator.ingestion.pipeline but as discrete
awaited steps, updating a job row before and after each stage so the UI can
poll progress. The manifest file and signature format match pipeline.py's so a
file ingested via API is recognized as already-indexed by a later CLI run, and
vice versa.

CPU-bound stages (parse, chunk, embed, index) are dispatched to threads via
``asyncio.to_thread``. Concurrency across files is bounded by an
``asyncio.Semaphore`` sized from ``settings.max_concurrent_ingest_jobs``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from citerator.config import Settings
from citerator.documents import jobs, registry
from citerator.ingestion.chunking import chunk_document, make_chunker
from citerator.ingestion.embedding import (
    CachedEmbedder,
    get_embedder,
    get_sparse_embedder,
)
from citerator.ingestion.loaders import load_document
from citerator.ingestion.store import ChunkStore, collection_name, make_client
from citerator.ingestion.tokens import get_tokenizer

logger = structlog.get_logger(__name__)

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore(settings: Settings) -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_ingest_jobs)
    return _semaphore


def _processed_dir(settings: Settings) -> Path:
    return Path(settings.documents_db_path).parent


def _manifest_path(settings: Settings, collection: str) -> Path:
    return _processed_dir(settings) / f"manifest__{collection}.json"


def read_manifest(settings: Settings, collection: str) -> dict[str, Any]:
    path = _manifest_path(settings, collection)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_manifest(settings: Settings, collection: str, data: dict[str, Any]) -> None:
    path = _manifest_path(settings, collection)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def compute_signature(chunker, embedder, sparse, tokenizer) -> str:
    """Hash of (chunker name+params, embedder, sparse, tokenizer).

    Matches pipeline.py's signature format so manifest entries written here are
    recognized by the CLI and vice versa.
    """

    chunker_name = getattr(chunker, "name", type(chunker).__name__)
    chunker_params = getattr(chunker, "params", {}) or {}
    embedder_name = getattr(embedder, "name", "") or ""
    sparse_name = getattr(sparse, "name", "none") if sparse else "none"
    tokenizer_name = getattr(tokenizer, "name", "") or ""

    payload = {
        "chunker": {"name": chunker_name, "params": chunker_params},
        "embedder": embedder_name,
        "sparse": sparse_name,
        "tokenizer": tokenizer_name,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _make_cached(base):
    try:
        return CachedEmbedder(base)
    except Exception:
        return base


async def process_file(
    path: Path,
    settings: Settings,
    meta: dict[str, Any] | None,
    job_id: str,
    *,
    force: bool = False,
) -> None:
    """Ingest a single file, updating ``job_id`` through each stage.

    Never propagates exceptions: any failure marks the job ``failed`` with the
    error string captured. This is a background task from the API's point of
    view, so silence would hide real problems -- the job row is the visible
    record.
    """

    db_path = settings.documents_db_path
    root = Path(settings.documents_root).resolve()
    resolved = path.resolve()

    if not resolved.exists():
        jobs.update_job(
            job_id, db_path=db_path, status="failed", error=f"File not found: {resolved}"
        )
        return

    try:
        async with _get_semaphore(settings):
            rel = _rel_posix(resolved, root)

            jobs.update_job(job_id, db_path=db_path, status="parsing")
            doc = await asyncio.to_thread(load_document, resolved, root)

            jobs.update_job(job_id, db_path=db_path, status="chunking", doc_id=doc.doc_id)

            tokenizer = get_tokenizer(settings.embedding_model or None)
            base_embedder = get_embedder(
                settings.embedder_kind, settings.embedding_model or None
            )
            embedder = _make_cached(base_embedder)
            sparse = get_sparse_embedder(settings.sparse_kind)

            chunker = make_chunker(
                settings.active_chunking_strategy,
                tokenizer,
                embedder=base_embedder,
            )
            chunks = await asyncio.to_thread(chunk_document, doc, chunker, tokenizer)

            signature = compute_signature(chunker, base_embedder, sparse, tokenizer)
            collection = collection_name(
                settings.active_chunking_strategy, base_embedder.name
            )

            if not chunks:
                registry.upsert_document(
                    {
                        "doc_id": doc.doc_id,
                        "source_file": rel,
                        "title": doc.title,
                        "doc_type": doc.doc_type,
                        "jurisdiction": doc.jurisdiction,
                        "effective_date": doc.effective_date,
                        "page_count": len(getattr(doc, "pages", []) or []),
                        "chunk_count": 0,
                        "doc_hash": doc.doc_hash,
                        "chunker": getattr(chunker, "name", type(chunker).__name__),
                        "chunker_params": getattr(chunker, "params", {}),
                        "embedder": base_embedder.name,
                        "sparse_embedder": getattr(sparse, "name", None),
                        "status": "empty",
                        "warnings": getattr(doc, "warnings", []) or [],
                    },
                    db_path=db_path,
                )
                jobs.update_job(
                    job_id,
                    db_path=db_path,
                    status="indexed",
                    doc_id=doc.doc_id,
                    warnings=getattr(doc, "warnings", []) or [],
                )
                return

            jobs.update_job(job_id, db_path=db_path, status="embedding")
            texts = [chunk.embed_text for chunk in chunks]
            dense = await asyncio.to_thread(embedder.embed_documents, texts)
            sparse_vecs = (
                await asyncio.to_thread(sparse.embed_documents, texts) if sparse else None
            )

            jobs.update_job(job_id, db_path=db_path, status="indexing")
            client = make_client(settings.qdrant_url)
            store = ChunkStore(
                client,
                collection,
                dim=base_embedder.dim,
                sparse=sparse is not None,
            )
            store.ensure_collection()
            if force:
                try:
                    store.delete_doc(doc.doc_id)
                except Exception:
                    pass
            await asyncio.to_thread(
                store.upsert,
                chunks,
                dense,
                sparse_vecs,
                base_embedder.name,
                datetime.now(timezone.utc),
            )

            registry.upsert_document(
                {
                    "doc_id": doc.doc_id,
                    "source_file": rel,
                    "title": doc.title,
                    "doc_type": doc.doc_type,
                    "jurisdiction": doc.jurisdiction,
                    "effective_date": doc.effective_date,
                    "page_count": len(getattr(doc, "pages", []) or []),
                    "chunk_count": len(chunks),
                    "doc_hash": doc.doc_hash,
                    "chunker": getattr(chunker, "name", type(chunker).__name__),
                    "chunker_params": getattr(chunker, "params", {}),
                    "embedder": base_embedder.name,
                    "sparse_embedder": getattr(sparse, "name", None),
                    "status": "indexed",
                    "warnings": getattr(doc, "warnings", []) or [],
                },
                db_path=db_path,
            )

            manifest = read_manifest(settings, collection)
            manifest[rel] = {
                "doc_id": doc.doc_id,
                "doc_hash": doc.doc_hash,
                "signature": signature,
                "chunk_count": len(chunks),
                "title": doc.title,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
            write_manifest(settings, collection, manifest)

            jobs.update_job(
                job_id,
                db_path=db_path,
                status="indexed",
                doc_id=doc.doc_id,
                warnings=getattr(doc, "warnings", []) or [],
            )
            logger.info(
                "ingest_job_indexed",
                job_id=job_id,
                doc_id=doc.doc_id,
                chunks=len(chunks),
                source_file=rel,
            )

    except Exception as exc:
        logger.warning(
            "ingest_job_failed",
            job_id=job_id,
            file=str(resolved),
            error=str(exc),
        )
        jobs.update_job(
            job_id,
            db_path=db_path,
            status="failed",
            error=str(exc),
        )


def delete_document(doc_id: str, settings: Settings) -> None:
    """Remove a document from Qdrant, the registry, the manifest, and disk.

    Idempotent: missing rows, missing files, and missing manifest entries are
    all silently skipped.
    """

    db_path = settings.documents_db_path

    row = registry.get_document(doc_id, db_path=db_path)
    source_file = row.get("source_file") if row else None

    base_embedder = get_embedder(settings.embedder_kind, settings.embedding_model or None)
    collection = collection_name(settings.active_chunking_strategy, base_embedder.name)

    try:
        client = make_client(settings.qdrant_url)
        store = ChunkStore(
            client,
            collection,
            dim=base_embedder.dim,
            sparse=get_sparse_embedder(settings.sparse_kind) is not None,
        )
        store.delete_doc(doc_id)
    except Exception as exc:
        logger.warning("delete_doc_qdrant_failed", doc_id=doc_id, error=str(exc))

    registry.delete_document(doc_id, db_path=db_path)

    manifest = read_manifest(settings, collection)
    changed = False
    for rel, entry in list(manifest.items()):
        if isinstance(entry, dict) and entry.get("doc_id") == doc_id:
            manifest.pop(rel, None)
            changed = True
    if changed:
        write_manifest(settings, collection, manifest)

    if source_file:
        root = Path(settings.documents_root).resolve()
        try:
            target = (root / source_file).resolve()
            if str(target).startswith(str(root)) and target.exists():
                target.unlink()
                sidecar = target.with_suffix(target.suffix + ".meta.json")
                if sidecar.exists():
                    sidecar.unlink()
        except OSError as exc:
            logger.warning("delete_doc_disk_failed", doc_id=doc_id, error=str(exc))
