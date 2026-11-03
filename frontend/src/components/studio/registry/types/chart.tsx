import { Cell, Legend, Pie, PieChart, ResponsiveContainer, BarChart, Bar, CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import type { DiagramNodeComponent } from "../definition";

type ChartPoint = { name: string; value: number };

function ChartNode({ data }: { data: { label?: string; chartType?: string; chartData?: ChartPoint[] } }) {
  const chartData = data.chartData ?? [];
  return (
    <div className="h-52 w-80 rounded-xl border border-line bg-white p-3 shadow-soft">
      <p className="mb-1 text-center text-xs font-semibold">{data.label ?? "Chart"}</p>
      <ResponsiveContainer width="100%" height="90%">
        {data.chartType === "pie" ? (
          <PieChart><Pie data={chartData} dataKey="value" nameKey="name" outerRadius={60}>{chartData.map((item, index) => <Cell key={item.name} fill={`hsl(${index * 55 + 160} 45% 45%)`} />)}</Pie><Legend /></PieChart>
        ) : data.chartType === "line" ? (
          <LineChart data={chartData}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis /><Tooltip /><Line type="monotone" dataKey="value" stroke="var(--accent)" /></LineChart>
        ) : (
          <BarChart data={chartData}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis /><Tooltip /><Bar dataKey="value" fill="var(--accent)" /></BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

export const ChartNodeComponent = ChartNode as DiagramNodeComponent;
