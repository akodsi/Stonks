import { useEffect, useState, useMemo } from "react";
import Plot from "react-plotly.js";
import axios from "axios";
import Spinner from "./Spinner";

interface PriceRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface Indicators {
  dates: string[];
  rsi: (number | null)[];
  macd: { macd: (number | null)[]; signal: (number | null)[]; histogram: (number | null)[] };
  bollinger: { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] };
  sma_50: (number | null)[];
  sma_200: (number | null)[];
}

interface EarningsDate {
  date: string;
  eps_estimate: number | null;
  eps_actual: number | null;
  surprise_pct: number | null;
}

const RANGES = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
  { label: "3Y", days: 1095 },
  { label: "5Y", days: 1825 },
];

type IndicatorKey = "sma" | "bollinger" | "rsi" | "macd" | "vol" | "earn";
const INDICATOR_LABELS: { key: IndicatorKey; label: string }[] = [
  { key: "vol", label: "Vol" },
  { key: "earn", label: "Earnings" },
  { key: "sma", label: "SMA" },
  { key: "bollinger", label: "BB" },
  { key: "rsi", label: "RSI" },
  { key: "macd", label: "MACD" },
];

export default function PriceChart({ symbol }: { symbol: string }) {
  const [prices, setPrices] = useState<PriceRow[]>([]);
  const [days, setDays] = useState(365);
  const [indicators, setIndicators] = useState<Indicators | null>(null);
  const [earnings, setEarnings] = useState<EarningsDate[]>([]);
  const [active, setActive] = useState<Set<IndicatorKey>>(new Set(["vol", "earn"]));
  const [loadingIndicators, setLoadingIndicators] = useState(false);

  useEffect(() => {
    axios
      .get<PriceRow[]>(`/api/ticker/${symbol}/prices?days=${days}`)
      .then((r) => setPrices([...r.data].reverse()))
      .catch(() => setPrices([]));
  }, [symbol, days]);

  // Fetch earnings dates once per symbol (cacheable, small payload).
  useEffect(() => {
    axios
      .get<EarningsDate[]>(`/api/ticker/${symbol}/earnings_dates?limit=20`)
      .then((r) => setEarnings(r.data || []))
      .catch(() => setEarnings([]));
  }, [symbol]);

  // Indicators fetched only when one of sma/bb/rsi/macd is toggled on.
  const indicatorActive =
    active.has("sma") || active.has("bollinger") || active.has("rsi") || active.has("macd");
  useEffect(() => {
    if (!indicatorActive) {
      setIndicators(null);
      return;
    }
    setLoadingIndicators(true);
    axios
      .get<Indicators>(`/api/ticker/${symbol}/indicators?days=${days}`)
      .then((r) => setIndicators(r.data))
      .catch(() => setIndicators(null))
      .finally(() => setLoadingIndicators(false));
  }, [symbol, days, indicatorActive]);

  function toggle(key: IndicatorKey) {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const hasVol = active.has("vol");
  const hasEarn = active.has("earn");
  const hasRSI = active.has("rsi") && indicators;
  const hasMACD = active.has("macd") && indicators;
  const subplotCount = (hasVol ? 1 : 0) + (hasRSI ? 1 : 0) + (hasMACD ? 1 : 0);

  // Earnings markers filtered to the visible range
  const visibleEarnings = useMemo(() => {
    if (!hasEarn || !prices.length) return [];
    const first = prices[0]?.date;
    const last = prices[prices.length - 1]?.date;
    if (!first || !last) return [];
    return earnings.filter((e) => e.date >= first && e.date <= last);
  }, [earnings, prices, hasEarn]);

  const plotData = useMemo(() => {
    const data: any[] = [];
    const pDates = prices.map((p) => p.date);

    data.push({
      x: pDates,
      open: prices.map((p) => p.open),
      high: prices.map((p) => p.high),
      low: prices.map((p) => p.low),
      close: prices.map((p) => p.close),
      type: "candlestick",
      increasing: { line: { color: "#10b981" } },
      decreasing: { line: { color: "#ef4444" } },
      name: symbol,
      yaxis: "y",
    });

    if (hasVol) {
      const volumeColors = prices.map((p) =>
        p.close >= p.open ? "rgba(16,185,129,0.55)" : "rgba(239,68,68,0.55)"
      );
      data.push({
        x: pDates,
        y: prices.map((p) => p.volume),
        type: "bar",
        name: "Volume",
        marker: { color: volumeColors },
        yaxis: "y2",
        hovertemplate: "Vol: %{y:.3s}<extra></extra>",
      });
    }

    if (indicators) {
      const iDates = indicators.dates;

      if (active.has("sma")) {
        data.push({
          x: iDates, y: indicators.sma_50, type: "scatter", mode: "lines",
          name: "SMA 50", line: { color: "#f59e0b", width: 1.5, dash: "dot" }, yaxis: "y",
        });
        data.push({
          x: iDates, y: indicators.sma_200, type: "scatter", mode: "lines",
          name: "SMA 200", line: { color: "#8b5cf6", width: 1.5, dash: "dot" }, yaxis: "y",
        });
      }

      if (active.has("bollinger")) {
        data.push({
          x: iDates, y: indicators.bollinger.upper, type: "scatter", mode: "lines",
          name: "BB Upper", line: { color: "#64748b", width: 1 }, yaxis: "y",
        });
        data.push({
          x: iDates, y: indicators.bollinger.middle, type: "scatter", mode: "lines",
          name: "BB Mid", line: { color: "#64748b", width: 1, dash: "dash" }, yaxis: "y",
        });
        data.push({
          x: iDates, y: indicators.bollinger.lower, type: "scatter", mode: "lines",
          name: "BB Lower", line: { color: "#64748b", width: 1 }, fill: "tonexty",
          fillcolor: "rgba(100,116,139,0.08)", yaxis: "y",
        });
      }

      if (hasRSI) {
        const rsiAxis = hasVol ? "y3" : "y2";
        data.push({
          x: iDates, y: indicators.rsi, type: "scatter", mode: "lines",
          name: "RSI", line: { color: "#06b6d4", width: 1.5 }, yaxis: rsiAxis,
        });
      }

      if (hasMACD) {
        const macdAxis =
          hasVol && hasRSI ? "y4" : hasVol || hasRSI ? "y3" : "y2";
        data.push({
          x: iDates, y: indicators.macd.macd, type: "scatter", mode: "lines",
          name: "MACD", line: { color: "#3b82f6", width: 1.5 }, yaxis: macdAxis,
        });
        data.push({
          x: iDates, y: indicators.macd.signal, type: "scatter", mode: "lines",
          name: "Signal", line: { color: "#f97316", width: 1.5 }, yaxis: macdAxis,
        });
        data.push({
          x: iDates, y: indicators.macd.histogram, type: "bar",
          name: "Histogram", marker: {
            color: indicators.macd.histogram.map((v) => (v && v >= 0 ? "#10b981" : "#ef4444")),
          }, yaxis: macdAxis,
        });
      }
    }

    return data;
  }, [prices, indicators, active, symbol, hasVol, hasRSI, hasMACD]);

  const layout = useMemo(() => {
    // Allocate vertical space proportionally to how many subplots are active.
    // Each slot gets a fixed 22% of the vertical space; main candle takes the rest.
    const slotHeight = 0.22;
    const gap = 0.04;
    let cursor = 0;
    const reserveMain = Math.max(0.35, 1 - subplotCount * slotHeight - subplotCount * gap);
    const mainBottom = 1 - reserveMain;
    let next = mainBottom - gap;

    const axes: any = {};
    // Volume — if active, sits immediately below main
    if (hasVol) {
      const top = next;
      const bottom = Math.max(0, top - slotHeight);
      axes.yaxis2 = {
        domain: [bottom, top],
        color: "#94a3b8",
        gridcolor: "#1e293b",
        tickformat: ".2s",
        tickfont: { size: 9 },
        title: { text: "Vol", font: { size: 9 } },
      };
      next = bottom - gap;
      cursor++;
    }
    if (hasRSI) {
      const axisName = hasVol ? "yaxis3" : "yaxis2";
      const top = next;
      const bottom = Math.max(0, top - slotHeight);
      axes[axisName] = {
        domain: [bottom, top],
        color: "#94a3b8",
        gridcolor: "#1e293b",
        range: [0, 100],
        dtick: 30,
        tickfont: { size: 9 },
        title: { text: "RSI", font: { size: 9 } },
      };
      next = bottom - gap;
      cursor++;
    }
    if (hasMACD) {
      const axisName =
        hasVol && hasRSI ? "yaxis4" : hasVol || hasRSI ? "yaxis3" : "yaxis2";
      const top = next;
      const bottom = Math.max(0, top - slotHeight);
      axes[axisName] = {
        domain: [bottom, top],
        color: "#94a3b8",
        gridcolor: "#1e293b",
        tickfont: { size: 9 },
        title: { text: "MACD", font: { size: 9 } },
      };
      cursor++;
    }

    const effectiveMainBottom = subplotCount === 0 ? 0 : mainBottom;

    // Earnings markers as shapes + annotations on the main axis
    const shapes: any[] = [];
    const annotations: any[] = [];
    if (hasEarn && visibleEarnings.length) {
      for (const e of visibleEarnings) {
        const hasSurprise = e.surprise_pct != null;
        const positive = hasSurprise && (e.surprise_pct as number) >= 0;
        const color = hasSurprise
          ? positive
            ? "#10b981"
            : "#ef4444"
          : "#64748b";
        shapes.push({
          type: "line",
          xref: "x",
          yref: "paper",
          x0: e.date,
          x1: e.date,
          y0: effectiveMainBottom,
          y1: 1,
          line: { color, width: 1, dash: "dot" },
          opacity: 0.55,
        });
        if (hasSurprise) {
          annotations.push({
            x: e.date,
            y: 1,
            xref: "x",
            yref: "paper",
            showarrow: false,
            text: `E ${positive ? "+" : ""}${(e.surprise_pct as number).toFixed(1)}%`,
            bgcolor: color,
            bordercolor: color,
            font: { size: 9, color: "#0f172a" },
            xanchor: "center",
            yanchor: "bottom",
            yshift: 2,
            opacity: 0.9,
          });
        }
      }
    }

    return {
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      margin: { t: 14, r: 10, b: 40, l: 60 },
      xaxis: { color: "#94a3b8", gridcolor: "#1e293b", rangeslider: { visible: false } },
      yaxis: {
        color: "#94a3b8",
        gridcolor: "#1e293b",
        tickprefix: "$",
        domain: [subplotCount ? mainBottom : 0, 1],
      },
      ...axes,
      shapes,
      annotations,
      showlegend: active.size > 0,
      legend: { orientation: "h" as const, y: -0.08, font: { color: "#94a3b8", size: 10 } },
      height: subplotCount > 0 ? 300 + cursor * 110 : 300,
    };
  }, [subplotCount, hasVol, hasRSI, hasMACD, hasEarn, visibleEarnings, active.size]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-sm font-medium text-slate-300">Price</h2>
        <div className="flex gap-3 items-center">
          <div className="flex gap-1">
            {INDICATOR_LABELS.map((ind) => (
              <button
                key={ind.key}
                onClick={() => toggle(ind.key)}
                className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                  active.has(ind.key)
                    ? "bg-emerald-700 text-white"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {ind.label}
              </button>
            ))}
            {loadingIndicators && <Spinner size="sm" />}
          </div>
          <div className="w-px h-4 bg-slate-700" />
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r.label}
                onClick={() => setDays(r.days)}
                className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                  days === r.days
                    ? "bg-blue-600 text-white"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <Plot
        data={plotData}
        layout={layout}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%" }}
      />
      {hasRSI && (
        <p className="text-[10px] text-slate-600 mt-1">RSI: 70 = overbought, 30 = oversold</p>
      )}
      {hasEarn && visibleEarnings.length > 0 && (
        <p className="text-[10px] text-slate-600 mt-1">
          Earnings markers: dashed line at announcement date. Badge shows EPS surprise vs consensus.
        </p>
      )}
    </div>
  );
}
