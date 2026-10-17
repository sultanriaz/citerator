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
    """Legacy in-process scheduling. Retained for direct callers that
    prefer to bypass the queue; the route handlers now use
    _enqueue_ingestion instead."""

    def runner() -> None:
        try:
            asyncio.run(coro)
        except Exception:
            logger.exception("background_task_failed")

    thread = threading.Thread(target=runner, daemon=True, name="citerator-bg")
    thread.start()


def _enqueue_ingestion(
    path,
    settings,
    meta,
    job_id: str,
    *,
    force: bool = False,
) -> None:
    """Submit an ingestion job to the configured queue backend.

    Inline backend runs in-process using the *actual* settings object so
    per-request overrides (document roots, embedder choice) apply without
    a serialization round trip. RQ backend serializes a small subset of
    settings and lets the worker resolve the rest from its own env.
    """

    from citerator.queue import get_queue

    queue = get_queue(settings)

    if queue.name == "inline":
        import asyncio as _asyncio
        import threading as _threading

        def runner() -> None:
            try:
                _asyncio.run(
                    ingest_service.process_file(path, settings, meta, job_id)
                )
            except Exception:
                logger.exception("inline_ingest_failed")

        _threading.Thread(
            target=runner, daemon=True, name="citerator-ingest"
        ).start()
        return

    overrides = {
        "llm_model": settings.llm_model,
        "llm_provider": settings.llm_provider,
        "active_chunking_strategy": settings.active_chunking_strategy,
    }
    queue.enqueue(
        "citerator.queue.jobs.run_ingestion_job",
        str(path),
        job_id,
        meta,
        overrides,
    )


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
    visibility: str | None = Form(None),
    settings: Settings = Depends(get_settings),
    tenant: Any = Depends(require_api_key),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files supplied")

    root = Path(settings.documents_root)
    root.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    tenant_id = getattr(tenant, "tenant_id", "global") or "global"
    owner_id = getattr(tenant, "user_id", None)
    vis = visibility or "tenant"

    meta = {
        "doc_type": doc_type,
        "jurisdiction": jurisdiction,
        "effective_date": effective_date,
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "visibility": vis,
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
            tenant_id=tenant_id,
            owner_id=owner_id,
            db_path=settings.documents_db_path,
        )
        _enqueue_ingestion(dest, settings, meta, job_id)
        accepted.append({"file_name": name, "job_id": job_id})

    return {"accepted": accepted, "count": len(accepted)}


@router.get("/jobs")
def list_jobs_endpoint(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    settings: Settings = Depends(get_settings),
    tenant: Any = Depends(require_api_key),
) -> list[dict[str, Any]]:
    return jobs.list_jobs(
        limit=limit,
        status=status,
        tenant_id=getattr(tenant, "tenant_id", None),
        is_admin=getattr(tenant, "is_admin", False),
        db_path=settings.documents_db_path,
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
    _enqueue_ingestion(target, settings, None, job_id)
    return {"job_id": job_id, "status": "queued"}


def authorize_document_access(
    row: dict[str, Any],
    tenant: Any,
    action: str = "read",  # "read" | "modify" | "delete"
) -> None:
    """Enforce default-deny tenant boundary and document ownership."""
    is_admin = getattr(tenant, "is_admin", False)
    t_id = getattr(tenant, "tenant_id", "global") or "global"
    u_id = getattr(tenant, "user_id", None)

    doc_tenant = row.get("tenant_id") or "global"
    doc_visibility = row.get("visibility") or "tenant"
    doc_owner = row.get("owner_id")

    # Global public documents are read-only for non-admin tenants
    if doc_tenant == "global" and doc_visibility == "public":
        if action == "read":
            return
        if not is_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only global administrators can modify or delete global public documents",
            )
        return

    # Cross-tenant boundary check
    if not is_admin and doc_tenant != t_id:
        logger.warning(
            "unauthorized_cross_tenant_document_access_denied",
            action=action,
            doc_id=row.get("doc_id"),
            doc_tenant=doc_tenant,
            caller_tenant=t_id,
            user_id=u_id,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Access denied: Document belongs to another tenant",
        )

    # Visibility check for reading private working drafts
    if action == "read":
        if not is_admin and doc_visibility == "private" and doc_owner and doc_owner != u_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Access denied: Private working draft belonging to another user",
            )

    # Modify / Delete checks
    if action in {"modify", "delete"}:
        if not is_admin and doc_owner and doc_owner != u_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Only the document owner or an admin can {action} this document",
            )


@router.get("")
def list_documents_endpoint(
    search: str | None = Query(None),
    doc_type: str | None = Query(None),
    jurisdiction: str | None = Query(None),
    status: str | None = Query(None),
    tenant_id: str | None = Query(None),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    settings: Settings = Depends(get_settings),
    tenant: Any = Depends(require_api_key),
) -> dict[str, Any]:
    t_id = getattr(tenant, "tenant_id", "global") or "global"
    is_admin = getattr(tenant, "is_admin", False)

    if tenant_id and not is_admin and tenant_id != t_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Cross-tenant document listing forbidden: cannot list documents for tenant '{tenant_id}'",
        )

    active_tenant = tenant_id if (is_admin and tenant_id) else t_id
    user_id = getattr(tenant, "user_id", None)

    rows = registry.list_documents(
        search=search,
        doc_type=doc_type,
        jurisdiction=jurisdiction,
        status=status,
        tenant_id=active_tenant,
        user_id=user_id,
        is_admin=is_admin,
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
    tenant: Any = Depends(require_api_key),
) -> dict[str, Any]:
    row = registry.get_document(doc_id, db_path=settings.documents_db_path)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    authorize_document_access(row, tenant, action="read")

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
                "tenant_id": payload.get("tenant_id"),
                "owner_id": payload.get("owner_id"),
                "visibility": payload.get("visibility"),
            }
        )

    chunks.sort(key=lambda c: (c["chunk_index"] is None, c["chunk_index"]))
    return {"doc_id": doc_id, "count": len(chunks), "chunks": chunks}


@router.get("/{doc_id}")
def get_document_endpoint(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    tenant: Any = Depends(require_api_key),
) -> dict[str, Any]:
    row = registry.get_document(doc_id, db_path=settings.documents_db_path)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    authorize_document_access(row, tenant, action="read")
    return row


@router.post("/{doc_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document_endpoint(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    tenant: Any = Depends(require_api_key),
) -> dict[str, str]:
    row = registry.get_document(doc_id, db_path=settings.documents_db_path)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    authorize_document_access(row, tenant, action="modify")

    doc_tenant = row.get("tenant_id") or "global"
    doc_owner = row.get("owner_id")

    root = Path(settings.documents_root)
    target = root / row["source_file"]
    if not target.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Source file missing: {row['source_file']}"
        )

    job_id = jobs.create_job(
        row["source_file"],
        tenant_id=doc_tenant,
        owner_id=doc_owner,
        db_path=settings.documents_db_path,
    )
    _schedule(ingest_service.process_file(target, settings, row, job_id, force=True))
    return {"job_id": job_id, "doc_id": doc_id, "status": "queued"}


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_endpoint(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    tenant: Any = Depends(require_api_key),
) -> Response:
    row = registry.get_document(doc_id, db_path=settings.documents_db_path)
    if row:
        authorize_document_access(row, tenant, action="delete")

    ingest_service.delete_document(doc_id, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

