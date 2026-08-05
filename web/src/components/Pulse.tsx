import { useEffect, useState } from "react";

interface PulseProps {
  lastClaimAt: string | null;
}

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.max(0, Math.floor(diffMs / 1000));

  if (diffSec < 60) return `${diffSec} saniye önce`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} dakika önce`;
  const diffHour = Math.floor(diffMin / 60);
  return `${diffHour} saat önce`;
}

export default function Pulse({ lastClaimAt }: PulseProps) {
  const [, setTick] = useState(0);

  // Re-render every second so the relative time stays live without
  // needing a new network request each time.
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center gap-2 p-4 rounded-lg border border-slate-200 bg-white">
      <span className="relative flex h-3 w-3">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500" />
      </span>
      <div>
        <p className="text-sm font-medium text-slate-700">Sistem canlı</p>
        <p className="text-xs text-slate-500">
          {lastClaimAt ? `Son ihbar: ${formatRelative(lastClaimAt)}` : "Henüz ihbar yok"}
        </p>
      </div>
    </div>
  );
}