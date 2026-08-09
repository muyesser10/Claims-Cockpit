import { BarChart3, CheckCircle2, XCircle, MinusCircle } from "lucide-react";
import { useQuality } from "../api/useQuality";
import type { QualityMetric, QualityStatus } from "../api/useQuality";
import ErrorScreen from "../components/ErrorScreen";

// Sayı biçimlendirmesi burada, veride değil: API ham oran gönderiyor (0.9938),
// ekran Türkçe yazıma çeviriyor (%99,38). Böylece aynı rapor başka bir yerde
// başka bir biçimde gösterilebilir.
const percent = new Intl.NumberFormat("tr-TR", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 2,
});
const seconds = new Intl.NumberFormat("tr-TR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatValue(value: number | null, unit: string): string {
  if (value === null) return "—";
  return unit === "seconds" ? `${seconds.format(value)} sn` : percent.format(value);
}

function formatTarget(metric: QualityMetric): string {
  const sign = metric.target_operator === "gte" ? "≥" : "≤";
  return `${sign} ${formatValue(metric.target, metric.unit)}`;
}

const STATUS_STYLES: Record<QualityStatus, { label: string; className: string }> = {
  pass: { label: "Hedef tutuyor", className: "bg-green-50 text-green-700 border-green-200" },
  fail: { label: "Hedefin altında", className: "bg-red-50 text-red-700 border-red-200" },
  unmeasured: { label: "Ölçülmedi", className: "bg-slate-50 text-slate-500 border-slate-200" },
};

function StatusBadge({ status }: { status: QualityStatus }) {
  const { label, className } = STATUS_STYLES[status];
  const Icon = status === "pass" ? CheckCircle2 : status === "fail" ? XCircle : MinusCircle;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium ${className}`}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </span>
  );
}

function MetricCard({ metric }: { metric: QualityMetric }) {
  const { sample, source } = metric;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium text-slate-700">{metric.label}</h2>
        <StatusBadge status={metric.status} />
      </div>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-2xl font-semibold tabular-nums text-slate-800">
          {formatValue(metric.value, metric.unit)}
        </span>
        <span className="text-sm text-slate-400">hedef {formatTarget(metric)}</span>
        {metric.numerator !== null && metric.denominator !== null && (
          <span className="text-sm text-slate-400 tabular-nums">
            {metric.numerator}/{metric.denominator}
          </span>
        )}
      </div>

      {metric.breakdown.length > 0 && (
        <dl className="mt-3 space-y-1 border-t border-slate-100 pt-3">
          {metric.breakdown.map((item) => (
            <div key={item.label} className="flex justify-between gap-3 text-xs">
              <dt className="text-slate-500">{item.label}</dt>
              <dd className="shrink-0 tabular-nums text-slate-600">
                {formatValue(item.value, metric.unit)}
                {item.numerator !== null && item.denominator !== null && (
                  <span className="ml-1.5 text-slate-400">
                    ({item.numerator}/{item.denominator})
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {metric.notes.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-slate-100 pt-3">
          {metric.notes.map((note) => (
            <li key={note} className="text-xs leading-relaxed text-slate-500">
              {note}
            </li>
          ))}
        </ul>
      )}

      {/* Künye. Sekiz metrik farklı koşulardan ve farklı günlerden geliyor;
          tek bir "son güncelleme" tarihi bunu gizlerdi. */}
      <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-400">
        {sample.n !== null && `n=${sample.n} ${sample.unit}`}
        {sample.description && ` · ${sample.description}`}
        {source && ` · ${source.run}`}
        {source?.measured_at && ` · ${source.measured_at}`}
        {source?.model && ` · ${source.model}`}
      </p>
    </div>
  );
}

export default function Metrics() {
  const { data, isLoading, isError, error, refetch } = useQuality();

  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Metrikler</h1>

      {isLoading && <p className="text-slate-500">Kalite raporu yükleniyor...</p>}

      {isError && (
        <ErrorScreen
          title="Kalite raporu yüklenemedi"
          message={error instanceof Error ? error.message : "Bilinmeyen hata"}
          onRetry={refetch}
        />
      )}

      {/* Boş durum: rapor geldi ama içinde satır yok. Hata değil — henüz hiçbir
          eval koşusu yapılmamış demek. */}
      {data && data.metrics.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-3 py-16 rounded-lg border border-slate-200 bg-white text-center">
          <BarChart3 className="h-8 w-8 text-slate-300" aria-hidden="true" />
          <p className="text-sm font-medium text-slate-600">Henüz veri yok</p>
          <p className="text-sm text-slate-400 max-w-sm">
            Kalite metrikleri ilk eval koşusu tamamlanınca burada görünecek.
          </p>
        </div>
      )}

      {data && data.metrics.length > 0 && (
        <>
          <p className="mb-4 text-sm text-slate-500">
            CLAUDE.md §7 kalite hedefleri. {data.summary.total} metrikten{" "}
            <span className="font-medium text-green-700">{data.summary.passed}</span> tutuyor,{" "}
            <span className="font-medium text-red-700">{data.summary.failed}</span> tutmuyor,{" "}
            <span className="font-medium text-slate-600">{data.summary.unmeasured}</span> henüz
            ölçülmedi.
          </p>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {data.metrics.map((metric) => (
              <MetricCard key={metric.key} metric={metric} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
