from __future__ import annotations

import pytest

from citerator.observability import log_sink
from citerator.observability.tracing import FakeTracer, NullTracer


@pytest.fixture(autouse=True)
def _reset():
    log_sink.clear_active_tracer()
    yield
    log_sink.clear_active_tracer()


def test_no_tracer_means_no_calls():
    log_sink.set_active_tracer(NullTracer())
    event = {
        "event": "query_start",
        "trace_id": "t1",
        "question": "hi",
    }
    result = log_sink.tracing_processor(None, "info", dict(event))
    assert result == event


def test_query_stage_with_trace_id_forwards():
    tracer = FakeTracer()
    log_sink.set_active_tracer(tracer)

    log_sink.tracing_processor(
        None,
        "info",
        {
            "event": "query_retrieved",
            "trace_id": "t1",
            "count": 8,
            "duration_ms": 12.3,
        },
    )
    assert len(tracer.spans) == 1
    assert tracer.spans[0]["name"] == "query_retrieved"
    assert tracer.spans[0]["trace_id"] == "t1"
    assert tracer.spans[0]["data"] == {"count": 8, "duration_ms": 12.3}


def test_reranked_is_treated_as_query_stage():
    tracer = FakeTracer()
    log_sink.set_active_tracer(tracer)

    log_sink.tracing_processor(
        None, "info", {"event": "reranked", "trace_id": "t1", "kept": 8}
    )
    assert len(tracer.spans) == 1


def test_non_query_event_with_trace_id_is_ignored():
    tracer = FakeTracer()
    log_sink.set_active_tracer(tracer)

    log_sink.tracing_processor(
        None,
        "info",
        {"event": "ingestion_started", "trace_id": "t1", "file": "x.md"},
    )
    assert tracer.spans == []


def test_query_event_without_trace_id_is_ignored():
    tracer = FakeTracer()
    log_sink.set_active_tracer(tracer)

    log_sink.tracing_processor(None, "info", {"event": "query_start"})
    assert tracer.spans == []
