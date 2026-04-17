interface SentimentBadgeProps {
  score: number | null | undefined;
  label?: string;
  size?: "sm" | "md" | "lg";
}

export default function SentimentBadge({ score, label, size = "sm" }: SentimentBadgeProps) {
  let bg = "bg-slate-700 text-slate-300";
  let text = label || "neutral";

  if (score != null && Number.isFinite(score)) {
    if (score > 0.15) {
      bg = "bg-emerald-900/60 text-emerald-400";
      text = label || "positive";
    } else if (score < -0.15) {
      bg = "bg-red-900/60 text-red-400";
      text = label || "negative";
    }
  }

  const sizeClass =
    size === "lg"
      ? "px-3 py-1.5 text-sm font-semibold"
      : size === "md"
        ? "px-2.5 py-1 text-xs font-medium"
        : "px-2 py-0.5 text-xs";

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full ${bg} ${sizeClass}`}>
      {score != null && Number.isFinite(score) && (
        <span className="font-mono">{score > 0 ? "+" : ""}{score.toFixed(2)}</span>
      )}
      <span className="capitalize">{text}</span>
    </span>
  );
}
