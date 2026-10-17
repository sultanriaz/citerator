"""Structlog configuration, called once from create_app().

Adds contextvars merging so trace_id bound by the tracing middleware appears
on every log line inside the request -- including log calls in Phase 3/4/5
modules this project does not edit -- and installs the log-forwarding
processor from log_sink.

Development vs. production is inferred from qdrant_url: localhost/127.0.0.1
gets the coloured console renderer, anything else gets JSON. This avoids
adding another Settings field just for a display flag.

Note: structlog.stdlib.add_logger_name is intentionally NOT in the chain.
It requires a stdlib logger object with a ``.name`` attribute, but
``configure`` is wired to PrintLoggerFactory (which has no ``.name``).
Dropping it keeps the level and event fields, which is everything we need.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from citerator.config import Settings
from citerator.observability.log_sink import set_active_tracer
from citerator.observability.tracing import get_tracer

_configured = False


def _is_dev(settings: Settings) -> bool:
    host = (settings.qdrant_url or "").lower()
    return "localhost" in host or "127.0.0.1" in host


def configure_logging(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    from citerator.observability.log_sink import tracing_processor

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        tracing_processor,
    ]

    renderer: Any
    if _is_dev(settings):
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    set_active_tracer(get_tracer(settings))