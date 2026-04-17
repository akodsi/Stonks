import { useEffect, useState, useRef, useCallback } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import PriceChart from "../components/PriceChart";
import RatioCard from "../components/RatioCard";
import TrendChart from "../components/TrendChart";
import FCFvsSBCChart from "../components/FCFvsSBCChart";
import SentimentSection from "../components/SentimentSection";
import type { SentimentData } from "../components/SentimentSection";
import NarrativeSection from "../components/NarrativeSection";
import { SkeletonCard, SkeletonChart, SkeletonText } from "../components/SkeletonBlock";
import ExportButton from "../components/ExportButton";
import { RATIO_TOOLTIPS } from "../components/ratioTooltips";

interface Company {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  market_cap: number;
  description: string;
  website: string;
}

interface PriceSnapshot {
  price: number;
  high_52w: number;
  low_52w: number;
}

interface Ratio {
  period_date: string;
  pe_ratio: number | null;
  pb_ratio: number | null;
  ev_ebitda: number | null;
  price_to_fcf: number | null;
  price_to_sales: number | null;
  gross_margin: number | null;
  operating_margin: number | null;
  net_margin: number | null;
  roe: number | null;
  roa: number | null;
  roic: number | null;
  debt_to_equity: number | null;
  revenue_growth: number | null;
  eps_growth: number | null;
  fcf_growth: number | null;
  fcf_margin: number | null;
  fcf_margin_ex_sbc: number | null;
  sbc_to_revenue: number | null;
  interest_coverage: number | null;
  debt_incl_leases_to_equity: number | null;
  net_dilution_to_revenue: number | null;
}

interface FinancialRow {
  period_date: string;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  eps_diluted: number | null;
  free_cash_flow: number | null;
  total_debt: number | null;
  sbc?: number | null;
}

interface SectorMedians {
  sector: string;
  peer_count: number;
  pe_ratio?: number | null;
  pb_ratio?: number | null;
  ev_ebitda?: number | null;
  price_to_fcf?: number | null;
  price_to_sales?: number | null;
  gross_margin?: number | null;
  operating_margin?: number | null;
  net_margin?: number | null;
  roe?: number | null;
  roa?: number | null;
  roic?: number | null;
  debt_to_equity?: number | null;
  revenue_growth?: number | null;
  net_income_growth?: number | null;
  eps_growth?: number | null;
  fcf_growth?: number | null;
}

interface Tearsheet {
  company: Company;
  price_snapshot: PriceSnapshot;
  ratios: Ratio[];
  financials_trend: FinancialRow[];
  sector_medians: SectorMedians;
}

function fmtCap(n: number | null) {
  if (!n) return "—";
  return n >= 1e12 ? `$${(n / 1e12).toFixed(2)}T` : n >= 1e9 ? `$${(n / 1e9).toFixed(1)}B` : `$${(n / 1e6).toFixed(0)}M`;
}

/* ── Section nav config ─── */

const SECTIONS = [
  { id: "price", label: "Price" },
  { id: "valuation", label: "Valuation" },
  { id: "profitability", label: "Profitability" },
  { id: "growth", label: "Growth" },
  { id: "trends", label: "Trends" },
  { id: "sentiment", label: "Sentiment" },
  { id: "ai-analysis", label: "AI Analysis" },
  { id: "about", label: "About" },
];

/* ── Skeleton loading state ─── */

function TearsheetSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex justify-between">
        <div className="space-y-2">
          <div className="animate-pulse bg-slate-800 h-7 w-64 rounded" />
          <div className="animate-pulse bg-slate-800 h-4 w-40 rounded" />
        </div>
        <div className="animate-pulse bg-slate-800 h-10 w-28 rounded" />
      </div>
      <SkeletonChart height="h-72" />
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} />)}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SkeletonChart height="h-48" />
        <SkeletonChart height="h-48" />
      </div>
      <SkeletonText lines={4} />
    </div>
  );
}

/* ── Component ─── */

export default function TickerPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const [data, setData] = useState<Tearsheet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sentiment, setSentiment] = useState<SentimentData | null>(null);
  const [inWatchlist, setInWatchlist] = useState(false);
  const [activeSection, setActiveSection] = useState("price");
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    setError("");
    axios
      .get<Tearsheet>(`/api/ticker/${symbol}/tearsheet`)
      .then((r) => setData(r.data))
      .catch((err) => {
        const detail = err.response?.data?.detail || err.message;
        setError(detail || `No data for ${symbol}. Go home and ingest it first.`);
      })
      .finally(() => setLoading(false));
    // Fetch sentiment separately (non-blocking)
    axios
      .get<SentimentData>(`/api/ticker/${symbol}/sentiment`)
      .then((r) => setSentiment(r.data))
      .catch(() => setSentiment(null));
    // Check watchlist status
    axios
      .get<{ in_watchlist: boolean }>(`/api/watchlist/${symbol}`)
      .then((r) => setInWatchlist(r.data.in_watchlist))
      .catch(() => setInWatchlist(false));
  }, [symbol]);

  // IntersectionObserver for active section highlight
  useEffect(() => {
    if (loading || !data) return;

    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id);
          }
        }
      },
      { rootMargin: "-80px 0px -60% 0px" }
    );

    SECTIONS.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observerRef.current!.observe(el);
    });

    return () => observerRef.current?.disconnect();
  }, [loading, data]);

  function refreshSentiment() {
    if (!symbol) return;
    axios
      .get<SentimentData>(`/api/ticker/${symbol}/sentiment`)
      .then((r) => setSentiment(r.data))
      .catch(() => setSentiment(null));
  }

  const toggleWatchlist = useCallback(async () => {
    if (!symbol) return;
    try {
      if (inWatchlist) {
        await axios.delete(`/api/watchlist/${symbol}`);
        setInWatchlist(false);
      } else {
        await axios.post(`/api/watchlist/${symbol}`);
        setInWatchlist(true);
      }
    } catch {
      /* ignore */
    }
  }, [symbol, inWatchlist]);

  if (loading) return <TearsheetSkeleton />;
  if (error) return <p className="text-red-400">{error}</p>;
  if (!data) return null;

  const { company, price_snapshot: ps, ratios, financials_trend: ft, sector_medians: sm } = data;
  const latest = ratios[0] ?? ({} as Ratio);
  const dates = ft.map((r) => r.period_date.slice(0, 4));

  // Ratios are returned newest-first; sparklines read oldest-first.
  // Slice to trailing 8 periods to keep the mini-chart scale readable.
  const ratiosOldestFirst = [...ratios].reverse().slice(-8);
  const history = (key: keyof Ratio): (number | null)[] =>
    ratiosOldestFirst.map((r) => (r[key] as number | null) ?? null);

  // 52w range position (0–100%)
  const range52Pct =
    ps.high_52w && ps.low_52w && ps.price
      ? ((ps.price - ps.low_52w) / (ps.high_52w - ps.low_52w)) * 100
      : null;

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-white">
              {company.name}{" "}
              <span className="text-slate-400 font-normal text-base">
                {symbol}
              </span>
            </h1>
            <button
              onClick={toggleWatchlist}
              title={inWatchlist ? "Remove from watchlist" : "Add to watchlist"}
              className="text-xl transition-colors hover:scale-110"
            >
              {inWatchlist ? (
                <span className="text-yellow-400">&#9733;</span>
              ) : (
                <span className="text-slate-600 hover:text-yellow-400">&#9734;</span>
              )}
            </button>
          </div>
          <p className="text-slate-400 text-sm mt-1">
            {company.sector} · {company.industry} · {fmtCap(company.market_cap)}
          </p>
        </div>
        <div className="text-right flex flex-col items-end gap-2">
          <p className="text-3xl font-bold text-white">
            {ps.price ? `$${ps.price.toFixed(2)}` : "—"}
          </p>
          {range52Pct !== null && (
            <p className="text-xs text-slate-500">
              52w ${ps.low_52w?.toFixed(2)} — ${ps.high_52w?.toFixed(2)}
            </p>
          )}
          <ExportButton
            symbol={symbol!}
            sectionIds={["price", "valuation", "profitability", "growth", "trends", "sentiment", "ai-analysis"]}
          />
        </div>
      </div>

      {/* 52w range bar */}
      {range52Pct !== null && (
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500 w-16">52w Low</span>
          <div className="flex-1 h-1.5 bg-slate-800 rounded-full relative">
            <div
              className="absolute top-0 h-1.5 w-2 bg-blue-400 rounded-full -translate-x-1/2"
              style={{ left: `${Math.min(Math.max(range52Pct, 0), 100)}%` }}
            />
          </div>
          <span className="text-xs text-slate-500 w-16 text-right">52w High</span>
        </div>
      )}

      {/* ── Sticky section nav ── */}
      <nav className="sticky top-0 z-10 bg-slate-950/90 backdrop-blur-sm border-b border-slate-800 -mx-6 px-6 py-2 flex gap-4 overflow-x-auto">
        {SECTIONS.map(({ id, label }) => (
          <a
            key={id}
            href={`#${id}`}
            className={`text-xs whitespace-nowrap transition-colors ${
              activeSection === id
                ? "text-blue-400 font-medium"
                : "text-slate-400 hover:text-white"
            }`}
          >
            {label}
          </a>
        ))}
      </nav>

      {/* ── Price Chart ── */}
      <section id="price" className="scroll-mt-12">
        <PriceChart symbol={symbol!} />
      </section>

      {/* ── Valuation ── */}
      <section id="valuation" className="scroll-mt-12">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Valuation
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <RatioCard label="P/E" value={latest.pe_ratio} peerValue={sm.pe_ratio} format="multiple" higherIsBetter={false}
            tooltip={RATIO_TOOLTIPS["P/E"]} history={history("pe_ratio")} />
          <RatioCard label="P/B" value={latest.pb_ratio} peerValue={sm.pb_ratio} format="multiple" higherIsBetter={false}
            tooltip={RATIO_TOOLTIPS["P/B"]} history={history("pb_ratio")} />
          <RatioCard label="EV/EBITDA" value={latest.ev_ebitda} peerValue={sm.ev_ebitda} format="multiple" higherIsBetter={false}
            tooltip={RATIO_TOOLTIPS["EV/EBITDA"]} history={history("ev_ebitda")} />
          <RatioCard label="P/FCF" value={latest.price_to_fcf} peerValue={null} format="multiple" higherIsBetter={false}
            tooltip={RATIO_TOOLTIPS["P/FCF"]} history={history("price_to_fcf")} />
          <RatioCard label="P/Sales" value={latest.price_to_sales} peerValue={sm.price_to_sales} format="multiple" higherIsBetter={false}
            tooltip={RATIO_TOOLTIPS["P/Sales"]} history={history("price_to_sales")} />
        </div>
      </section>

      {/* ── Profitability ── */}
      <section id="profitability" className="scroll-mt-12">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Profitability
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <RatioCard label="Gross Margin" value={latest.gross_margin} peerValue={sm.gross_margin} format="percent"
            tooltip={RATIO_TOOLTIPS["Gross Margin"]} history={history("gross_margin")} />
          <RatioCard label="Op. Margin" value={latest.operating_margin} peerValue={sm.operating_margin} format="percent"
            tooltip={RATIO_TOOLTIPS["Op. Margin"]} history={history("operating_margin")} />
          <RatioCard label="Net Margin" value={latest.net_margin} peerValue={sm.net_margin} format="percent"
            tooltip={RATIO_TOOLTIPS["Net Margin"]} history={history("net_margin")} />
          <RatioCard label="ROE" value={latest.roe} peerValue={sm.roe} format="percent"
            tooltip={RATIO_TOOLTIPS["ROE"]} history={history("roe")} />
          <RatioCard label="ROA" value={latest.roa} peerValue={null} format="percent"
            tooltip={RATIO_TOOLTIPS["ROA"]} history={history("roa")} />
          <RatioCard label="ROIC" value={latest.roic} peerValue={null} format="percent"
            tooltip={RATIO_TOOLTIPS["ROIC"]} history={history("roic")} />
        </div>
        {/* Cash-quality row surfaces the SBC/lease story that vanilla ratios hide */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mt-3">
          <RatioCard label="FCF Margin" value={latest.fcf_margin} peerValue={null} format="percent"
            tooltip={RATIO_TOOLTIPS["FCF Margin"]} history={history("fcf_margin")} />
          <RatioCard label="FCF Margin ex-SBC" value={latest.fcf_margin_ex_sbc} peerValue={null} format="percent"
            tooltip={RATIO_TOOLTIPS["FCF Margin ex-SBC"]} history={history("fcf_margin_ex_sbc")} />
          <RatioCard label="SBC / Revenue" value={latest.sbc_to_revenue} peerValue={null} format="percent" higherIsBetter={false}
            tooltip={RATIO_TOOLTIPS["SBC / Revenue"]} history={history("sbc_to_revenue")} />
          <RatioCard label="Interest Coverage" value={latest.interest_coverage} peerValue={null} format="multiple"
            tooltip={RATIO_TOOLTIPS["Interest Coverage"]} history={history("interest_coverage")} />
          <RatioCard label="Debt+Leases / Equity" value={latest.debt_incl_leases_to_equity} peerValue={null} format="multiple" higherIsBetter={false}
            tooltip={RATIO_TOOLTIPS["Debt+Leases / Equity"]} history={history("debt_incl_leases_to_equity")} />
        </div>
      </section>

      {/* ── Growth ── */}
      <section id="growth" className="scroll-mt-12">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Growth (YoY)
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <RatioCard label="Revenue Growth" value={latest.revenue_growth} peerValue={sm.revenue_growth} format="percent"
            tooltip={RATIO_TOOLTIPS["Revenue Growth"]} history={history("revenue_growth")} />
          <RatioCard label="EPS Growth" value={latest.eps_growth} peerValue={sm.eps_growth} format="percent"
            tooltip={RATIO_TOOLTIPS["EPS Growth"]} history={history("eps_growth")} />
          <RatioCard label="FCF Growth" value={latest.fcf_growth} peerValue={null} format="percent"
            tooltip={RATIO_TOOLTIPS["FCF Growth"]} history={history("fcf_growth")} />
          <RatioCard label="Debt / Equity" value={latest.debt_to_equity} peerValue={sm.debt_to_equity} format="multiple" higherIsBetter={false}
            tooltip={RATIO_TOOLTIPS["Debt / Equity"]} history={history("debt_to_equity")} />
        </div>
      </section>

      {/* ── Trend Charts ── */}
      <section id="trends" className="scroll-mt-12">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Financials Trend
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <TrendChart
            title="Revenue & Gross Profit"
            dates={dates}
            series={[
              { name: "Revenue", values: ft.map((r) => r.revenue ?? 0), format: "currency" },
              { name: "Gross Profit", values: ft.map((r) => r.gross_profit ?? 0), format: "currency" },
            ]}
          />
          <TrendChart
            title="Operating & Net Income"
            dates={dates}
            series={[
              { name: "Operating Income", values: ft.map((r) => r.operating_income ?? 0), format: "currency" },
              { name: "Net Income", values: ft.map((r) => r.net_income ?? 0), format: "currency" },
            ]}
          />
          <TrendChart
            title="EPS (Diluted)"
            dates={dates}
            series={[{ name: "EPS", values: ft.map((r) => r.eps_diluted ?? 0), format: "number" }]}
          />
          <FCFvsSBCChart
            dates={dates}
            fcf={ft.map((r) => r.free_cash_flow ?? null)}
            sbc={ft.map((r) => r.sbc ?? null)}
          />
        </div>
      </section>

      {/* ── Sentiment ── */}
      <section id="sentiment" className="scroll-mt-12">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Sentiment Analysis
        </h2>
        <SentimentSection data={sentiment} symbol={symbol!} onRefresh={refreshSentiment} />
      </section>

      {/* ── AI Analysis ── */}
      <section id="ai-analysis" className="scroll-mt-12">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          AI Analysis
        </h2>
        <NarrativeSection symbol={symbol!} />
      </section>

      {/* ── About ── */}
      {company.description && (
        <section id="about" className="scroll-mt-12 bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-300 mb-2">About</h2>
          <p className="text-slate-400 text-sm leading-relaxed">{company.description}</p>
          {company.website && (
            <a
              href={company.website}
              target="_blank"
              rel="noreferrer"
              className="text-blue-400 text-sm mt-2 inline-block hover:underline"
            >
              {company.website}
            </a>
          )}
        </section>
      )}

      {/* Peer note */}
      {sm.peer_count !== undefined && (
        <p className="text-xs text-slate-600">
          Sector medians based on {sm.peer_count} tracked peer{sm.peer_count !== 1 ? "s" : ""} in {sm.sector}.
          Add more tickers to enrich peer comparison.
        </p>
      )}
    </div>
  );
}
