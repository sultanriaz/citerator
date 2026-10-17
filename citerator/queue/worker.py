"""Worker entrypoint. Run as ``python -m citerator.queue.worker``.

This is the same entrypoint whether you're running a single worker for
development or a pool on a dedicated host. Scaling is a matter of
starting more workers; each one pulls jobs from the same Redis queue.

The worker does not expose HTTP. It reads jobs, executes the function
specified in each job, and writes status to SQLite. Horizontal scaling
is a matter of starting N of these.

Shutdown: RQ installs a SIGTERM handler that lets the current job finish
before exiting. That is what you want for ingestion (a half-written
document is worse than a delayed one). Long-running evaluations should
be interrupted with SIGKILL if a hard stop is required; the run row will
be left in ``running`` and can be cleaned up via the same SQLite update
documented in docs/evaluation.md.
"""

from __future__ import annotations

import sys

import structlog

from citerator.config import get_settings
from citerator.observability.logging_config import configure_logging


def main() -> int:
    try:
        from rq import Worker
        import redis
    except ImportError:
        print(
            "The rq worker requires the 'rq' and 'redis' packages.\n"
            "Install them with: pip install rq redis",
            file=sys.stderr,
        )
        return 2

    settings = get_settings()
    configure_logging(settings)

    logger = structlog.get_logger(__name__)
    logger.info(
        "worker_starting",
        redis_url=settings.queue_redis_url,
        queue=settings.queue_name,
    )

    connection = redis.Redis.from_url(settings.queue_redis_url)
    worker = Worker([settings.queue_name], connection=connection)
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())