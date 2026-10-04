"""Structlog processor forwarding /query stage events to the active tracer.

Runs on every log call. Returns event_dict unchanged for anything that
isn't a query-stage event with a bound trace_id, so ingestion/eval/settings
logging is completely unaffected.

To wire a tracer in, configure_logging() calls set_active_tracer() with the
result of get_tracer(settings). If that's a NullTracer, this processor is a
straight pass-through and the overhead is a couple of dict lookups.

The predicate _is_query_stage matches the event names actually emitted by
Phase 3's retrieval/generation modules as observed in production logs:

    query_start, query_retrieved, reranked, query_reranked,
    query_confidence, query_generated, query_citations_verified

If those names change, update _is_query_stage -- it is intentionally a single
short function, not scattered string matching.
"""

from __future__ import annotations

from typing import Any

from citerator.observability.tracing import NullTracer, Tracer

_active_tracer: Tracer | None = None

_RESERVED_KEYS = {"event", "level", "logger", "timestamp", "trace_id"}


def set_active_tracer(tracer: Tracer) -> None:
    global _active_tracer
    _active_tracer = tracer


def clear_active_tracer() -> None:
    global _active_tracer
    _active_tracer = None


def _is_query_stage(event: str) -> bool:
    if not event:
        return False
    if event.startswith("query_"):
        return True
    return event == "reranked"


def tracing_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    tracer = _active_tracer
    if tracer is None or isinstance(tracer, NullTracer):
        return event_dict

    trace_id = event_dict.get("trace_id")
    if not trace_id:
        return event_dict

    event = event_dict.get("event", "")
    if not _is_query_stage(event):
        return event_dict

    data = {k: v for k, v in event_dict.items() if k not in _RESERVED_KEYS}
    try:
        tracer.log_span(str(trace_id), name=str(event), data=data)
    except Exception:
        pass
    return event_dict
