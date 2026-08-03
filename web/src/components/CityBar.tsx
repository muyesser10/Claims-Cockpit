import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface CityBarProps {
  cityCounts: Record<string, number>;
}

export default function CityBar({ cityCounts }: CityBarProps) {
  const data = Object.entries(cityCounts)
    .map(([city, count]) => ({ city, count }))
    .sort((a, b) => b.count - a.count);

  return (
    <div className="p-4 rounded-lg border border-slate-200 bg-white">
      <h2 className="text-sm font-medium text-slate-700 mb-2">İl Bazlı Dağılım</h2>
      {data.length === 0 ? (
        <p className="text-slate-500">Henüz şehir verisi yok.</p>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" allowDecimals={false} />
            <YAxis type="category" dataKey="city" width={80} />
            <Tooltip />
            <Bar dataKey="count" fill="#2563eb" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}