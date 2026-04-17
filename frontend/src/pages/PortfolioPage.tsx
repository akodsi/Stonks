import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import Plot from "react-plotly.js";
import Spinner from "../components/Spinner";

/* ── Types ─── */

interface Holding {
  id: number;
  symbol: string;
  name: string | null;
  sector: string | null;
  shares: number;
  cost_basis: number;
  avg_cost: number;
  current_price: number | null;
  market_value: number | null;
  gain_loss: number | null;
  gain_loss_pct: number | null;
  purchase_date: string | null;
  notes: string | null;
}

interface Allocation {
  symbol: string;
  market_value: number;
  weight: number;
}

interface Benchmark {
  symbol: string;
  return_pct: number;
  start_date: string;
  start_price: number;
  end_price: number;
}

interface Summary {
  total_cost: number;
  total_value: number;
  total_gain_loss: number;
  total_gain_loss_pct: number | null;
  holdings_count: number;
  allocations: Allocation[];
  benchmark: Benchmark | null;
}

interface Performance {
  dates: string[];
  portfolio_values: number[];
  benchmark_values: (number | null)[];
  benchmark_symbol: string;
}

/* ── Formatters ─── */

function fmtUsd(n: number | null) {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtPct(n: number | null) {
  if (n == null) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

function glColor(n: number | null) {
  if (n == null) return "text-slate-400";
  return n >= 0 ? "text-emerald-400" : "text-red-400";
}

/* ── Component ��── */

export default function PortfolioPage() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [loading, setLoading] = useState(true);

  // Add holding form
  const [showAdd, setShowAdd] = useState(false);
  const [addSymbol, setAddSymbol] = useState("");
  const [addShares, setAddShares] = useState("");
  const [addCost, setAddCost] = useState("");
  const [addDate, setAddDate] = useState("");
  const [addNotes, setAddNotes] = useState("");
  const [addError, setAddError] = useState("");

  // Sort
  const [sortField, setSortField] = useState<string>("market_value");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  async function fetchAll() {
    setLoading(true);
    try {
      const [h, s, p] = await Promise.all([
        axios.get("/api/portfolio/holdings"),
        axios.get("/api/portfolio/summary"),
        axios.get("/api/portfolio/performance?days=365"),
      ]);
      setHoldings(h.data);
      setSummary(s.data);
      setPerf(p.data);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchAll();
  }, []);

  async function addHolding() {
    if (!addSymbol || !addShares || !addCost) return;
    setAddError("");
    const shares = parseFloat(addShares);
    const cost = parseFloat(addCost);
    if (isNaN(shares) || shares <= 0) {
      setAddError("Shares must be a positive number.");
      return;
    }
    if (isNaN(cost) || cost <= 0) {
      setAddError("Cost basis must be a positive number.");
      return;
    }
    try {
      await axios.post("/api/portfolio/holdings", {
        symbol: addSymbol.toUpperCase(),
        shares,
        cost_basis: cost,
        purchase_date: addDate || null,
        notes: addNotes || null,
      });
      setAddSymbol("");
      setAddShares("");
      setAddCost("");
      setAddDate("");
      setAddNotes("");
      setShowAdd(false);
      fetchAll();
    } catch (err: unknown) {
      const msg = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setAddError(msg || "Failed to add holding.");
    }
  }

  async function deleteHolding(id: number) {
    try {
      await axios.delete(`/api/portfolio/holdings/${id}`);
      fetchAll();
    } catch {
      /* ignore */
    }
  }

  function toggleSort(field: string) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  const sorted = useMemo(() => {
    return [...holdings].sort((a, b) => {
      const av = (a as unknown as Record<string, unknown>)[sortField];
      const bv = (b as unknown as Record<string, unknown>)[sortField];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [holdings, sortField, sortDir]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  const COLS: { key: string; label: string }[] = [
    { key: "symbol", label: "Symbol" },
    { key: "shares", label: "Shares" },
    { key: "avg_cost", label: "Avg Cost" },
    { key: "current_price", label: "Price" },
    { key: "market_value", label: "Mkt Value" },
    { key: "gain_loss", label: "Gain/Loss" },
    { key: "gain_loss_pct", label: "Return" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Portfolio</h1>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          {showAdd ? "Cancel" : "+ Add Holding"}
        </button>
      </div>

      {/* ── Add holding form ── */}
      {showAdd && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
            Add Holding
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <input
              type="text"
              value={addSymbol}
              onChange={(e) => setAddSymbol(e.target.value.toUpperCase())}
              placeholder="Symbol"
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 uppercase"
            />
            <input
              type="number"
              step="any"
              value={addShares}
              onChange={(e) => setAddShares(e.target.value)}
              placeholder="Shares"
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500"
            />
            <input
              type="number"
              step="any"
              value={addCost}
              onChange={(e) => setAddCost(e.target.value)}
              placeholder="Total Cost ($)"
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500"
            />
            <input
              type="date"
              value={addDate}
              onChange={(e) => setAddDate(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
            />
            <input
              type="text"
              value={addNotes}
              onChange={(e) => setAddNotes(e.target.value)}
              placeholder="Notes (optional)"
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500"
            />
          </div>
          {addError && <p className="text-red-400 text-sm">{addError}</p>}
          <button
            onClick={addHolding}
            disabled={!addSymbol || !addShares || !addCost}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            Add
          </button>
        </div>
      )}

      {/* ── Summary cards ── */}
      {summary && summary.holdings_count > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase">Total Value</p>
            <p className="text-xl font-bold text-white mt-1">
              {fmtUsd(summary.total_value)}
            </p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase">Total Cost</p>
            <p className="text-xl font-bold text-slate-300 mt-1">
              {fmtUsd(summary.total_cost)}
            </p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase">Total P&L</p>
            <p className={`text-xl font-bold mt-1 ${glColor(summary.total_gain_loss)}`}>
              {fmtUsd(summary.total_gain_loss)}
            </p>
            <p className={`text-xs mt-0.5 ${glColor(summary.total_gain_loss_pct)}`}>
              {fmtPct(summary.total_gain_loss_pct)}
            </p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase">
              vs {summary.benchmark?.symbol ?? "SPY"}
            </p>
            {summary.benchmark ? (
              <>
                <p className={`text-xl font-bold mt-1 ${glColor(summary.benchmark.return_pct)}`}>
                  {fmtPct(summary.benchmark.return_pct)}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">
                  since {summary.benchmark.start_date}
                </p>
              </>
            ) : (
              <p className="text-sm text-slate-500 mt-1">No benchmark data</p>
            )}
          </div>
        </div>
      )}

      {/* ── Performance chart ── */}
      {perf && perf.dates.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Portfolio vs {perf.benchmark_symbol}
          </h2>
          <Plot
            data={[
              {
                x: perf.dates,
                y: perf.portfolio_values,
                type: "scatter" as const,
                mode: "lines" as const,
                name: "Portfolio",
                line: { color: "#3b82f6", width: 2 },
              },
              {
                x: perf.dates,
                y: perf.benchmark_values,
                type: "scatter" as const,
                mode: "lines" as const,
                name: perf.benchmark_symbol,
                line: { color: "#6b7280", width: 1.5, dash: "dot" },
              },
            ]}
            layout={{
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
              font: { color: "#94a3b8", size: 11 },
              margin: { t: 10, b: 40, l: 60, r: 20 },
              xaxis: { gridcolor: "#1e293b" },
              yaxis: {
                gridcolor: "#1e293b",
                tickprefix: "$",
                zeroline: false,
              },
              legend: { orientation: "h", y: -0.15 },
              height: 350,
            }}
            config={{ displayModeBar: false, responsive: true }}
            className="w-full"
          />
        </div>
      )}

      {/* ── Allocation pie chart ── */}
      {summary && summary.allocations.length > 1 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Allocation
          </h2>
          <Plot
            data={[
              {
                values: summary.allocations.map((a) => a.market_value),
                labels: summary.allocations.map((a) => a.symbol),
                type: "pie" as const,
                hole: 0.45,
                textinfo: "label+percent",
                textfont: { size: 11, color: "#e2e8f0" },
                marker: {
                  colors: [
                    "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
                    "#06b6d4", "#ec4899", "#14b8a6", "#f97316", "#6366f1",
                  ],
                },
              },
            ]}
            layout={{
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
              font: { color: "#94a3b8", size: 11 },
              margin: { t: 10, b: 10, l: 10, r: 10 },
              height: 280,
              showlegend: false,
            }}
            config={{ displayModeBar: false, responsive: true }}
            className="w-full"
          />
        </div>
      )}

      {/* ── Holdings table ── */}
      {holdings.length > 0 ? (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-800">
            <span className="text-sm text-slate-400">
              {holdings.length} holding{holdings.length !== 1 ? "s" : ""}
            </span>
          </div>
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
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {sorted.map((h) => (
                  <tr
                    key={h.id}
                    className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/ticker/${h.symbol}`}
                        className="text-blue-400 hover:underline font-medium"
                      >
                        {h.symbol}
                      </Link>
                      {h.name && (
                        <span className="text-xs text-slate-500 ml-2">
                          {h.name}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {h.shares.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {fmtUsd(h.avg_cost)}
                    </td>
                    <td className="px-4 py-3 text-white font-medium">
                      {fmtUsd(h.current_price)}
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {fmtUsd(h.market_value)}
                    </td>
                    <td className={`px-4 py-3 font-medium ${glColor(h.gain_loss)}`}>
                      {fmtUsd(h.gain_loss)}
                    </td>
                    <td className={`px-4 py-3 font-medium ${glColor(h.gain_loss_pct)}`}>
                      {fmtPct(h.gain_loss_pct)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => deleteHolding(h.id)}
                        className="text-xs text-slate-500 hover:text-red-400 transition-colors"
                      >
                        Remove
                      </button>
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
            No holdings yet. Click &quot;+ Add Holding&quot; to track your positions.
          </p>
          <p className="text-slate-600 text-xs mt-1">
            Make sure tickers are ingested from the Home page first.
          </p>
        </div>
      )}
    </div>
  );
}
