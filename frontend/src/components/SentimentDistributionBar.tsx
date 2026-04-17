interface Props {
  positive: number;
  neutral: number;
  negative: number;
}

export default function SentimentDistributionBar({ positive, neutral, negative }: Props) {
  const total = positive + neutral + negative;
  if (total === 0) return null;

  const posPct = Math.round((positive / total) * 100);
  const neuPct = Math.round((neutral / total) * 100);
  const negPct = 100 - posPct - neuPct;

  return (
    <div className="space-y-1">
      <div className="flex h-2 rounded-full overflow-hidden gap-px">
        {posPct > 0 && (
          <div className="bg-emerald-500" style={{ width: `${posPct}%` }} />
        )}
        {neuPct > 0 && (
          <div className="bg-slate-600" style={{ width: `${neuPct}%` }} />
        )}
        {negPct > 0 && (
          <div className="bg-red-500" style={{ width: `${negPct}%` }} />
        )}
      </div>
      <div className="flex gap-3 text-xs text-slate-500">
        <span className="text-emerald-400">{positive} positive</span>
        <span>{neutral} neutral</span>
        <span className="text-red-400">{negative} negative</span>
      </div>
    </div>
  );
}
