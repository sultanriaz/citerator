import { apiFetch } from "./client";
import type { EscalationRequest, EscalationResponse } from "./types";

export async function postEscalation(
  body: EscalationRequest
): Promise<EscalationResponse> {
  const { data } = await apiFetch<EscalationResponse>("/escalations", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return data;
}