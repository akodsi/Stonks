"""
Portfolio tracker API routes — CRUD for holdings + returns + benchmark comparison.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db.connection import get_connection
from api.sanitize import clean, validate_symbol

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_DEFAULT_BENCHMARK = "SPY"


class HoldingCreate(BaseModel):
    symbol: str
    shares: float
    cost_basis: float
    purchase_date: Optional[str] = None
    notes: Optional[str] = None


class HoldingUpdate(BaseModel):
    shares: Optional[float] = None
    cost_basis: Optional[float] = None
    purchase_date: Optional[str] = None
    notes: Optional[str] = None


@router.get("/holdings")
def list_holdings():
    """Return all portfolio holdings with current prices and P&L."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT h.id, h.symbol, h.shares, h.cost_basis, h.purchase_date, h.notes, h.added_at,
               c.name, c.sector, c.industry, c.market_cap
        FROM portfolio_holdings h
        LEFT JOIN companies c ON h.symbol = c.symbol
        ORDER BY h.added_at DESC
        """
    ).fetchdf()

    if rows.empty:
        return []

    holdings = []  # type: List[Dict[str, Any]]
    for _, r in rows.iterrows():
        symbol = r["symbol"]

        # Get latest price
        price_row = conn.execute(
            "SELECT adj_close FROM prices WHERE symbol = ? ORDER BY date DESC LIMIT 1",
            [symbol],
        ).fetchone()
        current_price = float(price_row[0]) if price_row and price_row[0] is not None else None

        shares = float(r["shares"])
        cost_basis = float(r["cost_basis"])
        avg_cost = cost_basis / shares if shares > 0 else 0
        market_value = current_price * shares if current_price is not None else None
        gain_loss = (market_value - cost_basis) if market_value is not None else None
        gain_loss_pct = (gain_loss / cost_basis) if gain_loss is not None and cost_basis > 0 else None

        holdings.append({
            "id": int(r["id"]),
            "symbol": symbol,
            "name": r["name"],
            "sector": r["sector"],
            "shares": shares,
            "cost_basis": cost_basis,
            "avg_cost": round(avg_cost, 2),
            "current_price": current_price,
            "market_value": round(market_value, 2) if market_value is not None else None,
            "gain_loss": round(gain_loss, 2) if gain_loss is not None else None,
            "gain_loss_pct": round(gain_loss_pct, 4) if gain_loss_pct is not None else None,
            "purchase_date": str(r["purchase_date"]) if r["purchase_date"] else None,
            "notes": r["notes"],
        })

    return clean(holdings)


@router.post("/holdings")
def add_holding(body: HoldingCreate):
    """Add a new holding to the portfolio."""
    symbol = validate_symbol(body.symbol)
    conn = get_connection()

    # Verify company exists
    exists = conn.execute(
        "SELECT symbol FROM companies WHERE symbol = ?", [symbol]
    ).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail=f"{symbol} not found. Ingest it first.")

    # Atomic ID generation + insert to avoid race conditions
    purchase_date_val = body.purchase_date if body.purchase_date else None
    new_id = conn.execute(
        """
        INSERT INTO portfolio_holdings (id, symbol, shares, cost_basis, purchase_date, notes)
        VALUES ((SELECT COALESCE(MAX(id), 0) + 1 FROM portfolio_holdings), ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [symbol, body.shares, body.cost_basis, purchase_date_val, body.notes],
    ).fetchone()[0]

    return {"id": new_id, "symbol": symbol, "added": True}


@router.put("/holdings/{holding_id}")
def update_holding(holding_id: int, body: HoldingUpdate):
    """Update an existing holding."""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM portfolio_holdings WHERE id = ?", [holding_id]
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Holding not found.")

    updates = []  # type: List[str]
    params = []  # type: List[Any]

    if body.shares is not None:
        updates.append("shares = ?")
        params.append(body.shares)
    if body.cost_basis is not None:
        updates.append("cost_basis = ?")
        params.append(body.cost_basis)
    if body.purchase_date is not None:
        updates.append("purchase_date = ?")
        params.append(body.purchase_date)
    if body.notes is not None:
        updates.append("notes = ?")
        params.append(body.notes)

    if not updates:
        return {"updated": False}

    params.append(holding_id)
    conn.execute(
        f"UPDATE portfolio_holdings SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    return {"id": holding_id, "updated": True}


@router.delete("/holdings/{holding_id}")
def delete_holding(holding_id: int):
    """Remove a holding from the portfolio."""
    conn = get_connection()
    conn.execute("DELETE FROM portfolio_holdings WHERE id = ?", [holding_id])
    return {"id": holding_id, "deleted": True}


@router.get("/summary")
def portfolio_summary():
    """
    Portfolio-level summary: total value, total cost, total gain/loss,
    allocation breakdown, and benchmark comparison.
    """
    conn = get_connection()

    holdings_df = conn.execute(
        "SELECT symbol, shares, cost_basis, purchase_date FROM portfolio_holdings"
    ).fetchdf()

    if holdings_df.empty:
        return clean({
            "total_cost": 0,
            "total_value": 0,
            "total_gain_loss": 0,
            "total_gain_loss_pct": None,
            "holdings_count": 0,
            "allocations": [],
            "benchmark": None,
        })

    total_cost = 0.0
    total_value = 0.0
    allocations = []  # type: List[Dict[str, Any]]

    for _, row in holdings_df.iterrows():
        symbol = row["symbol"]
        shares = float(row["shares"])
        cost = float(row["cost_basis"])

        price_row = conn.execute(
            "SELECT adj_close FROM prices WHERE symbol = ? ORDER BY date DESC LIMIT 1",
            [symbol],
        ).fetchone()
        current_price = float(price_row[0]) if price_row and price_row[0] is not None else 0.0

        mv = current_price * shares
        total_cost += cost
        total_value += mv
        allocations.append({
            "symbol": symbol,
            "market_value": round(mv, 2),
            "weight": 0.0,  # filled below
        })

    # Compute weights
    for a in allocations:
        a["weight"] = round(a["market_value"] / total_value, 4) if total_value > 0 else 0

    total_gl = total_value - total_cost
    total_gl_pct = (total_gl / total_cost) if total_cost > 0 else None

    # ── Benchmark comparison ──
    # Find the earliest purchase_date and compute benchmark return since then
    benchmark = _get_benchmark_comparison(conn, holdings_df)

    return clean({
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_gain_loss": round(total_gl, 2),
        "total_gain_loss_pct": round(total_gl_pct, 4) if total_gl_pct is not None else None,
        "holdings_count": len(holdings_df),
        "allocations": allocations,
        "benchmark": benchmark,
    })


@router.get("/performance")
def portfolio_performance(days: int = Query(default=365, ge=1, le=3650)):
    """
    Daily portfolio value + benchmark value over time for charting.
    """
    conn = get_connection()

    holdings_df = conn.execute(
        "SELECT symbol, shares, cost_basis, purchase_date FROM portfolio_holdings"
    ).fetchdf()

    if holdings_df.empty:
        return clean({"dates": [], "portfolio_values": [], "benchmark_values": []})

    # Get all unique symbols
    symbols = holdings_df["symbol"].unique().tolist()

    # Get the benchmark symbol
    benchmark_sym = _get_benchmark_symbol(conn)

    # Fetch price data for all holdings + benchmark
    all_symbols = list(set(symbols + [benchmark_sym]))

    import pandas as pd
    price_frames = {}  # type: Dict[str, Any]
    for sym in all_symbols:
        pdf = conn.execute(
            """
            SELECT date, adj_close
            FROM prices
            WHERE symbol = ?
              AND date >= CURRENT_DATE - make_interval(days => ?)
            ORDER BY date
            """,
            [sym, int(days)],
        ).fetchdf()
        if not pdf.empty:
            price_frames[sym] = pdf.set_index("date")["adj_close"]

    if not price_frames:
        return clean({"dates": [], "portfolio_values": [], "benchmark_values": []})

    # Build a common date index
    all_dates = set()  # type: set
    for series in price_frames.values():
        all_dates.update(series.index.tolist())
    sorted_dates = sorted(all_dates)

    # Compute daily portfolio value
    portfolio_values = []  # type: List[float]
    for d in sorted_dates:
        daily_val = 0.0
        for _, row in holdings_df.iterrows():
            sym = row["symbol"]
            shares = float(row["shares"])
            if sym in price_frames:
                series = price_frames[sym]
                # Use latest available price on or before this date
                valid = series[series.index <= d]
                if not valid.empty:
                    daily_val += float(valid.iloc[-1]) * shares
        portfolio_values.append(round(daily_val, 2))

    # Compute benchmark series (normalized to portfolio start value)
    benchmark_values = []  # type: List[Optional[float]]
    if benchmark_sym in price_frames:
        bench_series = price_frames[benchmark_sym]
        first_valid = None  # type: Optional[float]
        start_val = portfolio_values[0] if portfolio_values else 0
        for d in sorted_dates:
            valid = bench_series[bench_series.index <= d]
            if not valid.empty:
                if first_valid is None:
                    first_valid = float(valid.iloc[-1])
                current = float(valid.iloc[-1])
                # Normalize: benchmark starts at same value as portfolio
                bench_val = (current / first_valid) * start_val if first_valid else 0
                benchmark_values.append(round(bench_val, 2))
            else:
                benchmark_values.append(None)
    else:
        benchmark_values = [None] * len(sorted_dates)

    return clean({
        "dates": [str(d) for d in sorted_dates],
        "portfolio_values": portfolio_values,
        "benchmark_values": benchmark_values,
        "benchmark_symbol": benchmark_sym,
    })


@router.get("/benchmark")
def get_benchmark():
    """Get the current benchmark symbol."""
    conn = get_connection()
    return {"benchmark": _get_benchmark_symbol(conn)}


@router.put("/benchmark/{symbol}")
def set_benchmark(symbol: str):
    """Set the benchmark symbol (e.g. SPY, QQQ, IWM)."""
    symbol = validate_symbol(symbol)
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO portfolio_settings (key, value) VALUES ('benchmark', ?)
        ON CONFLICT (key) DO UPDATE SET value = ?
        """,
        [symbol, symbol],
    )
    return {"benchmark": symbol}


def _get_benchmark_symbol(conn) -> str:
    """Get benchmark symbol from settings, default to SPY."""
    row = conn.execute(
        "SELECT value FROM portfolio_settings WHERE key = 'benchmark'"
    ).fetchone()
    return row[0] if row else _DEFAULT_BENCHMARK


def _get_benchmark_comparison(conn, holdings_df) -> Optional[Dict[str, Any]]:
    """Compute benchmark return over the portfolio holding period."""
    import pandas as pd

    # Find earliest purchase date
    valid_dates = holdings_df["purchase_date"].dropna()
    if valid_dates.empty:
        return None

    try:
        earliest = pd.Timestamp(valid_dates.min())
    except Exception:
        return None

    benchmark_sym = _get_benchmark_symbol(conn)

    bench_df = conn.execute(
        """
        SELECT date, adj_close FROM prices
        WHERE symbol = ?
        ORDER BY date ASC
        """,
        [benchmark_sym],
    ).fetchdf()

    if bench_df.empty:
        return None

    bench_df["date"] = pd.to_datetime(bench_df["date"])
    # Find price at or after earliest purchase date
    start_rows = bench_df[bench_df["date"] >= earliest]
    if start_rows.empty:
        return None

    start_price = float(start_rows.iloc[0]["adj_close"])
    end_price = float(bench_df.iloc[-1]["adj_close"])

    if start_price <= 0:
        return None

    bench_return = (end_price - start_price) / start_price

    return {
        "symbol": benchmark_sym,
        "return_pct": round(bench_return, 4),
        "start_date": str(start_rows.iloc[0]["date"].date()),
        "start_price": round(start_price, 2),
        "end_price": round(end_price, 2),
    }
