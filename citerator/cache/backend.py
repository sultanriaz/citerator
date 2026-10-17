"""Cache backends: in-process LRU and Redis.

Both implement the CacheBackend protocol. Values are opaque strings --
the semantic cache serializes AnswerResult to JSON before storing. This
keeps the backends dumb and swappable without changing the semantic layer.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)


class CacheBackend(Protocol):
    def get(self, key: str) -> str | None:
        ...

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        ...

    def delete(self, key: str) -> None:
        ...

    def keys(self, prefix: str = "") -> list[str]:
        ...

    def purge(self, prefix: str = "") -> int:
        ...


class InMemoryBackend:
    """Thread-safe LRU with per-entry TTL. Adequate for a single-process
    deployment; use RedisBackend when running multiple workers."""

    def __init__(self, max_entries: int = 1000):
        self._data: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._lock = threading.RLock()
        self._max = max_entries

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, (_, exp) in self._data.items() if exp < now]
        for k in expired:
            self._data.pop(k, None)

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            value, expires_at = entry
            if expires_at < time.time():
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._data[key] = (value, time.time() + ttl_seconds)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            self._evict_expired()
            return [k for k in self._data if k.startswith(prefix)]

    def purge(self, prefix: str = "") -> int:
        with self._lock:
            if not prefix:
                n = len(self._data)
                self._data.clear()
                return n
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys:
                self._data.pop(k, None)
            return len(keys)


class RedisBackend:
    """Redis-backed cache. All values are strings; TTL is native to Redis.

    Redis failures are logged and swallowed. A cache outage should not
    break the pipeline -- it should degrade to a cache miss and let the
    request proceed.
    """

    def __init__(self, url: str, max_entries: int = 1000):
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = "citerator:cache:"
        self._max = max_entries

    def _k(self, key: str) -> str:
        return self._prefix + key

    def get(self, key: str) -> str | None:
        try:
            return self._client.get(self._k(key))
        except Exception as exc:
            logger.warning("cache_redis_get_failed", error=str(exc))
            return None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            self._client.setex(self._k(key), ttl_seconds, value)
            self._trim()
        except Exception as exc:
            logger.warning("cache_redis_set_failed", error=str(exc))

    def delete(self, key: str) -> None:
        try:
            self._client.delete(self._k(key))
        except Exception as exc:
            logger.warning("cache_redis_delete_failed", error=str(exc))

    def keys(self, prefix: str = "") -> list[str]:
        try:
            full = self._k(prefix) + "*"
            return [
                k[len(self._prefix):] for k in self._client.keys(full)
            ]
        except Exception as exc:
            logger.warning("cache_redis_keys_failed", error=str(exc))
            return []

    def purge(self, prefix: str = "") -> int:
        try:
            full = self._k(prefix) + "*"
            keys = self._client.keys(full)
            if not keys:
                return 0
            return int(self._client.delete(*keys))
        except Exception as exc:
            logger.warning("cache_redis_purge_failed", error=str(exc))
            return 0

    def _trim(self) -> None:
        """Best-effort cap on entry count. Redis has no atomic LRU per
        namespace, so this evicts the oldest N when the namespace exceeds
        the configured maximum."""

        try:
            full = self._prefix + "*"
            count = self._client.dbsize()
            if count <= self._max:
                return
            keys = sorted(
                self._client.keys(full),
                key=lambda k: self._client.ttl(k),
            )
            to_remove = keys[: count - self._max]
            if to_remove:
                self._client.delete(*to_remove)
        except Exception:
            pass