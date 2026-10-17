"""Server-Sent Events streaming endpoint for /query.

The pipeline runs in two phases from the client's perspective:

  1. Retrieval + rerank + confidence scoring. Synchronous, ~1s warm. Emits
     a `stage` event per step so the UI can show a progress indicator
     that reflects real server state rather than a client-side timer.

  2. If the state is insufficient, emit a single `final` event with the
     full AnswerResult (no generation, no tokens).

  3. If confident or low_confidence, emit a `stage` event, then stream
     LLM tokens one at a time, then emit a `final` event with the
     assembled result including citations.

Event format (SSE):

    event: stage
    data: {"name": "retrieving"}

    event: token
    data: {"text": "The threshold"}

    event: final
    data: {"state": "confident", "answer": "...", ...}

    event: error
    data: {"detail": "..."}

Heartbeat comments (`: ping`) are sent periodically to defeat proxy idle
timeouts. Every event is a complete JSON object on one line so browsers
parse it without needing chunked reconstruction.

Synchronous LLM clients are executed on a background thread and their
tokens marshalled back to the event loop via an asyncio.Queue. This keeps
the ASGI worker responsive to heartbeats and client disconnects during
generation.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, AsyncIterator, Iterator

import structlog
from fastapi import APIRouter, Depends, Header
from starlette.responses import StreamingResponse

from citerator.api.deps import require_api_key
from citerator.api.schemas import QueryRequest
from citerator.config import Settings, get_settings
from citerator.generation.citations import parse_citations
from citerator.generation.llm import get_llm_client, stream_with_fallback
from citerator.generation.prompt import build_prompt
from citerator.ingestion.embedding import get_embedder, get_sparse_embedder
from citerator.ingestion.store import make_client
from citerator.retrieval.confidence import score_confidence
from citerator.retrieval.rerank import CrossEncoderReranker, rerank
from citerator.retrieval.search import RetrievalFilters, search

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["streaming"])


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _ping() -> str:
    return ": ping\n\n"


async def _stream_llm_tokens(
    llm, system: str, user: str
) -> AsyncIterator[str]:
    """Bridge a synchronous iterator to an async one without blocking the loop.

    The worker thread pushes tokens onto an asyncio.Queue via
    call_soon_threadsafe, which is the correct cross-thread bridge for
    asyncio. Exceptions propagate to the consumer. A None sentinel marks
    clean completion.
    """

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def worker() -> None:
        try:
            for token in stream_with_fallback(llm, system, user):
                loop.call_soon_threadsafe(queue.put_nowait, token)
            loop.call_soon_threadsafe(queue.put_nowait, None)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)

    thread = threading.Thread(target=worker, daemon=True, name="llm-stream")
    thread.start()

    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield item


async def _run_query_stream(
    request: QueryRequest,
    settings: Settings,
) -> AsyncIterator[str]:
    import time as _time

    total_start = _time.perf_counter()
    retrieve_ms = 0.0
    rerank_ms = 0.0
    generate_ms = 0.0

    try:
        filters = None
        if request.document_scope or request.jurisdiction:
            filters = RetrievalFilters(
                document_scope=request.document_scope,
                jurisdiction=request.jurisdiction,
            )

        yield _sse("stage", {"name": "retrieving"})
        _t0 = _time.perf_counter()

        embedder = get_embedder(
            settings.embedder_kind, settings.embedding_model or None
        )
        sparse = get_sparse_embedder(settings.sparse_kind)
        client = make_client(settings.qdrant_url)

        candidates = await asyncio.to_thread(
            search,
            request.question,
            settings,
            filters=filters,
            client=client,
            embedder=embedder,
            sparse_embedder=sparse,
        )
        retrieve_ms = (_time.perf_counter() - _t0) * 1000.0

        yield _sse("stage", {"name": "reranking"})
        _t1 = _time.perf_counter()

        reranker = CrossEncoderReranker(settings.rerank_model)
        reranked = await asyncio.to_thread(
            rerank, request.question, candidates, settings, reranker
        )
        rerank_ms = (_time.perf_counter() - _t1) * 1000.0

        yield _sse("stage", {"name": "scoring"})

        confidence = score_confidence(reranked, settings)

        from citerator.api.routes import _build_answer_result  # reuse

        if confidence.state == "insufficient":
            result = _build_answer_result(
                question=request.question,
                settings=settings,
                confidence=confidence,
                reranked=reranked,
                answer_text=None,
                citations=[],
                tokens=None,
                latency={
                    "retrieve": round(retrieve_ms, 2),
                    "rerank": round(rerank_ms, 2),
                    "generate": round(generate_ms, 2),
                    "total": round(
                        (_time.perf_counter() - total_start) * 1000.0, 2
                    ),
                },
                retrieval_details_enabled=request.show_retrieval_details,
            )
            yield _sse("final", result.model_dump())
            return

        yield _sse("stage", {"name": "generating"})
        _t2 = _time.perf_counter()

        system, user = build_prompt(request.question, reranked)
        llm = get_llm_client(settings)

        buffer: list[str] = []
        async for token in _stream_llm_tokens(llm, system, user):
            buffer.append(token)
            yield _sse("token", {"text": token})

        answer_text = "".join(buffer)
        generate_ms = (_time.perf_counter() - _t2) * 1000.0

        yield _sse("stage", {"name": "verifying_citations"})

        citations = parse_citations(answer_text, reranked)

        tokens = {
            "input": len(user.split()),
            "output": len(answer_text.split()),
        }

        result = _build_answer_result(
            question=request.question,
            settings=settings,
            confidence=confidence,
            reranked=reranked,
            answer_text=answer_text,
            citations=citations,
            tokens=tokens,
            latency={
                "retrieve": 0.0,
                "rerank": 0.0,
                "generate": 0.0,
                "total": 0.0,
            },
            retrieval_details_enabled=request.show_retrieval_details,
        )

        yield _sse("final", result.model_dump())

    except asyncio.CancelledError:
        logger.info("query_stream_cancelled", question=request.question)
        raise
    except Exception as exc:
        logger.warning(
            "query_stream_error", question=request.question, error=str(exc)
        )
        yield _sse("error", {"detail": str(exc)})


@router.post("/query/stream")
async def query_stream(
    request: QueryRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
    accept: str | None = Header(default=None),
) -> StreamingResponse:
    if not settings.stream_enabled:
        from fastapi import HTTPException, status

        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Streaming is disabled in settings.",
        )

    async def generator() -> AsyncIterator[str]:
        yield _ping()
        async for chunk in _run_query_stream(request, settings):
            yield chunk

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )