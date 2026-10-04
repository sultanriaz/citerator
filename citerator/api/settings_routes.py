"""Settings API for the Pipeline / Models / API tabs of the Settings screen.

All routes require X-API-Key via the existing require_api_key dependency.
Writes go through runtime_config.overrides, which validates the full merged
Settings before persisting -- an invalid combination is a 422 with a real
message, never a silent clamp or no-op.

The /settings/pipeline PUT verifies that a Qdrant collection actually exists
for a new chunking strategy before allowing the switch, so /query never ends
up pointed at an empty collection.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from citerator.api.deps import require_api_key
from citerator.config import Settings, get_settings
from citerator.runtime_config import overrides as overrides_store
from citerator.runtime_config.effective_settings import get_effective_settings

router = APIRouter(prefix="/settings", tags=["settings"])

_PIPELINE_FIELDS = [
    "active_chunking_strategy",
    "top_k_retrieve",
    "top_k_rerank",
    "rerank_model",
    "confidence_threshold",
    "confidence_floor",
]

_MODELS_FIELDS = ["llm_provider", "llm_model", "rerank_model"]
_API_FIELDS = ["api_key"]


class PipelineUpdate(BaseModel):
    active_chunking_strategy: str | None = None
    top_k_retrieve: int | None = None
    top_k_rerank: int | None = None
    rerank_model: str | None = None
    confidence_threshold: float | None = None
    confidence_floor: float | None = None


class ModelsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    rerank_model: str | None = None


class ThresholdPreviewRequest(BaseModel):
    confidence_threshold: float
    confidence_floor: float


class ResetRequest(BaseModel):
    section: Literal["pipeline", "models", "api", "all"]


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return "*" * (len(key) - 4) + key[-4:]


def _pipeline_view(settings: Settings, overrides: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: getattr(settings, k) for k in _PIPELINE_FIELDS},
        "is_override": {k: (k in overrides) for k in _PIPELINE_FIELDS},
    }


def _endpoint_catalog() -> list[dict[str, str]]:
    masked = _mask_key(get_settings().api_key)
    h = f'curl.exe -H "X-API-Key: {masked}"'
    hh = (
        f'curl.exe -H "X-API-Key: {masked}" '
        f'-H "Content-Type: application/json"'
    )
    return [
        {"method": "GET", "path": "/health",
         "description": "Health check and Qdrant collection counts.",
         "example": 'curl.exe http://localhost:8000/health'},
        {"method": "POST", "path": "/query",
         "description": "Ask a compliance question; returns answer, citations, confidence.",
         "example": (
             f'{hh} -X POST http://localhost:8000/query '
             f'-d "{{\\"question\\":\\"What is the CDD threshold?\\"}}"'
         )},
        {"method": "POST", "path": "/documents/upload",
         "description": "Upload documents for background ingestion.",
         "example": (
             f'{h} -X POST http://localhost:8000/documents/upload '
             f'-F "files=@docs/cdd_policy.md"'
         )},
        {"method": "GET", "path": "/documents",
         "description": "List indexed documents.",
         "example": f'{h} http://localhost:8000/documents'},
        {"method": "GET", "path": "/documents/jobs",
         "description": "Recent ingestion jobs and their statuses.",
         "example": f'{h} http://localhost:8000/documents/jobs'},
        {"method": "POST", "path": "/eval/runs",
         "description": "Start an evaluation run against eval/questions.json.",
         "example": (
             f'{hh} -X POST http://localhost:8000/eval/runs '
             f'-d "{{\\"label\\":\\"baseline\\"}}"'
         )},
        {"method": "GET", "path": "/eval/latest",
         "description": "Latest completed evaluation summary.",
         "example": f'{h} http://localhost:8000/eval/latest'},
        {"method": "GET", "path": "/eval/runs/compare?a=&b=",
         "description": "Compare two completed runs metric by metric.",
         "example": (
             f'{h} "http://localhost:8000/eval/runs/compare?a=<run_a>&b=<run_b>"'
         )},
        {"method": "GET", "path": "/settings/pipeline",
         "description": "Current pipeline settings and which are overridden.",
         "example": f'{h} http://localhost:8000/settings/pipeline'},
        {"method": "GET", "path": "/settings/models",
         "description": "Current model settings and the cost/privacy note.",
         "example": f'{h} http://localhost:8000/settings/models'},
        {"method": "GET", "path": "/settings/api",
         "description": "Masked API key, endpoint catalog, rate-limit config.",
         "example": f'{h} http://localhost:8000/settings/api'},
    ]


@router.get("/pipeline")
def get_pipeline(
    settings: Settings = Depends(get_effective_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    return _pipeline_view(settings, overrides_store.get_overrides())


@router.put("/pipeline")
def put_pipeline(
    request: PipelineUpdate,
    settings: Settings = Depends(get_effective_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    partial = request.model_dump(exclude_none=True)
    if not partial:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")

    new_strategy = partial.get("active_chunking_strategy")
    if new_strategy and new_strategy != settings.active_chunking_strategy:
        from citerator.ingestion.embedding import get_embedder
        from citerator.ingestion.store import collection_name, make_client

        embedder = get_embedder(
            settings.embedder_kind, settings.embedding_model or None
        )
        target = collection_name(new_strategy, embedder.name)
        try:
            client = make_client(settings.qdrant_url)
            exists = client.collection_exists(target)
        except Exception:
            exists = False
        if not exists:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"no indexed documents for strategy '{new_strategy}' "
                f"(collection '{target}' not found) -- ingest first",
            )

    try:
        overrides_store.set_overrides(partial)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc

    updated = get_effective_settings()
    return _pipeline_view(updated, overrides_store.get_overrides())


@router.post("/pipeline/preview-threshold")
def preview_threshold(
    request: ThresholdPreviewRequest,
    settings: Settings = Depends(get_effective_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from citerator.evaluation.questions import load_questions
    from citerator.ingestion.embedding import get_embedder, get_sparse_embedder
    from citerator.ingestion.store import make_client
    from citerator.retrieval.confidence import score_confidence
    from citerator.retrieval.rerank import CrossEncoderReranker, rerank
    from citerator.retrieval.search import search

    if request.confidence_floor >= request.confidence_threshold:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "confidence_floor must be less than confidence_threshold",
        )

    path = Path(settings.eval_questions_path)
    if not path.exists():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"question set not found: {path.as_posix()}",
        )

    questions = load_questions(path)

    candidate = settings.model_copy(
        update={
            "confidence_threshold": request.confidence_threshold,
            "confidence_floor": request.confidence_floor,
        }
    )

    embedder = get_embedder(
        candidate.embedder_kind, candidate.embedding_model or None
    )
    sparse = get_sparse_embedder(candidate.sparse_kind)
    client = make_client(candidate.qdrant_url)
    reranker = CrossEncoderReranker(candidate.rerank_model)

    counts = {"confident": 0, "low_confidence": 0, "insufficient": 0}

    for q in questions:
        try:
            candidates = search(
                q.question,
                candidate,
                client=client,
                embedder=embedder,
                sparse_embedder=sparse,
            )
            reranked = rerank(
                q.question, candidates, candidate, reranker=reranker
            )
            result = score_confidence(reranked, candidate)
            counts[result.state] = counts.get(result.state, 0) + 1
        except Exception:
            counts["insufficient"] += 1

    return {
        "total": len(questions),
        **counts,
        "note": (
            "scored fresh against eval/questions.json; not derived from stored "
            "evaluation run history"
        ),
    }


@router.get("/models")
def get_models(
    settings: Settings = Depends(get_effective_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    provider = (settings.llm_provider or "").lower()
    if provider in {"gemini", "google"}:
        note = "LLM calls are sent to Google's Gemini API"
    elif provider == "anthropic":
        note = "LLM calls are sent to Anthropic's API"
    elif provider == "openai":
        note = "LLM calls are sent to OpenAI's API"
    elif provider == "fake":
        note = (
            "using FakeLLMClient -- no network, no data leaves this machine"
        )
    else:
        note = f"unknown provider: {provider}"

    return {
        "embedding_model": {
            "value": settings.embedding_model,
            "editable": False,
            "reason": "requires re-ingestion",
        },
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "rerank_model": settings.rerank_model,
        "cost_privacy_note": note,
    }


@router.put("/models")
def put_models(
    request: ModelsUpdate,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    partial = request.model_dump(exclude_none=True)
    if not partial:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    try:
        overrides_store.set_overrides(partial)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc

    settings = get_effective_settings()
    provider = (settings.llm_provider or "").lower()
    if provider in {"gemini", "google"}:
        note = "LLM calls are sent to Google's Gemini API"
    elif provider == "anthropic":
        note = "LLM calls are sent to Anthropic's API"
    elif provider == "openai":
        note = "LLM calls are sent to OpenAI's API"
    elif provider == "fake":
        note = "using FakeLLMClient -- no network, no data leaves this machine"
    else:
        note = f"unknown provider: {provider}"

    return {
        "embedding_model": {
            "value": settings.embedding_model,
            "editable": False,
            "reason": "requires re-ingestion",
        },
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "rerank_model": settings.rerank_model,
        "cost_privacy_note": note,
    }


@router.get("/api")
def get_api(
    settings: Settings = Depends(get_effective_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    return {
        "api_key_masked": _mask_key(settings.api_key),
        "endpoints": _endpoint_catalog(),
        "rate_limit": {
            "requests_per_minute": settings.rate_limit_requests_per_minute,
            "window_seconds": 60,
        },
    }


@router.post("/api/regenerate")
def regenerate_api_key(
    _: None = Depends(require_api_key),
) -> dict[str, str]:
    new_key = secrets.token_urlsafe(32)
    overrides_store.set_overrides({"api_key": new_key})
    return {
        "api_key": new_key,
        "warning": "this key will not be shown again -- store it now",
    }


@router.post("/reset")
def reset_settings(
    request: ResetRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    if request.section == "pipeline":
        keys: list[str] | None = list(_PIPELINE_FIELDS)
    elif request.section == "models":
        keys = list(_MODELS_FIELDS)
    elif request.section == "api":
        keys = list(_API_FIELDS)
    elif request.section == "all":
        keys = None
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown section: {request.section}",
        )

    overrides_store.reset_overrides(keys)
    settings = get_effective_settings()
    effective_keys = keys if keys is not None else list(
        overrides_store.OVERRIDABLE_FIELDS
    )
    return {
        "section": request.section,
        "effective": {k: getattr(settings, k) for k in effective_keys},
    }
