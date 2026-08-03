interface StatCardsProps {
  statusCounts: Record<string, number>;
}

const statusLabels: Record<string, string> = {
  in_human_review: "İnceleme Bekliyor",
  approved: "Onaylandı",
  archived: "Reddedildi",
  dead_letter: "Hata",
  received: "Alındı",
  masked: "Maskelendi",
  classified: "Sınıflandırıldı",
};

export default function StatCards({ statusCounts }: StatCardsProps) {
  const entries = Object.entries(statusCounts);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
      <div className="p-4 rounded-lg border border-slate-200 bg-white">
        <p className="text-2xl font-semibold text-slate-900">{total}</p>
        <p className="text-sm text-slate-500">Toplam İhbar</p>
      </div>
      {entries.map(([status, count]) => (
        <div key={status} className="p-4 rounded-lg border border-slate-200 bg-white">
          <p className="text-2xl font-semibold text-slate-900">{count}</p>
          <p className="text-sm text-slate-500">{statusLabels[status] ?? status}</p>
        </div>
      ))}
    </div>
  );
}