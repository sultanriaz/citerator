"""HTTP routes for Citerator."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from citerator.api.deps import require_api_key
from citerator.api.schemas import HealthResponse, QueryRequest
from citerator.config import Settings, get_settings
from citerator.generation.answer import AnswerResult, answer_question
from citerator.ingestion.store import make_client
from citerator.retrieval.search import RetrievalFilters

router = APIRouter()


@router.post("/query", response_model=AnswerResult)
def query(
    request: QueryRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> AnswerResult:
    filters = None
    if request.document_scope or request.jurisdiction:
        filters = RetrievalFilters(
            document_scope=request.document_scope,
            jurisdiction=request.jurisdiction,
        )

    return answer_question(
        question=request.question,
        settings=settings,
        filters=filters,
        show_retrieval_details=request.show_retrieval_details,
    )


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    collections: dict[str, int] = {}
    try:
        client = make_client(settings.qdrant_url)
        for collection in client.get_collections().collections:
            collections[collection.name] = client.count(collection.name).count
    except Exception:
        collections = {}

    return HealthResponse(status="ok", collections=collections)