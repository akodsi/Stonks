"""
Computes financial ratios from stored financials + latest price.
All ratios are computed on-the-fly from DuckDB and stored in the ratios table.
"""
from typing import Dict, List, Optional
import pandas as pd
from db.connection import get_connection


def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _yoy_growth(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / prior


def get_latest_price(symbol: str) -> Optional[float]:
    conn = get_connection()
    row = conn.execute(
        "SELECT adj_close FROM prices WHERE symbol = ? ORDER BY date DESC LIMIT 1",
        [symbol],
    ).fetchone()
    return row[0] if row else None


def compute_ratios(symbol: str, period_type: str = "annual") -> List[dict]:
    """
    Compute all ratios for a symbol across all available periods.
    Stores results in the ratios table and returns them.
    """
    conn = get_connection()
    df = conn.execute(
        """
        SELECT * FROM financials
        WHERE symbol = ? AND period_type = ?
        ORDER BY period_date DESC
        """,
        [symbol, period_type],
    ).fetchdf()

    if df.empty:
        return []

    price = get_latest_price(symbol)
    market_cap = conn.execute(
        "SELECT market_cap FROM companies WHERE symbol = ?", [symbol]
    ).fetchone()
    mkt_cap = market_cap[0] if market_cap else None

    rows = []
    periods = df.to_dict(orient="records")

    for i, p in enumerate(periods):
        prior = periods[i + 1] if i + 1 < len(periods) else None

        rev = p.get("revenue")
        gp = p.get("gross_profit")
        op_inc = p.get("operating_income")
        net_inc = p.get("net_income")
        ebitda = p.get("ebitda")
        eps = p.get("eps_diluted") or p.get("eps")
        shares = p.get("shares_outstanding")
        assets = p.get("total_assets")
        liabilities = p.get("total_liabilities")
        equity = p.get("total_equity")
        cash = p.get("cash_and_equiv")
        debt = p.get("total_debt")
        op_cf = p.get("operating_cf")
        capex = p.get("capex")
        fcf = p.get("free_cash_flow")
        sbc = p.get("sbc")
        buybacks_raw = p.get("buybacks")  # yfinance returns this as a negative outflow
        interest_paid = p.get("interest_paid")
        op_leases = p.get("operating_leases") or 0.0

        # Enterprise value
        ev = None
        if mkt_cap and debt is not None and cash is not None:
            ev = mkt_cap + debt - cash

        # Book value per share
        bvps = _safe_div(equity, shares) if shares else None

        # --- Valuation ---
        pe = _safe_div(price, eps) if price else None
        pb = _safe_div(price, bvps) if price and bvps else None
        ev_ebitda = _safe_div(ev, ebitda)
        p_fcf = _safe_div(mkt_cap, fcf)
        p_sales = _safe_div(mkt_cap, rev)

        # --- Profitability ---
        gross_margin = _safe_div(gp, rev)
        op_margin = _safe_div(op_inc, rev)
        net_margin = _safe_div(net_inc, rev)
        roe = _safe_div(net_inc, equity)
        roa = _safe_div(net_inc, assets)
        # ROIC simplified: NOPAT / (equity + debt - cash)
        invested_capital = None
        if equity is not None and debt is not None and cash is not None:
            invested_capital = equity + debt - cash
        roic = _safe_div(net_inc, invested_capital)

        # --- Leverage ---
        d_e = _safe_div(debt, equity)
        # Interest coverage = operating income / interest paid. Uses the
        # cash-flow interest_paid row (InterestPaidSupplementalData) which
        # yfinance populates for most names; null-safe when missing.
        interest_coverage = (
            _safe_div(op_inc, abs(interest_paid))
            if interest_paid is not None and interest_paid != 0
            else None
        )
        # Current ratio needs current assets/liabilities — not in our schema yet; skip
        current_ratio = None
        # Lease-aware D/E — adds ASC 842 operating-lease liability to debt so
        # lease-heavy businesses (airlines, retail) aren't understated.
        total_debt_incl_leases = (debt or 0.0) + op_leases if debt is not None else None
        debt_incl_leases_to_equity = _safe_div(total_debt_incl_leases, equity)

        # --- Additional profitability / quality ---
        ebitda_margin = _safe_div(ebitda, rev)
        fcf_margin = _safe_div(fcf, rev)
        cash_to_debt = _safe_div(cash, debt)
        ocf_to_ni = _safe_div(op_cf, net_inc)

        # --- SBC-aware FCF ---
        # GAAP FCF adds SBC back to OCF because SBC is non-cash, but SBC is
        # still a real cost to shareholders (dilution). Subtracting it gives
        # a closer proxy to "cash available after paying employees in full".
        fcf_ex_sbc = (fcf - sbc) if (fcf is not None and sbc is not None) else None
        fcf_margin_ex_sbc = _safe_div(fcf_ex_sbc, rev)
        price_to_fcf_ex_sbc = _safe_div(mkt_cap, fcf_ex_sbc)
        sbc_to_revenue = _safe_div(sbc, rev) if sbc is not None else None
        # Net dilution = SBC − buybacks. Positive means shareholders are being
        # net-diluted; negative means the company is out-repurchasing comp.
        net_dilution = None
        if sbc is not None:
            buybacks_abs = abs(buybacks_raw) if buybacks_raw is not None else 0.0
            net_dilution = sbc - buybacks_abs
        net_dilution_to_revenue = _safe_div(net_dilution, rev)

        # --- Growth (YoY) ---
        rev_growth = _yoy_growth(rev, prior.get("revenue") if prior else None)
        ni_growth = _yoy_growth(net_inc, prior.get("net_income") if prior else None)
        eps_growth = _yoy_growth(eps, prior.get("eps_diluted") or prior.get("eps") if prior else None)
        fcf_growth = _yoy_growth(fcf, prior.get("free_cash_flow") if prior else None)

        rows.append({
            "symbol": symbol,
            "period_type": period_type,
            "period_date": p["period_date"],
            "pe_ratio": pe,
            "pb_ratio": pb,
            "ev_ebitda": ev_ebitda,
            "price_to_fcf": p_fcf,
            "price_to_sales": p_sales,
            "gross_margin": gross_margin,
            "operating_margin": op_margin,
            "net_margin": net_margin,
            "roe": roe,
            "roa": roa,
            "roic": roic,
            "debt_to_equity": d_e,
            "interest_coverage": interest_coverage,
            "current_ratio": current_ratio,
            "revenue_growth": rev_growth,
            "net_income_growth": ni_growth,
            "eps_growth": eps_growth,
            "fcf_growth": fcf_growth,
            "ebitda_margin": ebitda_margin,
            "fcf_margin": fcf_margin,
            "cash_to_debt": cash_to_debt,
            "ocf_to_net_income": ocf_to_ni,
            "fcf_ex_sbc": fcf_ex_sbc,
            "fcf_margin_ex_sbc": fcf_margin_ex_sbc,
            "price_to_fcf_ex_sbc": price_to_fcf_ex_sbc,
            "sbc_to_revenue": sbc_to_revenue,
            "net_dilution_to_revenue": net_dilution_to_revenue,
            "debt_incl_leases_to_equity": debt_incl_leases_to_equity,
        })

    if rows:
        ratio_df = pd.DataFrame(rows)
        cols = list(ratio_df.columns)
        col_list = ", ".join(cols)
        conn.register("ratio_staging", ratio_df)
        conn.execute(
            f"INSERT OR REPLACE INTO ratios ({col_list}) "
            f"SELECT {col_list} FROM ratio_staging"
        )
        conn.unregister("ratio_staging")

    return rows


def get_ratios(symbol: str, period_type: str = "annual") -> List[dict]:
    """Return stored ratios, recomputing if stale or missing."""
    conn = get_connection()
    df = conn.execute(
        """
        SELECT * FROM ratios
        WHERE symbol = ? AND period_type = ?
        ORDER BY period_date DESC
        """,
        [symbol, period_type],
    ).fetchdf()

    if df.empty:
        return compute_ratios(symbol, period_type)

    df["period_date"] = df["period_date"].astype(str)
    return df.to_dict(orient="records")


def get_sector_medians(symbol: str) -> dict:
    """
    Compute median ratios for all companies in the same sector (from tracked universe).
    Returns a flat dict of median values for the most recent annual period per company.
    """
    conn = get_connection()

    sector_row = conn.execute(
        "SELECT sector FROM companies WHERE symbol = ?", [symbol]
    ).fetchone()

    if not sector_row or not sector_row[0]:
        return {}

    sector = sector_row[0]

    # Latest annual ratio per company in same sector
    df = conn.execute(
        """
        SELECT r.*
        FROM ratios r
        JOIN companies c ON r.symbol = c.symbol
        WHERE c.sector = ?
          AND r.period_type = 'annual'
          AND r.symbol != ?
          AND r.period_date = (
              SELECT MAX(r2.period_date)
              FROM ratios r2
              WHERE r2.symbol = r.symbol AND r2.period_type = 'annual'
          )
        """,
        [sector, symbol],
    ).fetchdf()

    if df.empty:
        return {"sector": sector, "peer_count": 0}

    numeric_cols = [
        "pe_ratio", "pb_ratio", "ev_ebitda", "price_to_fcf", "price_to_sales",
        "gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic",
        "debt_to_equity", "interest_coverage", "current_ratio",
        "revenue_growth", "net_income_growth", "eps_growth", "fcf_growth",
        "ebitda_margin", "fcf_margin", "cash_to_debt", "ocf_to_net_income",
        "fcf_ex_sbc", "fcf_margin_ex_sbc", "price_to_fcf_ex_sbc",
        "sbc_to_revenue", "net_dilution_to_revenue", "debt_incl_leases_to_equity",
    ]

    medians = {"sector": sector, "peer_count": len(df)}
    for col in numeric_cols:
        if col in df.columns:
            val = df[col].dropna().median()
            medians[col] = None if pd.isna(val) else float(val)

    return medians
