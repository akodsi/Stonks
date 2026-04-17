import Plot from "react-plotly.js";

interface TrendChartProps {
  dates: string[];
  series: { name: string; values: (number | null)[]; format?: "currency" | "percent" | "number" }[];
  title: string;
  height?: number;
}

function formatTick(val: number, format: string): string {
  if (format === "currency") {
    return val >= 1e9 ? `$${(val / 1e9).toFixed(1)}B` : `$${(val / 1e6).toFixed(0)}M`;
  }
  if (format === "percent") return `${(val * 100).toFixed(1)}%`;
  return String(val);
}

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

export default function TrendChart({ dates, series, title, height = 240 }: TrendChartProps) {
  const format = series[0]?.format ?? "number";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <h3 className="text-sm font-medium text-slate-300 mb-3">{title}</h3>
      <Plot
        data={series.map((s, i) => ({
          x: dates,
          y: s.values,
          type: "bar" as const,
          name: s.name,
          marker: { color: COLORS[i % COLORS.length] },
        }))}
        layout={{
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          margin: { t: 10, r: 10, b: 40, l: 70 },
          xaxis: { color: "#94a3b8", gridcolor: "#1e293b", tickfont: { size: 11 } },
          yaxis: {
            color: "#94a3b8",
            gridcolor: "#1e293b",
            tickfont: { size: 11 },
            tickformat: format === "percent" ? ".1%" : format === "currency" ? "$.3s" : undefined,
          },
          legend: { font: { color: "#94a3b8", size: 11 }, orientation: "h", y: -0.2 },
          barmode: "group",
          height,
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%" }}
      />
    </div>
  );
}
