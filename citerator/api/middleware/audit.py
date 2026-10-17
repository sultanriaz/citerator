

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from citerator.config import Settings, get_settings
from citerator.governance import audit

logger = structlog.get_logger(__name__)

_PROMPT_VERSION = hashlib.sha256(
    b"citerator.prompt.system.v1"  # bumped when generation/prompt.py changes
).hexdigest()[:12]

_AUDITED_PATHS: list[tuple[str, str]] = [
    ("POST", "/query"),
    ("POST", "/escalations"),
    ("PATCH", "/escalations"),
    ("POST", "/settings/pipeline"),
    ("PUT", "/settings/pipeline"),
    ("POST", "/settings/pipeline/autotune"),
    ("PUT", "/settings/models"),
    ("POST", "/documents/upload"),
    ("DELETE", "/documents/"),
    ("POST", "/documents/"),
    ("POST", "/governance/"),
    ("PUT", "/governance/"),
    ("DELETE", "/governance/"),
]

_MAX_CAPTURE = 1_000_000


def _is_audited(method: str, path: str) -> bool:
    for m, prefix in _AUDITED_PATHS:
        if m != method:
            continue
        if prefix.endswith("/") and path.startswith(prefix):
            return True
        if prefix == path:
            return True
    return False


def _event_type(method: str, path: str) -> str:
    if path == "/query":
        return "query"
    if path.startswith("/escalations"):
        return "escalation"
    if path.startswith("/settings"):
        return "settings.change"
    if path.startswith("/documents"):
        return "document.change"
    if path.startswith("/governance"):
        return "governance.change"
    return f"{method.lower()}:{path}"


def _parse_json(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        payload = json.loads(body)
    except Exception:
        return {"_raw_length": len(body)}
    return payload if isinstance(payload, dict) else {"_value": payload}


class AuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "")
        path = scope.get("path", "")
        if not _is_audited(method, path):
            await self.app(scope, receive, send)
            return

        request_body = await self._read_body(receive)
        replay = self._replay(request_body)

        buffer: dict[str, Any] = {"start": None, "chunks": [], "status": 200}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                buffer["start"] = message
                buffer["status"] = int(message.get("status", 200))
                return
            if message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    buffer["chunks"].append(body)
                return
            await send(message)

        await self.app(scope, replay, send_wrapper)

        response_body = b"".join(buffer["chunks"])
        settings = get_settings()

        try:
            self._write_record(
                method=method,
                path=path,
                request_payload=_parse_json(request_body),
                response_payload=_parse_json(response_body),
                status_code=buffer["status"],
                scope=scope,
                settings=settings,
            )
        except Exception as exc:
            logger.warning(
                "audit_write_failed",
                path=path,
                error=str(exc),
                audit_required=settings.audit_required,
            )
            if settings.audit_required:
                await self._send_error(
                    send,
                    status_code=503,
                    code="audit_write_failed",
                    message=str(exc),
                )
                return

        if buffer["start"] is not None:
            await send(buffer["start"])
        if response_body:
            await send(
                {
                    "type": "http.response.body",
                    "body": response_body,
                    "more_body": False,
                }
            )
        else:
            await send({"type": "http.response.body", "body": b""})

    async def _read_body(self, receive: Receive) -> bytes:
        chunks: list[bytes] = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b""))
                more = msg.get("more_body", False)
            elif msg["type"] == "http.disconnect":
                break
        return b"".join(chunks)

    def _replay(self, body: bytes) -> Receive:
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

    def _write_record(
        self,
        *,
        method: str,
        path: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        status_code: int,
        scope: Scope,
        settings: Settings,
    ) -> None:
        api_key = ""
        for name, value in scope.get("headers", []):
            if name == b"x-api-key":
                try:
                    api_key = value.decode("latin-1")
                except Exception:
                    pass
                break
        actor = audit.actor_fingerprint(api_key) if api_key else None

        from structlog.contextvars import get_contextvars

        ctx = get_contextvars()
        trace_id = ctx.get("trace_id")
        tenant_id = ctx.get("tenant_id")
        user_id = ctx.get("user_id")

        payload: dict[str, Any] = {
            "method": method,
            "path": path,
            "status_code": status_code,
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "model": f"{settings.llm_provider}:{settings.llm_model or 'default'}",
            "prompt_version": _PROMPT_VERSION,
        }

        if path == "/query":
            payload["question"] = request_payload.get("question", "")
            payload["filters"] = {
                "document_scope": request_payload.get("document_scope"),
                "jurisdiction": request_payload.get("jurisdiction"),
            }
            payload["state"] = response_payload.get("state")
            payload["confidence"] = response_payload.get("confidence")
            citations = response_payload.get("citations") or []
            payload["cited_chunk_ids"] = [
                c.get("chunk_id") for c in citations if isinstance(c, dict)
            ]
            related = response_payload.get("related_passages") or []
            payload["retrieved_chunk_ids"] = [
                c.get("chunk_id") for c in related if isinstance(c, dict)
            ]
            payload["latency_ms"] = response_payload.get("latency_ms")
            payload["tokens"] = response_payload.get("tokens")
        else:
            payload["request_summary"] = _redact(request_payload)

        audit.append(_event_type(method, path), payload, actor=actor, settings=settings)

    async def _send_error(
        self,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"error": code, "detail": message},
        )
        await response({"type": "http"}, self._empty_receive, send)

    async def _empty_receive(self) -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove values that would leak credentials into the audit chain."""

    sensitive = {"api_key", "password", "secret", "token", "authorization"}
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k.lower() in sensitive:
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out