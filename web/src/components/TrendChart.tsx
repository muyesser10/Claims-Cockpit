import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from "recharts";

interface TrendPoint {
  date: string;
  count: number;
}

interface TrendChartProps {
  trend: TrendPoint[];
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" });
}

export default function TrendChart({ trend }: TrendChartProps) {
  const data = trend.map((point) => ({ ...point, label: formatDate(point.date) }));

  return (
    <div className="p-4 rounded-lg border border-slate-200 bg-white">
      <h2 className="text-sm font-medium text-slate-700 mb-2">Son 7 Gün Trend</h2>
      {data.length === 0 ? (
        <p className="text-slate-500">Henüz veri yok.</p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Line type="monotone" dataKey="count" stroke="#2563eb" strokeWidth={2} dot />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}