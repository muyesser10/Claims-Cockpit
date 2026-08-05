import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authenticatedFetch } from "./auth";

export type DamageType =
  | "collision"
  | "single_vehicle"
  | "glass"
  | "hail"
  | "fire"
  | "theft"
  | "animal"
  | "other";

export interface IncidentLocation {
  city: string | null;
  district: string | null;
}

export interface SourceReference {
  quote: string;
  start: number | null;
  end: number | null;
}

export interface ClaimExtraction {
  policy_no: string | null;
  plate: string | null;
  incident_date: string | null;
  damage_type: DamageType | null;
  injury: boolean | null;
  counterparty_exists: boolean | null;
  estimated_amount: number | null;
  damage_description: string | null;
  incident_location: IncidentLocation;
  source_references: Record<string, SourceReference>;
}

export interface ValidationFlag {
  field: string;
  rule: string;
  message: string;
}

export interface ClaimData {
  masked_text: string;
  // Absent when extraction failed (step_extract's except path) — validation
  // never runs in that case either, so the two are always absent together.
  extraction?: ClaimExtraction;
  validation_flags?: ValidationFlag[];
}

export interface Claim {
  id: number;
  channel: string;
  content_type: string;
  urgency: "critical" | "high" | "normal";
  data: ClaimData;
  status: string;
  created_at: string;
}

export interface QueueResponse {
  total: number;
  items: Claim[];
}

async function fetchQueue(): Promise<QueueResponse> {
  const res = await authenticatedFetch("/api/queue");
  if (!res.ok) {
    throw new Error(`Failed to fetch queue: ${res.status}`);
  }
  return res.json();
}

export function useQueue() {
  return useQuery({
    queryKey: ["queue"],
    queryFn: fetchQueue,
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
  });
}

// Operator-supplied field corrections, keyed by extraction field name (dotted
// for nested fields, e.g. "incident_location.city") — see api/routers/queue.py's
// EDITABLE_FIELDS for the whitelist the backend enforces.
export type ClaimEdits = Record<string, unknown>;

async function approveClaim(id: number, edits?: ClaimEdits): Promise<Claim> {
  const res = await authenticatedFetch(`/api/queue/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(edits && Object.keys(edits).length > 0 ? { edits } : {}),
  });
  if (!res.ok) {
    throw new Error(`Failed to approve claim: ${res.status}`);
  }
  return res.json();
}

async function rejectClaim(id: number): Promise<Claim> {
  const res = await authenticatedFetch(`/api/queue/${id}/reject`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`Failed to reject claim: ${res.status}`);
  }
  return res.json();
}

// Her iki mutation da invalidateQueries'in promise'ini DÖNDÜRÜR (fire-and-forget
// değil). react-query önce buradaki onSuccess'i await eder, sonra mutate()
// çağrısına verilen onSuccess'i çalıştırır — böylece Queue.tsx "sıradaki kayıt"ı
// tazelenmiş liste üzerinden seçebiliyor, bir tur bayat veri görmüyor.
export function useApproveClaim() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, edits }: { id: number; edits?: ClaimEdits }) => approveClaim(id, edits),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });
}

export function useRejectClaim() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => rejectClaim(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });
}
