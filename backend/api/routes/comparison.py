from typing import List
from fastapi import APIRouter, HTTPException, Query
from db.connection import get_connection
from fundamentals.ratios import get_ratios, get_sector_medians
from api.sanitize import clean

router = APIRouter(prefix="/compare", tags=["comparison"])


@router.get("/")
def compare_stocks(symbols: str = Query(..., description="Comma-separated symbols, 2-3")):
    """Compare 2-3 stocks: metadata, ratios, normalized price series."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if len(sym_list) < 2 or len(sym_list) > 3:
        raise HTTPException(status_code=400, detail="Provide 2-3 comma-separated symbols.")

    conn = get_connection()

    # Fetch company metadata
    companies = []
    for sym in sym_list:
        row = conn.execute(
            "SELECT symbol, name, sector, industry, market_cap FROM companies WHERE symbol = ?",
            [sym],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"{sym} not found. Ingest it first.")
        companies.append({
            "symbol": row[0],
            "name": row[1],
            "sector": row[2],
            "industry": row[3],
            "market_cap": row[4],
        })

    # Fetch latest annual ratios for each symbol
    ratios = {}
    for sym in sym_list:
        sym_ratios = get_ratios(sym, "annual")
        if sym_ratios:
            latest = sym_ratios[0]  # already sorted desc
            ratios[sym] = latest
        else:
            ratios[sym] = {}

    # Fetch normalized price series (% change from first date)
    price_series = {}
    for sym in sym_list:
        df = conn.execute(
            """
            SELECT date, adj_close FROM (
                SELECT date, adj_close
                FROM prices
                WHERE symbol = ?
                ORDER BY date DESC
                LIMIT 365
            ) sub
            ORDER BY date ASC
            """,
            [sym],
        ).fetchdf()

        if not df.empty and len(df) > 0:
            base = df["adj_close"].iloc[0]
            if base and base != 0:
                pct = ((df["adj_close"] / base) - 1) * 100
                price_series[sym] = {
                    "dates": df["date"].astype(str).tolist(),
                    "pct_change": [round(float(v), 2) if v == v else 0 for v in pct],
                }

    # Sector medians from first symbol
    sector_med = get_sector_medians(sym_list[0])

    return clean({
        "companies": companies,
        "ratios": ratios,
        "price_series": price_series,
        "sector_medians": sector_med,
    })
