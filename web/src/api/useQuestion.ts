import { useMutation } from "@tanstack/react-query";
import { authenticatedFetch } from "./auth";

export type AnswerMode = "sql" | "retrieval" | "hybrid";

export interface QuestionSource {
  claim_id: number;
  external_ref: string | null;
  snippet: string;
  score: number | null;
  // Nullable: Claim.urgency is nullable in the database, so a claim that never
  // made it past classification comes back without one. SourceChip falls back
  // to a neutral dot rather than indexing undefined.
  urgency: string | null;
  incident_date: string | null;
}

export interface QuestionResponse {
  question: string;
  answer: string | null;
  mode: AnswerMode;
  answerable: boolean;
  refusal_reason: string | null;
  sources: QuestionSource[];
  sql: string | null;
  row_count: number | null;
  duration_ms: number;
}

// Fallbacks for the statuses the api's /soru proxy can produce without a body
// worth showing. When it does send a Turkish `detail` — 503 and 504 both do —
// that message wins: it says which hop failed, and this file cannot know.
const STATUS_MESSAGES: Record<number, string> = {
  401: "Oturumunuz sona ermiş görünüyor, lütfen tekrar giriş yapın.",
  422: "Soru çok kısa veya çok uzun.",
  503: "Soru servisine ulaşılamıyor.",
  504: "Soru zaman aşımına uğradı, lütfen tekrar deneyin.",
};

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    // FastAPI puts a string under `detail` for an HTTPException and a list of
    // validation errors for a 422; only the string is worth showing an operator.
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Not JSON — fall through to the status message.
  }
  return STATUS_MESSAGES[res.status] ?? `Soru başarısız oldu (${res.status})`;
}

async function fetchAnswer(question: string): Promise<QuestionResponse> {
  const res = await authenticatedFetch("/api/soru", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }
  return res.json();
}

export function useQuestion() {
  // No retry: an answer costs 8-20 seconds and two or three LLM calls, so a
  // silent second attempt would double both and leave the operator watching a
  // spinner with no idea why. TanStack Query retries queries by default but not
  // mutations, which is the behaviour wanted here — stated so it stays that way.
  return useMutation({
    mutationFn: fetchAnswer,
    retry: false,
  });
}
