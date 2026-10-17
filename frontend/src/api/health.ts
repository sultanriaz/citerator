import { apiFetch } from "./client";
import type { HealthResponse } from "./types";

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await apiFetch<HealthResponse>("/health", {
    method: "GET",
    timeoutMs: 5_000,
  });
  return data;
}