import { useClaims } from "../api/useClaims";
import { useStats } from "../api/useStats";
import ClaimsTable from "../components/ClaimsTable";
import StatCards from "../components/StatCards";
import UrgencyDonut from "../components/UrgencyDonut";
import CityBar from "../components/CityBar";

export default function Dashboard() {
  const { data, isLoading, isError, error } = useClaims();
  const { data: stats, isLoading: statsLoading, isError: statsError } = useStats();

  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Pano</h1>

      {statsLoading && <p className="text-slate-500">İstatistikler yükleniyor...</p>}
      {statsError && <p className="text-red-600">İstatistikler yüklenemedi.</p>}
      {stats && (
        <>
          <StatCards statusCounts={stats.status_counts} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <UrgencyDonut urgencyCounts={stats.urgency_counts} />
            <CityBar cityCounts={stats.city_counts} />
          </div>
        </>
      )}

      {isLoading && <p className="text-slate-500">Yükleniyor...</p>}
      {isError && (
        <p className="text-red-600">
          İhbarlar yüklenemedi: {error instanceof Error ? error.message : "Bilinmeyen hata"}
        </p>
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