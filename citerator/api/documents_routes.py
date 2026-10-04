"""Document upload, job status, and registry endpoints.

All routes require the existing X-API-Key dependency. Uploads are saved under
``settings.documents_root`` and scheduled as background tasks -- the HTTP
response returns immediately with job_ids the client can poll.

Background ingestion runs in a dedicated thread with its own event loop.
``asyncio.create_task`` is not usable here: Starlette's test client tears down
its request loop when the response completes, cancelling any task scheduled
inside the endpoint. A thread owns its loop independently and survives.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from citerator.api.deps import require_api_key
from citerator.config import Settings, get_settings
from citerator.documents import ingest_service, jobs, registry
from citerator.ingestion.store import make_client

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED_EXTENSIONS = {".pdf", ".md", ".markdown", ".html", ".htm"}


def _schedule(coro) -> None:
    """Run a coroutine in a daemon thread with its own event loop."""

    def runner() -> None:
        try:
            asyncio.run(coro)
        except Exception:
            logger.exception("background_task_failed")

    thread = threading.Thread(target=runner, daemon=True, name="citerator-bg")
    thread.start()


def _safe_filename(name: str) -> str:
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty filename")
    if name != Path(name).name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Filename must not contain path separators: {name}",
        )
    if name in {".", ".."}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    return name


def _validate_extension(name: str) -> None:
    ext = Path(name).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported extension: {ext}. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )


async def _save_upload(file: UploadFile, dest: Path, max_bytes: int) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with dest.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"File exceeds {max_bytes} bytes",
                )
            fh.write(chunk)
    return total


def _write_sidecar(source: Path, meta: dict[str, Any]) -> None:
    payload = {k: v for k, v in meta.items() if v not in (None, "")}
    if not payload:
        return
    sidecar = source.with_suffix(source.suffix + ".meta.json")
    sidecar.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_documents(
    files: list[UploadFile] = File(...),
    doc_type: str | None = Form(None),
    jurisdiction: str | None = Form(None),
    effective_date: str | None = Form(None),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files supplied")

    root = Path(settings.documents_root)
    root.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    meta = {
        "doc_type": doc_type,
        "jurisdiction": jurisdiction,
        "effective_date": effective_date,
    }

    accepted: list[dict[str, str]] = []

    for upload in files:
        name = _safe_filename(upload.filename or "")
        _validate_extension(name)

        dest = root / name
        await _save_upload(upload, dest, max_bytes)
        _write_sidecar(dest, meta)

        job_id = jobs.create_job(
            dest.relative_to(root).as_posix(),
            db_path=settings.documents_db_path,
        )
        _schedule(ingest_service.process_file(dest, settings, meta, job_id))
        accepted.append({"file_name": name, "job_id": job_id})

    return {"accepted": accepted, "count": len(accepted)}


@router.get("/jobs")
def list_jobs_endpoint(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> list[dict[str, Any]]:
    return jobs.list_jobs(
        limit=limit, status=status, db_path=settings.documents_db_path
    )


@router.get("/chunking-strategies")
def chunking_strategies_endpoint(
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    rows = registry.list_documents(
        limit=None, sort="updated_at", order="desc", db_path=settings.documents_db_path
    )

    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        chunker = row.get("chunker") or "unknown"
        bucket = groups.setdefault(
            chunker,
            {
                "chunker": chunker,
                "document_count": 0,
                "total_chunk_count": 0,
                "chunk_counts": [],
                "active": chunker == settings.active_chunking_strategy,
                "note": (
                    "Corpus-shape statistics only. Retrieval-quality metrics "
                    "(hit@5, MRR) require labelled questions and belong to Phase 5."
                ),
            },
        )
        bucket["document_count"] += 1
        bucket["total_chunk_count"] += int(row.get("chunk_count") or 0)
        bucket["chunk_counts"].append(int(row.get("chunk_count") or 0))

    def _median(values: list[int]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        n = len(s)
        mid = n // 2
        if n % 2 == 1:
            return float(s[mid])
        return (s[mid - 1] + s[mid]) / 2.0

    strategies: list[dict[str, Any]] = []
    for bucket in groups.values():
        counts = bucket.pop("chunk_counts")
        bucket["avg_chunk_count"] = (
            round(sum(counts) / len(counts), 2) if counts else 0.0
        )
        bucket["median_chunk_count"] = _median(counts)
        strategies.append(bucket)

    return {"strategies": strategies, "active": settings.active_chunking_strategy}


@router.get("/jobs/{job_id}")
def get_job_endpoint(
    job_id: str,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    job = jobs.get_job(job_id, db_path=settings.documents_db_path)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job_endpoint(
    job_id: str,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, str]:
    job = jobs.get_job(job_id, db_path=settings.documents_db_path)
    if job is None or job["status"] != "failed":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Job not found or not in 'failed' state"
        )

    root = Path(settings.documents_root)
    target = root / job["file_name"]

    jobs.update_job(
        job_id,
        db_path=settings.documents_db_path,
        status="queued",
        error=None,
    )
    _schedule(ingest_service.process_file(target, settings, None, job_id))
    return {"job_id": job_id, "status": "queued"}


@router.get("")
def list_documents_endpoint(
    search: str | None = Query(None),
    doc_type: str | None = Query(None),
    jurisdiction: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    rows = registry.list_documents(
        search=search,
        doc_type=doc_type,
        jurisdiction=jurisdiction,
        status=status,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
        db_path=settings.documents_db_path,
    )
    return {"documents": rows, "count": len(rows), "limit": limit, "offset": offset}


@router.get("/{doc_id}/chunks")
def get_document_chunks_endpoint(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from citerator.ingestion.embedding import get_embedder
    from citerator.ingestion.store import collection_name
    from qdrant_client import models as qmodels

    embedder = get_embedder(settings.embedder_kind, settings.embedding_model or None)
    collection = collection_name(settings.active_chunking_strategy, embedder.name)

    client = make_client(settings.qdrant_url)
    try:
        result, _ = client.scroll(
            collection_name=collection,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id", match=qmodels.MatchValue(value=doc_id)
                    )
                ]
            ),
            limit=1000,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Qdrant unavailable: {exc}"
        ) from exc

    chunks = []
    for point in result:
        payload = point.payload or {}
        chunks.append(
            {
                "chunk_id": payload.get("chunk_id"),
                "section_path": payload.get("section_path") or [],
                "page_start": payload.get("page_start"),
                "page_end": payload.get("page_end"),
                "token_count": payload.get("token_count"),
                "text": payload.get("text"),
                "chunk_index": payload.get("chunk_index"),
            }
        )

    chunks.sort(key=lambda c: (c["chunk_index"] is None, c["chunk_index"]))
    return {"doc_id": doc_id, "count": len(chunks), "chunks": chunks}


@router.get("/{doc_id}")
def get_document_endpoint(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    row = registry.get_document(doc_id, db_path=settings.documents_db_path)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return row


@router.post("/{doc_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document_endpoint(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, str]:
    row = registry.get_document(doc_id, db_path=settings.documents_db_path)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    root = Path(settings.documents_root)
    target = root / row["source_file"]
    if not target.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Source file missing: {row['source_file']}"
        )

    job_id = jobs.create_job(
        row["source_file"], db_path=settings.documents_db_path
    )
    _schedule(ingest_service.process_file(target, settings, None, job_id, force=True))
    return {"job_id": job_id, "doc_id": doc_id, "status": "queued"}


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_endpoint(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> Response:
    ingest_service.delete_document(doc_id, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
