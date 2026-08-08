import { BarChart3 } from "lucide-react";

export default function Metrics() {
  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Metrikler</h1>
      <div className="flex flex-col items-center justify-center gap-3 py-16 rounded-lg border border-slate-200 bg-white text-center">
        <BarChart3 className="h-8 w-8 text-slate-300" aria-hidden="true" />
        <p className="text-sm font-medium text-slate-600">Henüz veri yok</p>
        <p className="text-sm text-slate-400 max-w-sm">
          Haftalık kalite metrikleri (RAG puanlama koşuları tamamlanınca) burada
          görünecek.
        </p>
      </div>
    </div>
  );
}