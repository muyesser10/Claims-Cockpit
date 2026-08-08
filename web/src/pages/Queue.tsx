import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useQueue, useApproveClaim, useRejectClaim } from "../api/useQueue";
import type { ClaimEdits, QueueResponse } from "../api/useQueue";
import ClaimsTable from "../components/ClaimsTable";
import QueueDetail from "../components/QueueDetail";
import ShortcutHelp from "../components/ShortcutHelp";
import ErrorScreen from "../components/ErrorScreen";

// Reddi onaylama adımındayken "vazgeç" saymadığımız tuşlar: tek başına basılan
// modifier'lar. Aksi halde Shift+/ ile '?' yazarken Shift'in kendisi akışı bozardı.
const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock"]);

// Form elemanına yazarken kısayol tetiklenmemeli — operatörün "Hasar Açıklaması"na
// 'a' harfi yazabilmesi gerekiyor.
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT";
}

export default function Queue() {
  const { data, isLoading, isError, error, refetch } = useQueue();
  const { mutate: approveMutate, isPending: isApproving } = useApproveClaim();
  const { mutate: rejectMutate, isPending: isRejecting } = useRejectClaim();
  const queryClient = useQueryClient();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  // Reddin iki adımlı onayı QueueDetail'den buraya taşındı: 'r' tuşunun ikinci
  // basışını yönetebilmek için tuş durum makinesinin tamamı tek yerde olmalı.
  const [confirmingReject, setConfirmingReject] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  const items = data?.items ?? [];
  const selectedClaim = items.find((claim) => claim.id === selectedId) ?? null;
  // Seçili kayıt polling sırasında listeden düşmüş olabilir (başka bir operatör
  // işlemiş olabilir); kısayollar o durumda da kapanmalı, o yüzden selectedId
  // değil "listede hâlâ duran seçim" üzerinden çalışıyoruz.
  const activeId = selectedClaim?.id ?? null;
  const isSubmitting = isApproving || isRejecting;

  const selectClaim = useCallback((id: number | null) => {
    setSelectedId(id);
    setConfirmingReject(false);
  }, []);

  // Onay/ret sonrası çağrılır. useApproveClaim/useRejectClaim'in onSuccess'i
  // invalidateQueries promise'ini döndürdüğü için buraya gelindiğinde cache
  // tazelenmiştir — render'daki `items` bayat olacağından listeyi queryClient'tan
  // okuyoruz. Backend zaten "önce en acil, aciliyet içinde FIFO" sırasıyla
  // döndürdüğü için (api/routers/queue.py) kalanların ilki sıradaki iştir.
  const selectNextAfter = useCallback(
    (processedId: number) => {
      const fresh = queryClient.getQueryData<QueueResponse>(["queue"]);
      const next = fresh?.items.find((claim) => claim.id !== processedId);
      selectClaim(next ? next.id : null);
    },
    [queryClient, selectClaim],
  );

  const handleApprove = useCallback(
    (edits?: ClaimEdits) => {
      if (activeId === null) return;
      approveMutate({ id: activeId, edits }, { onSuccess: () => selectNextAfter(activeId) });
    },
    [activeId, approveMutate, selectNextAfter],
  );

  const submitReject = useCallback(() => {
    if (activeId === null) return;
    setConfirmingReject(false);
    rejectMutate(activeId, { onSuccess: () => selectNextAfter(activeId) });
  }, [activeId, rejectMutate, selectNextAfter]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      // Ctrl+A / Cmd+A gibi tarayıcı kısayollarını ele geçirme.
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;

      // '?' seçimden bağımsız çalışır: kuyruk boşken de yardım açılabilsin ve
      // açık kalan overlay her durumda kapatılabilsin.
      if (event.key === "?") {
        event.preventDefault();
        setShowHelp((prev) => !prev);
        return;
      }
      if (showHelp) {
        // Yardım açıkken modal gibi davranır, eylem tuşları geçmez.
        if (event.key === "Escape") {
          event.preventDefault();
          setShowHelp(false);
        }
        return;
      }

      // Eylem kısayolları yalnızca seçili kayıt varken ve bekleyen istek yokken
      // (çift gönderim olmasın diye) çalışır.
      if (activeId === null || isSubmitting) return;

      if (confirmingReject) {
        // İkinci adım: 'r' veya Enter reddi onaylar, diğer her tuş vazgeçer.
        if (event.key === "r" || event.key === "R" || event.key === "Enter") {
          event.preventDefault();
          submitReject();
        } else if (!MODIFIER_KEYS.has(event.key)) {
          event.preventDefault();
          setConfirmingReject(false);
        }
        return;
      }

      if (event.key === "a" || event.key === "A") {
        event.preventDefault();
        // Kısayolla onay HIZLI onaydır: QueueDetail formundaki düzenlemeler
        // gönderilmez, kayıt geldiği gibi onaylanır. Alan düzeltecek operatör
        // zaten forma girip mouse ile "Onayla"ya basıyor.
        handleApprove();
      } else if (event.key === "r" || event.key === "R") {
        event.preventDefault();
        // İlk adım — UI'daki "Reddet" butonuna basmakla aynı.
        setConfirmingReject(true);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeId, isSubmitting, confirmingReject, showHelp, handleApprove, submitReject]);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Kuyruk</h1>
        <button
          type="button"
          onClick={() => setShowHelp(true)}
          className="text-xs text-slate-500 underline hover:text-slate-700"
        >
          Kısayollar: a = Onayla · r = Reddet · ? = Yardım
        </button>
      </div>

      {isLoading && <p className="text-slate-500">Yükleniyor...</p>}
      {isError && (
        <ErrorScreen
          title="Kuyruk yüklenemedi"
          message={error instanceof Error ? error.message : "Bilinmeyen hata"}
          onRetry={refetch}
        />
      )}

      {data && items.length === 0 && (
        <p className="text-slate-500 p-4 rounded-lg border border-slate-200 bg-white">
          Kuyruk boş — onay bekleyen ihbar yok.
        </p>
      )}

      {data && items.length > 0 && (
        <>
          <p className="text-slate-500 mb-2">Toplam {data.total} ihbar</p>
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="lg:w-[40%]">
              <ClaimsTable
                claims={items}
                onRowClick={(claim) => selectClaim(claim.id)}
                selectedId={selectedClaim?.id}
              />
            </div>
            <div className="lg:w-[60%]">
              {selectedClaim ? (
                <QueueDetail
                  key={selectedClaim.id}
                  claim={selectedClaim}
                  onApprove={handleApprove}
                  onReject={submitReject}
                  isSubmitting={isSubmitting}
                  confirmingReject={confirmingReject}
                  onConfirmingRejectChange={setConfirmingReject}
                />
              ) : (
                <p className="text-slate-500 p-4 rounded-lg border border-slate-200 bg-white">
                  Bir ihbar seçin.
                </p>
              )}
            </div>
          </div>
        </>
      )}

      {showHelp && <ShortcutHelp onClose={() => setShowHelp(false)} />}
    </div>
  );
}
