"""Evaluation HTTP routes.

Background runs are held in a module-level set so the concurrency limit
(``settings.max_concurrent_eval_runs``) can be enforced synchronously -- the
POST returns 409 rather than silently queueing. The same pattern Phase 4 uses
for ingestion jobs.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from citerator.api.deps import require_api_key
from citerator.config import Settings, get_settings
from citerator.evaluation import runner, store
from citerator.ingestion.embedding import get_embedder
from citerator.ingestion.store import collection_name, make_client

router = APIRouter(prefix="/eval", tags=["evaluation"])

_running_runs: set[str] = set()

_HIGHER_IS_BETTER = {
    "faithfulness_mean",
    "answer_relevancy_mean",
    "context_precision_mean",
    "context_recall_mean",
    "safety_refuse_pct",
    "safety_escalate_pct",
}
_LOWER_IS_BETTER = {
    "latency_p50_ms",
    "latency_p95_ms",
    "cost_per_query_usd_mean",
}


class StartRunRequest(BaseModel):
    question_set_path: str | None = None
    chunking_strategy: str | None = None
    top_k_retrieve: int | None = None
    top_k_rerank: int | None = None
    confidence_threshold: float | None = None
    confidence_floor: float | None = None
    label: str | None = None


def _schedule(coro) -> None:
    """Run a coroutine in a daemon thread with its own event loop."""

    def runner() -> None:
        try:
            asyncio.run(coro)
        finally:
            pass

    threading.Thread(target=runner, daemon=True, name="citerator-eval-bg").start()


async def _run_wrapper(run_id: str, run_settings: Settings) -> None:
    try:
        await runner.run_evaluation(run_id, run_settings, store)
    finally:
        _running_runs.discard(run_id)


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run_endpoint(
    request: StartRunRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, str]:
    if len(_running_runs) >= settings.max_concurrent_eval_runs:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"At capacity: {len(_running_runs)}/{settings.max_concurrent_eval_runs} runs in progress",
        )

    overrides: dict[str, Any] = {}
    if request.question_set_path:
        overrides["eval_questions_path"] = request.question_set_path
    if request.chunking_strategy:
        overrides["active_chunking_strategy"] = request.chunking_strategy
    for key in ("top_k_retrieve", "top_k_rerank", "confidence_threshold", "confidence_floor"):
        value = getattr(request, key)
        if value is not None:
            overrides[key] = value

    run_settings = settings.model_copy(update=overrides) if overrides else settings

    embedder = get_embedder(
        run_settings.embedder_kind, run_settings.embedding_model or None
    )

    run_id = store.create_run(
        question_set_path=run_settings.eval_questions_path,
        chunking_strategy=run_settings.active_chunking_strategy,
        embedder=embedder.name,
        sparse_embedder=run_settings.sparse_kind,
        rerank_model=run_settings.rerank_model,
        llm_provider=run_settings.llm_provider,
        llm_model=run_settings.llm_model,
        top_k_retrieve=run_settings.top_k_retrieve,
        top_k_rerank=run_settings.top_k_rerank,
        confidence_threshold=run_settings.confidence_threshold,
        confidence_floor=run_settings.confidence_floor,
        label=request.label,
    )

    _running_runs.add(run_id)
    _schedule(_run_wrapper(run_id, run_settings))
    return {"run_id": run_id, "status": "running"}


@router.get("/runs")
def list_runs_endpoint(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    rows = store.list_runs(limit=limit, offset=offset)
    return {"runs": rows, "count": len(rows), "limit": limit, "offset": offset}


@router.get("/latest")
def latest_endpoint(
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    recent = store.list_runs(limit=20, status="completed")
    if not recent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No completed runs yet")

    latest = recent[0]
    previous = recent[1] if len(recent) > 1 else None

    metric_names = list(_HIGHER_IS_BETTER) + list(_LOWER_IS_BETTER)
    metrics: dict[str, Any] = {}
    for name in metric_names:
        value = latest.get(name)
        prev_value = previous.get(name) if previous else None
        delta = (
            (value - prev_value)
            if (value is not None and prev_value is not None)
            else None
        )
        sparkline = [r.get(name) for r in recent[:10] if r.get(name) is not None]
        metrics[name] = {
            "value": value,
            "delta_vs_previous": delta,
            "sparkline": list(reversed(sparkline)),
        }

    return {
        "run_id": latest["run_id"],
        "timestamp": latest["created_at"],
        "label": latest.get("label"),
        "question_count": latest.get("question_count"),
        "metrics": metrics,
        "safety": {
            "refuse_pct": latest.get("safety_refuse_pct"),
            "escalate_pct": latest.get("safety_escalate_pct"),
        },
    }


@router.get("/runs/compare")
def compare_endpoint(
    a: str = Query(...),
    b: str = Query(...),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    run_a = store.get_run(a)
    run_b = store.get_run(b)
    if run_a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {a} not found")
    if run_b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {b} not found")

    deltas: dict[str, Any] = {}
    for name in list(_HIGHER_IS_BETTER) + list(_LOWER_IS_BETTER):
        va = run_a.get(name)
        vb = run_b.get(name)
        if va is None or vb is None:
            deltas[name] = {"value": None, "direction": None}
            continue
        deltas[name] = {
            "value": vb - va,
            "direction": (
                "higher_is_better" if name in _HIGHER_IS_BETTER else "lower_is_better"
            ),
        }

    return {"run_a": run_a, "run_b": run_b, "deltas": deltas}


def _light_chunks(chunk_ids: list[str], settings: Settings) -> list[dict[str, Any]]:
    if not chunk_ids:
        return []

    from qdrant_client import models as qmodels

    try:
        embedder = get_embedder(
            settings.embedder_kind, settings.embedding_model or None
        )
        collection = collection_name(
            settings.active_chunking_strategy, embedder.name
        )
        client = make_client(settings.qdrant_url)
        points, _ = client.scroll(
            collection_name=collection,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="chunk_id",
                        match=qmodels.MatchAny(any=chunk_ids),
                    )
                ]
            ),
            limit=len(chunk_ids),
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        return [{"chunk_id": cid} for cid in chunk_ids]

    by_id: dict[str, dict[str, Any]] = {}
    for p in points:
        payload = p.payload or {}
        cid = payload.get("chunk_id")
        if cid:
            by_id[cid] = {
                "chunk_id": cid,
                "doc_title": payload.get("doc_title"),
                "section_path": payload.get("section_path") or [],
                "page_start": payload.get("page_start"),
                "page_end": payload.get("page_end"),
                "excerpt": (payload.get("text") or "")[:200],
            }

    return [by_id.get(cid, {"chunk_id": cid}) for cid in chunk_ids]


@router.get("/runs/{run_id}")
def get_run_endpoint(
    run_id: str,
    category: str | None = Query(None),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    results = store.list_question_results(run_id, category=category)

    resolved: list[dict[str, Any]] = []
    for r in results:
        retrieved = _light_chunks(r.get("retrieved_chunk_ids") or [], settings)
        cited = _light_chunks(r.get("cited_chunk_ids") or [], settings)
        resolved.append(
            {
                **r,
                "retrieved_chunks": retrieved,
                "cited_chunks": cited,
            }
        )

    return {"run": run, "results": resolved}

