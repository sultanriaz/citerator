import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// Match whatever the client uses so tests exercise the same URL the
// browser will. In test mode Vite loads frontend/.env, so this resolves to
// VITE_API_BASE_URL (defaults to http://localhost:8000 if unset).
const BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

const confidentResponse = {
  state: "confident",
  answer: "Enhanced due diligence is required for politically exposed persons. [1]",
  confidence: 0.92,
  citations: [
    {
      chunk_id: "chunk-1",
      doc_title: "FATF Recommendations",
      section_path: ["Recommendation 10", "Customer due diligence"],
      page_start: 34,
      page_end: 35,
      source_file: "fatf-recommendations.pdf",
      excerpt: "Enhanced measures should be applied where higher risks are identified.",
    },
  ],
  related_passages: [
    {
      chunk_id: "chunk-1",
      doc_id: "doc-1",
      doc_hash: "h1",
      source_file: "fatf-recommendations.pdf",
      doc_title: "FATF Recommendations",
      doc_type: "standard",
      jurisdiction: "global",
      effective_date: "2023-02-01",
      section_path: ["Recommendation 10", "Customer due diligence"],
      page_start: 34,
      page_end: 35,
      char_start: 0,
      char_end: 200,
      text: "Enhanced measures should be applied where higher risks are identified.",
      token_count: 20,
      embed_token_count: 20,
      chunk_index: 0,
      chunker: "structure",
      chunker_params: {},
      rerank_score: 4.2,
    },
  ],
  escalation_draft: null,
  latency_ms: { retrieve: 200, rerank: 100, generate: 1200, total: 1500 },
  tokens: { input: 900, output: 120 },
  retrieval_details: null,
};

const lowConfidenceResponse = {
  ...confidentResponse,
  state: "low_confidence",
  confidence: 0.42,
  escalation_draft: {
    question: "When is enhanced due diligence required?",
    passages: confidentResponse.related_passages,
    suggested_note: "Low confidence answer; verify citations before relying on it.",
  },
};

const insufficientResponse = {
  ...confidentResponse,
  state: "insufficient",
  answer: null,
  confidence: 0.05,
  citations: [],
  tokens: null,
  escalation_draft: {
    question: "When is enhanced due diligence required?",
    passages: confidentResponse.related_passages,
    suggested_note: "Insufficient confidence to answer automatically.",
  },
};

export const handlers = [
  http.get(`${BASE}/eval/latest`, () =>
    HttpResponse.json({
      run_id: "eval-047",
      timestamp: new Date().toISOString(),
      label: "baseline",
      question_count: 22,
      metrics: {
        faithfulness_mean: { value: 0.89, delta_vs_previous: 0.03, sparkline: [0.71,0.75,0.79,0.82,0.85,0.89] },
        answer_relevancy_mean: { value: 0.92, delta_vs_previous: 0.04, sparkline: [0.8,0.82,0.85,0.88,0.9,0.92] },
        context_precision_mean: { value: 0.88, delta_vs_previous: 0.03, sparkline: [0.75,0.78,0.81,0.84,0.86,0.88] },
        context_recall_mean: { value: 0.91, delta_vs_previous: 0.04, sparkline: [0.78,0.81,0.84,0.87,0.89,0.91] },
        latency_p50_ms: { value: 1400, delta_vs_previous: -200, sparkline: [2200,2000,1800,1700,1550,1400] },
        latency_p95_ms: { value: 2800, delta_vs_previous: -200, sparkline: [3600,3400,3100,3000,2900,2800] },
        cost_per_query_usd_mean: { value: 0.0032, delta_vs_previous: -0.0004, sparkline: [0.005,0.0045,0.004,0.0036,0.0034,0.0032] },
      },
      safety: { refuse_pct: 98.3, escalate_pct: 96.7 },
    })
  ),
  http.get(`${BASE}/eval/runs`, () =>
    HttpResponse.json({
      runs: [
        { run_id: "eval-047", created_at: new Date().toISOString(), status: "completed", label: "Latest",
          chunking_strategy: "structure", embedder: "bge-small-en-v1.5", llm_provider: "gemini", llm_model: "gemini-3.5-flash-lite",
          rerank_model: "cross-encoder", top_k_retrieve: 20, top_k_rerank: 5, confidence_threshold: 0.72, confidence_floor: 0.15,
          question_count: 22, questions_completed: 22, error: null,
          faithfulness_mean: 0.89, answer_relevancy_mean: 0.92, context_precision_mean: 0.88, context_recall_mean: 0.91,
          latency_p50_ms: 1400, latency_p95_ms: 2800, cost_per_query_usd_mean: 0.0032,
          safety_refuse_pct: 98.3, safety_escalate_pct: 96.7,
          created_at_fmt: null } as unknown as Record<string, unknown>,
      ],
      count: 1, limit: 50, offset: 0,
    })
  ),
  http.get(`${BASE}/settings/pipeline`, () =>
    HttpResponse.json({
      active_chunking_strategy: "structure",
      top_k_retrieve: 20,
      top_k_rerank: 5,
      rerank_model: "cross-encoder/ms-marco-MiniLM-L-6-v2",
      confidence_threshold: 0.72,
      confidence_floor: 0.15,
      is_override: {},
    })
  ),
  http.put(`${BASE}/settings/pipeline`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      active_chunking_strategy: "structure",
      top_k_retrieve: (body.top_k_retrieve as number) ?? 20,
      top_k_rerank: (body.top_k_rerank as number) ?? 5,
      rerank_model: "cross-encoder/ms-marco-MiniLM-L-6-v2",
      confidence_threshold: (body.confidence_threshold as number) ?? 0.72,
      confidence_floor: (body.confidence_floor as number) ?? 0.15,
      is_override: {},
    });
  }),
  http.post(`${BASE}/settings/pipeline/preview-threshold`, () =>
    HttpResponse.json({ total: 120, confident: 66, low_confidence: 30, insufficient: 24, note: "Illustrative preview" })
  ),
  http.get(`${BASE}/settings/models`, () =>
    HttpResponse.json({
      embedding_model: { value: "BAAI/bge-base-en-v1.5", editable: false, reason: "requires re-ingestion" },
      llm_provider: "gemini",
      llm_model: "gemini-3.5-flash-lite",
      rerank_model: "cross-encoder/ms-marco-MiniLM-L-6-v2",
      cost_privacy_note: "LLM calls are sent to Google's Gemini API",
    })
  ),
  http.put(`${BASE}/settings/models`, async ({ request }) => {
    const body = (await request.json()) as Record<string, string>;
    return HttpResponse.json({
      embedding_model: { value: "BAAI/bge-base-en-v1.5", editable: false, reason: "requires re-ingestion" },
      llm_provider: body.llm_provider ?? "gemini",
      llm_model: body.llm_model ?? "gemini-3.5-flash-lite",
      rerank_model: body.rerank_model ?? "cross-encoder/ms-marco-MiniLM-L-6-v2",
      cost_privacy_note: "LLM calls are sent to Google's Gemini API",
    });
  }),
  http.get(`${BASE}/settings/api`, () =>
    HttpResponse.json({
      api_key_masked: "ct_demo............8f3a",
      endpoints: [
        { method: "POST", path: "/query", description: "Ask a compliance question", example: "curl -X POST http://localhost:8010/query" },
        { method: "POST", path: "/documents/upload", description: "Upload documents", example: "curl -X POST http://localhost:8010/documents/upload" },
        { method: "GET", path: "/eval/latest", description: "Latest evaluation", example: "curl -X GET http://localhost:8010/eval/latest" },
        { method: "GET", path: "/health", description: "Health check", example: "curl -X GET http://localhost:8010/health" },
      ],
      rate_limit: { requests_per_minute: 120, window_seconds: 60 },
    })
  ),
  http.post(`${BASE}/query`, async ({ request }) => {
    const body = (await request.json()) as { question: string };
    const q = body.question.toLowerCase();
    if (q.includes("insufficient") || q.includes("nothing")) {
      return HttpResponse.json(insufficientResponse, {
        headers: { "X-Trace-Id": "trace-insufficient" },
      });
    }
    if (q.includes("low")) {
      return HttpResponse.json(lowConfidenceResponse, {
        headers: { "X-Trace-Id": "trace-low" },
      });
    }
    return HttpResponse.json(confidentResponse, {
      headers: { "X-Trace-Id": "trace-confident" },
    });
  }),

  http.post(`${BASE}/feedback`, async ({ request }) => {
    const body = (await request.json()) as { trace_id: string; rating: string };
    return HttpResponse.json(
      {
        id: 1,
        trace_id: body.trace_id,
        rating: body.rating,
        comment: null,
        created_at: new Date().toISOString(),
      },
      { status: 201 }
    );
  }),

  http.post(`${BASE}/escalations`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      {
        id: 1,
        trace_id: (body.trace_id as string) ?? null,
        source: body.source,
        question: body.question,
        passages: body.passages ?? [],
        note: body.note,
        status: "open",
        resolution_note: null,
        webhook_delivered: false,
        webhook_error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      { status: 201 }
    );
  }),

  http.get(`${BASE}/health`, () =>
    HttpResponse.json({ status: "ok", collections: { test: 10 } })
  ),

  http.get(`${BASE}/documents`, () =>
    HttpResponse.json({
      documents: [
        {
          doc_id: "doc-1",
          source_file: "fatf-recommendations.pdf",
          title: "FATF Recommendations",
          doc_type: "standard",
          jurisdiction: "global",
          effective_date: "2023-02-01",
          page_count: 44,
          chunk_count: 84,
          doc_hash: "h1",
          chunker: "structure",
          chunker_params: {},
          embedder: "bge",
          sparse_embedder: "bm25",
          status: "indexed",
          warnings: [],
          indexed_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      count: 1,
      limit: 50,
      offset: 0,
    })
  ),

  http.get(`${BASE}/documents/jobs`, () =>
    HttpResponse.json([
      {
        job_id: "job-1",
        file_name: "policy.md",
        status: "indexed",
        doc_id: "doc-1",
        error: null,
        warnings: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ])
  ),

  http.get(`${BASE}/documents/chunking-strategies`, () =>
    HttpResponse.json({
      strategies: [
        {
          chunker: "structure",
          document_count: 1,
          total_chunk_count: 84,
          avg_chunk_count: 84,
          median_chunk_count: 84,
          active: true,
          note: "Corpus-shape statistics only.",
        },
      ],
      active: "structure",
    })
  ),

  http.post(`${BASE}/documents/upload`, () => {
    return HttpResponse.json(
      {
        accepted: [{ file_name: "hello.md", job_id: "job-test" }],
        count: 1,
      },
      { status: 202 }
    );
  }),

  http.get(`${BASE}/documents/:docId/chunks`, ({ params }) =>
    HttpResponse.json({
      doc_id: params.docId,
      count: 3,
      chunks: [
        {
          chunk_id: "c0",
          section_path: ["Recommendation 10"],
          page_start: 33,
          page_end: 33,
          token_count: 40,
          text: "Prior context.",
          chunk_index: 0,
        },
        {
          chunk_id: "chunk-1",
          section_path: ["Recommendation 10"],
          page_start: 34,
          page_end: 35,
          token_count: 60,
          text: "Enhanced measures should be applied where higher risks are identified.",
          chunk_index: 1,
        },
        {
          chunk_id: "c2",
          section_path: ["Recommendation 10"],
          page_start: 36,
          page_end: 36,
          token_count: 45,
          text: "Following context.",
          chunk_index: 2,
        },
      ],
    })
  ),

  http.delete(`${BASE}/documents/:docId`, () =>
    new HttpResponse(null, { status: 204 })
  ),

  http.post(`${BASE}/documents/:docId/reindex`, ({ params }) =>
    HttpResponse.json(
      { job_id: "job-reindex", doc_id: params.docId, status: "queued" },
      { status: 202 }
    )
  )
];

export const server = setupServer(...handlers);