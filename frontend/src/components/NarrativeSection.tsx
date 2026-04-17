import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { renderNarrativeText } from "../utils/narrativeRenderer";

/* ── Types ─────────────────────────────────────────────────────────────── */

type NarrativeType = "tearsheet" | "bull_bear" | "risk" | "sentiment_digest";

interface CachedNarrative {
  content: string;
  model: string;
  generated_date: string;
}

interface NarrativesResponse {
  ollama_available: boolean;
  narratives: Record<string, CachedNarrative>;
}

const TABS: { key: NarrativeType; label: string }[] = [
  { key: "tearsheet", label: "Summary" },
  { key: "bull_bear", label: "Bull / Bear" },
  { key: "risk", label: "Risks" },
  { key: "sentiment_digest", label: "Sentiment" },
];

/* ── Tab accent colors ─── */

const TAB_ACCENT: Record<NarrativeType, string> = {
  tearsheet: "border-l-blue-500",
  bull_bear: "border-l-emerald-500",
  risk: "border-l-amber-500",
  sentiment_digest: "border-l-purple-500",
};

/* ── Component ─────────────────────────────────────────────────────────── */

interface Props {
  symbol: string;
}

/**
 * Split a bull/bear narrative into two halves using the load-bearing
 * `## Bull Case` / `## Bear Case` headings emitted by the prompt. Falls back
 * to a single column if either heading is missing.
 */
function splitBullBear(content: string): { bull: string; bear: string } | null {
  if (!content) return null;
  const bullIdx = content.search(/##\s*Bull\s*Case/i);
  const bearIdx = content.search(/##\s*Bear\s*Case/i);
  if (bullIdx === -1 || bearIdx === -1) return null;
  // Preserve any shared thesis / preamble before the Bull heading by prepending it
  const preamble = content.slice(0, bullIdx).trim();
  const bull = content.slice(bullIdx, bearIdx).trim();
  const bear = content.slice(bearIdx).trim();
  return {
    bull: preamble ? `${preamble}\n\n${bull}` : bull,
    bear,
  };
}

export default function NarrativeSection({ symbol }: Props) {
  const [activeTab, setActiveTab] = useState<NarrativeType>("tearsheet");
  const [narratives, setNarratives] = useState<Record<string, CachedNarrative>>({});
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [ollamaAvailable, setOllamaAvailable] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Load cached narratives on mount / symbol change
  useEffect(() => {
    setNarratives({});
    setStreamingText("");
    setError(null);

    axios
      .get<NarrativesResponse>(`/api/ticker/${symbol}/narratives`)
      .then((res) => {
        setOllamaAvailable(res.data.ollama_available);
        setNarratives(res.data.narratives || {});
      })
      .catch(() => {
        setOllamaAvailable(false);
      });

    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [symbol]);

  const streamNarrative = useCallback(
    async (type: NarrativeType, regenerate: boolean = false) => {
      if (isStreaming) return;

      // Cancel any prior stream
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsStreaming(true);
      setStreamingText("");
      setError(null);

      const url = regenerate
        ? `/api/ticker/${symbol}/narratives/regenerate?type=${type}`
        : `/api/ticker/${symbol}/narratives/stream?type=${type}`;
      const method = regenerate ? "POST" : "GET";

      try {
        const response = await fetch(url, {
          method,
          signal: controller.signal,
        });

        if (!response.ok) {
          const text = await response.text();
          setError(text || `Error ${response.status}`);
          setIsStreaming(false);
          return;
        }

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let accumulated = "";
        let lineBuffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          lineBuffer += decoder.decode(value, { stream: true });
          const lines = lineBuffer.split("\n");
          // Keep the last (potentially incomplete) line in the buffer
          lineBuffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const payload = line.slice(6).trim();
            if (payload === "[DONE]") {
              setNarratives((prev) => ({
                ...prev,
                [type]: {
                  content: accumulated,
                  model: "ollama",
                  generated_date: new Date().toISOString().slice(0, 10),
                },
              }));
              break;
            }
            if (payload.startsWith("[ERROR]")) {
              try {
                setError(JSON.parse(payload.slice(7)));
              } catch {
                setError(payload.slice(7));
              }
              break;
            }
            try {
              accumulated += JSON.parse(payload);
            } catch {
              accumulated += payload;
            }
            setStreamingText(accumulated);
          }
        }
      } catch (e: any) {
        if (e.name !== "AbortError") {
          setError("Failed to connect. Is the backend running?");
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [symbol, isStreaming]
  );

  // Auto-generate when clicking a tab with no cached content
  function handleTabClick(type: NarrativeType) {
    setActiveTab(type);
    setStreamingText("");
    setError(null);

    if (!narratives[type] && ollamaAvailable && !isStreaming) {
      streamNarrative(type);
    }
  }

  function handleRegenerate() {
    if (isStreaming) return;
    streamNarrative(activeTab, true);
  }

  const cachedContent = narratives[activeTab]?.content;
  const displayText = cachedContent || streamingText;

  // Only bull_bear supports compare mode; other tabs fall back to single-column
  const isBullBear = activeTab === "bull_bear";
  const bullBearSplit =
    isBullBear && displayText ? splitBullBear(displayText) : null;
  const compareActive = isBullBear && compareMode && !!bullBearSplit;

  return (
    <div className="space-y-3">
      {/* Disclaimer */}
      <div className="bg-amber-900/20 border border-amber-800/30 rounded-lg px-4 py-2">
        <p className="text-xs text-amber-400/80">
          AI-generated analysis using a local LLM. Not financial advice. Always
          verify with primary sources.
        </p>
      </div>

      {/* Tab bar + regenerate */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1 items-center">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => handleTabClick(tab.key)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                activeTab === tab.key
                  ? "bg-blue-600 text-white"
                  : "text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              {tab.label}
              {narratives[tab.key] && (
                <span className="ml-1.5 w-1.5 h-1.5 bg-green-500 rounded-full inline-block" />
              )}
            </button>
          ))}
          {isBullBear && (
            <button
              onClick={() => setCompareMode((v) => !v)}
              disabled={!bullBearSplit}
              title={
                bullBearSplit
                  ? "Toggle side-by-side bull vs bear view"
                  : "Generate the Bull/Bear narrative first"
              }
              className={`ml-2 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                compareActive
                  ? "bg-emerald-700 text-white"
                  : "text-slate-400 hover:text-white hover:bg-slate-800 border border-slate-700"
              }`}
            >
              {compareActive ? "Compare: on" : "Compare"}
            </button>
          )}
        </div>
        <button
          onClick={handleRegenerate}
          disabled={isStreaming || !ollamaAvailable}
          className="text-xs text-slate-400 hover:text-white disabled:opacity-50 transition-colors"
        >
          {isStreaming ? "Generating..." : "Regenerate"}
        </button>
      </div>

      {/* Content area */}
      {compareActive && bullBearSplit ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 border-l-4 border-l-emerald-500 min-h-[300px]">
            <div className="max-w-prose">{renderNarrativeText(bullBearSplit.bull)}</div>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 border-l-4 border-l-red-500 min-h-[300px]">
            <div className="max-w-prose">{renderNarrativeText(bullBearSplit.bear)}</div>
          </div>
        </div>
      ) : (
        <div className={`bg-slate-900 border border-slate-800 rounded-xl p-5 min-h-[300px] border-l-4 ${TAB_ACCENT[activeTab]}`}>
          {!ollamaAvailable ? (
            <div className="text-center py-8">
              <p className="text-slate-400 text-sm mb-2">Local AI model unavailable</p>
              <p className="text-slate-500 text-xs">
                Ensure the backend is running with MLX and the model is downloaded.
              </p>
            </div>
          ) : error ? (
            <div className="text-center py-8">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          ) : displayText ? (
            <div className="max-w-prose">
              {renderNarrativeText(displayText)}
              {isStreaming && (
                <span className="inline-block w-2 h-4 bg-blue-500 animate-pulse ml-0.5" />
              )}
            </div>
          ) : isStreaming ? (
            <div className="space-y-3 py-4">
              <div className="animate-pulse bg-slate-800 h-3 w-full rounded" />
              <div className="animate-pulse bg-slate-800 h-3 w-5/6 rounded" />
              <div className="animate-pulse bg-slate-800 h-3 w-4/6 rounded" />
              <div className="animate-pulse bg-slate-800 h-3 w-full rounded" />
            </div>
          ) : (
            <div className="text-center py-8">
              <p className="text-slate-500 text-sm">
                Click a tab to generate AI analysis
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
