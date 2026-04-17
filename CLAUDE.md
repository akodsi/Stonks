# Stock Analyzer — Project Brief for Claude

## What this is
A personal stock research web app for US equities. Combines financial statement analysis, a stock screener, sentiment analysis (news + Reddit + earnings calls), and AI-generated narrative summaries via the Claude API.

## Stack
| Layer | Tool |
|---|---|
| Frontend | React + Tailwind v4 + Plotly (react-plotly.js) via Vite |
| Backend | FastAPI (Python 3.9) |
| Database | DuckDB (local file: `backend/data/stocks.duckdb`) |
| Financial data | yfinance >= 1.2.0 (primary, free) + FMP API (earnings transcripts) |
| News | NewsAPI |
| Social | Reddit public JSON API (no auth required — no PRAW) |
| Earnings transcripts | FMP API |
| NLP/Sentiment | FinBERT (local, via HuggingFace transformers + torch) |
| AI Narrative | MLX + Mistral 7B (local, via mlx-lm) — runs natively on Apple Silicon |
| RSS feeds | feedparser (supplementary news source) |
| Scheduling | APScheduler (daily EOD price refresh 6pm ET, weekly fundamentals Sunday 8am ET) |

## Python version
Python 3.9 — use `Optional[X]` not `X | None` for type hints.

## Project structure
```
Stock Project/
├── backend/
│   ├── main.py                    FastAPI app, lifespan scheduler, CORS
│   ├── .env                       API keys (gitignored)
│   ├── .env.example
│   ├── requirements.txt
│   ├── api/
│   │   ├── sanitize.py            clean() — replaces NaN/inf with None before JSON responses
│   │   └── routes/
│   │       ├── ticker.py          /ticker/* — ingest, prices, financials, list
│   │       ├── fundamentals.py    /ticker/{symbol}/ratios, /tearsheet
│   │       ├── screener.py        /screener/* — run presets/custom, saved screens
│   │       ├── sentiment.py       /ticker/{symbol}/sentiment, /sentiment/refresh, /sentiment/overview
│   │       ├── narratives.py      /ticker/{symbol}/narratives, /stream, /regenerate
│   │       └── portfolio.py       /portfolio/* — holdings CRUD, summary, performance, benchmark
│   ├── db/
│   │   ├── connection.py          DuckDB singleton (clears stale .lock on startup)
│   │   └── schema.py              All 8 tables — init_schema()
│   ├── fundamentals/
│   │   └── ratios.py              compute_ratios(), get_ratios(), get_sector_medians()
│   ├── screener/
│   │   ├── __init__.py
│   │   └── engine.py              run_screen(), presets, saved screen CRUD
│   ├── narrative/
│   │   ├── __init__.py
│   │   ├── ollama_client.py       MLX model singleton, generate(), generate_stream()
│   │   └── prompts.py             4 prompt builders (tearsheet, bull/bear, risk, sentiment)
│   ├── sentiment/
│   │   ├── __init__.py
│   │   └── finbert.py             FinBERT singleton, score_texts(), score_text()
│   └── ingestion/
│       ├── price.py               ingest_company(), ingest_prices(), ingest_prices_incremental()
│       ├── financials.py          ingest_financials() via yfinance, fetch_fmp_earnings_transcripts()
│       ├── news.py                ingest_news() via NewsAPI + FinBERT
│       ├── reddit.py              ingest_reddit() via public JSON API + FinBERT
│       └── scheduler.py           APScheduler job definitions
└── frontend/
    └── src/
        ├── App.tsx                Router shell + nav
        ├── pages/
        │   ├── HomePage.tsx       Ticker search + ingest trigger
        │   ├── TickerPage.tsx     Full tearsheet page
        │   ├── ScreenerPage.tsx   Stock screener with presets + custom builder
        │   ├── SentimentPage.tsx  Cross-ticker sentiment overview with sorting/filtering
        │   └── PortfolioPage.tsx  Portfolio tracker with holdings, P&L, benchmark chart
        └── components/
            ├── PriceChart.tsx     Candlestick with 1M/3M/6M/1Y/3Y/5Y toggle
            ├── RatioCard.tsx      Metric tile with green/red vs sector median
            ├── TrendChart.tsx     Bar chart for multi-year financial trends
            ├── SentimentSection.tsx  Sentiment dashboard (charts, headlines, Reddit)
            ├── SentimentBadge.tsx    Color-coded sentiment pill
            └── NarrativeSection.tsx  AI analysis tabs (summary, bull/bear, risks, sentiment)
```

## DuckDB schema (12 tables)
- `companies` — metadata (symbol, name, sector, industry, market_cap, aliases, subreddits, etc.)
- `prices` — daily OHLCV + adj_close
- `financials` — annual + quarterly income / balance sheet / cash flow
- `ratios` — computed P/E, margins, growth, leverage — cached here
- `news` — articles with FinBERT sentiment score, source_tier, full_text
- `reddit_posts` — Reddit mentions with sentiment score, source_type (investor/company/industry)
- `reddit_comments` — comment-level sentiment from high-engagement Reddit posts
- `earnings_transcripts` — chunked call transcripts with sentiment score
- `saved_screens` — user-defined screener templates (name + criteria JSON)
- `watchlist` — user watchlist symbols
- `narratives` — cached AI narrative summaries (keyed symbol + type + date, model field tracks which LLM generated it)
- `portfolio_holdings` — portfolio positions (symbol, shares, cost_basis, purchase_date, notes)
- `portfolio_settings` — portfolio config (benchmark symbol, etc.)

## Key API endpoints (backend runs on :8000)
- `POST /ticker/{symbol}/ingest` — full ingest: metadata + 5y prices + financials
- `GET /ticker/{symbol}` — company metadata
- `GET /ticker/{symbol}/prices?days=365` — EOD prices
- `GET /ticker/{symbol}/financials?period_type=annual` — statements
- `GET /ticker/{symbol}/ratios?period_type=annual` — ratios
- `GET /ticker/{symbol}/tearsheet` — full bundle for UI
- `GET /screener/presets` — list preset screen definitions
- `GET /screener/run?preset=value` — run a preset screen
- `POST /screener/run` — run custom screen with criteria body
- `GET /screener/screens` — list saved custom screens
- `POST /screener/screens` — save a custom screen
- `DELETE /screener/screens/{name}` — delete a saved screen
- `GET /ticker/{symbol}/sentiment?days=90` — aggregated sentiment (news + reddit + earnings)
- `POST /ticker/{symbol}/sentiment/refresh` — trigger fresh sentiment ingestion
- `GET /ticker/{symbol}/narratives` — cached AI narratives for today + model availability flag
- `GET /ticker/{symbol}/narratives/stream?type=tearsheet` — SSE stream narrative generation
- `POST /ticker/{symbol}/narratives/regenerate?type=tearsheet` — force re-generate and stream
- `GET /ticker/sentiment/overview?days=30` — cross-ticker sentiment summary
- `GET /portfolio/holdings` — list portfolio holdings with current P&L
- `POST /portfolio/holdings` — add a holding
- `PUT /portfolio/holdings/{id}` — update a holding
- `DELETE /portfolio/holdings/{id}` — remove a holding
- `GET /portfolio/summary` — portfolio total value, P&L, allocation, benchmark comparison
- `GET /portfolio/performance?days=365` — daily portfolio vs benchmark time series
- `GET /portfolio/benchmark` — get current benchmark symbol
- `PUT /portfolio/benchmark/{symbol}` — set benchmark (SPY, QQQ, etc.)

## Known issues / decisions already made
- **NaN/inf sanitization**: always wrap DuckDB `.fetchdf().to_dict()` responses with `clean()` from `api/sanitize.py` — pandas produces NaN for missing data which breaks JSON serialization
- **DuckDB lock**: connection.py clears stale `.lock` files on startup (left by crashed processes)
- **yfinance rate limits**: use yfinance >= 1.2.0; do not hammer Yahoo Finance in rapid succession during testing
- **Reddit**: use public Reddit JSON API (`reddit.com/r/{sub}/search.json?q={symbol}`) — no credentials needed
- **MLX for local LLM**: Ollama has Metal shader compatibility issues on M5 chips — use Apple MLX (`mlx-lm`) instead. Model is lazy-loaded singleton in `narrative/ollama_client.py`
- **Sentiment relevance filtering**: news.py and reddit.py look up company name from DB and filter results by relevance (keyword matching) to avoid pulling unrelated articles (e.g., Shakira for SHAK)
- **Python 3.9**: no `X | Y` union syntax, no `match` statements
- **Route ordering**: static routes (`/search`, `/`) must be defined before `/{symbol}` in ticker.py or FastAPI will swallow them
- **Ratios schema migration**: `schema.py` runs `ALTER TABLE ratios ADD COLUMN IF NOT EXISTS` on startup for the 4 new ratio columns (ebitda_margin, fcf_margin, cash_to_debt, ocf_to_net_income) — safe to re-run. Existing ratio rows won't have these populated until next `compute_ratios()` call (re-ingest or Sunday scheduler)

## How to run
```bash
# Backend
cd backend
source venv/bin/activate
uvicorn main:app --reload   # runs on :8000

# Frontend (separate terminal)
cd frontend
npm run dev                 # runs on :3000, proxies /api/* to :8000
```

## Phases completed
- [x] Phase 1 — Data Foundation (DuckDB schema, yfinance ingestion, FastAPI skeleton, APScheduler)
- [x] Phase 2 — Fundamentals Engine (ratio calc, tearsheet API, tearsheet UI with candlestick + ratio cards + trend charts + peer comparison)
- [x] Phase 3 — Stock Screener (filter engine, 5 presets, custom screen builder with save/load, sortable results table)
- [x] Phase 4 — Sentiment Pipeline (NewsAPI + Reddit + earnings transcripts → FinBERT scoring, sentiment API, time-series charts + headlines on tearsheet, relevance filtering by company name)
- [x] Phase 5 — AI Narrative Layer (MLX + Mistral 7B local LLM, 4 prompt templates, SSE streaming, caching in narratives table, NarrativeSection UI with tabs + disclaimer)
- [x] Phase 5b — Narrative Data Optimization:
  - Prompts now include company description (truncated, from `companies.description`)
  - News articles include `summary` + `published_at`; Reddit posts include `body`, `subreddit`, `score`, `num_comments`, `created_at`; Reddit sorted by engagement (upvotes) not recency
  - Earnings: top-3 most sentiment-charged transcript excerpts passed as quoted text (instead of avg score only); separate unbiased AVG query kept for composite weighting
  - Temporal sentiment bucketing: 7d / 30d / 90d windows with improving/deteriorating/stable trend labels shown in sentiment prompt
  - 4 new ratios computed + stored + shown in all prompts: EBITDA Margin, FCF Margin, Cash/Debt, OCF/NI
  - `_truncate(text, max_chars)` helper added to prompts.py for safe text injection
  - `_derive_trend()` and `_bucket_line()` helpers added for temporal trend formatting

- [x] Phase 5b (pipeline) — News + Reddit pipeline improvements:
  - RSS feeds as supplementary news source (feedparser) — Reuters, CNBC, MarketWatch, Seeking Alpha, BBC Business, Yahoo Finance per-symbol feeds
  - Press release / low-quality source filtering (PR Newswire, Business Wire, GlobeNewsWire, etc.)
  - Full article text scraping via newspaper3k for T1/T2 sources
  - Expanded Reddit to 12 investor subs + auto-detected company subs + sector-mapped industry subs
  - Comment-level sentiment from high-engagement posts (score >= 100), stored in reddit_comments table
- [x] Phase 6 — Polish (partial):
  - Portfolio tracker with benchmark comparison (holdings CRUD, P&L, allocation pie chart, portfolio vs SPY performance chart, configurable benchmark)
  - PDF tearsheet export (ExportButton component)
  - Sentiment overview page (cross-ticker sentiment table with composite scores, momentum, sector filter, time range toggle)
  - Navigation: added Sentiment + Portfolio to nav bar, all pages accessible

## Phases remaining

### Phase 6 — Remaining
- Email/push alerts on screener threshold breaks
