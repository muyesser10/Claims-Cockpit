import { AlertCircle, RefreshCw } from "lucide-react";

interface ErrorScreenProps {
  /** Neyin başarısız olduğu — "Kuyruk yüklenemedi" gibi. */
  title?: string;
  /** Teknik detay: hata mesajı, durum kodu vb. */
  message: string;
  /** Verilmezse retry butonu hiç çizilmez (ör. tekrar denenecek bir şey yoksa). */
  onRetry?: () => void;
  retryLabel?: string;
  /** true: sayfanın bir bölümüne sığan küçük versiyon. */
  compact?: boolean;
}

// Paylaşılan hata gösterimi (S4-9). İki kullanımı var:
//   - compact=false → sayfanın tamamı çökmüş (Kuyruk, ErrorBoundary fallback'i)
//   - compact=true  → sayfanın tek bir bölümü çökmüş (Pano'nun iki bağımsız
//     sorgusu; biri patlarken diğeri veri göstermeye devam ediyor)
// Modal değil: sabit konumlu bir katman yerine sayfa akışında duran bir kart,
// projenin geri kalanıyla aynı Tailwind idiom'u (ShortcutHelp.tsx modal, bu değil).
//
// Retry metni bilerek iddiasız: React Query varsayılan olarak 3 deneme yapıyor,
// yani isError'a düşüldüğünde buton aslında 4. denemeyi tetikliyor. "Tekrar Dene"
// bunu olduğu gibi anlatıyor, düzeleceğine dair bir söz vermiyor.
export default function ErrorScreen({
  title = "Bir hata oluştu",
  message,
  onRetry,
  retryLabel = "Tekrar Dene",
  compact = false,
}: ErrorScreenProps) {
  // onRetry doğrudan onClick'e bağlanmıyor: React tıklama olayını argüman olarak
  // geçirir ve çağıranlar buraya çoğunlukla TanStack Query'nin refetch'ini veriyor
  // — refetch(event) ise olayı RefetchOptions sanır.
  const handleRetry = () => onRetry?.();

  if (compact) {
    return (
      <div
        role="alert"
        className="flex items-start gap-2 p-3 rounded-lg border border-slate-200 bg-white"
      >
        <AlertCircle className="h-4 w-4 shrink-0 text-red-600 mt-0.5" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-700">{title}</p>
          <p className="text-sm text-red-600 break-words">{message}</p>
          {onRetry && (
            <button
              type="button"
              onClick={handleRetry}
              className="mt-1 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              {retryLabel}
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div role="alert" className="flex justify-center py-10">
      <div className="w-full max-w-md p-4 rounded-lg border border-slate-200 bg-white text-center">
        <AlertCircle className="mx-auto mb-3 h-8 w-8 text-red-600" aria-hidden="true" />
        <h2 className="text-sm font-medium text-slate-700 mb-1">{title}</h2>
        <p className="text-sm text-red-600 mb-4 break-words">{message}</p>
        {onRetry && (
          <button
            type="button"
            onClick={handleRetry}
            className="inline-flex items-center gap-2 px-4 py-2 rounded bg-blue-600 text-white text-sm font-medium disabled:opacity-50"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {retryLabel}
          </button>
        )}
      </div>
    </div>
  );
}
