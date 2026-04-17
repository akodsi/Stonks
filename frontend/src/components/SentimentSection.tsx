import { useState, useRef, useCallback } from "react";
import Plot from "react-plotly.js";
import axios from "axios";
import SentimentBadge from "./SentimentBadge";
import SentimentDistributionBar from "./SentimentDistributionBar";

function safeHref(url: string): string | undefined {
  try {
    const protocol = new URL(url).protocol;
    if (protocol === "http:" || protocol === "https:") return url;
  } catch {}
  return undefined;
}
import { renderNarrativeText } from "../utils/narrativeRenderer";

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Article {
  title: string;
  source: string;
  url: string;
  published_at: string;
  summary?: string;
  sentiment_score: number;
  sentiment_label: string;
}

interface RedditPost {
  title: string;
  subreddit: string;
  url: string;
  score: number;
  num_comments: number;
  created_at: string;
  sentiment_score: number;
  sentiment_label: string;
  source_type?: string;
}

interface EarningsCall {
  quarter: string;
  earnings_date: string;
  avg_score: number;
  chunk_count: number;
}

interface TimePoint {
  date: string;
  score: number;
  count?: number;
}

interface Distribution {
  positive: number;
  neutral: number;
  negative: number;
}

interface RedditTrack {
  items: RedditPost[];
  avg_score: number | null;
  count: number;
  distribution?: Distribution;
}

export interface SentimentData {
  news: {
    articles: Article[];
    avg_score: number | null;
    recency_weighted_avg?: number | null;
    count: number;
    distribution?: Distribution;
    time_series: TimePoint[];
  };
  reddit: {
    investor?: RedditTrack;
    consumer?: RedditTrack;
    // backward-compat flat fields
    posts: RedditPost[];
    avg_score: number | null;
    count: number;
    time_series: TimePoint[];
  };
  earnings: {
    calls: EarningsCall[];
    avg_score: number | null;
  };
  composite: {
    score: number | null;
    label: string;
    momentum?: string;
    time_buckets?: Record<string, { score: number | null; count: number }>;
  };
}

interface Props {
  data: SentimentData | null;
  symbol: string;
  onRefresh?: () => void;
}

/* ── Momentum indicator ─────────────────────────────────────────────────── */

function MomentumIndicator({ momentum }: { momentum?: string }) {
  if (!momentum || momentum === "stable") return null;
  const improving = momentum === "improving";
  return (
    <p className={`text-xs ${improving ? "text-emerald-400" : "text-red-400"} mb-3`}>
      {improving ? "▲" : "▼"} Sentiment {improving ? "improving" : "deteriorating"} over the past 7 days
    </p>
  );
}

/* ── Reddit post list ───────────────────────────────────────────────────── */

function RedditPostList({ posts }: { posts: RedditPost[] }) {
  if (posts.length === 0) {
    return <p className="text-xs text-slate-500">No posts found.</p>;
  }
  return (
    <div className="space-y-2 max-h-64 overflow-y-auto">
      {posts.slice(0, 15).map((p, i) => (
        <div key={i} className="flex items-start gap-2 text-xs">
          <SentimentBadge score={p.sentiment_score} label={p.sentiment_label} />
          <div className="flex-1 min-w-0">
            <a
              href={safeHref(p.url)}
              target="_blank"
              rel="noreferrer"
              className="text-blue-400 hover:underline line-clamp-1"
            >
              {p.title}
            </a>
            <span className="text-slate-500">
              r/{p.subreddit} · <span className="font-medium text-slate-400">{p.score} pts</span> · {p.num_comments} comments
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Component ─────────────────────────────────────────────────────────── */

export default function SentimentSection({ data, symbol, onRefresh }: Props) {
  const [refreshing, setRefreshing] = useState(false);

  // Inline AI summary state
  const [summaryText, setSummaryText] = useState("");
  const [summaryStreaming, setSummaryStreaming] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryDone, setSummaryDone] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await axios.post(`/api/ticker/${symbol}/sentiment/refresh`);
      if (onRefresh) onRefresh();
    } catch {
      /* ignore */
    } finally {
      setRefreshing(false);
    }
  }

  const streamSummary = useCallback(async (regenerate: boolean = false) => {
    if (summaryStreaming) return;
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setSummaryStreaming(true);
    setSummaryText("");
    setSummaryError(null);
    setSummaryDone(false);

    const url = regenerate
      ? `/api/ticker/${symbol}/narratives/regenerate?type=sentiment_digest`
      : `/api/ticker/${symbol}/narratives/stream?type=sentiment_digest`;
    const method = regenerate ? "POST" : "GET";

    try {
      const response = await fetch(url, { method, signal: controller.signal });
      if (!response.ok) {
        setSummaryError(`Error ${response.status}`);
        setSummaryStreaming(false);
        return;
      }

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);
          if (payload === "[DONE]") { setSummaryDone(true); break; }
          if (payload.startsWith("[ERROR]")) { setSummaryError(payload.slice(8)); break; }
          accumulated += payload;
          setSummaryText(accumulated);
        }
      }
    } catch (e: any) {
      if (e.name !== "AbortError") setSummaryError("Failed to connect. Is the backend running?");
    } finally {
      setSummaryStreaming(false);
    }
  }, [symbol, summaryStreaming]);

  if (!data) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-center">
        <p className="text-slate-500 text-sm mb-3">No sentiment data yet.</p>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          {refreshing ? "Fetching..." : "Fetch Sentiment Data"}
        </button>
      </div>
    );
  }

  const { news, reddit, earnings, composite } = data;
  const hasTimeSeries = news.time_series.length > 0 || reddit.time_series.length > 0;
  const investorTrack = reddit.investor;
  const consumerTrack = reddit.consumer;

  return (
    <div className="space-y-4">
      {/* Composite score + refresh button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-400">Composite Sentiment:</span>
          <SentimentBadge score={composite.score} label={composite.label} size="lg" />
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="text-xs text-slate-400 hover:text-white disabled:opacity-50 transition-colors"
        >
          {refreshing ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {/* Sentiment time-series chart */}
      {hasTimeSeries && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-1">Sentiment Over Time</h3>
          <MomentumIndicator momentum={composite.momentum} />
          <Plot
            data={[
              ...(news.time_series.length > 0
                ? [
                    {
                      x: news.time_series.map((p) => p.date),
                      y: news.time_series.map((p) => p.score),
                      type: "scatter" as const,
                      mode: "lines+markers" as const,
                      name: "News",
                      line: { color: "#3b82f6", width: 2 },
                      marker: { size: 5 },
                    },
                  ]
                : []),
              ...(reddit.time_series.length > 0
                ? [
                    {
                      x: reddit.time_series.map((p) => p.date),
                      y: reddit.time_series.map((p) => p.score),
                      type: "scatter" as const,
                      mode: "lines+markers" as const,
                      name: "Reddit",
                      line: { color: "#f59e0b", width: 2 },
                      marker: { size: 5 },
                    },
                  ]
                : []),
            ]}
            layout={{
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
              margin: { t: 10, r: 10, b: 40, l: 50 },
              xaxis: { color: "#94a3b8", gridcolor: "#1e293b" },
              yaxis: {
                color: "#94a3b8",
                gridcolor: "#1e293b",
                range: [-1, 1],
                title: { text: "Score", font: { size: 11, color: "#94a3b8" } },
              },
              legend: { font: { color: "#94a3b8", size: 11 }, orientation: "h", y: -0.2 },
              height: 250,
              shapes: [
                {
                  type: "line",
                  x0: 0, x1: 1, xref: "paper",
                  y0: 0, y1: 0,
                  line: { color: "#475569", width: 1, dash: "dash" },
                },
              ],
            }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%" }}
          />
        </div>
      )}

      {/* News */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div className="mb-3">
          <div className="flex items-center gap-2 mb-2">
            <h3 className="text-sm font-medium text-slate-300">
              News
              <span className="text-slate-500 font-normal ml-1">({news.count} articles)</span>
            </h3>
            {news.avg_score != null && (
              <SentimentBadge score={news.avg_score} size="sm" />
            )}
          </div>
          {news.distribution && (
            <SentimentDistributionBar
              positive={news.distribution.positive}
              neutral={news.distribution.neutral}
              negative={news.distribution.negative}
            />
          )}
        </div>
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {news.articles.length === 0 ? (
            <p className="text-xs text-slate-500">No news articles found.</p>
          ) : (
            news.articles.slice(0, 15).map((a, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <SentimentBadge score={a.sentiment_score} label={a.sentiment_label} />
                <div className="flex-1 min-w-0">
                  <a
                    href={safeHref(a.url.includes("finance.yahoo.com") ? `https://www.google.com/search?q=${encodeURIComponent(a.title)}&tbm=nws` : a.url)}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-400 hover:underline line-clamp-1"
                  >
                    {a.title}
                  </a>
                  {a.summary && (
                    <p className="text-slate-500 line-clamp-2 mt-0.5">{a.summary}</p>
                  )}
                  <span className="text-slate-500">
                    {a.source} · {a.published_at.slice(0, 10)}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Reddit — Investor Sentiment */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div className="mb-3">
          <div className="flex items-center gap-2 mb-2">
            <h3 className="text-sm font-medium text-slate-300">
              Investor Sentiment
              <span className="text-slate-500 font-normal ml-1">
                ({investorTrack ? investorTrack.count : reddit.count} posts · r/investing, r/stocks, r/wallstreetbets &amp; more)
              </span>
            </h3>
            {investorTrack?.avg_score != null && (
              <SentimentBadge score={investorTrack.avg_score} size="sm" />
            )}
          </div>
          {investorTrack?.distribution && (
            <SentimentDistributionBar
              positive={investorTrack.distribution.positive}
              neutral={investorTrack.distribution.neutral}
              negative={investorTrack.distribution.negative}
            />
          )}
        </div>
        <RedditPostList posts={investorTrack ? investorTrack.items : reddit.posts} />
      </div>

      {/* Reddit — Consumer & Community Sentiment */}
      {(consumerTrack && consumerTrack.count > 0) && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="mb-3">
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-sm font-medium text-slate-300">
                Consumer &amp; Community Sentiment
                <span className="text-slate-500 font-normal ml-1">
                  ({consumerTrack.count} posts · company &amp; industry subreddits)
                </span>
              </h3>
              {consumerTrack.avg_score != null && (
                <SentimentBadge score={consumerTrack.avg_score} size="sm" />
              )}
            </div>
            {consumerTrack.distribution && (
              <SentimentDistributionBar
                positive={consumerTrack.distribution.positive}
                neutral={consumerTrack.distribution.neutral}
                negative={consumerTrack.distribution.negative}
              />
            )}
          </div>
          <RedditPostList posts={consumerTrack.items} />
        </div>
      )}

      {/* Earnings call sentiment */}
      {earnings.calls.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">
            Earnings Call Sentiment
            {earnings.avg_score != null && (
              <span className="ml-2">
                <SentimentBadge score={earnings.avg_score} size="sm" />
              </span>
            )}
          </h3>
          <Plot
            data={[
              {
                x: earnings.calls.map((c) => c.quarter),
                y: earnings.calls.map((c) => c.avg_score),
                type: "bar" as const,
                marker: {
                  color: earnings.calls.map((c) =>
                    c.avg_score > 0.15 ? "#10b981" : c.avg_score < -0.15 ? "#ef4444" : "#64748b"
                  ),
                },
                name: "Sentiment",
              },
            ]}
            layout={{
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
              margin: { t: 10, r: 10, b: 40, l: 50 },
              xaxis: { color: "#94a3b8", gridcolor: "#1e293b" },
              yaxis: { color: "#94a3b8", gridcolor: "#1e293b", range: [-1, 1] },
              showlegend: false,
              height: 200,
            }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%" }}
          />
        </div>
      )}

      {/* Inline AI Sentiment Summary */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl border-l-4 border-l-purple-500 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-200">AI Sentiment Summary</h3>
          {summaryDone || summaryText ? (
            <button
              onClick={() => streamSummary(true)}
              disabled={summaryStreaming}
              className="text-xs text-slate-400 hover:text-white disabled:opacity-50 transition-colors"
            >
              {summaryStreaming ? "Generating..." : "Regenerate"}
            </button>
          ) : null}
        </div>

        <div className="bg-amber-900/20 border border-amber-800/30 rounded-lg px-3 py-1.5 mb-4">
          <p className="text-xs text-amber-400/80">
            AI-generated analysis using a local LLM. Not financial advice. Always verify with primary sources.
          </p>
        </div>

        {summaryError ? (
          <p className="text-red-400 text-sm">{summaryError}</p>
        ) : summaryText ? (
          <div className="max-w-prose">
            {renderNarrativeText(summaryText)}
            {summaryStreaming && (
              <span className="inline-block w-2 h-4 bg-purple-500 animate-pulse ml-0.5" />
            )}
          </div>
        ) : summaryStreaming ? (
          <div className="space-y-3 py-2">
            <div className="animate-pulse bg-slate-800 h-3 w-full rounded" />
            <div className="animate-pulse bg-slate-800 h-3 w-5/6 rounded" />
            <div className="animate-pulse bg-slate-800 h-3 w-4/6 rounded" />
          </div>
        ) : (
          <div className="text-center py-4">
            <button
              onClick={() => streamSummary(false)}
              className="bg-purple-700 hover:bg-purple-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              Generate AI Summary
            </button>
            <p className="text-xs text-slate-500 mt-2">
              Synthesizes news, investor &amp; consumer sentiment into a narrative
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
