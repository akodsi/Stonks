"""
Narrative API routes — AI-generated analyst memos via Ollama.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from db.connection import get_connection
from api.sanitize import clean, validate_symbol
from narrative.ollama_client import (
    is_available,
    generate_stream,
    OllamaUnavailableError,
    OLLAMA_MODEL,
)
from narrative.prompts import (
    build_tearsheet_prompt,
    build_bull_bear_prompt,
    build_risk_prompt,
    build_sentiment_prompt,
)

router = APIRouter(prefix="/ticker", tags=["narratives"])

VALID_TYPES = ["tearsheet", "bull_bear", "risk", "sentiment_digest"]

# Per-type generation budget. Tight ceilings force punchy output;
# risk runs cool since it's factual, others warmer for voice.
_GEN_CONFIG = {
    "tearsheet":        {"max_tokens": 900, "temperature": 0.7},
    "bull_bear":        {"max_tokens": 600, "temperature": 0.7},
    "risk":             {"max_tokens": 600, "temperature": 0.4},
    "sentiment_digest": {"max_tokens": 900, "temperature": 0.7},
}


def _fetch_tearsheet_data(symbol: str) -> dict:
    """Fetch tearsheet bundle directly from DB (mirrors fundamentals.tearsheet)."""
    from fundamentals.ratios import get_ratios, get_sector_medians

    conn = get_connection()

    company = conn.execute(
        "SELECT * FROM companies WHERE symbol = ?", [symbol]
    ).fetchdf()
    if company.empty:
        raise HTTPException(status_code=404, detail=f"{symbol} not found.")

    price_data = conn.execute(
        """
        SELECT
            adj_close AS price,
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

    ratios = get_ratios(symbol, "annual")

    financials = conn.execute(
        """
        SELECT period_date, revenue, gross_profit, operating_income, net_income,
               ebitda, eps_diluted, free_cash_flow, total_debt, total_equity
        FROM financials
        WHERE symbol = ? AND period_type = 'annual'
        ORDER BY period_date ASC
        """,
        [symbol],
    ).fetchdf()
    financials["period_date"] = financials["period_date"].astype(str)

    peers = get_sector_medians(symbol)

    return {
        "company": company.to_dict(orient="records")[0],
        "price_snapshot": price_data.to_dict(orient="records")[0] if not price_data.empty else {},
        "ratios": ratios,
        "financials_trend": financials.to_dict(orient="records"),
        "sector_medians": peers,
    }


def _fetch_sentiment_buckets(symbol: str) -> dict:
    """Split sentiment into 3 time buckets (7d / 30d / 90d) for trend detection."""
    conn = get_connection()

    news_buckets_df = conn.execute(
        """
        SELECT
            CASE
                WHEN published_at >= CURRENT_TIMESTAMP - INTERVAL '7 days' THEN 'last_7d'
                WHEN published_at >= CURRENT_TIMESTAMP - INTERVAL '30 days' THEN '8_30d'
                ELSE '31_90d'
            END AS bucket,
            AVG(sentiment_score) AS avg_score,
            COUNT(*) AS cnt
        FROM news
        WHERE symbol = ?
          AND published_at >= CURRENT_TIMESTAMP - INTERVAL '90 days'
        GROUP BY bucket
        """,
        [symbol],
    ).fetchdf()

    reddit_buckets_df = conn.execute(
        """
        SELECT
            CASE
                WHEN created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days' THEN 'last_7d'
                WHEN created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days' THEN '8_30d'
                ELSE '31_90d'
            END AS bucket,
            AVG(sentiment_score) AS avg_score,
            COUNT(*) AS cnt
        FROM reddit_posts
        WHERE symbol = ?
          AND created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days'
        GROUP BY bucket
        """,
        [symbol],
    ).fetchdf()

    def _to_dict(df):
        result = {}
        for _, row in df.iterrows():
            result[row["bucket"]] = {
                "avg_score": float(row["avg_score"]) if row["avg_score"] is not None else None,
                "count": int(row["cnt"]),
            }
        return result

    return {
        "news_buckets": _to_dict(news_buckets_df),
        "reddit_buckets": _to_dict(reddit_buckets_df),
    }


def _fetch_sentiment_data(symbol: str, days: int = 90) -> dict:
    """Fetch sentiment summary directly from DB (mirrors sentiment route)."""
    conn = get_connection()
    days_int = int(days)

    news_df = conn.execute(
        """
        SELECT title, source, sentiment_score, sentiment_label,
               summary, published_at
        FROM news
        WHERE symbol = ?
          AND published_at >= CURRENT_TIMESTAMP - make_interval(days => ?)
        ORDER BY published_at DESC
        LIMIT 10
        """,
        [symbol, days_int],
    ).fetchdf()

    reddit_df = conn.execute(
        """
        SELECT title, sentiment_score, sentiment_label,
               body, subreddit, score, num_comments, created_at
        FROM reddit_posts
        WHERE symbol = ?
          AND created_at >= CURRENT_TIMESTAMP - make_interval(days => ?)
        ORDER BY score DESC
        LIMIT 10
        """,
        [symbol, days_int],
    ).fetchdf()

    # Full average for composite weighting (unbiased)
    earnings_avg_df = conn.execute(
        """
        SELECT AVG(sentiment_score) AS avg_score
        FROM earnings_transcripts
        WHERE symbol = ? AND sentiment_score IS NOT NULL
        """,
        [symbol],
    ).fetchdf()

    # Top 3 most sentiment-charged transcript excerpts for prompt context
    earnings_excerpts_df = conn.execute(
        """
        SELECT chunk_text, sentiment_score, quarter, earnings_date
        FROM earnings_transcripts
        WHERE symbol = ? AND sentiment_score IS NOT NULL
        ORDER BY ABS(sentiment_score) DESC
        LIMIT 3
        """,
        [symbol],
    ).fetchdf()

    news_avg = None  # type: Optional[float]
    if not news_df.empty and not news_df["sentiment_score"].dropna().empty:
        news_avg = float(news_df["sentiment_score"].dropna().mean())

    reddit_avg = None  # type: Optional[float]
    if not reddit_df.empty and not reddit_df["sentiment_score"].dropna().empty:
        reddit_avg = float(reddit_df["sentiment_score"].dropna().mean())

    earnings_avg = None  # type: Optional[float]
    if not earnings_avg_df.empty:
        val = earnings_avg_df["avg_score"].iloc[0]
        if val is not None:
            earnings_avg = float(val)

    earnings_excerpts = []  # type: list
    if not earnings_excerpts_df.empty:
        for _, row in earnings_excerpts_df.iterrows():
            earnings_excerpts.append({
                "text": row.get("chunk_text", ""),
                "score": float(row["sentiment_score"]) if row.get("sentiment_score") is not None else None,
                "quarter": row.get("quarter", ""),
                "date": str(row.get("earnings_date", "")),
            })

    # Composite
    sources = []
    if news_avg is not None:
        sources.append((news_avg, 0.4))
    if reddit_avg is not None:
        sources.append((reddit_avg, 0.3))
    if earnings_avg is not None:
        sources.append((earnings_avg, 0.3))

    composite_score = None  # type: Optional[float]
    composite_label = "neutral"
    if sources:
        total_weight = sum(w for _, w in sources)
        composite_score = sum(s * w for s, w in sources) / total_weight
        if composite_score > 0.15:
            composite_label = "positive"
        elif composite_score < -0.15:
            composite_label = "negative"

    # Temporal buckets for trend detection
    buckets = _fetch_sentiment_buckets(symbol)

    return {
        "news": {
            "articles": news_df.to_dict(orient="records") if not news_df.empty else [],
            "avg_score": news_avg,
            "count": len(news_df),
        },
        "reddit": {
            "posts": reddit_df.to_dict(orient="records") if not reddit_df.empty else [],
            "avg_score": reddit_avg,
            "count": len(reddit_df),
        },
        "earnings": {
            "avg_score": earnings_avg,
            "excerpts": earnings_excerpts,
        },
        "composite": {
            "score": round(composite_score, 4) if composite_score is not None else None,
            "label": composite_label,
        },
        "buckets": buckets,
    }


def _build_prompt(narrative_type: str, tearsheet: dict, sentiment: Optional[dict]) -> str:
    if narrative_type == "tearsheet":
        return build_tearsheet_prompt(tearsheet)
    elif narrative_type == "bull_bear":
        return build_bull_bear_prompt(tearsheet)
    elif narrative_type == "risk":
        return build_risk_prompt(tearsheet)
    elif narrative_type == "sentiment_digest":
        return build_sentiment_prompt(tearsheet, sentiment)
    raise ValueError(f"Unknown narrative type: {narrative_type}")


def _stream_and_cache(symbol: str, narrative_type: str, prompt: str):
    """Generator that yields SSE chunks and caches the full result when done."""
    import json as _json
    full_text = ""
    cfg = _GEN_CONFIG.get(narrative_type, {"max_tokens": 800, "temperature": 0.7})
    try:
        for chunk in generate_stream(
            prompt,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        ):
            full_text += chunk
            # JSON-encode so newlines inside the chunk don't break SSE framing
            yield f"data: {_json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

        # Cache
        conn = get_connection()
        today = date.today().isoformat()
        conn.execute(
            """
            INSERT OR REPLACE INTO narratives (symbol, narrative_type, generated_date, content, model)
            VALUES (?, ?, ?, ?, ?)
            """,
            [symbol, narrative_type, today, full_text, OLLAMA_MODEL],
        )
    except OllamaUnavailableError as e:
        yield f"data: [ERROR] {_json.dumps(str(e))}\n\n"


@router.get("/{symbol}/narratives")
def get_narratives(symbol: str):
    """Return cached narratives for today + Ollama availability."""
    symbol = validate_symbol(symbol)
    conn = get_connection()
    today = date.today().isoformat()

    df = conn.execute(
        "SELECT narrative_type, content, model, generated_date "
        "FROM narratives WHERE symbol = ? AND generated_date = ?",
        [symbol, today],
    ).fetchdf()

    available = is_available()
    result = {
        "ollama_available": available,
        "narratives": {},
    }

    if not df.empty:
        for row in df.to_dict(orient="records"):
            result["narratives"][row["narrative_type"]] = {
                "content": row["content"],
                "model": row["model"],
                "generated_date": str(row["generated_date"]),
            }

    return clean(result)


@router.get("/{symbol}/narratives/stream")
def stream_narrative(symbol: str, type: str = "tearsheet"):
    """Stream a narrative via SSE."""
    symbol = validate_symbol(symbol)
    if type not in VALID_TYPES:
        raise HTTPException(400, f"type must be one of {VALID_TYPES}")

    if not is_available():
        raise HTTPException(503, "Local AI model is not available. Check backend logs.")

    tearsheet = _fetch_tearsheet_data(symbol)
    sentiment = _fetch_sentiment_data(symbol) if type == "sentiment_digest" else None
    prompt = _build_prompt(type, tearsheet, sentiment)

    return StreamingResponse(
        _stream_and_cache(symbol, type, prompt),
        media_type="text/event-stream",
    )


@router.post("/{symbol}/narratives/regenerate")
def regenerate_narrative(symbol: str, type: str = "tearsheet"):
    """Delete today's cache and re-stream."""
    symbol = validate_symbol(symbol)
    if type not in VALID_TYPES:
        raise HTTPException(400, f"type must be one of {VALID_TYPES}")

    if not is_available():
        raise HTTPException(503, "Local AI model is not available. Check backend logs.")

    # Clear cache
    conn = get_connection()
    today = date.today().isoformat()
    conn.execute(
        "DELETE FROM narratives WHERE symbol = ? AND narrative_type = ? AND generated_date = ?",
        [symbol, type, today],
    )

    tearsheet = _fetch_tearsheet_data(symbol)
    sentiment = _fetch_sentiment_data(symbol) if type == "sentiment_digest" else None
    prompt = _build_prompt(type, tearsheet, sentiment)

    return StreamingResponse(
        _stream_and_cache(symbol, type, prompt),
        media_type="text/event-stream",
    )
