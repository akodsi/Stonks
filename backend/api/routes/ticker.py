import pandas as pd
import numpy as np
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query
from db.connection import get_connection
from ingestion.price import ingest_company, ingest_prices
from ingestion.financials import ingest_financials, ingest_earnings_transcripts
from ingestion.news import ingest_news
from ingestion.reddit import ingest_reddit
from api.sanitize import clean, validate_symbol

router = APIRouter(prefix="/ticker", tags=["ticker"])


@router.get("/search")
def search_tickers(q: str = "", limit: int = Query(default=10, ge=1, le=100)):
    """Search tracked tickers by symbol or name for autocomplete."""
    if not q.strip():
        return []
    conn = get_connection()
    df = conn.execute(
        """
        SELECT symbol, name, sector, market_cap
        FROM companies
        WHERE symbol ILIKE ? OR name ILIKE ?
        ORDER BY
            CASE WHEN symbol ILIKE ? THEN 0 ELSE 1 END,
            symbol
        LIMIT ?
        """,
        [f"{q}%", f"%{q}%", f"{q}%", limit],
    ).fetchdf()
    return clean(df.to_dict(orient="records"))


@router.get("/")
def list_tickers():
    """List all tracked tickers."""
    conn = get_connection()
    df = conn.execute(
        "SELECT symbol, name, sector, market_cap FROM companies ORDER BY symbol"
    ).fetchdf()
    return clean(df.to_dict(orient="records"))


@router.post("/{symbol}/ingest")
def ingest_ticker(symbol: str):
    """
    Trigger full ingestion for a new ticker: metadata, 5y prices, financials.
    """
    symbol = validate_symbol(symbol)
    try:
        ingest_company(symbol)
        price_rows = ingest_prices(symbol, period="5y")
        fin_counts = ingest_financials(symbol)
    except Exception as e:
        print(f"[ingest] Failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed for {symbol}. Check backend logs.")

    # Sentiment ingestion (best-effort — don't fail the whole ingest)
    news_count = 0
    reddit_count = 0
    transcript_count = 0
    try:
        news_count = ingest_news(symbol)
    except Exception as e:
        print(f"[ingest] News failed for {symbol}: {e}")
    try:
        reddit_count = ingest_reddit(symbol)
    except Exception as e:
        print(f"[ingest] Reddit failed for {symbol}: {e}")
    try:
        transcript_count = ingest_earnings_transcripts(symbol)
    except Exception as e:
        print(f"[ingest] Transcripts failed for {symbol}: {e}")

    return {
        "symbol": symbol,
        "price_rows": price_rows,
        "financials": fin_counts,
        "sentiment": {
            "news": news_count,
            "reddit": reddit_count,
            "transcripts": transcript_count,
        },
    }


@router.get("/{symbol}")
def get_ticker(symbol: str):
    """Return company metadata."""
    symbol = validate_symbol(symbol)
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM companies WHERE symbol = ?", [symbol]
    ).fetchdf()

    if row.empty:
        raise HTTPException(status_code=404, detail=f"{symbol} not found. POST /ticker/{symbol}/ingest first.")

    return clean(row.to_dict(orient="records")[0])


@router.get("/{symbol}/prices")
def get_prices(symbol: str, days: int = Query(default=365, ge=1, le=3650)):
    """Return last N days of EOD prices."""
    symbol = validate_symbol(symbol)
    conn = get_connection()
    df = conn.execute(
        """
        SELECT date, open, high, low, close, adj_close, volume
        FROM prices
        WHERE symbol = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        [symbol, days],
    ).fetchdf()

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No price data for {symbol}.")

    df["date"] = df["date"].astype(str)
    return clean(df.to_dict(orient="records"))


@router.get("/{symbol}/financials")
def get_financials(symbol: str, period_type: str = "annual"):
    """Return financial statements. period_type: annual | quarterly"""
    symbol = validate_symbol(symbol)
    if period_type not in ("annual", "quarterly"):
        raise HTTPException(status_code=400, detail="period_type must be 'annual' or 'quarterly'")

    conn = get_connection()
    df = conn.execute(
        """
        SELECT *
        FROM financials
        WHERE symbol = ? AND period_type = ?
        ORDER BY period_date DESC
        """,
        [symbol, period_type],
    ).fetchdf()

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No {period_type} financials for {symbol}.")

    df["period_date"] = df["period_date"].astype(str)
    return clean(df.to_dict(orient="records"))


@router.get("/{symbol}/indicators")
def get_indicators(symbol: str, days: int = Query(default=365, ge=1, le=3650)):
    """Compute technical indicators: RSI, MACD, Bollinger Bands, SMA 50/200."""
    symbol = validate_symbol(symbol)
    conn = get_connection()
    # Fetch extra rows for longest lookback (SMA 200 needs 200 prior points)
    fetch_days = days + 250
    df = conn.execute(
        """
        SELECT date, adj_close AS close FROM (
            SELECT date, adj_close
            FROM prices
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT ?
        ) sub
        ORDER BY date ASC
        """,
        [symbol, fetch_days],
    ).fetchdf()

    if df.empty or len(df) < 26:
        raise HTTPException(status_code=404, detail=f"Not enough price data for {symbol}.")

    close = df["close"].astype(float)
    dates = df["date"].astype(str)

    # RSI (14-period)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.rolling(14, min_periods=14).mean()
    avg_loss = loss.rolling(14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    # Bollinger Bands (20, 2)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20

    # SMA 50 and 200
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    # Trim to requested days
    trim = max(0, len(df) - days)
    s = slice(trim, None)

    def to_list(series):
        return [None if (v != v) else round(float(v), 4) for v in series.iloc[s]]

    return clean({
        "dates": dates.iloc[s].tolist(),
        "rsi": to_list(rsi),
        "macd": {
            "macd": to_list(macd_line),
            "signal": to_list(signal_line),
            "histogram": to_list(histogram),
        },
        "bollinger": {
            "upper": to_list(bb_upper),
            "middle": to_list(sma20),
            "lower": to_list(bb_lower),
        },
        "sma_50": to_list(sma50),
        "sma_200": to_list(sma200),
    })


@router.get("/{symbol}/earnings_dates")
def get_earnings_dates(symbol: str, limit: int = Query(default=16, ge=1, le=40)):
    """Historical earnings announcement dates + EPS surprise for price-chart markers."""
    symbol = validate_symbol(symbol)
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.get_earnings_dates(limit=limit)
    except Exception as e:
        print(f"[earnings_dates] yfinance failed for {symbol}: {e}")
        return []

    if df is None or df.empty:
        return []

    # yfinance returns a DatetimeIndex; columns vary slightly by version.
    df = df.reset_index()
    date_col = next((c for c in df.columns if "date" in c.lower() or "Earnings" in c), df.columns[0])
    df["date"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")

    def _col(name: str):
        return df[name] if name in df.columns else None

    rows = []
    today = pd.Timestamp.utcnow().tz_localize(None).strftime("%Y-%m-%d")
    for idx, r in df.iterrows():
        d = r["date"]
        # Drop future estimates — we only want realized earnings for markers
        if d > today:
            continue
        est = r.get("EPS Estimate") if "EPS Estimate" in df.columns else None
        act = r.get("Reported EPS") if "Reported EPS" in df.columns else None
        surp = r.get("Surprise(%)") if "Surprise(%)" in df.columns else None
        rows.append({
            "date": d,
            "eps_estimate": None if pd.isna(est) else float(est),
            "eps_actual": None if pd.isna(act) else float(act),
            "surprise_pct": None if pd.isna(surp) else float(surp),
        })
    return clean(rows)
