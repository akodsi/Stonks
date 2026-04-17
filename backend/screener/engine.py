"""
Stock screener engine — filters the ratios table by user-defined criteria.
Includes preset screens and CRUD for saved custom screens.
"""
import json
from typing import Any, Dict, List, Optional
from db.connection import get_connection
from api.sanitize import clean


# ── Allowed fields & operators (SQL injection prevention) ─────────────────

ALLOWED_FIELDS = {
    "pe_ratio", "pb_ratio", "ev_ebitda", "price_to_fcf", "price_to_sales",
    "gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic",
    "debt_to_equity", "interest_coverage", "current_ratio",
    "revenue_growth", "net_income_growth", "eps_growth", "fcf_growth",
}

ALLOWED_OPERATORS = {"<", ">", "<=", ">=", "=", "!="}


# ── Preset screen definitions ────────────────────────────────────────────

PRESETS: Dict[str, List[Dict[str, Any]]] = {
    "value": [
        {"field": "pe_ratio", "operator": "<", "value": 20},
        {"field": "pb_ratio", "operator": "<", "value": 3},
        {"field": "price_to_fcf", "operator": "<", "value": 20},
        {"field": "ev_ebitda", "operator": "<", "value": 15},
    ],
    "growth": [
        {"field": "revenue_growth", "operator": ">", "value": 0.10},
        {"field": "eps_growth", "operator": ">", "value": 0.10},
        {"field": "net_income_growth", "operator": ">", "value": 0.10},
    ],
    "quality": [
        {"field": "gross_margin", "operator": ">", "value": 0.40},
        {"field": "roe", "operator": ">", "value": 0.15},
        {"field": "roic", "operator": ">", "value": 0.12},
        {"field": "debt_to_equity", "operator": "<", "value": 1.0},
    ],
    "momentum": [
        {"field": "revenue_growth", "operator": ">", "value": 0.15},
        {"field": "eps_growth", "operator": ">", "value": 0.20},
        {"field": "fcf_growth", "operator": ">", "value": 0.10},
    ],
    "dividend": [
        {"field": "pe_ratio", "operator": "<", "value": 25},
        {"field": "debt_to_equity", "operator": "<", "value": 1.5},
        {"field": "net_margin", "operator": ">", "value": 0.05},
    ],
}


# ── Filter engine ────────────────────────────────────────────────────────

def run_screen(criteria: List[Dict[str, Any]]) -> List[dict]:
    """
    Run a screen against the most recent annual ratio per symbol.
    Each criterion: {"field": str, "operator": str, "value": float}
    Returns list of matching rows with company metadata.
    """
    # Validate criteria
    for c in criteria:
        if c["field"] not in ALLOWED_FIELDS:
            raise ValueError(f"Invalid field: {c['field']}")
        if c["operator"] not in ALLOWED_OPERATORS:
            raise ValueError(f"Invalid operator: {c['operator']}")

    # Build dynamic WHERE clauses
    where_parts = []
    params = []  # type: List[Any]
    for c in criteria:
        where_parts.append(f"latest.{c['field']} {c['operator']} ?")
        params.append(float(c["value"]))

    # Always start with rn = 1, then append user criteria
    filter_parts = ["latest.rn = 1"] + where_parts
    where_sql = "WHERE " + " AND ".join(filter_parts)

    sql = f"""
        WITH latest AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY period_date DESC) AS rn
            FROM ratios
            WHERE period_type = 'annual'
        )
        SELECT
            latest.symbol,
            c.name,
            c.sector,
            c.industry,
            c.market_cap,
            latest.period_date,
            latest.pe_ratio,
            latest.pb_ratio,
            latest.ev_ebitda,
            latest.price_to_fcf,
            latest.price_to_sales,
            latest.gross_margin,
            latest.operating_margin,
            latest.net_margin,
            latest.roe,
            latest.roa,
            latest.roic,
            latest.debt_to_equity,
            latest.revenue_growth,
            latest.net_income_growth,
            latest.eps_growth,
            latest.fcf_growth
        FROM latest
        JOIN companies c ON latest.symbol = c.symbol
        {where_sql}
        ORDER BY latest.symbol
    """

    conn = get_connection()
    df = conn.execute(sql, params).fetchdf()

    if df.empty:
        return []

    df["period_date"] = df["period_date"].astype(str)
    return clean(df.to_dict(orient="records"))


# ── Saved screens CRUD ───────────────────────────────────────────────────

def save_screen(name: str, criteria: List[Dict[str, Any]]) -> None:
    """Save or update a custom screen."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO saved_screens (name, criteria_json, created_at, updated_at)
        VALUES (?, ?, current_timestamp, current_timestamp)
        ON CONFLICT (name) DO UPDATE SET
            criteria_json = EXCLUDED.criteria_json,
            updated_at    = current_timestamp
        """,
        [name, json.dumps(criteria)],
    )


def load_screen(name: str) -> Optional[List[Dict[str, Any]]]:
    """Load a saved screen's criteria by name. Returns None if not found."""
    conn = get_connection()
    row = conn.execute(
        "SELECT criteria_json FROM saved_screens WHERE name = ?", [name]
    ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def list_screens() -> List[Dict[str, Any]]:
    """List all saved custom screens."""
    conn = get_connection()
    df = conn.execute(
        "SELECT name, criteria_json, created_at, updated_at FROM saved_screens ORDER BY name"
    ).fetchdf()
    if df.empty:
        return []
    rows = df.to_dict(orient="records")
    for r in rows:
        r["criteria"] = json.loads(r.pop("criteria_json"))
        r["created_at"] = str(r["created_at"])
        r["updated_at"] = str(r["updated_at"])
    return rows


def delete_screen(name: str) -> bool:
    """Delete a saved screen. Returns True if it existed."""
    conn = get_connection()
    existing = conn.execute(
        "SELECT 1 FROM saved_screens WHERE name = ?", [name]
    ).fetchone()
    if not existing:
        return False
    conn.execute("DELETE FROM saved_screens WHERE name = ?", [name])
    return True
