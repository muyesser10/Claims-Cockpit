import { useQuery } from "@tanstack/react-query";
import { authenticatedFetch } from "./auth";

interface TrendPoint {
  date: string;
  count: number;
}

interface StatsResponse {
  urgency_counts: Record<string, number>;
  status_counts: Record<string, number>;
  city_counts: Record<string, number>;
  trend: TrendPoint[];
  last_claim_at: string | null;
}

async function fetchStats(): Promise<StatsResponse> {
  const res = await authenticatedFetch("/api/istatistik/ozet");
  if (!res.ok) {
    throw new Error(`Failed to fetch stats: ${res.status}`);
  }
  return res.json();
}

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  });
}