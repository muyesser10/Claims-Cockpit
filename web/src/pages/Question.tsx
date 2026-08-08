import { useState } from "react";
import { useQuestion } from "../api/useQuestion";
import SourceChip from "../components/SourceChip";
import ErrorScreen from "../components/ErrorScreen";

const modeLabels: Record<string, string> = {
  sql: "SQL",
  retrieval: "Arama",
  hybrid: "Hibrit",
};

export default function Question() {
  const [input, setInput] = useState("");
  // Tekrar denerken input'taki metin değil, gerçekten sorulan soru gönderilmeli
  // — kullanıcı hata ekranını görürken kutuyu düzenlemiş olabilir.
  const [askedQuestion, setAskedQuestion] = useState<string | null>(null);
  const { mutate, data, isPending, isError, error } = useQuestion();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    const question = input.trim();
    setAskedQuestion(question);
    mutate(question);
  }

  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Soru</h1>

      <form onSubmit={handleSubmit} className="flex gap-2 mb-6">
        <input
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
          placeholder="Örn: Bu hafta kaç kritik ihbar geldi?"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button
          type="submit"
          disabled={isPending || !input.trim()}
          className="px-4 py-2 rounded bg-blue-600 text-white text-sm font-medium disabled:opacity-50"
        >
          Sor
        </button>
      </form>

      {isPending && (
        <p className="text-slate-500">Cevap hazırlanıyor, bu 8-20 saniye sürebilir...</p>
      )}

      {/* compact: form sayfanın asıl işi, hata onun altındaki cevap alanını
          kaplıyor — tam sayfa görünüm soru kutusunu gereksizce itelerdi. */}
      {isError && (
        <ErrorScreen
          compact
          title="Cevap alınamadı"
          message={error instanceof Error ? error.message : "Bilinmeyen hata"}
          onRetry={askedQuestion ? () => mutate(askedQuestion) : undefined}
        />
      )}

      {data && !data.answerable && (
        <div className="p-4 rounded-lg border border-slate-200 bg-slate-50">
          <p className="text-sm text-slate-600">{data.refusal_reason}</p>
        </div>
      )}

      {data && data.answerable && (
        <div>
          <div className="p-4 rounded-lg border border-slate-200 bg-white mb-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600">
                {modeLabels[data.mode] ?? data.mode}
              </span>
              <span className="text-xs text-slate-400">{(data.duration_ms / 1000).toFixed(1)} sn</span>
            </div>
            <p className="text-sm text-slate-800">{data.answer}</p>
            {data.sql && (
              <pre className="mt-3 p-2 rounded bg-slate-50 text-xs text-slate-500 overflow-x-auto">
                {data.sql}
              </pre>
            )}
            {data.row_count != null && (
              <p className="text-xs text-slate-400 mt-1">{data.row_count} kayıt</p>
            )}
          </div>

          <div>
            <h2 className="text-sm font-medium text-slate-700 mb-2">Kaynaklar</h2>
            {data.sources.length === 0 ? (
              <p className="text-slate-500 text-sm">Bu cevap için kaynak kayıt yok.</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {data.sources.map((source) => (
                  <SourceChip key={source.claim_id} source={source} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}