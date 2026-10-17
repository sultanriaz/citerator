"""Job functions executed by the queue.

These are the entry points a worker calls. They wrap the existing
services (ingest_service, evaluation.runner) and are responsible for
setting the process-wide settings and any per-job context before
delegating.

Both functions are synchronous. The services they call are async; the
job functions bridge with asyncio.run(). This matches how the API
dispatches them today (via daemon threads with their own event loop),
and it's the pattern RQ expects — synchronous callables.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog

from citerator.config import Settings, get_settings

logger = structlog.get_logger(__name__)


def _settings_from_payload(payload: dict[str, Any] | None) -> Settings:
    """Return the process settings, optionally overridden by values the
    submitting process captured.

    Overrides are intentionally limited to scalars that matter for
    reproducibility (LLM model, top-k values). Passing a full Settings
    object through the queue would couple workers to the API's schema
    version; passing a small dict keeps the payload portable.
    """

    base = get_settings()
    if not payload:
        return base
    allowed = {
        "llm_model",
        "llm_provider",
        "top_k_retrieve",
        "top_k_rerank",
        "confidence_threshold",
        "confidence_floor",
        "active_chunking_strategy",
    }
    overrides = {k: v for k, v in payload.items() if k in allowed}
    return base.model_copy(update=overrides) if overrides else base


def run_ingestion_job(
    file_path: str,
    job_id: str,
    meta: dict[str, Any] | None = None,
    settings_overrides: dict[str, Any] | None = None,
) -> None:
    """Ingest a single file, updating the job row in SQLite.

    The Documents route enqueues this. The function name and signature
    are the queue contract; do not rename without a migration.
    """

    from citerator.documents import ingest_service

    settings = _settings_from_payload(settings_overrides)
    logger.info(
        "queue_ingestion_start",
        job_id=job_id,
        file_path=file_path,
    )
    asyncio.run(
        ingest_service.process_file(
            Path(file_path), settings, meta, job_id
        )
    )


def run_evaluation_job(
    run_id: str,
    settings_overrides: dict[str, Any] | None = None,
) -> None:
    """Execute a full evaluation run.

    The runner already handles its own exception capture and status
    updates; this wrapper only sets up the process context.
    """

    from citerator.evaluation import runner, store

    settings = _settings_from_payload(settings_overrides)
    logger.info("queue_evaluation_start", run_id=run_id)
    asyncio.run(runner.run_evaluation(run_id, settings, store))