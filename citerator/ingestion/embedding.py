"""Embedding models behind one interface, plus a content-hash cache.

Dense:   BGEEmbedder (local, free, private), OpenAIEmbedder (API), HashEmbedder (offline/tests)
Sparse:  FastembedBM25 (real BM25 vectors for hybrid search), HashSparseEmbedder (offline/tests)

Never mix vectors from different models in one collection: the collection name includes the
embedder name (see store.collection_name).
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from pathlib import Path
from typing import NamedTuple, Protocol

import numpy as np

log = logging.getLogger("citerator.embedding")

_WORD = re.compile(r"\w+", re.UNICODE)
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class DenseEmbedder(Protocol):
    name: str
    dim: int
    max_tokens: int  # hard input limit of the model; longer text is silently truncated
    tokenizer_name: str | None

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


# --------------------------------------------------------------------------- dense


class BGEEmbedder:
    """Local sentence-transformers model. No documents leave the machine."""

    max_tokens = 512

    def __init__(
        self,
        model_name: str = "BAAI/bge-base-en-v1.5",
        device: str | None = None,
        batch_size: int = 32,
        use_query_instruction: bool = True,
    ):
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self.tokenizer_name = model_name
        self.batch_size = batch_size
        self.use_query_instruction = use_query_instruction
        self._model = SentenceTransformer(model_name, device=device)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return self._model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=len(texts) > 200
        ).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        prefix = BGE_QUERY_INSTRUCTION if self.use_query_instruction else ""
        return self._model.encode([prefix + text], normalize_embeddings=True)[0].astype(np.float32)


class OpenAIEmbedder:
    """OpenAI embeddings API. Check current pricing before choosing; track usage in `tokens_used`."""

    max_tokens = 8191
    tokenizer_name = None  # sizes are approximated; chunks are far below the 8191 limit

    DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}

    def __init__(self, model: str = "text-embedding-3-small", batch_size: int = 96):
        from openai import OpenAI

        self.name = model
        self.dim = self.DIMS.get(model, 1536)
        self.batch_size = batch_size
        self.tokens_used = 0
        self._client = OpenAI()

    def _embed(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), self.batch_size):
            resp = self._client.embeddings.create(model=self.name, input=texts[i: i + self.batch_size])
            self.tokens_used += resp.usage.total_tokens
            out += [d.embedding for d in resp.data]
        arr = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.where(norms == 0, 1, norms)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts) if texts else np.zeros((0, self.dim), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text])[0]


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder. Offline, instant, no model download.

    Not a quality embedder. It exists so tests, CI and smoke runs work without downloads, and it
    still captures lexical overlap, so retrieval comparisons stay meaningful on small examples.
    """

    max_tokens = 8192
    tokenizer_name = None

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = f"hash-{dim}"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for w in _WORD.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


class CachedEmbedder:
    """Wraps an embedder with an on-disk cache keyed by (model, sha256(text)).

    Re-ingesting unchanged text, or re-running semantic chunking, costs nothing.
    """

    def __init__(self, inner: DenseEmbedder, cache_path: Path):
        self.inner = inner
        cache_path = Path(cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(cache_path))
        self._db.execute("CREATE TABLE IF NOT EXISTS emb (model TEXT, h TEXT, vec BLOB, PRIMARY KEY (model, h))")
        self.hits = 0
        self.misses = 0

    name = property(lambda self: self.inner.name)
    dim = property(lambda self: self.inner.dim)
    max_tokens = property(lambda self: self.inner.max_tokens)
    tokenizer_name = property(lambda self: self.inner.tokenizer_name)

    @staticmethod
    def _h(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        hashes = [self._h(t) for t in texts]
        found: dict[str, np.ndarray] = {}
        for i in range(0, len(hashes), 500):
            part = list(set(hashes[i: i + 500]))
            marks = ",".join("?" * len(part))
            rows = self._db.execute(f"SELECT h, vec FROM emb WHERE model=? AND h IN ({marks})", [self.name, *part])
            for h, blob in rows:
                found[h] = np.frombuffer(blob, dtype=np.float32)
        missing = [(i, t) for i, (t, h) in enumerate(zip(texts, hashes)) if h not in found]
        uniq: dict[str, str] = {}
        for i, t in missing:
            uniq.setdefault(hashes[i], t)
        if uniq:
            vecs = self.inner.embed_documents(list(uniq.values()))
            with self._db:
                for (h, _), v in zip(uniq.items(), vecs):
                    found[h] = np.asarray(v, dtype=np.float32)
                    self._db.execute(
                        "INSERT OR REPLACE INTO emb VALUES (?,?,?)", (self.name, h, found[h].tobytes())
                    )
        self.misses += len(missing)
        self.hits += len(texts) - len(missing)
        return np.stack([found[h] for h in hashes])

    def embed_query(self, text: str) -> np.ndarray:
        return self.inner.embed_query(text)

    def close(self) -> None:
        self._db.close()


# --------------------------------------------------------------------------- sparse


class SparseVec(NamedTuple):
    indices: list[int]
    values: list[float]


class SparseEmbedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[SparseVec]: ...

    def embed_query(self, text: str) -> SparseVec: ...


class FastembedBM25:
    """BM25 sparse vectors via fastembed. Qdrant applies IDF at query time (Modifier.IDF)."""

    name = "bm25"

    def __init__(self, model_name: str = "Qdrant/bm25"):
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name=model_name)

    @staticmethod
    def _to_vec(e) -> SparseVec:
        return SparseVec([int(i) for i in e.indices], [float(v) for v in e.values])

    def embed_documents(self, texts: list[str]) -> list[SparseVec]:
        return [self._to_vec(e) for e in self._model.embed(texts)]

    def embed_query(self, text: str) -> SparseVec:
        return self._to_vec(next(iter(self._model.query_embed(text))))


class HashSparseEmbedder:
    """Term-frequency sparse vectors over hashed tokens. Offline stand-in for BM25 (tests)."""

    name = "hash-sparse"
    BUCKETS = 2**20

    def _vec(self, text: str) -> SparseVec:
        counts: dict[int, float] = {}
        for w in _WORD.findall(text.lower()):
            idx = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "little") % self.BUCKETS
            counts[idx] = counts.get(idx, 0.0) + 1.0
        return SparseVec(list(counts.keys()), list(counts.values()))

    def embed_documents(self, texts: list[str]) -> list[SparseVec]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> SparseVec:
        return self._vec(text)


# --------------------------------------------------------------------------- factories


def get_embedder(kind: str, model_name: str | None = None) -> DenseEmbedder:
    if kind == "bge":
        return BGEEmbedder(model_name or "BAAI/bge-base-en-v1.5")
    if kind == "openai":
        return OpenAIEmbedder(model_name or "text-embedding-3-small")
    if kind == "hash":
        return HashEmbedder()
    raise ValueError(f"unknown embedder {kind!r} (choose bge, openai, hash)")


def get_sparse_embedder(kind: str) -> SparseEmbedder | None:
    if kind in ("none", "", None):
        return None
    if kind == "bm25":
        try:
            return FastembedBM25()
        except Exception as exc:
            log.warning("BM25 sparse embedder unavailable (%s). Continuing WITHOUT sparse vectors; "
                        "hybrid search will not work until you re-ingest with fastembed installed.", exc)
            return None
    if kind == "hash":
        return HashSparseEmbedder()
    raise ValueError(f"unknown sparse embedder {kind!r} (choose bm25, hash, none)")
