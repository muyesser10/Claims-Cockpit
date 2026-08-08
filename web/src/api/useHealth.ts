import { useQuery } from "@tanstack/react-query";

export interface HealthResponse {
  status: string;
  service: string;
  demo_offline: boolean;
}

// Plain fetch, not authenticatedFetch: /health is deliberately unauthenticated
// (api/main.py), and the offline badge has to be readable before anyone logs
// in — a demo where the banner only appears after login is a banner nobody
// sees at the moment it matters.
async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch("/api/health");
  if (!res.ok) {
    throw new Error(`Failed to fetch health: ${res.status}`);
  }
  return res.json();
}

// No polling and no retry, unlike the data hooks. Whether the process is in
// offline mode is fixed for the life of that process, so re-asking buys
// nothing; and a failure here must stay silent — the badge is an extra, and a
// missing /health is not something to put in front of an operator.
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    retry: false,
    staleTime: Infinity,
  });
}
