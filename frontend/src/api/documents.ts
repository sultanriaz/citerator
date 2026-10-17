import { apiFetch } from "./client";
import type {
  ChunkingStrategiesResponse,
  DocumentChunksResponse,
  DocumentsResponse,
  JobRow,
  ReindexResponse,
  UploadMeta,
  UploadResponse,
} from "./types";

export async function listDocuments(
  params: { limit?: number; offset?: number; status?: string } = {}
): Promise<DocumentsResponse> {
  const search = new URLSearchParams();
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  if (params.status) search.set("status", params.status);
  const qs = search.toString();
  const { data } = await apiFetch<DocumentsResponse>(
    `/documents${qs ? `?${qs}` : ""}`
  );
  return data;
}

export async function getDocumentChunks(
  docId: string
): Promise<DocumentChunksResponse> {
  const { data } = await apiFetch<DocumentChunksResponse>(
    `/documents/${encodeURIComponent(docId)}/chunks`
  );
  return data;
}

export async function uploadDocuments(
  files: File[],
  meta: UploadMeta = {}
): Promise<UploadResponse> {
  const form = new FormData();
  for (const f of files) {
    form.append("files", f, f.name);
  }
  if (meta.doc_type) form.append("doc_type", meta.doc_type);
  if (meta.jurisdiction) form.append("jurisdiction", meta.jurisdiction);
  if (meta.effective_date) form.append("effective_date", meta.effective_date);
  if (meta.visibility) form.append("visibility", meta.visibility);

  const { data } = await apiFetch<UploadResponse>("/documents/upload", {
    method: "POST",
    body: form,
    timeoutMs: 120_000,
  });
  return data;
}

export async function listJobs(params: { limit?: number; status?: string } = {}): Promise<JobRow[]> {
  const search = new URLSearchParams();
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.status) search.set("status", params.status);
  const qs = search.toString();
  const { data } = await apiFetch<JobRow[]>(`/documents/jobs${qs ? `?${qs}` : ""}`);
  return data;
}

export async function getJob(jobId: string): Promise<JobRow> {
  const { data } = await apiFetch<JobRow>(
    `/documents/jobs/${encodeURIComponent(jobId)}`
  );
  return data;
}

export async function retryJob(jobId: string): Promise<{ job_id: string; status: string }> {
  const { data } = await apiFetch<{ job_id: string; status: string }>(
    `/documents/jobs/${encodeURIComponent(jobId)}/retry`,
    { method: "POST" }
  );
  return data;
}

export async function deleteDocument(docId: string): Promise<void> {
  await apiFetch<void>(`/documents/${encodeURIComponent(docId)}`, {
    method: "DELETE",
  });
}

export async function reindexDocument(docId: string): Promise<ReindexResponse> {
  const { data } = await apiFetch<ReindexResponse>(
    `/documents/${encodeURIComponent(docId)}/reindex`,
    { method: "POST" }
  );
  return data;
}

export async function getChunkingStrategies(): Promise<ChunkingStrategiesResponse> {
  const { data } = await apiFetch<ChunkingStrategiesResponse>(
    "/documents/chunking-strategies"
  );
  return data;
}