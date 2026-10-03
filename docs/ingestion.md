# Ingestion pipeline (Phase 2)

    folder of PDF/MD/HTML -> load + clean -> chunk -> embed -> Qdrant, plus a JSON run report

## Run it

    # 1. chunk stats only, no embeddings, no database (fast, free)
    python -m citerator.ingestion.pipeline --input data/raw --strategy structure --dry-run

    # 2. real ingestion (needs Qdrant running: docker compose -f docker\docker-compose.yml up -d)
    python -m citerator.ingestion.pipeline --input data/raw --strategy structure --embedder bge

    # 3. compare strategies on retrieval quality (needs labelled questions in eval/questions.json)
    python -m eval.compare_chunking --input data/raw --strategies fixed structure semantic --embedders bge

Optional per-document metadata goes next to the file: `name.pdf.meta.json`
`{"title": "...", "doc_type": "standard", "jurisdiction": "international", "effective_date": "2025-06-01"}`

## Design decisions

- **Chunk size is measured in tokens of the embedding model's own tokenizer.** BGE truncates input
  above 512 tokens without warning. The pipeline refuses `--max-tokens` above model limit - 64.
- **All chunkers only choose cut points** (character spans). One shared finalizer adds tokens, pages,
  section paths and IDs, so strategies are directly comparable and citations behave identically.
- **Breadcrumbs are embedded, not stored.** Structure-aware chunks embed "Doc > Section > ..." plus the
  text; the stored text stays clean for display and citation.
- **Idempotent and resumable.** Manifest keyed by content hash + pipeline settings; deterministic UUIDv5
  chunk IDs; stale points deleted per document before upsert; manifest saved after every document.
- **Dense + sparse vectors from day one** (named vectors `dense` and `bm25`), so Phase 3 hybrid search
  needs no re-ingestion. One collection per (strategy, embedder); never mix embedding models.
- **Labels for evaluation are page/section level**, so they are valid for every chunker.

## Known limits

- Tables in PDFs are read as plain text. Scanned pages are flagged in the report, not OCR'd.
- Dehyphenation joins "cross-\nborder" into "crossborder" (only before a lowercase letter).
- PyMuPDF is AGPL-licensed. Fine for a portfolio; check its commercial licence before shipping
  closed-source client work. The loader is isolated in `loaders.py` if you need to swap it.
- Without a downloadable HF tokenizer the pipeline falls back to an approximate regex tokenizer and
  says so in the report (`tokenizer_exact: false`).
