# Security & Quality — Remaining Issues

Tracked items from codebase audit (2026-04-05). Critical, high, and medium issues have been fixed.

## Medium Priority — FIXED (2026-04-05)

### ~~1. No input validation on `days`/`limit` query params~~
- **Fixed**: Added `Query(ge=1, le=3650)` bounds on all `days` params and `Query(ge=1, le=100)` on `limit` in ticker.py, sentiment.py, portfolio.py

### ~~2. No ticker symbol format validation~~
- **Fixed**: Added `validate_symbol()` in `api/sanitize.py` (`^[A-Z0-9.\-]{1,10}$`), applied across all route files

### ~~3. Unclosed `requests.Session` in reddit.py~~
- **Fixed**: Wrapped session in `try/finally` with `session.close()` in `ingest_reddit()`

### ~~4. Unclosed DuckDB cursors~~
- **Fixed**: Added `get_cursor()` context manager in `db/connection.py` for callers that want auto-cleanup

### ~~5. URL validation missing in frontend links~~
- **Fixed**: Added `safeHref()` helper in `SentimentSection.tsx` — validates `http:`/`https:` protocol before rendering

### ~~6. Missing portfolio form validation (frontend)~~
- **Fixed**: Added `isNaN()` and `> 0` checks for shares/cost_basis in `PortfolioPage.tsx` before API call

## Low Priority

### 7. FMP API key in query string
- **File**: backend/ingestion/financials.py (line ~141)
- **Issue**: API key in URL gets logged by proxies/servers
- **Fix**: Pass via `Authorization` header if FMP supports it

### 8. No rate limiting on any backend endpoints
- **Fix**: Add `slowapi` or similar middleware, especially on `/search` and `/ingest`

### 9. No security headers (CSP, X-Frame-Options, etc.)
- **File**: backend/main.py
- **Fix**: Add `starlette.middleware` for security headers or use a dedicated package

### 10. Broad `except Exception:` blocks (~32 occurrences)
- **Files**: Throughout ingestion code
- **Fix**: Use specific exceptions (RequestException, JSONDecodeError, etc.)

### 11. CORS allows all methods/headers
- **File**: backend/main.py (lines 44-50)
- **Fix**: Explicitly list allowed methods: `["GET", "POST", "PUT", "DELETE"]`
