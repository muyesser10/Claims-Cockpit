import {useQuery} from "@tanstack/react-query";
import { authenticatedFetch } from "./auth";

interface Claim {
    id: number;
    channel: string;
    content_type: string;
    urgency: "critical" | "high" | "normal";
    data: Record<string, unknown>;
    status: string;
    created_at: string;
}

interface ClaimsResponse {
    total: number;
    items: Claim[];
}

async function fetchClaims(): Promise<ClaimsResponse> {
    const res = await authenticatedFetch("/api/claims");
    if (!res.ok) {
        throw new Error(`Failed to fetch claims: ${res.status}`);
    }
    return res.json();
}

export function useClaims() {
    return useQuery({
        queryKey: ["claims"],
        queryFn: fetchClaims,
        refetchInterval: 30000, // Refetch every 30 seconds
        refetchIntervalInBackground: false,
    });
}