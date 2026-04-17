from fastapi import APIRouter, HTTPException
from db.connection import get_connection
from fundamentals.ratios import get_ratios, compute_ratios, get_sector_medians
from api.sanitize import clean, validate_symbol

router = APIRouter(prefix="/ticker", tags=["fundamentals"])


@router.get("/{symbol}/ratios")
def ratios(symbol: str, period_type: str = "annual"):
    symbol = validate_symbol(symbol)
    if period_type not in ("annual", "quarterly"):
        raise HTTPException(status_code=400, detail="period_type must be 'annual' or 'quarterly'")
    data = get_ratios(symbol, period_type)
    if not data:
        raise HTTPException(status_code=404, detail=f"No ratios for {symbol}. Ingest financials first.")
    return clean(data)


@router.post("/{symbol}/ratios/refresh")
def refresh_ratios(symbol: str, period_type: str = "annual"):
    symbol = validate_symbol(symbol)
    data = compute_ratios(symbol, period_type)
    if not data:
        raise HTTPException(status_code=404, detail=f"No financials to compute ratios for {symbol}.")
    return clean({"computed": len(data), "data": data})


@router.get("/{symbol}/tearsheet")
def tearsheet(symbol: str):
    """
    Full tearsheet: company info + latest ratios + multi-year financials trend
    + sector peer medians.
    """
    symbol = validate_symbol(symbol)
    conn = get_connection()

    # Company
    company = conn.execute(
        "SELECT * FROM companies WHERE symbol = ?", [symbol]
    ).fetchdf()
    if company.empty:
        raise HTTPException(status_code=404, detail=f"{symbol} not found.")

    # Latest price + 52w high/low
    price_data = conn.execute(
        """
        SELECT
            adj_close                                    AS price,
            MAX(high) OVER (ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high_52w,
            MIN(low)  OVER (ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS low_52w,
            date
        FROM prices
        WHERE symbol = ?
        ORDER BY date DESC
        LIMIT 1
        """,
        [symbol],
    ).fetchdf()

    # Annual ratios (all years)
    ratios = get_ratios(symbol, "annual")

    # Multi-year financials for trend charts (oldest first).
    # sbc is surfaced so the FCF-vs-SBC chart can render without another round-trip.
    financials = conn.execute(
        """
        SELECT period_date, revenue, gross_profit, operating_income, net_income,
               ebitda, eps_diluted, free_cash_flow, total_debt, total_equity,
               sbc, buybacks, interest_paid, operating_leases, short_term_investments
        FROM financials
        WHERE symbol = ? AND period_type = 'annual'
        ORDER BY period_date ASC
        """,
        [symbol],
    ).fetchdf()
    financials["period_date"] = financials["period_date"].astype(str)

    # Sector peer medians
    peers = get_sector_medians(symbol)

    return clean({
        "company": company.to_dict(orient="records")[0],
        "price_snapshot": price_data.to_dict(orient="records")[0] if not price_data.empty else {},
        "ratios": ratios,
        "financials_trend": financials.to_dict(orient="records"),
        "sector_medians": peers,
    })
