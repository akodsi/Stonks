interface RatioCardProps {
  label: string;
  value: number | null | undefined;
  peerValue?: number | null;
  format?: "number" | "percent" | "multiple" | "currency";
  higherIsBetter?: boolean; // for coloring vs peer
  decimals?: number;
  tooltip?: string;
  history?: (number | null)[]; // oldest → newest, same scale as `value`
}

function fmt(
  val: number | null | undefined,
  format: RatioCardProps["format"] = "number",
  decimals = 2
): string {
  if (val == null || !Number.isFinite(val)) return "—";
  switch (format) {
    case "percent":
      return `${(val * 100).toFixed(decimals)}%`;
    case "multiple":
      return `${val.toFixed(decimals)}x`;
    case "currency":
      return val >= 1e9
        ? `$${(val / 1e9).toFixed(1)}B`
        : `$${(val / 1e6).toFixed(0)}M`;
    default:
      return val.toFixed(decimals);
  }
}

/**
 * Inline SVG sparkline — 48x16, oldest-left newest-right.
 * Color: green if current > start (improving), red otherwise.
 * SVG beats Plotly for 8-point 48px sparklines (bundle + render cost).
 */
function Sparkline({
  points,
  higherIsBetter = true,
}: {
  points: (number | null)[];
  higherIsBetter?: boolean;
}) {
  const clean = points.filter((p): p is number => p != null && Number.isFinite(p));
  if (clean.length < 2) return null;

  const w = 48;
  const h = 16;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;

  const xs = clean.map((_, i) => (i / (clean.length - 1)) * w);
  const ys = clean.map((v) => h - ((v - min) / range) * h);

  const d =
    "M " +
    xs.map((x, i) => `${x.toFixed(2)},${ys[i].toFixed(2)}`).join(" L ");

  const start = clean[0];
  const end = clean[clean.length - 1];
  const improving = higherIsBetter ? end > start : end < start;
  const color = improving ? "#10b981" : "#ef4444";

  return (
    <svg
      width={w}
      height={h}
      className="mt-1 overflow-visible"
      aria-hidden="true"
    >
      <path d={d} fill="none" stroke={color} strokeWidth={1.25} />
      <circle
        cx={xs[xs.length - 1]}
        cy={ys[ys.length - 1]}
        r={1.6}
        fill={color}
      />
    </svg>
  );
}

export default function RatioCard({
  label,
  value,
  peerValue,
  format = "number",
  higherIsBetter = true,
  decimals = 2,
  tooltip,
  history,
}: RatioCardProps) {
  let peerColor = "text-slate-500";
  if (value != null && peerValue != null) {
    const better = higherIsBetter ? value > peerValue : value < peerValue;
    peerColor = better ? "text-emerald-400" : "text-red-400";
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-1">
      <span
        className="text-xs text-slate-500 uppercase tracking-wide flex items-center gap-1"
        title={tooltip}
      >
        {label}
        {tooltip && (
          <span
            className="text-slate-600 cursor-help"
            aria-label={tooltip}
            title={tooltip}
          >
            ⓘ
          </span>
        )}
      </span>
      <span className="text-xl font-semibold text-white">
        {fmt(value, format, decimals)}
      </span>
      {peerValue != null && (
        <span className={`text-xs ${peerColor}`}>
          Sector: {fmt(peerValue, format, decimals)}
        </span>
      )}
      {history && history.length >= 2 && (
        <Sparkline points={history} higherIsBetter={higherIsBetter} />
      )}
    </div>
  );
}
