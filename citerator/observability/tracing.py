"""Tracer Protocol plus Null, Langfuse, and Fake implementations.

Langfuse SDK construction is fully isolated inside LangfuseTracer -- every
version-specific call sits behind a defensive try/except so a live SDK drift
or a Langfuse outage never breaks a real user's query.

get_tracer() is cheap to call per request. The LangfuseTracer instance
memoizes its underlying SDK client on first use, so constructing a fresh
LangfuseTracer per request costs one object allocation, not one SDK init.
"""

from __future__ import annotations

from typing import Any, Protocol

import structlog

from citerator.config import Settings

logger = structlog.get_logger(__name__)


class Tracer(Protocol):
    def start_trace(self, trace_id: str, name: str, input: dict) -> None: ...
    def end_trace(self, trace_id: str, output: dict, metadata: dict) -> None: ...
    def log_span(self, trace_id: str, name: str, data: dict) -> None: ...
    def score(
        self, trace_id: str, name: str, value: float, comment: str | None
    ) -> None: ...


class NullTracer:
    """No-op tracer. The default when tracing is disabled or misconfigured."""

    def start_trace(self, trace_id: str, name: str, input: dict) -> None:
        return None

    def end_trace(self, trace_id: str, output: dict, metadata: dict) -> None:
        return None

    def log_span(self, trace_id: str, name: str, data: dict) -> None:
        return None

    def score(
        self, trace_id: str, name: str, value: float, comment: str | None
    ) -> None:
        return None


class FakeTracer:
    """Deterministic in-memory recorder for tests."""

    def __init__(self) -> None:
        self.start_traces: list[dict[str, Any]] = []
        self.end_traces: list[dict[str, Any]] = []
        self.spans: list[dict[str, Any]] = []
        self.scores: list[dict[str, Any]] = []

    def start_trace(self, trace_id: str, name: str, input: dict) -> None:
        self.start_traces.append(
            {"trace_id": trace_id, "name": name, "input": input}
        )

    def end_trace(self, trace_id: str, output: dict, metadata: dict) -> None:
        self.end_traces.append(
            {"trace_id": trace_id, "output": output, "metadata": metadata}
        )

    def log_span(self, trace_id: str, name: str, data: dict) -> None:
        self.spans.append({"trace_id": trace_id, "name": name, "data": data})

    def score(
        self, trace_id: str, name: str, value: float, comment: str | None
    ) -> None:
        self.scores.append(
            {
                "trace_id": trace_id,
                "name": name,
                "value": value,
                "comment": comment,
            }
        )


class LangfuseTracer:
    """Real Langfuse backend. Isolates all SDK-version-specific code."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None
        self._client_ready = False

    def _get_client(self) -> Any:
        if self._client_ready:
            return self._client
        self._client_ready = True
        try:
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=self._settings.langfuse_public_key,
                secret_key=self._settings.langfuse_secret_key,
                host=self._settings.langfuse_host,
            )
        except Exception as exc:
            logger.warning("langfuse_client_init_failed", error=str(exc))
            self._client = None
        return self._client

    def start_trace(self, trace_id: str, name: str, input: dict) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.trace(id=trace_id, name=name, input=input)
        except Exception as exc:
            logger.warning("langfuse_start_trace_failed", error=str(exc))

    def end_trace(self, trace_id: str, output: dict, metadata: dict) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            trace = client.trace(id=trace_id)
            trace.update(output=output, metadata=metadata)
        except Exception as exc:
            logger.warning("langfuse_end_trace_failed", error=str(exc))

    def log_span(self, trace_id: str, name: str, data: dict) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            trace = client.trace(id=trace_id)
            trace.span(name=name, input=data)
        except Exception as exc:
            logger.warning("langfuse_log_span_failed", error=str(exc))

    def score(
        self, trace_id: str, name: str, value: float, comment: str | None
    ) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.score(
                trace_id=trace_id, name=name, value=value, comment=comment
            )
        except Exception as exc:
            logger.warning("langfuse_score_failed", error=str(exc))


_tracer_singleton: Tracer | None = None
_warned_missing_keys = False


def get_tracer(settings: Settings) -> Tracer:
    """Return the active tracer, memoized for the process lifetime.

    NullTracer when tracing is disabled or Langfuse keys are missing.
    LangfuseTracer when both are configured. The underlying Langfuse client
    inside LangfuseTracer is lazy and built on first use, not here.
    """

    global _tracer_singleton, _warned_missing_keys

    if _tracer_singleton is not None:
        return _tracer_singleton

    if not settings.enable_tracing:
        _tracer_singleton = NullTracer()
        return _tracer_singleton

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        if not _warned_missing_keys:
            logger.info(
                "tracing_disabled",
                reason="langfuse keys not configured",
                hint="set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to enable",
            )
            _warned_missing_keys = True
        _tracer_singleton = NullTracer()
        return _tracer_singleton

    try:
        _tracer_singleton = LangfuseTracer(settings)
    except Exception as exc:
        logger.warning("tracer_init_failed", error=str(exc))
        _tracer_singleton = NullTracer()
    return _tracer_singleton


def reset_tracer_cache() -> None:
    """For tests only: clears the memoized tracer."""

    global _tracer_singleton, _warned_missing_keys
    _tracer_singleton = None
    _warned_missing_keys = False
