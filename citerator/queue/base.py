"""Queue backends.

InlineQueue and RQQueue implement the same interface. The interface is
deliberately minimal — enqueue, and a status probe — because job
progress is tracked in SQLite, not in the queue.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Protocol

import structlog

logger = structlog.get_logger(__name__)


class QueueBackend(Protocol):
    def enqueue(self, func_path: str, *args: Any, **kwargs: Any) -> str:
        """Submit a job. Returns a queue-side job ID (opaque to callers)."""

    @property
    def name(self) -> str:
        ...


class InlineQueue:
    """Run jobs in a daemon thread. Process-local, dies with the process,
    no external dependency. Correct for single-node dev and small
    deployments where job volume is low."""

    name = "inline"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, threading.Thread] = {}

    def enqueue(self, func_path: str, *args: Any, **kwargs: Any) -> str:
        import uuid

        queue_id = str(uuid.uuid4())
        func = _resolve_func(func_path)

        def runner() -> None:
            try:
                func(*args, **kwargs)
            except Exception as exc:
                logger.warning(
                    "inline_job_failed",
                    func=func_path,
                    queue_id=queue_id,
                    error=str(exc),
                )
            finally:
                with self._lock:
                    self._active.pop(queue_id, None)

        thread = threading.Thread(
            target=runner, daemon=True, name=f"inline-job-{queue_id[:8]}"
        )
        with self._lock:
            self._active[queue_id] = thread
        thread.start()
        return queue_id


class RQQueue:
    """Redis-backed queue. A separate worker process (invoked as
    ``python -m citerator.queue.worker``) pulls jobs and executes them.

    Enqueue is fire-and-forget: the API submits and returns immediately.
    Job status is read from SQLite, never from Redis, so an RQ outage
    does not lose client-visible state — it just delays execution.
    """

    name = "rq"

    def __init__(
        self,
        url: str,
        *,
        queue_name: str = "citerator",
        job_timeout: int = 900,
        result_ttl: int = 86400,
    ) -> None:
        import redis
        from rq import Queue

        self._conn = redis.Redis.from_url(url)
        self._queue = Queue(name=queue_name, connection=self._conn)
        self._timeout = job_timeout
        self._result_ttl = result_ttl

    def enqueue(self, func_path: str, *args: Any, **kwargs: Any) -> str:
        func = _resolve_func(func_path)
        job = self._queue.enqueue(
            func,
            *args,
            **kwargs,
            job_timeout=self._timeout,
            result_ttl=self._result_ttl,
        )
        return job.id

    def active_job_count(self) -> int:
        return len(self._queue)


def _resolve_func(path: str) -> Callable:
    """Import a dotted path like 'citerator.queue.jobs.run_ingestion_job'.

    Explicit resolution (vs. passing the function object) keeps RQ
    payloads serializable and version-tolerant: the queue stores a
    string, the worker resolves it against its own code tree. A rolling
    deploy can update workers without draining the queue first.
    """

    module_path, _, func_name = path.rpartition(".")
    if not module_path or not func_name:
        raise ValueError(f"Invalid function path: {path!r}")
    import importlib

    module = importlib.import_module(module_path)
    func = getattr(module, func_name, None)
    if func is None:
        raise AttributeError(f"{module_path} has no attribute {func_name}")
    return func

_queue_singleton: QueueBackend | None = None
_queue_lock = threading.Lock()


def get_queue(settings=None) -> QueueBackend:
    """Return the process-wide queue backend.

    Switches on settings.queue_backend. 'rq' constructs an RQQueue; any
    other value (including the default 'inline') returns the inline
    backend. An RQ construction failure logs a warning and falls back to
    inline rather than crashing the API — the point of the fallback is
    that a broken queue degrades to synchronous execution, not to a
    broken service.
    """

    global _queue_singleton

    from citerator.config import get_settings

    s = settings or get_settings()

    with _queue_lock:
        if _queue_singleton is not None:
            return _queue_singleton

        if s.queue_backend == "rq":
            try:
                _queue_singleton = RQQueue(
                    s.queue_redis_url,
                    queue_name=s.queue_name,
                    job_timeout=s.queue_job_timeout_seconds,
                    result_ttl=s.queue_result_ttl_seconds,
                )
                logger.info("queue_initialized", backend="rq", url=s.queue_redis_url)
                return _queue_singleton
            except Exception as exc:
                logger.warning(
                    "queue_rq_init_failed",
                    error=str(exc),
                    fallback="inline",
                )

        _queue_singleton = InlineQueue()
        logger.info("queue_initialized", backend="inline")
        return _queue_singleton


def reset_queue() -> None:
    global _queue_singleton
    with _queue_lock:
        _queue_singleton = None