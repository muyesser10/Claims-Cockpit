import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

interface UrgencyDonutProps {
  urgencyCounts: Record<string, number>;
}

const urgencyLabels: Record<string, string> = {
  critical: "Kritik",
  high: "Yüksek",
  normal: "Normal",
};

const urgencyColors: Record<string, string> = {
  critical: "#dc2626",
  high: "#f97316",
  normal: "#94a3b8",
};

export default function UrgencyDonut({ urgencyCounts }: UrgencyDonutProps) {
  const data = Object.entries(urgencyCounts).map(([urgency, count]) => ({
    name: urgencyLabels[urgency] ?? urgency,
    value: count,
    color: urgencyColors[urgency] ?? "#cbd5e1",
  }));

  if (data.length === 0) {
    return <p className="text-slate-500">Henüz veri yok.</p>;
  }

  return (
    <div className="p-4 rounded-lg border border-slate-200 bg-white">
      <h2 className="text-sm font-medium text-slate-700 mb-2">Aciliyet Dağılımı</h2>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80}>
            {data.map((entry) => (
              <Cell key={entry.name} fill={entry.color} />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}