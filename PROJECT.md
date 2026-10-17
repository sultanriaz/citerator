# Citerator

A retrieval-augmented compliance Q&A system for AML/KYC teams. Analysts ask
regulatory questions in plain English and get answers strictly grounded in
the firm's indexed documents — every claim tied to a numbered citation and
a page reference. When evidence is weak, the pipeline refuses to answer and
escalates to a human instead.

> **Decision-support tool, not legal advice. Verify citations before acting.**

---

## What it does

Citerator ingests regulatory documents (PDF, Markdown, HTML), chunks them
with awareness of document structure, embeds them with both dense and sparse
vectors, and answers analyst questions with three deliberately distinct
behaviors:

| State | When | What the user sees |
|---|---|---|
| `confident` | Retrieval evidence is strong | Answer text with inline `[n]` citations linking to source excerpts |
| `low_confidence` | Evidence is thin but retrievable | Answer text, a warning banner, and a prominent "Escalate to compliance team" button |
| `insufficient` | No answer passes the confidence floor | **No answer generated.** Closest passages shown for context, plus an escalation draft for a human reviewer |

The third state is the one that matters. A compliance tool that hallucinates
an AML threshold is worse than useless. Citerator is built around the
principle that refusing to answer is a feature, not a failure.

---

## Architecture
# ---------------------------------------------------------------
# Part 2: what's been built (all 9 phases + loops)
# ---------------------------------------------------------------
@'

---

## What's been built

### Phase 2 — Ingestion

- PDF / Markdown / HTML loaders with header/footer stripping, dehyphenation,
  cross-page paragraph merging, and heading-level detection
- Three chunking strategies: fixed-size, structure-aware, semantic
- Tokenizer abstraction with HuggingFace and regex implementations
- Dense (BGE) and sparse (BM25) embeddings, plus hash-based offline fakes
- Qdrant collection management with automatic schema upgrades
- CLI pipeline writing per-run JSON reports and an idempotent manifest

### Phase 3 — Retrieval + generation

- Hybrid search with RRF fusion in a single Qdrant round trip
- Cross-encoder reranking with a deterministic fake for tests
- Sigmoid confidence scoring with three-state banding
- Provider-agnostic LLM client (OpenAI / Anthropic / Gemini / fake)
- Grounded prompt construction and `[n]` citation parsing with validation
- `POST /query` returning a full `AnswerResult` contract

### Phase 4 — Document management

- `POST /documents/upload` accepting multipart uploads with metadata
- Live per-file ingestion status: `queued -> parsing -> chunking -> embedding
  -> indexing -> indexed`
- SQLite-backed document registry and job tracker
- Chunk browser, reindex, and idempotent delete
- Shared manifest with the CLI pipeline so API- and CLI-ingested files are
  recognized as already-indexed by either

### Phase 5 — Evaluation harness

- Real 22-question labelled benchmark across four categories
- Ragas scoring: faithfulness, answer relevancy, context precision, context
  recall
- Safety metrics: refuse rate on out-of-corpus, escalate rate on
  underspecified
- Run history with per-question results, filtering by category
- Compare endpoint with direction tags (`higher_is_better` /
  `lower_is_better`) for the UI

### Phase 6 — Runtime settings API

- Hot-reloadable `confidence_threshold`, `confidence_floor`, `top_k_*`,
  `llm_model`, and more — effective on the next request, no restart
- FastAPI `dependency_overrides` mechanism so existing routes pick up new
  values without code changes
- Rate limiting middleware (fixed-window, per API key, 429 with `Retry-After`)
- API key regeneration with show-once semantics

### Phase 7 — Observability

- Structlog with contextvars so a trace ID bound at request start appears
  on every log line — including inside modules this project doesn't edit
- Langfuse tracer with three implementations (Null / Langfuse / Fake)
- Feedback endpoint wired to the UI's thumbs up/down, forwarded to Langfuse
  as a score attached to the original trace
- Escalation records with best-effort webhook delivery — the record is
  always persisted even if the webhook fails

### Phase 8 — Frontend foundation

- React 18 + Vite + TypeScript + Tailwind
- Design tokens (CSS custom properties) driving a dark-first theme
- App shell: sidebar with animated active indicator, top bar, persistent
  footer, responsive mobile nav
- **Ask screen** with all three answer states wired to the real API
- Citation chips, source cards, evidence panel with surrounding-chunk
  context, retrieval details drawer, escalation modal
- Feedback buttons, copy-with-citations, "Flag for review"

### Phase 9 — Documents screen

- Upload modal with drag-drop and metadata
- Live ingestion job table with 2-second polling while work is in flight
- Indexed documents table with Reindex and Delete actions
- Chunk preview drawer
- Chunking-strategy statistics

### Loops 1 and 2 — Self-improvement

- **Loop 1 (calibration):** Replaces heuristic `sigmoid(rerank_score)` with a
  logistic curve fitted to real `(score, faithfulness)` pairs from eval
  history. Confidence now means P(correct) on this corpus.
- **Loop 2 (auto-tune):** Sweeps `confidence_threshold` against the labelled
  set, scores each candidate on a weighted objective (safety refuse x 0.40 +
  safety escalate x 0.30 + answer rate x 0.30), rejects any that don't meet
  safety floors, and persists the winner through the runtime config API.
