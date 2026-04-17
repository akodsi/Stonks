import Plot from "react-plotly.js";

interface FCFvsSBCChartProps {
  dates: string[];
  fcf: (number | null)[];
  sbc: (number | null)[];
  height?: number;
}

function fmtUsd(v: number): string {
  if (v === 0) return "$0";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${v < 0 ? "-" : ""}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${v < 0 ? "-" : ""}$${(abs / 1e6).toFixed(0)}M`;
  return `${v < 0 ? "-" : ""}$${abs.toFixed(0)}`;
}

export default function FCFvsSBCChart({
  dates,
  fcf,
  sbc,
  height = 280,
}: FCFvsSBCChartProps) {
  // SBC stacks downward from zero so the visual dominance matches its economic
  // drag. FCF ex-SBC overlays as a line so the reader sees the true number.
  const sbcDownward = sbc.map((v) => (v == null ? null : -Math.abs(v)));
  const fcfExSbc = fcf.map((f, i) => {
    const s = sbc[i];
    if (f == null || s == null) return null;
    return f - s;
  });

  const hasAnySbc = sbc.some((v) => v != null && v !== 0);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-medium text-slate-300">
          FCF vs Stock-Based Compensation
        </h3>
      </div>
      <Plot
        data={[
          {
            x: dates,
            y: fcf,
            type: "bar",
            name: "GAAP FCF",
            marker: {
              color: fcf.map((v) =>
                v == null ? "#475569" : v >= 0 ? "#10b981" : "#ef4444"
              ),
            },
            hovertemplate: "GAAP FCF: %{y:$.2s}<extra></extra>",
          },
          {
            x: dates,
            y: sbcDownward,
            type: "bar",
            name: "SBC (shown as drag)",
            marker: { color: "#dc2626", opacity: 0.85 },
            customdata: sbc as (number | null)[],
            hovertemplate: "SBC: %{customdata:$.2s}<extra></extra>",
            visible: hasAnySbc ? true : "legendonly",
          },
          {
            x: dates,
            y: fcfExSbc,
            type: "scatter",
            mode: "lines+markers",
            name: "FCF ex-SBC",
            line: { color: "#f8fafc", width: 2 },
            marker: { color: "#f8fafc", size: 7 },
            hovertemplate: "FCF ex-SBC: %{y:$.2s}<extra></extra>",
          },
        ]}
        layout={{
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          margin: { t: 10, r: 10, b: 40, l: 70 },
          barmode: "relative",
          xaxis: { color: "#94a3b8", gridcolor: "#1e293b", tickfont: { size: 11 } },
          yaxis: {
            color: "#94a3b8",
            gridcolor: "#1e293b",
            zeroline: true,
            zerolinecolor: "#64748b",
            zerolinewidth: 1.5,
            tickformat: "$.3s",
            tickfont: { size: 11 },
          },
          legend: {
            font: { color: "#94a3b8", size: 10 },
            orientation: "h",
            y: -0.2,
          },
          height,
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%" }}
      />
      <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">
        SBC (stock-based compensation) is the value of shares issued to employees.
        GAAP FCF adds it back because it's non-cash — but the dilution is real.
        FCF ex-SBC{" "}
        {hasAnySbc ? (
          <span className="text-slate-300">
            = FCF − SBC shows cash available to shareholders after paying employees in full.
          </span>
        ) : (
          "is not available for this company."
        )}
      </p>
      {hasAnySbc &&
        fcfExSbc.some((v, i) => {
          const f = fcf[i];
          return v != null && f != null && v < 0 && f > 0;
        }) && (
          <p className="text-[11px] text-amber-400 mt-1">
            Heads up: FCF flips negative once SBC is subtracted in at least one year.
          </p>
        )}
    </div>
  );
}
