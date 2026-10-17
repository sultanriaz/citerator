import { apiFetch, type ApiResult } from "./client";
import type { QueryRequest, QueryResponse } from "./types";

export function postQuery(body: QueryRequest): Promise<ApiResult<QueryResponse>> {
  return apiFetch<QueryResponse>("/query", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 90_000,
  });
}