import { useState, useEffect, useRef, useCallback } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import Spinner from "../components/Spinner";
import Plot from "react-plotly.js";

interface Suggestion {
  symbol: string;
  name: string;
  sector: string;
}

interface CompanyInfo {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  market_cap: number | null;
}

interface CompareData {
  companies: CompanyInfo[];
  ratios: Record<string, Record<string, number | null>>;
  price_series: Record<string, { dates: string[]; pct_change: number[] }>;
  sector_medians: Record<string, number | null>;
}

const RATIO_ROWS: { key: string; label: string; format: "pct" | "x"; higherIsBetter: boolean }[] = [
  { key: "pe_ratio", label: "P/E", format: "x", higherIsBetter: false },
  { key: "pb_ratio", label: "P/B", format: "x", higherIsBetter: false },
  { key: "ev_ebitda", label: "EV/EBITDA", format: "x", higherIsBetter: false },
  { key: "gross_margin", label: "Gross Margin", format: "pct", higherIsBetter: true },
  { key: "operating_margin", label: "Op. Margin", format: "pct", higherIsBetter: true },
  { key: "net_margin", label: "Net Margin", format: "pct", higherIsBetter: true },
  { key: "roe", label: "ROE", format: "pct", higherIsBetter: true },
  { key: "roa", label: "ROA", format: "pct", higherIsBetter: true },
  { key: "debt_to_equity", label: "Debt/Equity", format: "x", higherIsBetter: false },
  { key: "revenue_growth", label: "Rev Growth", format: "pct", higherIsBetter: true },
  { key: "eps_growth", label: "EPS Growth", format: "pct", higherIsBetter: true },
];

const COLORS = ["#3b82f6", "#10b981", "#f59e0b"];

function fmtRatio(val: number | null, format: "pct" | "x"): string {
  if (val == null || !Number.isFinite(val)) return "—";
  return format === "pct" ? `${(val * 100).toFixed(1)}%` : val.toFixed(2);
}

function fmtCap(n: number | null) {
  if (!n) return "—";
  return n >= 1e12 ? `$${(n / 1e12).toFixed(2)}T` : n >= 1e9 ? `$${(n / 1e9).toFixed(1)}B` : `$${(n / 1e6).toFixed(0)}M`;
}

/* ── Autocomplete input ─── */

function TickerInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (sym: string) => void;
  placeholder: string;
}) {
  const [query, setQuery] = useState(value);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [show, setShow] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShow(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function search(q: string) {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!q.trim()) { setSuggestions([]); setShow(false); return; }
    timerRef.current = setTimeout(async () => {
      try {
        const r = await axios.get(`/api/ticker/search?q=${encodeURIComponent(q)}&limit=6`);
        setSuggestions(r.data);
        setShow(r.data.length > 0);
      } catch { setSuggestions([]); }
    }, 300);
  }

  return (
    <div ref={wrapperRef} className="relative">
      <input
        type="text"
        value={query}
        onChange={(e) => { const v = e.target.value.toUpperCase(); setQuery(v); search(v); }}
        onFocus={() => suggestions.length > 0 && setShow(true)}
        placeholder={placeholder}
        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 uppercase"
      />
      {show && (
        <div className="absolute z-20 mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg shadow-xl overflow-hidden">
          {suggestions.map((s) => (
            <button
              key={s.symbol}
              onClick={() => { setQuery(s.symbol); onChange(s.symbol); setShow(false); }}
              className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-slate-700/50 transition-colors"
            >
              <span className="text-sm font-medium text-white w-14">{s.symbol}</span>
              <span className="text-xs text-slate-400 truncate">{s.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main component ─── */

export default function ComparePage() {
  const [symbols, setSymbols] = useState(["", "", ""]);
  const [data, setData] = useState<CompareData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function updateSymbol(idx: number, val: string) {
    setSymbols((prev) => prev.map((s, i) => (i === idx ? val : s)));
  }

  async function compare() {
    const valid = symbols.filter((s) => s.trim());
    if (valid.length < 2) { setError("Enter at least 2 tickers."); return; }
    setLoading(true);
    setError("");
    setData(null);
    try {
      const r = await axios.get(`/api/compare?symbols=${valid.join(",")}`);
      setData(r.data);
    } catch (err: unknown) {
      const msg = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(msg || "Comparison failed.");
    } finally {
      setLoading(false);
    }
  }

  // Find best value for a metric across symbols
  function bestSymbol(key: string, higherIsBetter: boolean): string | null {
    if (!data) return null;
    let best: string | null = null;
    let bestVal: number | null = null;
    for (const sym of Object.keys(data.ratios)) {
      const v = data.ratios[sym]?.[key];
      if (v == null || !Number.isFinite(v)) continue;
      if (bestVal === null || (higherIsBetter ? v > bestVal : v < bestVal)) {
        bestVal = v;
        best = sym;
      }
    }
    return best;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Compare Stocks</h1>

      <div className="flex flex-wrap gap-3 items-end">
        {symbols.map((s, i) => (
          <div key={i} className="w-40">
            <label className="text-xs text-slate-500 mb-1 block">
              Stock {i + 1}{i >= 2 ? " (optional)" : ""}
            </label>
            <TickerInput
              value={s}
              onChange={(val) => updateSymbol(i, val)}
              placeholder={["AAPL", "MSFT", "GOOG"][i]}
            />
          </div>
        ))}
        <button
          onClick={compare}
          disabled={loading || symbols.filter((s) => s.trim()).length < 2}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
        >
          {loading ? <><Spinner size="sm" className="text-white" /> Comparing...</> : "Compare"}
        </button>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {data && (
        <>
          {/* Company summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {data.companies.map((c, i) => (
              <div key={c.symbol} className="bg-slate-900 border border-slate-800 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[i] }} />
                  <Link to={`/ticker/${c.symbol}`} className="text-blue-400 hover:underline font-medium text-sm">
                    {c.symbol}
                  </Link>
                </div>
                <p className="text-white text-sm">{c.name}</p>
                <p className="text-xs text-slate-500">{c.sector} · {fmtCap(c.market_cap)}</p>
              </div>
            ))}
          </div>

          {/* Normalized price chart */}
          {Object.keys(data.price_series).length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Price Performance (% Change)
              </h2>
              <Plot
                data={data.companies.map((c, i) => {
                  const series = data.price_series[c.symbol];
                  return {
                    x: series?.dates ?? [],
                    y: series?.pct_change ?? [],
                    type: "scatter" as const,
                    mode: "lines" as const,
                    name: c.symbol,
                    line: { color: COLORS[i], width: 2 },
                  };
                })}
                layout={{
                  paper_bgcolor: "transparent",
                  plot_bgcolor: "transparent",
                  font: { color: "#94a3b8", size: 11 },
                  margin: { t: 10, b: 40, l: 50, r: 20 },
                  xaxis: { gridcolor: "#1e293b" },
                  yaxis: { gridcolor: "#1e293b", ticksuffix: "%", zeroline: true, zerolinecolor: "#334155" },
                  legend: { orientation: "h", y: -0.15 },
                  height: 350,
                }}
                config={{ displayModeBar: false, responsive: true }}
                className="w-full"
              />
            </div>
          )}

          {/* Side-by-side ratio table */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider px-5 py-3 border-b border-slate-800">
              Key Metrics Comparison
            </h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800">
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">
                    Metric
                  </th>
                  {data.companies.map((c, i) => (
                    <th key={c.symbol} className="px-4 py-3 text-right text-xs font-medium uppercase" style={{ color: COLORS[i] }}>
                      {c.symbol}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {RATIO_ROWS.map((row) => {
                  const best = bestSymbol(row.key, row.higherIsBetter);
                  return (
                    <tr key={row.key} className="border-b border-slate-800/50">
                      <td className="px-4 py-2.5 text-slate-400">{row.label}</td>
                      {data.companies.map((c) => {
                        const val = data.ratios[c.symbol]?.[row.key] ?? null;
                        const isBest = c.symbol === best;
                        return (
                          <td
                            key={c.symbol}
                            className={`px-4 py-2.5 text-right ${
                              isBest ? "text-emerald-400 font-medium" : "text-slate-300"
                            }`}
                          >
                            {fmtRatio(val, row.format)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!loading && !data && !error && (
        <p className="text-slate-500 text-sm text-center py-12">
          Enter 2-3 tickers above and click Compare.
        </p>
      )}
    </div>
  );
}
