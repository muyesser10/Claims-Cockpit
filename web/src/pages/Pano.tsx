import { useClaims } from "../api/useClaims";
import ClaimsTable from "../components/ClaimsTable";

export default function Pano() {
  const { data, isLoading, isError, error } = useClaims();

  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Pano</h1>

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