/**
 * TypeScript mirrors of the Citerator backend's response shapes.
 * If a backend field name drifts, fix it here.
 */

export type AnswerState = "confident" | "low_confidence" | "insufficient";

export interface Citation {
  chunk_id: string;
  doc_title: string;
  section_path: string[];
  page_start: number | null;
  page_end: number | null;
  source_file: string;
  excerpt: string;
}

export interface RetrievedChunk {
  chunk_id: string;
  doc_id: string;
  doc_hash: string;
  source_file: string;
  doc_title: string;
  doc_type: string;
  jurisdiction: string | null;
  effective_date: string | null;
  section_path: string[];
  page_start: number | null;
  page_end: number | null;
  char_start: number;
  char_end: number;
  text: string;
  token_count: number;
  embed_token_count: number;
  chunk_index: number;
  chunker: string;
  chunker_params: Record<string, unknown>;
  embedding_model?: string | null;
  ingested_at?: string | null;
  fused_score?: number | null;
  dense_score?: number | null;
  sparse_score?: number | null;
  rank?: number | null;
  rerank_score?: number | null;
  tenant_id?: string | null;
  owner_id?: string | null;
  visibility?: string | null;
  [key: string]: unknown;
}

export interface EscalationDraft {
  question: string;
  passages: RetrievedChunk[];
  suggested_note: string;
}

export interface LatencyMs {
  retrieve?: number;
  rerank?: number;
  generate?: number;
  total?: number;
  [key: string]: number | undefined;
}

export interface TokensUsed {
  input: number | null;
  output: number | null;
}

export interface RetrievalDetail {
  chunk_id: string;
  doc_title?: string;
  section_path?: string[];
  source_file?: string;
  dense_score?: number | null;
  sparse_score?: number | null;
  fused_score?: number | null;
  rerank_score?: number | null;
  used_in_answer?: boolean;
  [key: string]: unknown;
}

export interface QueryResponse {
  state: AnswerState;
  answer: string | null;
  confidence: number;
  citations: Citation[];
  related_passages: RetrievedChunk[];
  escalation_draft: EscalationDraft | null;
  latency_ms: LatencyMs;
  tokens: TokensUsed | null;
  retrieval_details: RetrievalDetail[] | null;
}

export interface QueryRequest {
  question: string;
  document_scope?: string[] | null;
  jurisdiction?: string | null;
  show_retrieval_details?: boolean;
}

export interface HealthResponse {
  status: string;
  collections: Record<string, number>;
}

export interface DocumentRow {
  doc_id: string;
  source_file: string;
  title: string | null;
  doc_type: string | null;
  jurisdiction: string | null;
  effective_date: string | null;
  page_count: number | null;
  chunk_count: number | null;
  doc_hash: string | null;
  chunker: string | null;
  chunker_params: Record<string, unknown> | null;
  embedder: string | null;
  sparse_embedder: string | null;
  status: string;
  warnings: string[];
  tenant_id?: string | null;
  owner_id?: string | null;
  visibility?: string | null;
  indexed_at: string | null;
  updated_at: string | null;
}

export interface DocumentsResponse {
  documents: DocumentRow[];
  count: number;
  limit: number;
  offset: number;
}

export interface ChunkRow {
  chunk_id: string | null;
  section_path: string[];
  page_start: number | null;
  page_end: number | null;
  token_count: number | null;
  text: string | null;
  chunk_index: number | null;
}

export interface DocumentChunksResponse {
  doc_id: string;
  count: number;
  chunks: ChunkRow[];
}

export type FeedbackRating = "up" | "down";

export interface FeedbackRequest {
  trace_id: string;
  rating: FeedbackRating;
  comment?: string;
}

export interface FeedbackResponse {
  id: number;
  trace_id: string;
  rating: FeedbackRating;
  comment: string | null;
  created_at: string;
}

export type EscalationSource = "escalated" | "flagged";
export type EscalationStatus = "open" | "acknowledged" | "resolved";

export interface EscalationPassage {
  chunk_id?: string | null;
  doc_title?: string | null;
  section_path?: string[] | null;
  page_start?: number | null;
  page_end?: number | null;
  excerpt?: string | null;
}

export interface EscalationRequest {
  trace_id?: string | null;
  source: EscalationSource;
  question: string;
  passages: EscalationPassage[];
  note: string;
}

export interface EscalationResponse {
  id: number;
  trace_id: string | null;
  source: EscalationSource;
  question: string;
  passages: EscalationPassage[];
  note: string;
  status: EscalationStatus;
  resolution_note: string | null;
  webhook_delivered: boolean;
  webhook_error: string | null;
  created_at: string;
  updated_at: string;
}
export interface JobRow {
  job_id: string;
  file_name: string;
  status: string;
  doc_id: string | null;
  error: string | null;
  warnings: string[];
  tenant_id?: string | null;
  owner_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadAcceptedItem {
  file_name: string;
  job_id: string;
}

export interface UploadResponse {
  accepted: UploadAcceptedItem[];
  count: number;
}

export interface UploadMeta {
  doc_type?: string;
  jurisdiction?: string;
  effective_date?: string;
  tenant_id?: string;
  owner_id?: string;
  visibility?: "tenant" | "public" | "private";
}

export interface ChunkingStrategyRow {
  chunker: string;
  document_count: number;
  total_chunk_count: number;
  avg_chunk_count: number;
  median_chunk_count: number;
  active: boolean;
  note: string;
}

export interface ChunkingStrategiesResponse {
  strategies: ChunkingStrategyRow[];
  active: string;
}

export interface ReindexResponse {
  job_id: string;
  doc_id: string;
  status: string;
}
export interface MetricPoint {
  value: number | null;
  delta_vs_previous: number | null;
  sparkline: number[];
}

export interface EvalSafety {
  refuse_pct: number | null;
  escalate_pct: number | null;
}

export interface EvalLatest {
  run_id: string;
  timestamp: string;
  label: string | null;
  question_count: number;
  metrics: Record<string, MetricPoint>;
  safety: EvalSafety;
}

export interface EvalRun {
  run_id: string;
  created_at: string;
  updated_at: string;
  status: string;
  label: string | null;
  question_set_path: string | null;
  chunking_strategy: string | null;
  embedder: string | null;
  sparse_embedder: string | null;
  rerank_model: string | null;
  llm_provider: string | null;
  llm_model: string | null;
  top_k_retrieve: number | null;
  top_k_rerank: number | null;
  confidence_threshold: number | null;
  confidence_floor: number | null;
  question_count: number;
  questions_completed: number;
  error: string | null;
  faithfulness_mean: number | null;
  answer_relevancy_mean: number | null;
  context_precision_mean: number | null;
  context_recall_mean: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  cost_per_query_usd_mean: number | null;
  safety_refuse_pct: number | null;
  safety_escalate_pct: number | null;
}

export interface EvalRunsResponse {
  runs: EvalRun[];
  count: number;
  limit: number;
  offset: number;
}

export interface EvalQuestionResult {
  id: number;
  run_id: string;
  question: string;
  category: string | null;
  expected_behavior: string | null;
  ground_truth: string | null;
  state: string | null;
  passed: boolean;
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  latency_ms: number | null;
  cost_usd: number | null;
  answer_text: string | null;
  retrieved_chunk_ids: string[];
  cited_chunk_ids: string[];
  error: string | null;
  retrieved_chunks?: Array<Record<string, unknown>>;
  cited_chunks?: Array<Record<string, unknown>>;
}

export interface EvalRunDetail {
  run: EvalRun;
  results: EvalQuestionResult[];
}

export interface PipelineSettings {
  active_chunking_strategy: string;
  top_k_retrieve: number;
  top_k_rerank: number;
  rerank_model: string;
  confidence_threshold: number;
  confidence_floor: number;
  is_override: Record<string, boolean>;
}

export interface ThresholdPreview {
  total: number;
  confident: number;
  low_confidence: number;
  insufficient: number;
  note: string;
}

export interface ModelsSettings {
  embedding_model: { value: string; editable: boolean; reason: string };
  llm_provider: string;
  llm_model: string;
  rerank_model: string;
  cost_privacy_note: string;
}

export interface EndpointEntry {
  method: string;
  path: string;
  description: string;
  example: string;
}

export interface ApiSettings {
  api_key_masked: string;
  endpoints: EndpointEntry[];
  rate_limit: { requests_per_minute: number; window_seconds: number };
}

export type UserRole = "admin" | "analyst" | "viewer";

export interface TenantContext {
  tenantId: string;
  tenantName: string;
  userId: string;
  userName: string;
  userRole: UserRole;
}

