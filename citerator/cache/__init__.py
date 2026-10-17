"""Semantic response cache.

Two-tier lookup: exact match on normalized question + scope hash first
(O(1)), then a semantic scan over recent entries (O(n) with n <= max_entries).
The exact tier catches the bulk of traffic (analysts asking the same
question twice); the semantic tier catches phrasing variations.

Storage is pluggable: Redis for multi-process deployments, in-process
LRU for single-process. Both use the same interface and both serialize
AnswerResult as JSON. Redis keys are namespaced by tenant so a shared
Redis instance serves multiple workspaces without collision.

Invalidation: entries expire by TTL and are evicted when the cache hits
max_entries. The cache does not currently invalidate on document change
-- doing so would require a reverse index from chunk_id to question
embeddings. Call `POST /settings/cache/purge` after re-ingesting to clear
the cache explicitly.
"""

from citerator.cache.semantic import SemanticCache, get_cache, reset_cache

__all__ = ["SemanticCache", "get_cache", "reset_cache"]