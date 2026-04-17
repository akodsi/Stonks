from fastapi import APIRouter, HTTPException
from db.connection import get_connection
from api.sanitize import clean, validate_symbol

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("/")
def list_watchlist():
    """Return all watchlist entries with company metadata."""
    conn = get_connection()
    df = conn.execute(
        """
        SELECT w.symbol, c.name, c.sector, c.industry, c.market_cap, w.added_at
        FROM watchlist w
        LEFT JOIN companies c ON w.symbol = c.symbol
        ORDER BY w.added_at DESC
        """
    ).fetchdf()
    if "added_at" in df.columns:
        df["added_at"] = df["added_at"].astype(str)
    return clean(df.to_dict(orient="records"))


@router.get("/{symbol}")
def check_watchlist(symbol: str):
    """Check if a symbol is in the watchlist."""
    symbol = validate_symbol(symbol)
    conn = get_connection()
    row = conn.execute(
        "SELECT symbol FROM watchlist WHERE symbol = ?", [symbol]
    ).fetchone()
    return {"in_watchlist": row is not None}


@router.post("/{symbol}")
def add_to_watchlist(symbol: str):
    """Add a symbol to the watchlist."""
    symbol = validate_symbol(symbol)
    conn = get_connection()
    # Verify the company exists
    exists = conn.execute(
        "SELECT symbol FROM companies WHERE symbol = ?", [symbol]
    ).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail=f"{symbol} not found. Ingest it first.")

    conn.execute(
        """
        INSERT INTO watchlist (symbol) VALUES (?)
        ON CONFLICT (symbol) DO NOTHING
        """,
        [symbol],
    )
    return {"symbol": symbol, "added": True}


@router.delete("/{symbol}")
def remove_from_watchlist(symbol: str):
    """Remove a symbol from the watchlist."""
    symbol = validate_symbol(symbol)
    conn = get_connection()
    conn.execute("DELETE FROM watchlist WHERE symbol = ?", [symbol])
    return {"symbol": symbol, "removed": True}
