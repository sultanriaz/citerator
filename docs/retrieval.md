# Citerator Retrieval and Answering

This document describes Phase 3: hybrid retrieval, cross-encoder reranking,
confidence scoring, grounded generation, citation validation, and the `/query`
API.

## How to run

1. Ensure Phase 2 ingestion has populated the Qdrant collection you intend to use.
2. Set the Phase 3 settings in `.env` or the environment:
   - `EMBEDDER_KIND` must match the ingestion `--embedder` value.
   - `SPARSE_KIND` must match the ingestion `--sparse` value.
   - `ACTIVE_CHUNKING_STRATEGY` must match the ingestion `--chunker` value.
3. Start the API:

```bash
uvicorn citerator.api.app:app --reload