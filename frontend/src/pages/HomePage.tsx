import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Spinner from "../components/Spinner";

interface Suggestion {
  symbol: string;
  name: string;
  sector: string;
  market_cap: number | null;
}

export default function HomePage() {
  const [symbol, setSymbol] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const navigate = useNavigate();
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const searchTickers = useCallback((q: string) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!q.trim()) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    timerRef.current = setTimeout(async () => {
      try {
        const r = await axios.get(`/api/ticker/search?q=${encodeURIComponent(q)}&limit=8`);
        setSuggestions(r.data);
        setShowSuggestions(r.data.length > 0);
        setHighlightIdx(-1);
      } catch {
        setSuggestions([]);
      }
    }, 300);
  }, []);

  function handleChange(val: string) {
    const upper = val.toUpperCase();
    setSymbol(upper);
    searchTickers(upper);
  }

  function selectSuggestion(s: Suggestion) {
    setSymbol(s.symbol);
    setShowSuggestions(false);
    navigate(`/ticker/${s.symbol}`);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!showSuggestions || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIdx((i) => (i < suggestions.length - 1 ? i + 1 : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIdx((i) => (i > 0 ? i - 1 : suggestions.length - 1));
    } else if (e.key === "Enter" && highlightIdx >= 0) {
      e.preventDefault();
      selectSuggestion(suggestions[highlightIdx]);
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  }

  async function handleIngest(e: React.FormEvent) {
    e.preventDefault();
    if (!symbol.trim()) return;

    const ticker = symbol.trim().toUpperCase();
    setLoading(true);
    setError("");
    setShowSuggestions(false);

    try {
      await axios.post(`/api/ticker/${ticker}/ingest`);
      navigate(`/ticker/${ticker}`);
    } catch (err: unknown) {
      const msg =
        axios.isAxiosError(err) && err.response?.data?.detail
          ? err.response.data.detail
          : "Ingestion failed. Check the ticker symbol.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6">
      <h1 className="text-3xl font-bold text-white">Analyze a Stock</h1>
      <p className="text-slate-400 text-sm">
        Enter a US equity ticker to view the tearsheet, or search for an already-ingested stock.
      </p>

      <div ref={wrapperRef} className="w-full max-w-sm relative">
        <form onSubmit={handleIngest} className="flex gap-3">
          <input
            type="text"
            value={symbol}
            onChange={(e) => handleChange(e.target.value)}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            onKeyDown={handleKeyDown}
            placeholder="AAPL"
            className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 uppercase"
          />
          <button
            type="submit"
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
          >
            {loading ? (
              <>
                <Spinner size="sm" className="text-white" />
                <span>Ingesting...</span>
              </>
            ) : (
              "Analyze"
            )}
          </button>
        </form>

        {/* Autocomplete dropdown */}
        {showSuggestions && (
          <div className="absolute z-20 mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg shadow-xl overflow-hidden">
            {suggestions.map((s, i) => (
              <button
                key={s.symbol}
                onClick={() => selectSuggestion(s)}
                className={`w-full text-left px-4 py-2.5 flex items-center gap-3 transition-colors ${
                  i === highlightIdx
                    ? "bg-slate-700"
                    : "hover:bg-slate-700/50"
                }`}
              >
                <span className="text-sm font-medium text-white w-16">
                  {s.symbol}
                </span>
                <span className="text-sm text-slate-400 flex-1 truncate">
                  {s.name}
                </span>
                {s.sector && (
                  <span className="text-xs text-slate-500">{s.sector}</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}
    </div>
  );
}
