"""
Fetches EOD price data and company metadata via yfinance.
"""
import json
import re
import time
import yfinance as yf
import pandas as pd
import requests
from datetime import date, timedelta
from typing import List, Optional
from db.connection import get_connection

_REDDIT_USER_AGENT = "StockAnalyzer/1.0"
_STRIP_SUFFIXES = re.compile(
    r"\b(inc\.?|corp\.?|ltd\.?|llc\.?|plc\.?|co\.?|group|holdings?|technologies?|systems?|services?|solutions?|international|global)\b",
    re.IGNORECASE,
)

# Hand-curated product/brand aliases for tickers where the legal name
# doesn't match how news and Reddit discussions refer to the company.
# Critical for short, common-word tickers (SNAP, F, T) and for brand-heavy
# businesses where "Snapchat" / "YouTube" / "Instagram" is the surface term.
_BRAND_OVERRIDES = {
    "SNAP":  ["Snapchat", "Snap Inc"],
    "META":  ["Meta Platforms", "Facebook", "Instagram", "WhatsApp"],
    "GOOGL": ["Google", "Alphabet", "YouTube"],
    "GOOG":  ["Google", "Alphabet", "YouTube"],
    "AMZN":  ["Amazon", "AWS", "Amazon Web Services"],
    "AAPL":  ["Apple", "iPhone", "iPad", "Mac"],
    "TSLA":  ["Tesla"],
    "NVDA":  ["Nvidia", "GeForce"],
    "NFLX":  ["Netflix"],
    "CMG":   ["Chipotle"],
    "SBUX":  ["Starbucks"],
    "NKE":   ["Nike"],
    "DIS":   ["Disney", "ESPN", "Marvel", "Pixar", "Hulu"],
    "F":     ["Ford Motor", "Ford Motor Company"],
    "GM":    ["General Motors", "Chevrolet", "Cadillac", "GMC"],
    "TGT":   ["Target Corporation", "Target Corp"],
    "WMT":   ["Walmart"],
    "COST":  ["Costco"],
    "HD":    ["Home Depot"],
    "PYPL":  ["PayPal", "Venmo"],
    "SHOP":  ["Shopify"],
    "V":     ["Visa Inc", "Visa"],
    "MA":    ["Mastercard"],
    "JPM":   ["JPMorgan", "JPMorgan Chase", "Chase Bank"],
    "BAC":   ["Bank of America", "Merrill Lynch"],
    "GS":    ["Goldman Sachs"],
    "XOM":   ["ExxonMobil", "Exxon Mobil"],
    "CVX":   ["Chevron"],
    "PFE":   ["Pfizer"],
    "JNJ":   ["Johnson & Johnson", "Johnson and Johnson"],
    "MRK":   ["Merck"],
    "UNH":   ["UnitedHealth", "UnitedHealthcare", "Optum"],
    "LLY":   ["Eli Lilly", "Lilly"],
    "BA":    ["Boeing"],
    "CAT":   ["Caterpillar Inc", "Caterpillar"],
    "DE":    ["John Deere", "Deere & Company"],
    "KO":    ["Coca-Cola", "Coca Cola"],
    "PEP":   ["PepsiCo", "Pepsi", "Frito-Lay", "Gatorade"],
    "MCD":   ["McDonald's", "McDonalds"],
    "ABNB":  ["Airbnb"],
}


def _build_aliases(symbol: str, long_name: Optional[str], short_name: Optional[str]) -> List[str]:
    """Derive a deduplicated list of search aliases for a company."""
    seen = set()  # type: set
    aliases = []  # type: List[str]

    def _add(term: Optional[str]) -> None:
        if not term:
            return
        t = term.strip()
        key = t.lower()
        if key and key not in seen:
            seen.add(key)
            aliases.append(t)

    _add(long_name)
    _add(short_name)

    # Brand alias: short_name stripped of legal suffixes
    if short_name:
        stripped = _STRIP_SUFFIXES.sub("", short_name).strip().rstrip(",.")
        if stripped and stripped.lower() != short_name.lower():
            _add(stripped)

    # Hand-curated brand/product aliases for ambiguous or brand-heavy tickers.
    # Inserted BEFORE the bare symbol so they rank as distinctive search terms.
    for brand in _BRAND_OVERRIDES.get(symbol.upper(), []):
        _add(brand)

    _add(symbol.upper())
    return aliases


def _detect_company_subreddits(symbol: str, short_name: Optional[str]) -> List[str]:
    """Try to discover company-specific subreddits via Reddit's about.json endpoint."""
    found = []  # type: List[str]
    seen = set()  # type: set

    def _add_candidate(name: str) -> None:
        normalized = re.sub(r"[^a-z0-9]", "", name.lower())
        if normalized and normalized not in seen:
            seen.add(normalized)

    _add_candidate(symbol)
    if short_name:
        _add_candidate(short_name)
    # Brand overrides: e.g., SNAP → "snapchat", META → "facebook"/"instagram"
    for brand in _BRAND_OVERRIDES.get(symbol.upper(), []):
        _add_candidate(brand)

    candidates = list(seen)

    for name in candidates:
        if not re.match(r"^[a-zA-Z0-9_]{1,21}$", name):
            continue
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{name}/about.json",
                headers={"User-Agent": _REDDIT_USER_AGENT},
                timeout=2,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                subscribers = data.get("subscribers", 0) or 0
                if subscribers >= 1000:
                    found.append(name)
            time.sleep(0.5)
        except Exception:
            pass

    return found


def refresh_aliases_for_existing_companies() -> int:
    """
    Recompute aliases for every row in `companies` using the current
    _BRAND_OVERRIDES table. Idempotent — safe to run at every startup.
    Returns number of rows updated.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT symbol, name, aliases FROM companies"
    ).fetchall()

    updated = 0
    for symbol, long_name, aliases_json in rows:
        old_aliases = []
        try:
            if aliases_json:
                old_aliases = json.loads(aliases_json)
        except Exception:
            old_aliases = []

        # Re-derive aliases. Use longName for both long_name and short_name
        # since we don't store shortName separately — _build_aliases will
        # dedupe and _STRIP_SUFFIXES still runs.
        new_aliases = _build_aliases(symbol, long_name, long_name)

        # Only write if the set actually changed (normalized comparison)
        if sorted(a.lower() for a in old_aliases) != sorted(a.lower() for a in new_aliases):
            conn.execute(
                "UPDATE companies SET aliases = ?, updated_at = current_timestamp WHERE symbol = ?",
                [json.dumps(new_aliases), symbol],
            )
            updated += 1

    if updated:
        print(f"[aliases] Refreshed aliases for {updated} companies on startup.")
    return updated


def ingest_company(symbol: str) -> dict:
    """Fetch and upsert company metadata, including aliases and company subreddits."""
    ticker = yf.Ticker(symbol)
    info = ticker.info

    long_name = info.get("longName")
    short_name = info.get("shortName")
    aliases = _build_aliases(symbol, long_name, short_name)
    subreddits = _detect_company_subreddits(symbol, short_name)

    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO companies
            (symbol, name, sector, industry, exchange, market_cap, country, website, description,
             aliases, subreddits, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
        """,
        [
            symbol.upper(),
            long_name,
            info.get("sector"),
            info.get("industry"),
            info.get("exchange"),
            info.get("marketCap"),
            info.get("country"),
            info.get("website"),
            info.get("longBusinessSummary"),
            json.dumps(aliases),
            json.dumps(subreddits),
        ],
    )
    return info


def ingest_prices(symbol: str, period: str = "5y") -> int:
    """
    Fetch historical EOD prices and upsert into prices table.
    Returns number of rows inserted/updated.
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, auto_adjust=False)

    if df.empty:
        return 0

    df = df.reset_index()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["symbol"] = symbol.upper()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    conn = get_connection()
    conn.register("price_staging", df)
    conn.execute(
        """
        INSERT OR REPLACE INTO prices (symbol, date, open, high, low, close, adj_close, volume)
        SELECT symbol, date, "open", high, low, close, adj_close, volume::BIGINT
        FROM price_staging
        """
    )
    conn.unregister("price_staging")

    return len(df)


def get_latest_price_date(symbol: str) -> Optional[date]:
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(date) FROM prices WHERE symbol = ?", [symbol.upper()]
    ).fetchone()
    return row[0] if row else None


def ingest_prices_incremental(symbol: str) -> int:
    """Only fetch prices newer than what we already have."""
    latest = get_latest_price_date(symbol)
    if latest is None:
        return ingest_prices(symbol, period="5y")

    # yfinance start param is inclusive
    start = (latest + timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    if start >= today:
        return 0

    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, auto_adjust=False)

    if df.empty:
        return 0

    df = df.reset_index()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["symbol"] = symbol.upper()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    conn = get_connection()
    conn.register("price_staging", df)
    conn.execute(
        """
        INSERT OR REPLACE INTO prices (symbol, date, open, high, low, close, adj_close, volume)
        SELECT symbol, date, "open", high, low, close, adj_close, volume::BIGINT
        FROM price_staging
        """
    )
    conn.unregister("price_staging")

    return len(df)
