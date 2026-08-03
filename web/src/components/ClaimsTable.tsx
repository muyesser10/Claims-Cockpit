// Only the fields this table renders are required here — `data` is never
// read, so it's typed loosely on purpose. That keeps this compatible with
// both useClaims.ts's Claim (Pano) and useQueue.ts's richer Claim (Kuyruk)
// without importing one hook's type into the other's caller.
interface Claim {
  id: number;
  channel: string;
  content_type: string;
  urgency: "critical" | "high" | "normal";
  data: unknown;
  status: string;
  created_at: string;
}

interface ClaimsTableProps {
  claims: Claim[];
  onRowClick?: (claim: Claim) => void;
  selectedId?: number;
}

const urgencyStyles: Record<Claim["urgency"], string> = {
  critical: "bg-red-100 text-red-800 border-l-4 border-red-600",
  high: "bg-orange-50 text-orange-800 border-l-4 border-orange-400",
  normal: "bg-white text-slate-700",
};

const urgencyLabels: Record<Claim["urgency"], string> = {
  critical: "Kritik",
  high: "Yüksek",
  normal: "Normal",
};

export default function ClaimsTable({ claims, onRowClick, selectedId }: ClaimsTableProps) {
  const sorted = [...claims].sort((a, b) => {
    const order = { critical: 0, high: 1, normal: 2 };
    return order[a.urgency] - order[b.urgency];
  });

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="text-left border-b border-slate-300">
          <th className="p-2">ID</th>
          <th className="p-2">Kanal</th>
          <th className="p-2">Aciliyet</th>
          <th className="p-2">Durum</th>
          <th className="p-2">Oluşturulma</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((claim) => (
          <tr
            key={claim.id}
            onClick={onRowClick ? () => onRowClick(claim) : undefined}
            className={`${urgencyStyles[claim.urgency]} ${onRowClick ? "cursor-pointer" : ""} ${
              claim.id === selectedId ? "ring-2 ring-inset ring-blue-500" : ""
            }`}
          >
            <td className="p-2">{claim.id}</td>
            <td className="p-2">{claim.channel}</td>
            <td className="p-2 font-semibold">
              {urgencyLabels[claim.urgency]}
            </td>
            <td className="p-2">{claim.status}</td>
            <td className="p-2">
              {new Date(claim.created_at).toLocaleString("tr-TR")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}