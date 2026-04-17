interface SkeletonProps {
  className?: string;
}

function SkeletonBlock({ className = "" }: SkeletonProps) {
  return (
    <div className={`animate-pulse rounded bg-slate-800 ${className}`} />
  );
}

export function SkeletonCard() {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-3">
      <SkeletonBlock className="h-3 w-24" />
      <SkeletonBlock className="h-6 w-16" />
      <SkeletonBlock className="h-3 w-20" />
    </div>
  );
}

export function SkeletonChart({ height = "h-64" }: { height?: string }) {
  return <SkeletonBlock className={`w-full ${height} rounded-lg`} />;
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }).map((_, i) => (
        <SkeletonBlock
          key={i}
          className={`h-3 ${i === lines - 1 ? "w-3/4" : "w-full"}`}
        />
      ))}
    </div>
  );
}

export default SkeletonBlock;
