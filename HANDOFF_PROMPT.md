# Handoff Prompt — Stock Analyzer (Phase 5b–6)

Use this as your opening message to a new Claude instance.

---

## Prompt to paste

I'm building a personal stock research web app. Phases 1–5 are complete. I need you to continue with Phase 5b (narrative data optimization) and Phase 6.

**Read `CLAUDE.md` in the project root first** — it has the full architecture, stack, file structure, DuckDB schema, all API endpoints, known issues, and what remains to be built. Do not assume anything about the project structure; read the file.

The project is at:
`/Users/andrewkodsi/Desktop/Claude Code Projects/Stock Project/`

### What's already built
- **Phase 1**: DuckDB schema (9 tables), yfinance ingestion, FastAPI skeleton, APScheduler (daily prices 6pm ET, weekly fundamentals Sunday 8am ET, daily sentiment 7pm ET)
- **Phase 2**: Ratio calculations, tearsheet API + UI (candlestick chart, ratio cards with peer comparison, trend charts)
- **Phase 3**: Stock screener — filter engine with 5 presets (Value, Growth, Quality, Momentum, Dividend), custom screen builder with save/load/delete, sortable results table at `/screener`
- **Phase 4**: Sentiment pipeline — NewsAPI + Reddit public JSON API + FMP earnings transcripts → FinBERT scoring (`ProsusAI/finbert`), sentiment API endpoint, time-series charts + headlines with sentiment badges on tearsheet. Relevance filtering added (company name lookup + keyword matching to avoid unrelated results like Shakira for SHAK).
- **Phase 5**: AI Narrative Layer — local LLM via Apple MLX (`mlx-lm`) using `mlx-community/Mistral-7B-Instruct-v0.3-4bit`. Prompt templates for 4 narrative types (tearsheet summary, bull/bear case, risk flags, sentiment digest). SSE streaming to frontend. Caching in `narratives` table. NarrativeSection component with tabs, regenerate button, and disclaimer. **Note**: Ollama does not work on M5 MacBook Air due to Metal shader issues — use MLX instead.

### Key architecture notes for what's next
- DuckDB connection uses cursor-per-call pattern for thread safety (`db/connection.py`)
- FinBERT model is lazy-loaded singleton in `sentiment/finbert.py`
- MLX model is lazy-loaded singleton in `narrative/ollama_client.py` (file named for historical reasons — it uses MLX, not Ollama)
- The `narratives` table exists: `(symbol, narrative_type, generated_date, content, model)` — composite PK on first three
- All API responses must be wrapped with `clean()` from `api/sanitize.py`
- Prompt templates are in `narrative/prompts.py` — each builder takes a tearsheet dict and optionally sentiment dict, injects formatted metrics

---

**Phase 5b — Narrative Data Optimization** (start here)

The AI narrative layer works end-to-end but the quality of outputs can be improved by optimizing what data the model sees and the richness of the sentiment pipeline feeding into it.

1. **Optimize data for LLM consumption**
   - The 7B model has limited context (~4096 tokens). Current prompts dump all available metrics. Pre-process the data to surface only the most relevant/notable data points (e.g., metrics that diverge significantly from sector medians, multi-year trend inflections, outlier growth/decline).
   - Rank and prioritize which metrics to include based on what's interesting about this specific stock, rather than a one-size-fits-all template.
   - Consider a two-pass approach: first pass identifies notable data points, second pass builds a focused prompt.

2. **Improve Reddit data pipeline**
   - Currently pulls from 3 subreddits (investing, stocks, wallstreetbets) with basic title+body search
   - Add more subreddits relevant to specific sectors (e.g., r/technology for tech stocks, r/dividends for dividend stocks)
   - Weight posts by engagement (upvotes, comment count) — a 500-upvote post matters more than a 2-upvote post
   - Deduplicate cross-posts across subreddits
   - Pull top comments from high-engagement threads for richer sentiment signal
   - Consider time-decay weighting — recent posts should carry more weight

3. **Improve news pipeline**
   - Add RSS feeds as supplementary news sources (reduce sole dependency on NewsAPI free tier, which has a 100 req/day limit)
   - Where available, fetch full article text instead of just title+description for deeper FinBERT scoring
   - Filter out low-quality sources (press release wires, SEO content farms)
   - Tag articles by theme (earnings, product launch, regulatory, management change) for more structured narrative input

4. **Enrich sentiment context in narrative prompts**
   - Pass sentiment trend data (not just current snapshot) — is sentiment improving, declining, or stable over the last 30/60/90 days?
   - Highlight divergence between sources (e.g., news positive but Reddit negative = interesting signal)
   - Include specific headline quotes in the prompt so the LLM can reference real articles
   - Surface the most-discussed themes from Reddit titles

**Phase 6 — Polish**
- **Watchlist**: persist a list of tracked tickers the user cares about (stored in DuckDB), shown on the home page as quick-access cards with last price + daily change
- **Navigation**: add the watchlist to the home page
- **UI polish**: loading states, empty states, error boundaries where missing
- **PDF tearsheet export**: generate a PDF from the tearsheet page data

**Constraints to respect:**
- Python 3.9 — use `Optional[X]` not `X | None`, use `List[X]` / `Dict[X, Y]` from typing
- Always wrap DuckDB `.fetchdf().to_dict()` results with `clean()` from `api/sanitize.py` before returning from any route — prevents NaN/inf JSON serialization errors
- DuckDB connection: use `get_connection()` from `db/connection.py` — it returns a cursor, not the raw connection
- Do not use PRAW for Reddit — use the public JSON API (already implemented)
- Do not use Ollama — it has Metal shader issues on M5. Use MLX (`mlx-lm`) for local inference.
- yfinance >= 1.2.0 is already installed; do not downgrade
- FinBERT model: `ProsusAI/finbert` (already implemented in `sentiment/finbert.py`)
- Keep responses concise, implement incrementally, test each phase before moving to the next
