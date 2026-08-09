import { useQuery } from "@tanstack/react-query";
import { authenticatedFetch } from "./auth";

// Şekil api/models/schemas.py'deki QualityReportOut ile birebir; o da
// eval/report.py'nin ürettiği quality_report.json'ı yansıtıyor. Tipler elle
// yazıldı çünkü repoda OpenAPI'dan tip üretimi kurulu değil (web/package.json'da
// `types` betiği yok, openapi-typescript bağımlılıklarda değil) ve diğer altı
// hook da aynı şeyi yapıyor — CLAUDE.md'nin kuralı henüz uygulanmamış durumda.

export type QualityStatus = "pass" | "fail" | "unmeasured";

export interface QualitySample {
  n: number | null;
  unit: string;
  description: string;
}

export interface QualitySource {
  run: string;
  measured_at: string | null;
  model: string | null;
}

export interface QualityBreakdown {
  label: string;
  value: number | null;
  numerator: number | null;
  denominator: number | null;
}

export interface QualityMetric {
  key: string;
  label: string;
  value: number | null;
  /** "ratio" → yüzde olarak gösterilir, "seconds" → süre olarak. */
  unit: string;
  target: number;
  target_operator: "gte" | "lte";
  status: QualityStatus;
  sample: QualitySample;
  source: QualitySource | null;
  numerator: number | null;
  denominator: number | null;
  breakdown: QualityBreakdown[];
  notes: string[];
}

export interface QualityReport {
  schema_version: number;
  generated_at: string;
  summary: { total: number; passed: number; failed: number; unmeasured: number };
  metrics: QualityMetric[];
}

async function fetchQuality(): Promise<QualityReport> {
  const res = await authenticatedFetch("/api/istatistik/kalite");
  if (!res.ok) {
    throw new Error(`Kalite raporu alınamadı: ${res.status}`);
  }
  return res.json();
}

// Diğer ekranların aksine polling yok. Rapor commit'lenmiş bir dosya; ancak yeni
// bir eval koşusu ve yeni bir image ile değişiyor, yani 30 saniyede bir sormak
// aynı baytları tekrar çekmek olurdu.
export function useQuality() {
  return useQuery({
    queryKey: ["quality"],
    queryFn: fetchQuality,
    staleTime: Infinity,
  });
}
