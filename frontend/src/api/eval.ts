import { apiFetch } from "./client";
import type { EvalLatest, EvalRunDetail, EvalRunsResponse } from "./types";

export async function getEvalLatest(): Promise<EvalLatest> {
  const { data } = await apiFetch<EvalLatest>("/eval/latest");
  return data;
}

export async function listEvalRuns(limit = 50, offset = 0): Promise<EvalRunsResponse> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const { data } = await apiFetch<EvalRunsResponse>(`/eval/runs?${qs}`);
  return data;
}

export async function getEvalRun(
  runId: string,
  category?: string
): Promise<EvalRunDetail> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  const { data } = await apiFetch<EvalRunDetail>(
    `/eval/runs/${encodeURIComponent(runId)}${qs}`
  );
  return data;
}

export async function startEvalRun(label?: string): Promise<{ run_id: string; status: string }> {
  const { data } = await apiFetch<{ run_id: string; status: string }>("/eval/runs", {
    method: "POST",
    body: JSON.stringify({ label: label ?? null }),
  });
  return data;
}