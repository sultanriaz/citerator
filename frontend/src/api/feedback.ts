import { apiFetch } from "./client";
import type { FeedbackRequest, FeedbackResponse } from "./types";

export async function postFeedback(body: FeedbackRequest): Promise<FeedbackResponse> {
  const { data } = await apiFetch<FeedbackResponse>("/feedback", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return data;
}