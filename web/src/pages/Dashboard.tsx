import { useClaims } from "../api/useClaims";
import { useStats } from "../api/useStats";
import ClaimsTable from "../components/ClaimsTable";
import StatCards from "../components/StatCards";
import UrgencyDonut from "../components/UrgencyDonut";
import CityBar from "../components/CityBar";
import TrendChart from "../components/TrendChart";
import Pulse from "../components/Pulse";
import ErrorScreen from "../components/ErrorScreen";
import OfflineBadge from "../components/OfflineBadge";

export default function Dashboard() {
  // İki bağımsız sorgu: biri patlarken diğeri veri göstermeye devam ediyor,
  // o yüzden hata gösterimi de bölüm bazında (compact) — tüm sayfayı kaplayan
  // bir hata ekranı çalışan yarıyı da gizlerdi.
  const { data, isLoading, isError, error, refetch } = useClaims();
  const {
    data: stats,
    isLoading: statsLoading,
    isError: statsIsError,
    error: statsError,
    refetch: refetchStats,
  } = useStats();

  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Pano</h1>

      {/* Çevrimdışı demoda görünür, aksi halde hiçbir şey çizmez. */}
      <OfflineBadge />

      {statsLoading && <p className="text-slate-500">İstatistikler yükleniyor...</p>}
      {statsIsError && (
        <div className="mb-4">
          <ErrorScreen
            compact
            title="İstatistikler yüklenemedi"
            message={statsError instanceof Error ? statsError.message : "Bilinmeyen hata"}
            onRetry={refetchStats}
          />
        </div>
      )}
      {stats && (
        <>
          <div className="mb-4">
            <Pulse lastClaimAt={stats.last_claim_at} />
          </div>
          <StatCards statusCounts={stats.status_counts} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <UrgencyDonut urgencyCounts={stats.urgency_counts} />
            <CityBar cityCounts={stats.city_counts} />
          </div>
          <div className="mb-6">
            <TrendChart trend={stats.trend} />
          </div>
        </>
      )}

      {isLoading && <p className="text-slate-500">Yükleniyor...</p>}
      {isError && (
        <ErrorScreen
          compact
          title="İhbarlar yüklenemedi"
          message={error instanceof Error ? error.message : "Bilinmeyen hata"}
          onRetry={refetch}
        />
      )}
      {data && (
        <>
          <p className="text-slate-500 mb-2">Toplam {data.total} ihbar</p>
          <ClaimsTable claims={data.items} />
        </>
      )}
    </div>
  );
}