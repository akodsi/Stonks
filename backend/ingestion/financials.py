"""
Fetches financial statements via yfinance (free) with FMP as fallback for richer data.
"""
import os
import hashlib
import requests
import yfinance as yf
import pandas as pd
from datetime import date
from typing import List, Optional
from db.connection import get_connection


FMP_BASE = "https://financialmodelingprep.com/api/v3"


def _fmp_key() -> str:
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        raise ValueError("FMP_API_KEY not set in environment")
    return key


# ---------------------------------------------------------------------------
# yfinance ingestion (primary — free, no key required)
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None and str(val) != "nan" else None
    except (TypeError, ValueError):
        return None


def _ingest_statements_yf(symbol: str, period_type: str) -> int:
    """
    period_type: 'annual' | 'quarterly'
    """
    ticker = yf.Ticker(symbol)
    freq = "yearly" if period_type == "annual" else "quarterly"

    income = ticker.get_income_stmt(freq=freq, as_dict=False)
    balance = ticker.get_balance_sheet(freq=freq, as_dict=False)
    cashflow = ticker.get_cash_flow(freq=freq, as_dict=False)

    if income is None or income.empty:
        return 0

    rows = []
    for col in income.columns:
        period_date = pd.to_datetime(col).date()

        def g(df, *keys):
            for k in keys:
                try:
                    v = df.loc[k, col]
                    result = _safe_float(v)
                    if result is not None:
                        return result
                except KeyError:
                    continue
            return None

        revenue = g(income, "TotalRevenue", "Revenue")
        gross_profit = g(income, "GrossProfit")
        operating_income = g(income, "OperatingIncome", "EBIT")
        net_income = g(income, "NetIncome")
        ebitda = g(income, "EBITDA", "NormalizedEBITDA")
        eps = g(income, "BasicEPS", "EPS")
        eps_diluted = g(income, "DilutedEPS")
        shares = g(income, "BasicAverageShares", "DilutedAverageShares")

        total_assets = g(balance, "TotalAssets")
        total_liabilities = g(balance, "TotalLiabilitiesNetMinorityInterest", "TotalLiabilities")
        total_equity = g(balance, "StockholdersEquity", "CommonStockEquity")
        cash = g(balance, "CashAndCashEquivalents", "CashCashEquivalentsAndShortTermInvestments")
        total_debt = g(balance, "TotalDebt", "LongTermDebt")

        operating_cf = g(cashflow, "OperatingCashFlow", "CashFlowFromContinuingOperatingActivities")
        capex = g(cashflow, "CapitalExpenditure")
        fcf = g(cashflow, "FreeCashFlow")
        if fcf is None and operating_cf is not None and capex is not None:
            fcf = operating_cf + capex  # capex is typically negative
        dividends = g(cashflow, "CommonStockDividendPaid", "PaymentOfDividends")

        # SBC is a non-cash expense added back to OCF — material for most
        # tech names and load-bearing for the "GAAP FCF is misleading" story.
        sbc = g(cashflow, "StockBasedCompensation")
        # Buybacks come through yfinance as a negative outflow; we keep the
        # signed value and take magnitude downstream in ratios.
        buybacks = g(cashflow, "RepurchaseOfCapitalStock", "CommonStockPayments")
        interest_paid = g(cashflow, "InterestPaidSupplementalData", "InterestPaid")
        da = g(
            cashflow,
            "DepreciationAmortizationDepletion",
            "DepreciationAndAmortization",
        )

        # Balance-sheet additions: lease liability (ASC 842) and the split
        # between pure cash and short-term investments (T-bills / CDs).
        # cash_and_equiv was previously filled via a fallback to
        # CashCashEquivalentsAndShortTermInvestments — prefer the pure-cash
        # field now that we capture ST investments separately.
        pure_cash = g(balance, "CashAndCashEquivalents")
        if pure_cash is not None:
            cash = pure_cash
        short_term_investments = g(
            balance, "OtherShortTermInvestments", "ShortTermInvestments"
        )
        operating_leases = g(
            balance,
            "OperatingLeaseLiability",
            "LongTermOperatingLease",
            "OperatingLeasesCurrent",
        )

        rows.append({
            "symbol": symbol.upper(),
            "period_type": period_type,
            "period_date": period_date,
            "revenue": revenue,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "net_income": net_income,
            "ebitda": ebitda,
            "eps": eps,
            "eps_diluted": eps_diluted,
            "shares_outstanding": shares,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "cash_and_equiv": cash,
            "total_debt": total_debt,
            "operating_cf": operating_cf,
            "capex": capex,
            "free_cash_flow": fcf,
            "dividends_paid": dividends,
            "sbc": sbc,
            "buybacks": buybacks,
            "interest_paid": interest_paid,
            "depreciation_amortization": da,
            "operating_leases": operating_leases,
            "short_term_investments": short_term_investments,
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    cols = list(df.columns)
    col_list = ", ".join(cols)
    conn = get_connection()
    conn.register("fin_staging", df)
    conn.execute(
        f"""
        INSERT OR REPLACE INTO financials ({col_list})
        SELECT {col_list} FROM fin_staging
        """
    )
    conn.unregister("fin_staging")
    return len(rows)


def ingest_financials(symbol: str) -> dict:
    """Ingest both annual and quarterly statements. Returns row counts."""
    annual = _ingest_statements_yf(symbol, "annual")
    quarterly = _ingest_statements_yf(symbol, "quarterly")
    return {"annual": annual, "quarterly": quarterly}


# ---------------------------------------------------------------------------
# FMP ingestion (richer data, key required — used for earnings transcripts)
# ---------------------------------------------------------------------------

def fetch_fmp_earnings_transcripts(symbol: str, limit: int = 4) -> List[dict]:
    """
    Returns up to `limit` most recent earnings call transcripts from FMP.
    Each item: { quarter, date, content }
    """
    url = f"{FMP_BASE}/earning_call_transcript/{symbol.upper()}?limit={limit}&apikey={_fmp_key()}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def ingest_earnings_transcripts(symbol: str, limit: int = 4) -> int:
    """Fetch and chunk earnings transcripts, upsert into earnings_transcripts table."""
    try:
        transcripts = fetch_fmp_earnings_transcripts(symbol, limit)
    except Exception as e:
        print(f"[transcripts] FMP fetch failed for {symbol}: {e}")
        return 0

    CHUNK_SIZE = 2000  # characters per chunk
    rows = []

    for t in transcripts:
        content = t.get("content", "")
        earnings_date_str = t.get("date", "")
        quarter = t.get("quarter", "") + " " + str(t.get("year", ""))

        try:
            earnings_date = date.fromisoformat(earnings_date_str[:10])
        except ValueError:
            continue

        chunks = [content[i:i + CHUNK_SIZE] for i in range(0, len(content), CHUNK_SIZE)]
        for idx, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(f"{symbol}{earnings_date}{idx}".encode()).hexdigest()
            rows.append({
                "id": chunk_id,
                "symbol": symbol.upper(),
                "earnings_date": earnings_date,
                "quarter": quarter.strip(),
                "chunk_index": idx,
                "chunk_text": chunk,
                "sentiment_score": None,
                "sentiment_label": None,
                "fetched_at": pd.Timestamp.now(),
            })

    if not rows:
        return 0

    # Score chunks with FinBERT
    try:
        from sentiment.finbert import score_texts
        texts = [r["chunk_text"] for r in rows]
        scores = score_texts(texts)
        for r, s in zip(rows, scores):
            r["sentiment_score"] = s["sentiment_score"]
            r["sentiment_label"] = s["sentiment_label"]
    except Exception as e:
        print(f"[transcripts] FinBERT scoring failed for {symbol}: {e}")

    df = pd.DataFrame(rows)
    conn = get_connection()
    conn.register("transcript_staging", df)
    conn.execute("INSERT OR REPLACE INTO earnings_transcripts SELECT * FROM transcript_staging")
    conn.unregister("transcript_staging")
    return len(rows)
