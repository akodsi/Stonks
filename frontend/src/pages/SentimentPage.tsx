import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import Spinner from "../components/Spinner";
import SentimentBadge from "../components/SentimentBadge";

/* ── Types ─── */

interface SentimentRow {
  symbol: string;
  name: string;
  sector: string | null;
  composite_score: number | null;
  composite_label: string;
  momentum: string;
  news_avg: number | null;
  news_count: number;
  reddit_avg: number | null;
  reddit_count: number;
  earnings_avg: number | null;
}

/* ── Helpers ─── */

function momentumBadge(m: string) {
  if (m === "improving") return "text-emerald-400 bg-emerald-400/10";
  if (m === "deteriorating") return "text-red-400 bg-red-400/10";
  return "text-slate-400 bg-slate-400/10";
}

function momentumArrow(m: string) {
  if (m === "improving") return "\u2191";
  if (m === "deteriorating") return "\u2193";
  return "\u2192";
}

/* ── Component ──�� */

export default function SentimentPage() {
  const [data, setData] = useState<SentimentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [sortField, setSortField] = useState("composite_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [sectorFilter, setSectorFilter] = useState("");

  async function fetchData(d: number) {
    setLoading(true);
    try {
      const r = await axios.get(`/api/ticker/sentiment/overview?days=${d}`);
      setData(r.data);
    } catch {
      setData([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData(days);
  }, [days]);

  // Extract unique sectors
  const sectors = useMemo(() => {
    const s = new Set<string>();
    data.forEach((r) => r.sector && s.add(r.sector));
    return Array.from(s).sort();
  }, [data]);

  // Filter + sort
  const filtered = useMemo(() => {
    let rows = data;
    if (sectorFilter) {
      rows = rows.filter((r) => r.sector === sectorFilter);
    }
    return [...rows].sort((a, b) => {
      const av = (a as unknown as Record<string, unknown>)[sortField];
      const bv = (b as unknown as Record<string, unknown>)[sortField];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [data, sectorFilter, sortField, sortDir]);

  function toggleSort(field: string) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  // Summary stats
  const avgComposite = useMemo(() => {
    const valid = data.filter((r) => r.composite_score != null);
    if (valid.length === 0) return null;
    return valid.reduce((sum, r) => sum + (r.composite_score ?? 0), 0) / valid.length;
  }, [data]);

  const improvingCount = data.filter((r) => r.momentum === "improving").length;
  const deterioratingCount = data.filter((r) => r.momentum === "deteriorating").length;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  const COLS: { key: string; label: string }[] = [
    { key: "symbol", label: "Symbol" },
    { key: "name", label: "Name" },
    { key: "sector", label: "Sector" },
    { key: "composite_score", label: "Composite" },
    { key: "momentum", label: "Momentum" },
    { key: "news_avg", label: "News" },
    { key: "news_count", label: "Articles" },
    { key: "reddit_avg", label: "Reddit" },
    { key: "reddit_count", label: "Posts" },
    { key: "earnings_avg", label: "Earnings" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Sentiment Overview</h1>

      {/* ── Controls ── */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex gap-1">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                days === d
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
        <select
          value={sectorFilter}
          onChange={(e) => setSectorFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white"
        >
          <option value="">All Sectors</option>
          {sectors.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <span className="text-xs text-slate-500 ml-auto">
          {filtered.length} ticker{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* ── Summary cards ── */}
      {data.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase">Market Avg</p>
            {avgComposite != null ? (
              <SentimentBadge score={avgComposite} size="lg" />
            ) : (
              <p className="text-slate-500 text-sm mt-1">—</p>
            )}
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase">Tracked</p>
            <p className="text-xl font-bold text-white mt-1">{data.length}</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase">Improving</p>
            <p className="text-xl font-bold text-emerald-400 mt-1">
              {improvingCount}
            </p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase">Deteriorating</p>
            <p className="text-xl font-bold text-red-400 mt-1">
              {deterioratingCount}
            </p>
          </div>
        </div>
      )}

      {/* ── Table ── */}
      {filtered.length > 0 ? (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800">
                  {COLS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => toggleSort(col.key)}
                      className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-300 transition-colors whitespace-nowrap"
                    >
                      {col.label}
                      {sortField === col.key && (
                        <span className="ml-1">
                          {sortDir === "asc" ? "\u25B2" : "\u25BC"}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <tr
                    key={row.symbol}
                    className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/ticker/${row.symbol}`}
                        className="text-blue-400 hover:underline font-medium"
                      >
                        {row.symbol}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-white text-xs">
                      {row.name}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">
                      {row.sector ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      {row.composite_score != null ? (
                        <SentimentBadge score={row.composite_score} size="sm" />
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${momentumBadge(row.momentum)}`}
                      >
                        {momentumArrow(row.momentum)} {row.momentum}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {row.news_avg != null ? (
                        <SentimentBadge score={row.news_avg} size="sm" />
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">
                      {row.news_count}
                    </td>
                    <td className="px-4 py-3">
                      {row.reddit_avg != null ? (
                        <SentimentBadge score={row.reddit_avg} size="sm" />
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">
                      {row.reddit_count}
                    </td>
                    <td className="px-4 py-3">
                      {row.earnings_avg != null ? (
                        <SentimentBadge score={row.earnings_avg} size="sm" />
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="text-center py-16">
          <p className="text-slate-500 text-sm">
            No sentiment data available. Ingest tickers from the Home page and refresh sentiment.
          </p>
        </div>
      )}
    </div>
  );
}
