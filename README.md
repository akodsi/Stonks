# Stonks

> Fundamentals. Sentiment. Local AI. Zero bullshit.

A personal stock research app that stops treating you like a retail donkey. It
pulls the raw data, crunches the ratios that actually matter, reads the news
*and* the earnings call *and* Reddit, then hands it all to a local LLM that
writes you a tearsheet — committing to a thesis instead of hedging it.

Runs on your laptop. Your data, your keys, your model. No SaaS tab to close.

```
        _____ _             _
       / ____| |           | |
      | (___ | |_ ___  _ __| | _____
       \___ \| __/ _ \| '_ \ |/ / __|
       ____) | || (_) | | | |   <\__ \
      |_____/ \__\___/|_| |_|_|\_\___/
                  number go up
```

---

## The thing it does that nobody else does

Most fundamentals dashboards lie to you in one very specific way: they show
**GAAP Free Cash Flow** and call it a day. Problem: GAAP FCF adds back
stock-based compensation because it's "non-cash." But SBC is real — your
equity is being diluted to pay engineers.

Snap Inc. FY2025:

| Metric                 | Value     |
| ---------------------- | --------- |
| Reported GAAP FCF      | **+$437M** |
| Stock-based comp       | $1,017M   |
| **FCF ex-SBC (real)**  | **−$580M** |
| Net income             | −$460M    |

Every other dashboard shows a glowing green FCF bar. This one shows the real
number *and* forces the LLM to mention it when writing the narrative. If
`SBC/revenue > 3%`, the prompt emits an `SBC BURDEN` line that the model is
contractually obligated to cite.

That single fix alone pays for this repo.

---

## Features

**Tearsheet**
- Candlestick chart with SMA, Bollinger Bands, RSI, MACD, volume subchart
- Earnings-date markers with EPS surprise badges
- 20+ ratio cards, each with a hover tooltip and a 48×16 inline sparkline
- Trend charts for Revenue / Income / EPS / FCF-vs-SBC
- Sector-median peer comparison that grows as you add tickers

**Screener**
- 5 presets (Value, Growth, Quality, Dividend, Distressed)
- Custom screen builder with save/load
- All screening happens in DuckDB in-process — results are instant

**Sentiment Pipeline**
- NewsAPI + 6 RSS feeds (Reuters, CNBC, WSJ, Bloomberg via Google News)
- Reddit public JSON API across 12+ investor subs + auto-detected company subs
- Two-track taxonomy: DD/investor vs speculative/retail
- FinBERT scoring on articles, Reddit posts, Reddit comments, and earnings
  transcript chunks
- Relevance filter that stops "snap" meaning Shakira's hip-snap

**AI Narratives (local)**
- 4 prompt templates: Tearsheet, Bull/Bear, Risk, Sentiment Digest
- Thesis-first structure with a banned-phrase list ("robust", "well-positioned",
  "only time will tell" — gone)
- Deviation-ranked ratios block so the 7B model's attention stays on what's
  actually interesting
- Side-by-side Bull vs Bear compare mode in the UI
- SSE streaming, cached per day in DuckDB

**Portfolio**
- Holdings CRUD with cost basis and purchase dates
- Live P&L, allocation pie chart, portfolio-vs-SPY (or any benchmark) chart
- Configurable benchmark

**Watchlist**
- Because of course

---

## Stack

| Layer          | Tool                                                              |
| -------------- | ----------------------------------------------------------------- |
| Frontend       | React + Vite + Tailwind v4 + Plotly (react-plotly.js) + TypeScript |
| Backend        | FastAPI (Python 3.9)                                              |
| Database       | DuckDB (single file, no server)                                   |
| Market data    | yfinance >= 1.2.0                                                 |
| News           | NewsAPI + RSS (feedparser) + newspaper3k for full-text            |
| Social         | Reddit public JSON API (no PRAW, no auth)                         |
| Transcripts    | Financial Modeling Prep                                           |
| Sentiment      | FinBERT (HuggingFace transformers)                                |
| Local LLM      | Apple MLX + Mistral 7B Instruct 4-bit (swappable)                 |
| Scheduling     | APScheduler                                                       |

**Why MLX over Ollama?** Ollama has Metal shader compatibility issues on M5
MacBooks. MLX ships native Apple-silicon kernels and lazy-loads the model as a
singleton. Zero friction.

**Why DuckDB?** It's SQL, it's columnar, it's embedded, it reads pandas
DataFrames directly. 15 tables, 200+ columns, entire universe of tracked
stocks fits in a single `.duckdb` file you can git-ignore.

**Why Python 3.9?** Corporate hostage situation. Don't ask.

---

## Quick start

```bash
# 1. Clone + keys
git clone https://github.com/akodsi/Stonks.git
cd Stonks
cp backend/.env.example backend/.env
# edit backend/.env → add FMP_API_KEY, NEWS_API_KEY

# 2. Backend
cd backend
python3.9 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload                 # :8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                                # :3000, proxies /api → :8000

# 4. Open http://localhost:3000, search "SNAP", watch the AI destroy it
```

First ingest takes ~30s per ticker (prices + fundamentals + news + Reddit +
transcripts + FinBERT scoring). After that, cached. The Sunday 8am scheduler
refreshes fundamentals weekly; EOD prices refresh daily at 6pm ET.

---

## Project layout

```
Stonks/
├── backend/
│   ├── api/routes/                 # 8 route modules
│   ├── db/                          # DuckDB schema + singleton connection
│   ├── fundamentals/ratios.py       # 28 ratios incl. FCF ex-SBC, lease-adj D/E
│   ├── ingestion/                   # price, financials, news, reddit, relevance
│   ├── narrative/
│   │   ├── ollama_client.py         # MLX model singleton + SSE streaming
│   │   └── prompts.py               # 4 prompt builders + banned-phrase guardrails
│   ├── screener/engine.py           # DuckDB-native filter engine
│   ├── sentiment/finbert.py         # FinBERT singleton
│   └── main.py                      # FastAPI + lifespan scheduler
└── frontend/src/
    ├── pages/                       # Home, Ticker, Screener, Sentiment,
    │                                # Portfolio, Watchlist, Compare
    └── components/                  # PriceChart, RatioCard (w/ sparkline),
                                     # FCFvsSBCChart, NarrativeSection, etc.
```

---

## API cheat sheet

```
POST  /ticker/{symbol}/ingest              full ingest (metadata + prices + financials + sentiment)
GET   /ticker/{symbol}/tearsheet           everything the UI needs in one payload
GET   /ticker/{symbol}/ratios              computed ratios (28 fields)
GET   /ticker/{symbol}/indicators          RSI, MACD, BB, SMA 50/200
GET   /ticker/{symbol}/earnings_dates      historical earnings + EPS surprise
GET   /ticker/{symbol}/sentiment           aggregated news + reddit + transcripts
GET   /ticker/{symbol}/narratives/stream   SSE stream AI analysis
POST  /ticker/{symbol}/narratives/regenerate?type=tearsheet
GET   /screener/run?preset=value
POST  /screener/run                        custom screen body
GET   /portfolio/summary                   P&L + benchmark comparison
GET   /portfolio/performance?days=365      portfolio vs benchmark timeseries
```

Full list: hit `http://localhost:8000/docs` when the backend is running.

---

## Design choices worth defending

**Thesis-first narratives.** Every AI output has to start with `**Thesis:**` on
its own line, committing to a direction. No "mixed signals." No "time will
tell." A prompt banned-phrase list keeps the model honest.

**Deviation-ranked ratios.** A 7B model has finite attention. Instead of
dumping 28 ratios, the prompt sorts them by magnitude of deviation from the
sector median and highlights the top 8. P/E at 1.01x sector P/E is noise. P/E
at 2.3x sector P/E is a story.

**Two-track Reddit.** `r/wallstreetbets` and `r/ValueInvesting` are not the
same signal. The sentiment engine splits them into `investor` (DD-heavy) and
`speculative` (retail), then reports the divergence so the LLM can call it
out: *"retail is euphoric, pros are skeptical — guess which one history
favors."*

**Relevance gating.** A cashtag like `$SNAP` accepts unconditionally. A bare
keyword "snap" requires either a distinctive alias match ("Snapchat", "Snap
Inc") OR a ticker mention plus a financial-context word ("earnings", "stock",
"layoffs", "activist", etc.). Kills the Shakira-concert-for-SHAK problem.

**SBC callout threshold.** 3% of revenue. Below that (AAPL ~3%, MSFT ~4%, JPM
<1%), SBC is noise. Above it, the prompt forces the LLM to mention it. SNAP
(17%) cannot escape.

---

## Status

Phases 1–5 complete. Phase 6 in progress (PDF export and sentiment overview
shipped; email/push alerts on screener breaks are next).

This is a personal tool, not financial advice, not for paper-handed shorts,
and definitely not for your mother-in-law asking about Nvidia at Thanksgiving.
Do your own research. Verify with primary sources. The local LLM will be wrong
sometimes. Think of it as a very opinionated intern.

---

## License

Personal use. Do what you want, but if you ship it as a SaaS without crediting
the SBC-aware FCF math, that's between you and your god.
