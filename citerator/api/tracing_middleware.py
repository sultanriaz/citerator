"""Per-request tracing middleware for POST /query.

Only /query is traced. Other paths pass through untouched -- no trace_id
generated, no X-Trace-Id header added. That matches the explicit scope
decision to keep ingestion/eval/settings requests out of the trace graph.

The X-Trace-Id header is added on every /query response regardless of
whether a real tracer is configured, because the frontend uses it as the
handle for POST /feedback. Langfuse being off does not break feedback.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Awaitable, Callable

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from citerator.observability.tracing import get_tracer

logger = structlog.get_logger(__name__)

ReceiveCallable = Callable[[], Awaitable[Message]]
SendCallable = Callable[[Message], Awaitable[None]]


class TracingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def _resolve_trace_id(self, scope: Scope) -> str:
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name == b"x-trace-id":
                try:
                    candidate = raw_value.decode("ascii").strip()
                except Exception:
                    continue
                if candidate:
                    return candidate
        return str(uuid.uuid4())

    async def _read_body(self, receive: ReceiveCallable) -> bytes:
        chunks: list[bytes] = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b""))
                more = msg.get("more_body", False)
            elif msg["type"] == "http.disconnect":
                more = False
        return b"".join(chunks)

    def _replay(self, body: bytes) -> ReceiveCallable:
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        return replay

    def _extract_question(self, body: bytes) -> str:
        if not body:
            return ""
        try:
            payload = json.loads(body)
        except Exception:
            return ""
        if isinstance(payload, dict):
            q = payload.get("question", "")
            return str(q) if q else ""
        return ""

    def _extract_output(
        self, status: int, body: bytes
    ) -> dict[str, Any]:
        out: dict[str, Any] = {"status": status}
        if not body:
            return out
        try:
            payload = json.loads(body)
        except Exception:
            return out
        if not isinstance(payload, dict):
            return out
        for key in ("state", "confidence", "tokens", "latency_ms"):
            if key in payload:
                out[key] = payload[key]
        return out

    async def __call__(
        self, scope: Scope, receive: ReceiveCallable, send: SendCallable
    ) -> None:
        is_query = (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/query"
        )
        if not is_query:
            await self.app(scope, receive, send)
            return

        body = await self._read_body(receive)
        replay = self._replay(body)
        question = self._extract_question(body)
        trace_id = self._resolve_trace_id(scope)

        from citerator.runtime_config.effective_settings import (
            get_effective_settings,
        )

        try:
            tracer = get_tracer(get_effective_settings())
        except Exception:
            tracer = None

        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        if tracer is not None:
            try:
                tracer.start_trace(
                    trace_id, name="query", input={"question": question}
                )
            except Exception:
                pass

        status_holder = [200]
        response_chunks: list[bytes] = []

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder[0] = int(message.get("status", 200))
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-trace-id", trace_id.encode("ascii", errors="replace"))
                )
                message = {**message, "headers": headers}
            elif message["type"] == "http.response.body":
                response_chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay, send_wrapper)
        finally:
            if tracer is not None:
                try:
                    output = self._extract_output(
                        status_holder[0], b"".join(response_chunks)
                    )
                    tracer.end_trace(
                        trace_id, output=output, metadata={"path": "/query"}
                    )
                except Exception:
                    pass
            structlog.contextvars.clear_contextvars()
