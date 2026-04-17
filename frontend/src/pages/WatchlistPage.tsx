import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import Spinner from "../components/Spinner";

interface WatchlistItem {
  symbol: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  added_at: string;
}

function fmtCap(n: number | null) {
  if (!n) return "—";
  return n >= 1e12
    ? `$${(n / 1e12).toFixed(2)}T`
    : n >= 1e9
    ? `$${(n / 1e9).toFixed(1)}B`
    : `$${(n / 1e6).toFixed(0)}M`;
}

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);

  async function fetchWatchlist() {
    setLoading(true);
    try {
      const r = await axios.get("/api/watchlist");
      setItems(r.data);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchWatchlist();
  }, []);

  async function remove(symbol: string) {
    try {
      await axios.delete(`/api/watchlist/${symbol}`);
      setItems((prev) => prev.filter((i) => i.symbol !== symbol));
    } catch {
      /* ignore */
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Watchlist</h1>

      {items.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-slate-500 text-sm">
            Your watchlist is empty. Add stocks from the tearsheet page using the star icon.
          </p>
        </div>
      ) : (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">
                  Symbol
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">
                  Sector
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">
                  Mkt Cap
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.symbol}
                  className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/ticker/${item.symbol}`}
                      className="text-blue-400 hover:underline font-medium"
                    >
                      {item.symbol}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-white">
                    {item.name ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-400">
                    {item.sector ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-300">
                    {fmtCap(item.market_cap)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => remove(item.symbol)}
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
      )}
    </div>
  );
}
