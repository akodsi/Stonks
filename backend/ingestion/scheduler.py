"""
APScheduler jobs for daily EOD data refresh.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import List
from db.connection import get_connection
from ingestion.price import ingest_prices_incremental, ingest_company
from ingestion.financials import ingest_financials
from ingestion.news import ingest_news
from ingestion.reddit import ingest_reddit


def get_tracked_symbols() -> List[str]:
    conn = get_connection()
    rows = conn.execute("SELECT symbol FROM companies").fetchall()
    return [r[0] for r in rows]


def daily_price_refresh():
    symbols = get_tracked_symbols()
    for symbol in symbols:
        try:
            n = ingest_prices_incremental(symbol)
            print(f"[scheduler] {symbol}: {n} new price rows")
        except Exception as e:
            print(f"[scheduler] price refresh failed for {symbol}: {e}")


def weekly_fundamentals_refresh():
    symbols = get_tracked_symbols()
    for symbol in symbols:
        try:
            counts = ingest_financials(symbol)
            print(f"[scheduler] {symbol} financials: {counts}")
        except Exception as e:
            print(f"[scheduler] financials refresh failed for {symbol}: {e}")


def daily_sentiment_refresh():
    """Refresh news and Reddit sentiment for all tracked tickers."""
    symbols = get_tracked_symbols()
    for symbol in symbols:
        try:
            ingest_news(symbol)
        except Exception as e:
            print(f"[scheduler] news refresh failed for {symbol}: {e}")
        try:
            ingest_reddit(symbol)
        except Exception as e:
            print(f"[scheduler] reddit refresh failed for {symbol}: {e}")


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()

    # Daily at 6pm ET (after US market close)
    scheduler.add_job(
        daily_price_refresh,
        CronTrigger(hour=18, minute=0, timezone="America/New_York"),
        id="daily_price_refresh",
        replace_existing=True,
    )

    # Weekly on Sunday at 8am ET (earnings/financials don't change daily)
    scheduler.add_job(
        weekly_fundamentals_refresh,
        CronTrigger(day_of_week="sun", hour=8, minute=0, timezone="America/New_York"),
        id="weekly_fundamentals_refresh",
        replace_existing=True,
    )

    # Daily at 7pm ET (after prices, before next trading day)
    scheduler.add_job(
        daily_sentiment_refresh,
        CronTrigger(hour=19, minute=0, timezone="America/New_York"),
        id="daily_sentiment_refresh",
        replace_existing=True,
    )

    return scheduler
