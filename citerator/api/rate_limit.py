"""In-process fixed-window rate limiter.

Pure ASGI middleware, so it wraps every route without touching any existing
route file. Keyed by the X-API-Key header when present, otherwise by client
IP. The window is 60 seconds; the limit is read fresh on every request via
get_effective_settings so a change on the Settings screen takes effect live.

GET /health is exempt.

Known limitations (documented in docs/settings.md): in-process only --
counters reset on process restart and are not shared across multiple worker
processes. A Redis-backed limiter is the fix if this is ever run with more
than one worker.
"""

from __future__ import annotations

import time
from threading import Lock

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from citerator.runtime_config.effective_settings import get_effective_settings

_WINDOW_SECONDS = 60
_EXEMPT_PATHS = {"/health"}


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app
        self._lock = Lock()
        self._counters: dict[str, tuple[int, int]] = {}

    def _key(self, scope: Scope) -> str:
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name == b"x-api-key":
                try:
                    return f"key:{raw_value.decode('latin-1')}"
                except Exception:
                    break
        client = scope.get("client")
        if client:
            return f"ip:{client[0]}"
        return "ip:unknown"

    def _check(self, key: str, limit: int) -> tuple[bool, int]:
        now = int(time.time())
        window_start = (now // _WINDOW_SECONDS) * _WINDOW_SECONDS

        with self._lock:
            count, window = self._counters.get(key, (0, window_start))
            if window != window_start:
                count, window = 0, window_start

            if count >= limit:
                retry_after = (window + _WINDOW_SECONDS) - now
                return False, max(1, retry_after)

            self._counters[key] = (count + 1, window)
            return True, 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        try:
            limit = get_effective_settings().rate_limit_requests_per_minute
        except Exception:
            limit = 120

        key = self._key(scope)
        allowed, retry_after = self._check(key, limit)

        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
