import { useState } from "react";
import { useQueue, useApproveClaim, useRejectClaim } from "../api/useQueue";
import type { ClaimEdits } from "../api/useQueue";
import ClaimsTable from "../components/ClaimsTable";
import QueueDetail from "../components/QueueDetail";

export default function Queue() {
  const { data, isLoading, isError, error } = useQueue();
  const approveClaim = useApproveClaim();
  const rejectClaim = useRejectClaim();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const items = data?.items ?? [];
  const selectedClaim = items.find((claim) => claim.id === selectedId) ?? null;

  function handleApprove(edits?: ClaimEdits) {
    if (!selectedClaim) return;
    approveClaim.mutate(
      { id: selectedClaim.id, edits },
      { onSuccess: () => setSelectedId(null) },
    );
  }

  function handleReject() {
    if (!selectedClaim) return;
    rejectClaim.mutate(selectedClaim.id, { onSuccess: () => setSelectedId(null) });
  }

  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Kuyruk</h1>

      {isLoading && <p className="text-slate-500">Yükleniyor...</p>}
      {isError && (
        <p className="text-red-600">
          Kuyruk yüklenemedi: {error instanceof Error ? error.message : "Bilinmeyen hata"}
        </p>
      )}

      {data && (
        <>
          <p className="text-slate-500 mb-2">Toplam {data.total} ihbar</p>
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="lg:w-[40%]">
              <ClaimsTable
                claims={items}
                onRowClick={(claim) => setSelectedId(claim.id)}
                selectedId={selectedClaim?.id}
              />
            </div>
            <div className="lg:w-[60%]">
              {selectedClaim ? (
                <QueueDetail
                  key={selectedClaim.id}
                  claim={selectedClaim}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  isSubmitting={approveClaim.isPending || rejectClaim.isPending}
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
    </div>
  );
}
