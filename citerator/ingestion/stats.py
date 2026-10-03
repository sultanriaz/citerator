"""Chunk statistics used in run reports and the chunking-strategy comparison charts."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .models import Chunk


def _pct(values: list[float], p: float) -> float:
    return float(np.percentile(values, p)) if values else 0.0


def compute_stats(chunks: list[Chunk], model_max_tokens: int = 512) -> dict:
    """Aggregate statistics over a set of chunks (possibly from several documents).

    - overlap_ratio: share of all chunk characters (excluding each document's first chunk) that
      were already present in the previous chunk of the same document. Pooled rather than a
      per-chunk mean, so one small tail chunk cannot distort it. 0 for strategies without overlap.
    - pct_cross_page: share of chunks whose text spans more than one page (PDF only).
    - pct_over_model_limit: share whose EMBEDDED text exceeds the embedding model's limit and
      would be silently truncated. This should be 0.
    """
    if not chunks:
        return {"n_chunks": 0}
    tokens = [c.token_count for c in chunks]
    embed_tokens = [c.embed_token_count for c in chunks]
    chars = [len(c.text) for c in chunks]

    by_doc: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        by_doc[c.doc_id].append(c)
    shared_chars, successor_chars = 0, 0
    for doc_chunks in by_doc.values():
        doc_chunks.sort(key=lambda c: c.chunk_index)
        for prev, cur in zip(doc_chunks, doc_chunks[1:]):
            shared_chars += max(0, prev.char_end - cur.char_start)
            successor_chars += cur.char_end - cur.char_start

    paged = [c for c in chunks if c.page_start is not None and c.page_end is not None]
    return {
        "n_chunks": len(chunks),
        "n_documents": len(by_doc),
        "tokens_mean": round(float(np.mean(tokens)), 1),
        "tokens_median": round(_pct(tokens, 50), 1),
        "tokens_p95": round(_pct(tokens, 95), 1),
        "tokens_min": int(min(tokens)),
        "tokens_max": int(max(tokens)),
        "embed_tokens_total": int(sum(embed_tokens)),
        "chars_mean": round(float(np.mean(chars)), 1),
        "overlap_ratio": round(shared_chars / successor_chars, 4) if successor_chars else 0.0,
        "pct_cross_page": round(100 * sum(c.page_start != c.page_end for c in paged) / len(paged), 2) if paged else None,
        "pct_over_model_limit": round(100 * sum(t > model_max_tokens for t in embed_tokens) / len(chunks), 2),
        "pct_tiny_chunks": round(100 * sum(t < 30 for t in tokens) / len(chunks), 2),
    }


def format_stats(stats: dict) -> str:
    if not stats.get("n_chunks"):
        return "  (no chunks)"
    rows = [
        ("chunks", stats["n_chunks"]),
        ("documents", stats["n_documents"]),
        ("tokens mean / median / p95", f'{stats["tokens_mean"]} / {stats["tokens_median"]} / {stats["tokens_p95"]}'),
        ("tokens min / max", f'{stats["tokens_min"]} / {stats["tokens_max"]}'),
        ("overlap ratio (pooled)", stats["overlap_ratio"]),
        ("chunks crossing pages (%)", stats["pct_cross_page"]),
        ("chunks over model limit (%)", stats["pct_over_model_limit"]),
        ("tiny chunks <30 tokens (%)", stats["pct_tiny_chunks"]),
        ("tokens to embed", stats["embed_tokens_total"]),
    ]
    width = max(len(k) for k, _ in rows)
    return "\n".join(f"  {k:<{width}}  {v}" for k, v in rows)
