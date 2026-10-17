import { apiFetch } from "./client";
import type {
  ApiSettings,
  ModelsSettings,
  PipelineSettings,
  ThresholdPreview,
} from "./types";

export async function getPipelineSettings(): Promise<PipelineSettings> {
  const { data } = await apiFetch<PipelineSettings>("/settings/pipeline");
  return data;
}

export async function updatePipelineSettings(
  patch: Partial<Omit<PipelineSettings, "is_override">>
): Promise<PipelineSettings> {
  const { data } = await apiFetch<PipelineSettings>("/settings/pipeline", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
  return data;
}

export async function previewThreshold(
  confidence_threshold: number,
  confidence_floor: number
): Promise<ThresholdPreview> {
  const { data } = await apiFetch<ThresholdPreview>(
    "/settings/pipeline/preview-threshold",
    {
      method: "POST",
      body: JSON.stringify({ confidence_threshold, confidence_floor }),
      timeoutMs: 120_000,
    }
  );
  return data;
}

export async function getModelsSettings(): Promise<ModelsSettings> {
  const { data } = await apiFetch<ModelsSettings>("/settings/models");
  return data;
}

export async function updateModelsSettings(patch: {
  llm_provider?: string;
  llm_model?: string;
  rerank_model?: string;
}): Promise<ModelsSettings> {
  const { data } = await apiFetch<ModelsSettings>("/settings/models", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
  return data;
}

export async function getApiSettings(): Promise<ApiSettings> {
  const { data } = await apiFetch<ApiSettings>("/settings/api");
  return data;
}

export async function regenerateApiKey(): Promise<{ api_key: string; warning: string }> {
  const { data } = await apiFetch<{ api_key: string; warning: string }>(
    "/settings/api/regenerate",
    { method: "POST" }
  );
  return data;
}