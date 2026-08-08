import { PlugZap } from "lucide-react";

import { useHealth } from "../api/useHealth";

// Görünürlük kuralı: yalnızca /health açıkça demo_offline=true derse çizilir.
// İstek henüz dönmediyse, hata verdiyse veya alan yoksa hiçbir şey gösterilmez
// — canlı bir sistemde yanlışlıkla "kayıtlı cevap" yazan bir bant, çevrimdışı
// demoda eksik bir banttan çok daha kötüdür.
//
// Kart idiom'u ErrorScreen'in compact varyantıyla aynı (ikon + iki satır),
// yalnızca renk ailesi amber: bu bir hata değil, bir çalışma kipi bildirimi.
export default function OfflineBadge() {
  const { data } = useHealth();

  if (!data?.demo_offline) {
    return null;
  }

  return (
    <div
      role="status"
      className="flex items-start gap-2 p-3 mb-4 rounded-lg border border-amber-300 bg-amber-50"
    >
      <PlugZap className="h-4 w-4 shrink-0 text-amber-700 mt-0.5" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-amber-900">
          Çevrimdışı Demo Modu — Kayıtlı Cevaplar Gösteriliyor
        </p>
        <p className="text-sm text-amber-800">
          Sınıflandırma, alan çıkarımı ve soru cevapları önceden kaydedilmiş yanıtlardan
          geliyor. Maskeleme, doğrulama, arama ve veritabanı sorguları gerçek çalışıyor.
        </p>
      </div>
    </div>
  );
}
