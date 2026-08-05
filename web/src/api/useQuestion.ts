import { useMutation } from "@tanstack/react-query";
import { authenticatedFetch } from "./auth";

export type AnswerMode = "sql" | "retrieval" | "hybrid";

export interface QuestionSource {
  claim_id: number;
  external_ref: string | null;
  snippet: string;
  score: number | null;
  urgency: "critical" | "high" | "normal";
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

// TODO(Çağrı, S3-2): swap this for a real POST /api/soru call once the
// endpoint lands. Contract frozen by Çağrı — see team message. Mock covers
// all three response shapes (retrieval with sources, sql with no sources,
// answerable=false).
async function fetchAnswer(question: string): Promise<QuestionResponse> {
  await new Promise((resolve) => setTimeout(resolve, 1500));

  const lower = question.toLowerCase();

  if (lower.includes("kaç") || lower.includes("sayı")) {
    return {
      question,
      answer: "Bu hafta toplam 12 kritik ihbar geldi.",
      mode: "sql",
      answerable: true,
      refusal_reason: null,
      sources: [],
      sql: "SELECT COUNT(*) FROM claims WHERE urgency = 'critical' AND created_at >= now() - interval '7 days'",
      row_count: 12,
      duration_ms: 4200,
    };
  }

  if (lower.includes("bilmiyorum") || lower.includes("imkansız")) {
    return {
      question,
      answer: null,
      mode: "retrieval",
      answerable: false,
      refusal_reason: "Bu soruyu mevcut verilerle yanıtlayamıyorum.",
      sources: [],
      sql: null,
      row_count: null,
      duration_ms: 6100,
    };
  }

  return {
    question,
    answer: "Son bir haftada İstanbul'da 3 çarpışma vakası bildirildi, ikisi kritik aciliyette.",
    mode: "hybrid",
    answerable: true,
    refusal_reason: null,
    sources: [
      {
        claim_id: 7,
        external_ref: "GT-000007",
        snippet: "aracima carptilar, plaka [PLATE_1]...",
        score: 0.87,
        urgency: "normal",
        incident_date: "2026-08-03",
      },
      {
        claim_id: 8,
        external_ref: null,
        snippet: "yarali var, ambulans cagirdik...",
        score: 0.74,
        urgency: "critical",
        incident_date: null,
      },
    ],
    sql: null,
    row_count: null,
    duration_ms: 9400,
  };
}

export function useQuestion() {
  return useMutation({
    mutationFn: fetchAnswer,
  });
}