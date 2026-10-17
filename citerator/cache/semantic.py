"""Semantic cache implementation.

Entries are stored as JSON blobs keyed by a scope hash. Each entry embeds
the question's dense vector so a lookup can perform cosine similarity
across the current namespace without a second embedding pass.

Lookup algorithm:

  1. Exact tier: normalized question + scope hash → dict lookup. O(1).
  2. Semantic tier: embed the question once, load the namespace's vectors
     into a numpy array, compute cosine similarity, return the highest
     entry above threshold. O(n) with n bounded by max_entries.

The semantic tier is skipped when the exact tier hits. A hot FAQ is
served from the exact tier in microseconds.

Scope: the cache key includes a hash of (document_scope, jurisdiction) so
a filtered query does not return an unfiltered answer. Two questions with
identical text but different scopes are separate cache entries.

Tenant: the namespace prefix includes the tenant ID when present, so a
shared Redis instance serves isolated workspaces without leaking answers
across tenants.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any

import structlog

from citerator.cache.backend import CacheBackend, InMemoryBackend, RedisBackend
from citerator.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_CACHE_VERSION = "v1"


@dataclass
class CacheEntry:
    question: str
    scope_hash: str
    embedding: list[float]
    result_json: str


def _normalize(question: str) -> str:
    return " ".join(question.lower().split())


def _scope_hash(
    document_scope: list[str] | None, jurisdiction: str | None
) -> str:
    payload = {
        "document_scope": sorted(document_scope or []),
        "jurisdiction": jurisdiction or "",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _question_hash(question: str) -> str:
    return hashlib.sha256(_normalize(question).encode("utf-8")).hexdigest()[:24]


class SemanticCache:
    def __init__(
        self,
        backend: CacheBackend,
        embedder,
        *,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 3600,
        max_entries: int = 1000,
    ):
        self.backend = backend
        self.embedder = embedder
        self.threshold = similarity_threshold
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._lock = threading.RLock()

    def _namespace(self, tenant: str | None) -> str:
        return f"{_CACHE_VERSION}:{tenant or '_default'}:"

    def _exact_key(self, question: str, scope_hash: str, tenant: str | None) -> str:
        return f"{self._namespace(tenant)}exact:{scope_hash}:{_question_hash(question)}"

    def _semantic_key(self, question: str, scope_hash: str, tenant: str | None) -> str:
        return f"{self._namespace(tenant)}sem:{scope_hash}:{_question_hash(question)}"

    def lookup(
        self,
        question: str,
        *,
        document_scope: list[str] | None = None,
        jurisdiction: str | None = None,
        tenant: str | None = None,
    ) -> dict[str, Any] | None:
        scope = _scope_hash(document_scope, jurisdiction)

        exact = self.backend.get(self._exact_key(question, scope, tenant))
        if exact is not None:
            logger.info("cache_hit", tier="exact", question=question[:80])
            return json.loads(exact)

        try:
            query_vec = self.embedder.embed_query(question)
        except Exception as exc:
            logger.warning("cache_embed_failed", error=str(exc))
            return None

        namespace = f"{self._namespace(tenant)}sem:{scope}:"
        keys = self.backend.keys(namespace)
        if not keys:
            return None

        import numpy as np

        query_arr = np.asarray(query_vec, dtype=float)
        query_norm = float(np.linalg.norm(query_arr))
        if query_norm == 0.0:
            return None

        best: tuple[float, str] | None = None
        for key in keys:
            raw = self.backend.get(key)
            if not raw:
                continue
            try:
                entry = json.loads(raw)
                vec = np.asarray(entry["embedding"], dtype=float)
            except Exception:
                continue
            norm = float(np.linalg.norm(vec))
            if norm == 0.0:
                continue
            similarity = float(np.dot(query_arr, vec) / (query_norm * norm))
            if best is None or similarity > best[0]:
                best = (similarity, entry["result_json"])

        if best is None or best[0] < self.threshold:
            return None

        logger.info(
            "cache_hit",
            tier="semantic",
            similarity=round(best[0], 4),
            question=question[:80],
        )
        return json.loads(best[1])

    def store(
        self,
        question: str,
        result: dict[str, Any],
        *,
        document_scope: list[str] | None = None,
        jurisdiction: str | None = None,
        tenant: str | None = None,
    ) -> None:
        # Only cache answers that actually answered the question. Refusals
        # and escalations are cheap to recompute and their passages may
        # change as the corpus does.
        if result.get("state") == "insufficient":
            return
        if not result.get("answer"):
            return

        scope = _scope_hash(document_scope, jurisdiction)
        try:
            vec = self.embedder.embed_query(question)
        except Exception as exc:
            logger.warning("cache_embed_failed", error=str(exc))
            return

        result_json = json.dumps(result, default=str)
        entry = {
            "question": question,
            "scope_hash": scope,
            "embedding": list(map(float, vec)),
            "result_json": result_json,
        }

        with self._lock:
            self.backend.set(
                self._exact_key(question, scope, tenant),
                result_json,
                self.ttl,
            )
            self.backend.set(
                self._semantic_key(question, scope, tenant),
                json.dumps(entry),
                self.ttl,
            )

    def purge(self, *, tenant: str | None = None) -> int:
        with self._lock:
            prefix = self._namespace(tenant) if tenant else _CACHE_VERSION
            return self.backend.purge(prefix)


_cache_singleton: SemanticCache | None = None
_cache_lock = threading.Lock()


def get_cache(settings: Settings | None = None) -> SemanticCache | None:
    """Return the process-wide cache, or None when caching is disabled.

    A caller that gets None should proceed without caching. Returning None
    rather than a no-op cache means the hot path has zero overhead when
    the feature is off.
    """

    global _cache_singleton

    s = settings or get_settings()
    if not s.cache_enabled:
        return None

    with _cache_lock:
        if _cache_singleton is not None:
            return _cache_singleton

        if s.cache_backend == "redis":
            try:
                backend: CacheBackend = RedisBackend(
                    s.cache_redis_url, max_entries=s.cache_max_entries
                )
            except Exception as exc:
                logger.warning(
                    "cache_redis_init_failed",
                    error=str(exc),
                    fallback="memory",
                )
                backend = InMemoryBackend(max_entries=s.cache_max_entries)
        else:
            backend = InMemoryBackend(max_entries=s.cache_max_entries)

        try:
            from citerator.ingestion.embedding import get_embedder

            embedder = get_embedder(
                s.embedder_kind, s.embedding_model or None
            )
        except Exception as exc:
            logger.warning("cache_embedder_init_failed", error=str(exc))
            return None

        _cache_singleton = SemanticCache(
            backend,
            embedder,
            similarity_threshold=s.cache_similarity_threshold,
            ttl_seconds=s.cache_ttl_seconds,
            max_entries=s.cache_max_entries,
        )
        logger.info(
            "cache_initialized",
            backend=s.cache_backend,
            max_entries=s.cache_max_entries,
            threshold=s.cache_similarity_threshold,
        )
        return _cache_singleton


def reset_cache() -> None:
    """Drop the singleton. Call after settings change or in tests."""

    global _cache_singleton
    with _cache_lock:
        _cache_singleton = None