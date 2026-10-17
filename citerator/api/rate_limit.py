"""In-process fixed-window rate limiter.

Pure ASGI middleware. The limit is read from effective settings lazily and
cached briefly so per-request SQLite opens don't happen on every call. A
change made through /settings/pipeline is picked up within the cache window.

The ``limit`` keyword is accepted at construction so citerator/api/app.py can
pass the effective rate from Settings at startup. When omitted, the limit is
resolved lazily from the runtime settings.

Keyed by the X-API-Key header when present, otherwise client IP. Window is
60 seconds. GET /health is exempt.

Known limitations in docs/settings.md: in-process only, resets on restart,
not shared across workers.
"""

from __future__ import annotations

import time
from threading import Lock

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_WINDOW_SECONDS = 60
_LIMIT_CACHE_SECONDS = 5
_EXEMPT_PATHS = {"/health"}


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, limit: int | None = None, **_ignored) -> None:
        self.app = app
        self._lock = Lock()
        self._counters: dict[str, tuple[int, int]] = {}
        self._limit_override = limit
        self._cached_limit: int = limit if limit is not None else 120
        self._cached_at: float = 0.0 if limit is None else time.time()

    def _current_limit(self) -> int:
        if self._limit_override is not None:
            return self._limit_override
        now = time.time()
        if now - self._cached_at < _LIMIT_CACHE_SECONDS:
            return self._cached_limit
        try:
            from citerator.runtime_config.effective_settings import (
                get_effective_settings,
            )

            self._cached_limit = int(
                get_effective_settings().rate_limit_requests_per_minute
            )
        except Exception:
            pass
        self._cached_at = now
        return self._cached_limit

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

        # Read the limit fresh on every request when no explicit override
        # was given at construction time. Falls back to the cached value
        # if the settings read fails. This is what makes a runtime
        # rate_limit_requests_per_minute change take effect without a
        # server restart.
        if self._limit_override is not None:
            limit = self._limit_override
        else:
            try:
                from citerator.runtime_config.effective_settings import (
                    get_effective_settings,
                )

                limit = int(
                    get_effective_settings().rate_limit_requests_per_minute
                )
                self._cached_limit = limit
            except Exception:
                limit = self._current_limit()
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