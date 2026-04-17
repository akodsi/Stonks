import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import Spinner from "../components/Spinner";

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Criterion {
  field: string;
  operator: string;
  value: number;
}

interface ScreenResult {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  ev_ebitda: number | null;
  gross_margin: number | null;
  operating_margin: number | null;
  net_margin: number | null;
  roe: number | null;
  revenue_growth: number | null;
  eps_growth: number | null;
  debt_to_equity: number | null;
  [key: string]: unknown;
}

interface SavedScreen {
  name: string;
  criteria: Criterion[];
}

/* ── Field options for dropdown ─────────────────────────────────────────── */

const FIELD_OPTIONS = [
  { label: "P/E Ratio", value: "pe_ratio" },
  { label: "P/B Ratio", value: "pb_ratio" },
  { label: "EV/EBITDA", value: "ev_ebitda" },
  { label: "P/FCF", value: "price_to_fcf" },
  { label: "P/Sales", value: "price_to_sales" },
  { label: "Gross Margin", value: "gross_margin" },
  { label: "Op. Margin", value: "operating_margin" },
  { label: "Net Margin", value: "net_margin" },
  { label: "ROE", value: "roe" },
  { label: "ROA", value: "roa" },
  { label: "ROIC", value: "roic" },
  { label: "Debt/Equity", value: "debt_to_equity" },
  { label: "Revenue Growth", value: "revenue_growth" },
  { label: "NI Growth", value: "net_income_growth" },
  { label: "EPS Growth", value: "eps_growth" },
  { label: "FCF Growth", value: "fcf_growth" },
];

const OPERATORS = ["<", "<=", ">", ">=", "=", "!="];
const PRESETS = ["value", "growth", "quality", "momentum", "dividend"];

const FIELD_LABEL: Record<string, string> = {};
FIELD_OPTIONS.forEach((f) => (FIELD_LABEL[f.value] = f.label));

/* ── Formatters ─────────────────────────────────────────────────────────── */

function fmtVal(val: unknown, field: string): string {
  if (val == null || !Number.isFinite(val as number)) return "—";
  const n = val as number;
  if (field === "market_cap") {
    return n >= 1e12 ? `$${(n / 1e12).toFixed(2)}T` : n >= 1e9 ? `$${(n / 1e9).toFixed(1)}B` : `$${(n / 1e6).toFixed(0)}M`;
  }
  if (field.includes("margin") || field.includes("growth") || field === "roe" || field === "roa" || field === "roic") {
    return `${(n * 100).toFixed(1)}%`;
  }
  return n.toFixed(2);
}

/* ── Component ─────────────────────────────────────────────────────────── */

export default function ScreenerPage() {
  const [results, setResults] = useState<ScreenResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activePreset, setActivePreset] = useState("");
  const [activeCriteria, setActiveCriteria] = useState<Criterion[]>([]);

  // Custom criteria builder state
  const [criteria, setCriteria] = useState<Criterion[]>([
    { field: "pe_ratio", operator: "<", value: 20 },
  ]);

  // Saved screens
  const [savedScreens, setSavedScreens] = useState<SavedScreen[]>([]);
  const [saveName, setSaveName] = useState("");
  const [showSaved, setShowSaved] = useState(false);

  // Sort state
  const [sortField, setSortField] = useState("symbol");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // Pagination state
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  /* ── Fetch helpers ─── */

  async function runPreset(preset: string) {
    setLoading(true);
    setError("");
    setActivePreset(preset);
    try {
      const r = await axios.get(`/api/screener/run?preset=${preset}`);
      setResults(r.data.results);
      setActiveCriteria(r.data.criteria);
      setPage(1);
    } catch (err: unknown) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(detail || "Screen failed.");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  async function runCustom() {
    if (criteria.length === 0) return;
    setLoading(true);
    setError("");
    setActivePreset("");
    try {
      const r = await axios.post("/api/screener/run", { criteria });
      setResults(r.data.results);
      setActiveCriteria(criteria);
      setPage(1);
    } catch (err: unknown) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(detail || "Screen failed.");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  async function fetchSaved() {
    try {
      const r = await axios.get("/api/screener/screens");
      setSavedScreens(r.data);
    } catch {
      /* ignore */
    }
  }

  async function saveCustom() {
    const name = saveName.trim();
    if (!name || criteria.length === 0) return;
    try {
      await axios.post("/api/screener/screens", { name, criteria });
      setSaveName("");
      fetchSaved();
    } catch {
      /* ignore */
    }
  }

  async function deleteSaved(name: string) {
    try {
      await axios.delete(`/api/screener/screens/${encodeURIComponent(name)}`);
      fetchSaved();
    } catch {
      /* ignore */
    }
  }

  function loadSaved(screen: SavedScreen) {
    setCriteria(screen.criteria);
    setShowSaved(false);
  }

  /* ── Criteria builder helpers ─── */

  function updateCriterion(i: number, patch: Partial<Criterion>) {
    setCriteria((prev) => prev.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  }

  function addCriterion() {
    setCriteria((prev) => [...prev, { field: "pe_ratio", operator: "<", value: 20 }]);
  }

  function removeCriterion(i: number) {
    setCriteria((prev) => prev.filter((_, idx) => idx !== i));
  }

  /* ── Sorting ─── */

  function toggleSort(field: string) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  }

  const sorted = useMemo(() => {
    return [...results].sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [results, sortField, sortDir]);

  /* ── Pagination ─── */

  const totalPages = Math.ceil(sorted.length / pageSize);
  const paginated = useMemo(
    () => sorted.slice((page - 1) * pageSize, page * pageSize),
    [sorted, page, pageSize]
  );

  /* ── CSV export ─── */

  function exportCsv() {
    if (sorted.length === 0) return;
    const cols = TABLE_COLS;
    const header = cols.map((c) => c.label).join(",");
    const rows = sorted.map((row) =>
      cols.map((c) => {
        const v = row[c.key];
        if (v == null) return "";
        if (typeof v === "string") return `"${v.replace(/"/g, '""')}"`;
        return String(v);
      }).join(",")
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `screener_results_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  /* ── Determine which columns to show ─── */

  const criteriaFields = activeCriteria.map((c) => c.field);
  const TABLE_COLS = [
    { key: "symbol", label: "Symbol" },
    { key: "name", label: "Name" },
    { key: "sector", label: "Sector" },
    { key: "market_cap", label: "Mkt Cap" },
    ...criteriaFields
      .filter((f) => !["symbol", "name", "sector", "market_cap"].includes(f))
      .map((f) => ({ key: f, label: FIELD_LABEL[f] || f })),
  ];

  /* ── Render ─── */

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Stock Screener</h1>

      {/* Preset buttons */}
      <div className="flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p}
            onClick={() => runPreset(p)}
            className={`px-4 py-2 rounded-lg text-sm font-medium capitalize transition-colors ${
              activePreset === p
                ? "bg-blue-600 text-white"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Custom criteria builder */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
            Custom Screen
          </h2>
          <div className="flex gap-2">
            <button
              onClick={() => { setShowSaved(!showSaved); if (!showSaved) fetchSaved(); }}
              className="text-xs text-slate-400 hover:text-white transition-colors"
            >
              {showSaved ? "Hide Saved" : "Saved Screens"}
            </button>
          </div>
        </div>

        {/* Saved screens dropdown */}
        {showSaved && (
          <div className="bg-slate-800 rounded-lg p-3 space-y-2">
            {savedScreens.length === 0 ? (
              <p className="text-xs text-slate-500">No saved screens yet.</p>
            ) : (
              savedScreens.map((s) => (
                <div key={s.name} className="flex items-center justify-between">
                  <button
                    onClick={() => loadSaved(s)}
                    className="text-sm text-blue-400 hover:underline"
                  >
                    {s.name}
                  </button>
                  <button
                    onClick={() => deleteSaved(s.name)}
                    className="text-xs text-slate-500 hover:text-red-400 transition-colors"
                  >
                    Delete
                  </button>
                </div>
              ))
            )}
          </div>
        )}

        {/* Criteria rows */}
        {criteria.map((c, i) => (
          <div key={i} className="flex gap-2 items-center">
            <select
              value={c.field}
              onChange={(e) => updateCriterion(i, { field: e.target.value })}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white flex-1"
            >
              {FIELD_OPTIONS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
            <select
              value={c.operator}
              onChange={(e) => updateCriterion(i, { operator: e.target.value })}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white w-20"
            >
              {OPERATORS.map((op) => (
                <option key={op} value={op}>
                  {op}
                </option>
              ))}
            </select>
            <input
              type="number"
              step="any"
              value={c.value}
              onChange={(e) => updateCriterion(i, { value: parseFloat(e.target.value) || 0 })}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white w-28"
            />
            <button
              onClick={() => removeCriterion(i)}
              className="text-slate-500 hover:text-red-400 text-sm px-2 transition-colors"
            >
              X
            </button>
          </div>
        ))}

        {/* Builder actions */}
        <div className="flex flex-wrap gap-3 items-center">
          <button
            onClick={addCriterion}
            className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
          >
            + Add Criterion
          </button>
          <button
            onClick={runCustom}
            disabled={loading || criteria.length === 0}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            {loading ? (<><Spinner size="sm" className="inline text-white" /> Running...</>) : "Run Screen"}
          </button>
          <div className="flex gap-2 items-center ml-auto">
            <input
              type="text"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="Screen name"
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white w-40 placeholder-slate-500"
            />
            <button
              onClick={saveCustom}
              disabled={!saveName.trim() || criteria.length === 0}
              className="text-sm text-slate-400 hover:text-white disabled:opacity-30 transition-colors"
            >
              Save
            </button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && <p className="text-red-400 text-sm">{error}</p>}

      {/* Results */}
      {results.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
            <span className="text-sm text-slate-400">
              {results.length} stock{results.length !== 1 ? "s" : ""} matched
            </span>
            <button
              onClick={exportCsv}
              className="text-xs text-slate-400 hover:text-white transition-colors"
            >
              Export CSV
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800">
                  {TABLE_COLS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => toggleSort(col.key)}
                      className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-300 transition-colors whitespace-nowrap"
                    >
                      {col.label}
                      {sortField === col.key && (
                        <span className="ml-1">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginated.map((row) => (
                  <tr
                    key={row.symbol}
                    className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
                  >
                    {TABLE_COLS.map((col) => (
                      <td key={col.key} className="px-4 py-3 whitespace-nowrap">
                        {col.key === "symbol" ? (
                          <Link
                            to={`/ticker/${row.symbol}`}
                            className="text-blue-400 hover:underline font-medium"
                          >
                            {row.symbol}
                          </Link>
                        ) : col.key === "name" ? (
                          <span className="text-white">{String(row.name ?? "")}</span>
                        ) : col.key === "sector" ? (
                          <span className="text-slate-400">{String(row.sector ?? "")}</span>
                        ) : (
                          <span className="text-slate-300">
                            {fmtVal(row[col.key], col.key)}
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination bar */}
          {totalPages > 1 && (
            <div className="px-5 py-3 border-t border-slate-800 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, sorted.length)} of {sorted.length}
              </span>
              <div className="flex items-center gap-3">
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
                  className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white"
                >
                  {[25, 50, 100].map((n) => (
                    <option key={n} value={n}>{n} / page</option>
                  ))}
                </select>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="text-xs text-slate-400 hover:text-white disabled:opacity-30 transition-colors"
                >
                  Prev
                </button>
                <span className="text-xs text-slate-400">
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="text-xs text-slate-400 hover:text-white disabled:opacity-30 transition-colors"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!loading && results.length === 0 && !error && (
        <p className="text-slate-500 text-sm text-center py-12">
          Run a preset or custom screen to see results. Make sure you&apos;ve ingested tickers from the Home page first.
        </p>
      )}
    </div>
  );
}
