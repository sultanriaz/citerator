from __future__ import annotations

import sys
from pathlib import Path

import pytest

from citerator.config import Settings
from citerator.observability import tracing
from citerator.observability.tracing import (
    FakeTracer,
    LangfuseTracer,
    NullTracer,
    get_tracer,
    reset_tracer_cache,
)


@pytest.fixture(autouse=True)
def _isolate():
    reset_tracer_cache()
    yield
    reset_tracer_cache()


def _settings(**overrides) -> Settings:
    base = dict(
        enable_tracing=True,
        langfuse_public_key="",
        langfuse_secret_key="",
        langfuse_host="https://cloud.langfuse.com",
    )
    base.update(overrides)
    return Settings(**base)


def test_disabled_returns_null():
    assert isinstance(get_tracer(_settings(enable_tracing=False)), NullTracer)


def test_missing_keys_returns_null():
    t = get_tracer(_settings(langfuse_public_key="x", langfuse_secret_key=""))
    assert isinstance(t, NullTracer)
    t = get_tracer(_settings(langfuse_public_key="", langfuse_secret_key="x"))
    assert isinstance(t, NullTracer)


def test_both_keys_returns_langfuse_tracer():
    t = get_tracer(
        _settings(langfuse_public_key="pk", langfuse_secret_key="sk")
    )
    assert isinstance(t, LangfuseTracer)


def test_langfuse_sdk_not_imported_when_keys_missing(monkeypatch):
    called = {"import": 0}

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langfuse" or name.startswith("langfuse."):
            called["import"] += 1
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    reset_tracer_cache()
    t = get_tracer(_settings(langfuse_public_key="", langfuse_secret_key=""))
    assert isinstance(t, NullTracer)
    assert called["import"] == 0


def test_fake_tracer_records_calls_in_order():
    t = FakeTracer()
    t.start_trace("t1", "query", {"q": "hi"})
    t.log_span("t1", "query_retrieved", {"count": 3})
    t.log_span("t1", "reranked", {"kept": 5})
    t.end_trace("t1", {"state": "confident"}, {"path": "/query"})
    t.score("t1", "user_feedback", 1.0, "great")

    assert t.start_traces[0]["name"] == "query"
    assert [s["name"] for s in t.spans] == ["query_retrieved", "reranked"]
    assert t.end_traces[0]["output"] == {"state": "confident"}
    assert t.scores[0]["value"] == 1.0
