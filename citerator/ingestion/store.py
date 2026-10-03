"""Qdrant collection management and deterministic upserts.

Collections hold a named dense vector ("dense") and, optionally, a named sparse BM25 vector
("bm25") from day one, so Phase 3 hybrid search needs no re-ingestion.
"""
from __future__ import annotations

import logging
import re
import warnings
from datetime import datetime
from pathlib import Path

from qdrant_client import QdrantClient, models

from .embedding import SparseVec
from .models import Chunk

log = logging.getLogger("citerator.store")

DENSE = "dense"
SPARSE = "bm25"
BATCH = 128


def make_client(url: str) -> QdrantClient:
    """http(s) URL -> server; ':memory:' -> in-process; anything else -> local folder."""
    if url.startswith(("http://", "https://")):
        return QdrantClient(url=url)
    if url == ":memory:":
        return QdrantClient(location=":memory:")
    Path(url).mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=url)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def collection_name(strategy: str, embedder_name: str) -> str:
    return f"citerator__{slug(strategy)}__{slug(embedder_name)}"


def payload_for(chunk: Chunk, embedding_model: str, ingested_at: datetime) -> dict:
    payload = chunk.model_dump(exclude={"embed_text"})
    payload["embedding_model"] = embedding_model
    payload["ingested_at"] = ingested_at.isoformat()
    return payload


class ChunkStore:
    def __init__(self, client: QdrantClient, collection: str, dim: int, sparse: bool):
        self.client = client
        self.collection = collection
        self.dim = dim
        self.sparse = sparse

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            info = self.client.get_collection(self.collection)
            vectors = info.config.params.vectors
            size = vectors[DENSE].size if isinstance(vectors, dict) and DENSE in vectors else None
            if size != self.dim:
                raise RuntimeError(
                    f"Collection {self.collection!r} has vector size {size}, but the embedder produces "
                    f"{self.dim}. Never mix embedding models in one collection; delete it or use another name."
                )
            has_sparse = bool(info.config.params.sparse_vectors and SPARSE in info.config.params.sparse_vectors)
            if self.sparse and not has_sparse:
                raise RuntimeError(
                    f"Collection {self.collection!r} has no sparse vectors; re-create it to enable hybrid search."
                )
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={DENSE: models.VectorParams(size=self.dim, distance=models.Distance.COSINE)},
            sparse_vectors_config=(
                {SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)} if self.sparse else None
            ),
        )
        for field in ("doc_id", "source_file", "doc_type", "jurisdiction"):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")  # local mode warns that indexes have no effect
                    self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)
            except Exception as exc:  # not fatal anywhere
                log.debug("payload index %s skipped: %s", field, exc)

    def delete_doc(self, doc_id: str) -> None:
        self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])
            ),
            wait=True,
        )

    def upsert(
        self,
        chunks: list[Chunk],
        dense,
        sparse: list[SparseVec] | None,
        embedding_model: str,
        ingested_at: datetime,
    ) -> None:
        for i in range(0, len(chunks), BATCH):
            points = []
            for j in range(i, min(i + BATCH, len(chunks))):
                vector: dict = {DENSE: [float(x) for x in dense[j]]}
                if self.sparse and sparse is not None:
                    vector[SPARSE] = models.SparseVector(indices=sparse[j].indices, values=sparse[j].values)
                points.append(
                    models.PointStruct(
                        id=chunks[j].chunk_id,
                        vector=vector,
                        payload=payload_for(chunks[j], embedding_model, ingested_at),
                    )
                )
            self.client.upsert(self.collection, points=points, wait=True)

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count
