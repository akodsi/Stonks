"""
Sentiment API routes — fetch and aggregate sentiment data for a ticker.
"""
import math
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from db.connection import get_connection
from api.sanitize import clean, validate_symbol

router = APIRouter(prefix="/ticker", tags=["sentiment"])

_RECENCY_HALF_LIFE_DAYS = 14.0  # exponential decay half-life for news recency weighting


def _recency_weight(published_at_str: str, now_ts: Any) -> float:
    """Exponential decay weight based on age in days."""
    try:
        import pandas as pd
        ts = pd.Timestamp(published_at_str)
        delta_days = max((now_ts - ts).total_seconds() / 86400.0, 0.0)
        return math.exp(-0.693 * delta_days / _RECENCY_HALF_LIFE_DAYS)
    except Exception:
        return 1.0


def _distribution(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count positive/neutral/negative labels in a list of rows."""
    d = {"positive": 0, "neutral": 0, "negative": 0}
    for r in rows:
        label = (r.get("sentiment_label") or "neutral").lower()
        if label in d:
            d[label] += 1
    return d


def _recency_weighted_avg(rows: List[Dict[str, Any]], date_field: str, now_ts: Any) -> Optional[float]:
    """Compute exponentially recency-weighted average sentiment score."""
    total_w = 0.0
    total_sw = 0.0
    for r in rows:
        sc = r.get("sentiment_score")
        if sc is None:
            continue
        w = _recency_weight(str(r.get(date_field, "")), now_ts)
        total_w += w
        total_sw += float(sc) * w
    if total_w == 0:
        return None
    return round(total_sw / total_w, 4)


def _time_bucket_score(rows: List[Dict[str, Any]], date_field: str, now_ts: Any) -> Dict[str, Any]:
    """Compute average scores for last_7d, 8_30d, and 31_90d buckets."""
    import pandas as pd
    buckets = {
        "last_7d": {"scores": [], "count": 0},
        "8_30d": {"scores": [], "count": 0},
        "31_90d": {"scores": [], "count": 0},
    }
    for r in rows:
        sc = r.get("sentiment_score")
        if sc is None:
            continue
        try:
            ts = pd.Timestamp(str(r.get(date_field, "")))
            age_days = (now_ts - ts).total_seconds() / 86400.0
        except Exception:
            continue
        if age_days <= 7:
            buckets["last_7d"]["scores"].append(float(sc))
            buckets["last_7d"]["count"] += 1
        elif age_days <= 30:
            buckets["8_30d"]["scores"].append(float(sc))
            buckets["8_30d"]["count"] += 1
        elif age_days <= 90:
            buckets["31_90d"]["scores"].append(float(sc))
            buckets["31_90d"]["count"] += 1

    result = {}
    for key, data in buckets.items():
        scores = data["scores"]
        result[key] = {
            "score": round(sum(scores) / len(scores), 4) if scores else None,
            "count": data["count"],
        }
    return result


def _derive_momentum(buckets: Dict[str, Any]) -> str:
    """Compare last_7d vs 8_30d to derive a momentum label."""
    recent = (buckets.get("last_7d") or {}).get("score")
    older = (buckets.get("8_30d") or {}).get("score")
    if recent is None or older is None:
        return "stable"
    diff = recent - older
    if diff > 0.05:
        return "improving"
    elif diff < -0.05:
        return "deteriorating"
    return "stable"


@router.get("/sentiment/overview")
def sentiment_overview(days: int = Query(default=30, ge=1, le=3650)):
    """
    Return sentiment summary for ALL tracked tickers — used by the dedicated Sentiment page.
    Shows composite score, momentum, article/post counts, and trend for each ticker.
    """
    import pandas as pd

    conn = get_connection()
    days_int = int(days)

    symbols_rows = conn.execute("SELECT symbol FROM companies ORDER BY symbol").fetchall()
    symbols = [r[0] for r in symbols_rows]

    results = []  # type: List[Dict[str, Any]]
    for sym in symbols:
        news_row = conn.execute(
            """
            SELECT AVG(sentiment_score) AS avg_score, COUNT(*) AS cnt
            FROM news
            WHERE symbol = ?
              AND published_at >= CURRENT_TIMESTAMP - make_interval(days => ?)
              AND sentiment_score IS NOT NULL
            """,
            [sym, days_int],
        ).fetchone()
        news_avg = float(news_row[0]) if news_row and news_row[0] is not None else None
        news_count = int(news_row[1]) if news_row else 0

        reddit_row = conn.execute(
            """
            SELECT AVG(sentiment_score) AS avg_score, COUNT(*) AS cnt
            FROM reddit_posts
            WHERE symbol = ?
              AND created_at >= CURRENT_TIMESTAMP - make_interval(days => ?)
              AND sentiment_score IS NOT NULL
            """,
            [sym, days_int],
        ).fetchone()
        reddit_avg = float(reddit_row[0]) if reddit_row and reddit_row[0] is not None else None
        reddit_count = int(reddit_row[1]) if reddit_row else 0

        earnings_row = conn.execute(
            """
            SELECT AVG(sentiment_score) AS avg_score
            FROM earnings_transcripts
            WHERE symbol = ? AND sentiment_score IS NOT NULL
            """,
            [sym],
        ).fetchone()
        earnings_avg = float(earnings_row[0]) if earnings_row and earnings_row[0] is not None else None

        # Composite
        sources = []  # type: List[tuple]
        if news_avg is not None:
            sources.append((news_avg, 0.4))
        if reddit_avg is not None:
            sources.append((reddit_avg, 0.3))
        if earnings_avg is not None:
            sources.append((earnings_avg, 0.3))

        composite = None  # type: Optional[float]
        if sources:
            tw = sum(w for _, w in sources)
            composite = sum(s * w for s, w in sources) / tw

        # Quick momentum: 7d vs 8-30d
        recent_row = conn.execute(
            f"""
            SELECT AVG(sentiment_score) FROM (
                SELECT sentiment_score FROM news
                WHERE symbol = ? AND published_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
                  AND sentiment_score IS NOT NULL
                UNION ALL
                SELECT sentiment_score FROM reddit_posts
                WHERE symbol = ? AND created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
                  AND sentiment_score IS NOT NULL
            )
            """,
            [sym, sym],
        ).fetchone()
        older_row = conn.execute(
            f"""
            SELECT AVG(sentiment_score) FROM (
                SELECT sentiment_score FROM news
                WHERE symbol = ?
                  AND published_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                  AND published_at < CURRENT_TIMESTAMP - INTERVAL '7 days'
                  AND sentiment_score IS NOT NULL
                UNION ALL
                SELECT sentiment_score FROM reddit_posts
                WHERE symbol = ?
                  AND created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                  AND created_at < CURRENT_TIMESTAMP - INTERVAL '7 days'
                  AND sentiment_score IS NOT NULL
            )
            """,
            [sym, sym],
        ).fetchone()

        recent_score = float(recent_row[0]) if recent_row and recent_row[0] is not None else None
        older_score = float(older_row[0]) if older_row and older_row[0] is not None else None

        if recent_score is not None and older_score is not None:
            diff = recent_score - older_score
            momentum = "improving" if diff > 0.05 else ("deteriorating" if diff < -0.05 else "stable")
        else:
            momentum = "stable"

        name_row = conn.execute(
            "SELECT name, sector FROM companies WHERE symbol = ?", [sym]
        ).fetchone()

        if news_count == 0 and reddit_count == 0 and earnings_avg is None:
            continue

        label = "neutral"
        if composite is not None:
            if composite > 0.15:
                label = "positive"
            elif composite < -0.15:
                label = "negative"

        results.append({
            "symbol": sym,
            "name": name_row[0] if name_row else sym,
            "sector": name_row[1] if name_row else None,
            "composite_score": round(composite, 4) if composite is not None else None,
            "composite_label": label,
            "momentum": momentum,
            "news_avg": round(news_avg, 4) if news_avg is not None else None,
            "news_count": news_count,
            "reddit_avg": round(reddit_avg, 4) if reddit_avg is not None else None,
            "reddit_count": reddit_count,
            "earnings_avg": round(earnings_avg, 4) if earnings_avg is not None else None,
        })

    results.sort(key=lambda r: abs(r.get("composite_score") or 0), reverse=True)
    return clean(results)


@router.get("/{symbol}/sentiment")
def get_sentiment(symbol: str, days: int = Query(default=90, ge=1, le=3650)):
    """
    Return aggregated sentiment data: news, reddit (investor + consumer), earnings transcripts.
    Includes distribution counts, recency-weighted averages, momentum, and time buckets.
    """
    import pandas as pd

    symbol = validate_symbol(symbol)
    conn = get_connection()
    now_ts = pd.Timestamp.now()
    days_int = int(days)

    # ── News ──────────────────────────────────────────────────────────
    news_df = conn.execute(
        """
        SELECT id, title, source, url, published_at, summary,
               sentiment_score, sentiment_label,
               COALESCE(source_tier, 3) AS source_tier,
               full_text
        FROM news
        WHERE symbol = ?
          AND published_at >= CURRENT_TIMESTAMP - make_interval(days => ?)
          AND sentiment_score IS NOT NULL
        ORDER BY published_at DESC
        """,
        [symbol, days_int],
    ).fetchdf()

    news_articles = []  # type: List[Dict[str, Any]]
    news_avg = None  # type: Optional[float]
    news_recency_avg = None  # type: Optional[float]
    news_ts = []  # type: List[Dict[str, Any]]
    news_dist = {"positive": 0, "neutral": 0, "negative": 0}
    news_top_movers = []  # type: List[Dict[str, Any]]

    if not news_df.empty:
        news_df["published_at"] = news_df["published_at"].astype(str)
        news_articles = news_df.to_dict(orient="records")
        valid_scores = news_df["sentiment_score"].dropna()
        news_avg = float(valid_scores.mean()) if not valid_scores.empty else None
        news_recency_avg = _recency_weighted_avg(news_articles, "published_at", now_ts)
        news_dist = _distribution(news_articles)

        # Top movers: articles with highest absolute deviation from the 30d average
        if news_avg is not None and len(news_articles) > 3:
            scored = [
                (abs(float(a["sentiment_score"]) - news_avg), a)
                for a in news_articles
                if a.get("sentiment_score") is not None
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            news_top_movers = [a for _, a in scored[:3]]

        ts_df = conn.execute(
            """
            SELECT CAST(published_at AS DATE) AS date,
                   AVG(sentiment_score) AS score,
                   COUNT(*) AS count
            FROM news
            WHERE symbol = ?
              AND published_at >= CURRENT_TIMESTAMP - make_interval(days => ?)
            GROUP BY CAST(published_at AS DATE)
            ORDER BY date
            """,
            [symbol, days_int],
        ).fetchdf()
        if not ts_df.empty:
            ts_df["date"] = ts_df["date"].astype(str)
            news_ts = ts_df.to_dict(orient="records")

    # ── Reddit (split by source_type) ─────────────────────────────────
    reddit_df = conn.execute(
        """
        SELECT id, title, subreddit, body, url, score, num_comments,
               created_at, sentiment_score, sentiment_label,
               COALESCE(source_type, 'investor') AS source_type
        FROM reddit_posts
        WHERE symbol = ?
          AND created_at >= CURRENT_TIMESTAMP - make_interval(days => ?)
          AND sentiment_score IS NOT NULL
        ORDER BY created_at DESC
        """,
        [symbol, days_int],
    ).fetchdf()

    investor_posts = []  # type: List[Dict[str, Any]]
    consumer_posts = []  # type: List[Dict[str, Any]]
    reddit_ts = []  # type: List[Dict[str, Any]]

    if not reddit_df.empty:
        reddit_df["created_at"] = reddit_df["created_at"].astype(str)
        all_reddit = reddit_df.to_dict(orient="records")

        # Add relative engagement labels based on percentile rank within this result set
        scores_list = sorted(
            [r["score"] for r in all_reddit if r.get("score") is not None]
        )
        if len(scores_list) >= 3:
            p20 = scores_list[max(0, int(len(scores_list) * 0.2) - 1)]
            p80 = scores_list[min(len(scores_list) - 1, int(len(scores_list) * 0.8))]
            for post in all_reddit:
                s = post.get("score") or 0
                if s >= p80:
                    post["engagement_label"] = "high"
                elif s <= p20:
                    post["engagement_label"] = "low"
                else:
                    post["engagement_label"] = "medium"

        # Split by source_type
        for post in all_reddit:
            st = post.get("source_type", "investor")
            if st == "investor":
                investor_posts.append(post)
            else:
                # company + industry both go to consumer/community track
                consumer_posts.append(post)

        ts_df = conn.execute(
            """
            SELECT CAST(created_at AS DATE) AS date,
                   AVG(sentiment_score) AS score,
                   COUNT(*) AS count
            FROM reddit_posts
            WHERE symbol = ?
              AND created_at >= CURRENT_TIMESTAMP - make_interval(days => ?)
            GROUP BY CAST(created_at AS DATE)
            ORDER BY date
            """,
            [symbol, days_int],
        ).fetchdf()
        if not ts_df.empty:
            ts_df["date"] = ts_df["date"].astype(str)
            reddit_ts = ts_df.to_dict(orient="records")

    def _avg(rows: List[Dict[str, Any]]) -> Optional[float]:
        scores = [float(r["sentiment_score"]) for r in rows if r.get("sentiment_score") is not None]
        return round(sum(scores) / len(scores), 4) if scores else None

    # Merge comment-level sentiment into post dicts (from reddit_comments table)
    try:
        comment_agg_df = conn.execute(
            """
            SELECT post_id,
                   AVG(sentiment_score) AS comment_avg_score,
                   COUNT(*) AS comment_count
            FROM reddit_comments
            WHERE symbol = ?
            GROUP BY post_id
            """,
            [symbol],
        ).fetchdf()
        if not comment_agg_df.empty:
            comment_map = {
                row["post_id"]: {
                    "comment_avg_score": row["comment_avg_score"],
                    "comment_count": int(row["comment_count"]),
                }
                for row in comment_agg_df.to_dict(orient="records")
            }
            for post in (investor_posts + consumer_posts):
                pid = post.get("id", "")
                if pid in comment_map:
                    post.update(comment_map[pid])
    except Exception:
        pass  # reddit_comments table may not exist yet on first run

    investor_avg = _avg(investor_posts)
    consumer_avg = _avg(consumer_posts)
    # Combined reddit avg for backward-compat composite calc
    all_reddit_rows = investor_posts + consumer_posts
    reddit_avg = _avg(all_reddit_rows)

    # ── Earnings transcripts ──────────────────────────────────────────
    earnings_df = conn.execute(
        """
        SELECT quarter, earnings_date,
               AVG(sentiment_score) AS avg_score,
               COUNT(*) AS chunk_count
        FROM earnings_transcripts
        WHERE symbol = ?
          AND sentiment_score IS NOT NULL
        GROUP BY quarter, earnings_date
        ORDER BY earnings_date DESC
        """,
        [symbol],
    ).fetchdf()

    earnings_calls = []  # type: List[Dict[str, Any]]
    earnings_avg = None  # type: Optional[float]
    earnings_excerpts = []  # type: List[Dict[str, Any]]

    if not earnings_df.empty:
        earnings_df["earnings_date"] = earnings_df["earnings_date"].astype(str)
        earnings_calls = earnings_df.to_dict(orient="records")
        earnings_avg = float(earnings_df["avg_score"].dropna().mean()) if not earnings_df["avg_score"].dropna().empty else None

        # Build rich excerpts: for each of the 3 most recent earnings calls, find the
        # chunk with highest ABS sentiment, then return that chunk + adjacent chunks
        # for narrative continuity. Prefer executive/guidance sections when detectable.
        import re as _re
        _EXEC_PATTERN = _re.compile(
            r"^\s*(CEO|CFO|PRESIDENT|CHIEF EXECUTIVE|CHIEF FINANCIAL|OPERATOR"
            r"|MODERATOR|THANK YOU|GOOD MORNING|GOOD AFTERNOON)",
            _re.IGNORECASE,
        )

        recent_calls = earnings_calls[:3]  # 3 most recent
        for call in recent_calls:
            q = call["quarter"]
            ed = call["earnings_date"]

            # Fetch all chunks for this call
            chunks_df = conn.execute(
                """
                SELECT chunk_index, chunk_text, sentiment_score
                FROM earnings_transcripts
                WHERE symbol = ? AND quarter = ? AND earnings_date = ?
                  AND sentiment_score IS NOT NULL
                ORDER BY chunk_index
                """,
                [symbol, q, ed],
            ).fetchdf()

            if chunks_df.empty:
                continue

            chunks = chunks_df.to_dict(orient="records")

            # Prefer executive-sounding chunks; fall back to highest-ABS chunk
            exec_chunks = [
                c for c in chunks if _EXEC_PATTERN.match(c.get("chunk_text", ""))
            ]
            candidate_pool = exec_chunks if len(exec_chunks) >= 2 else chunks

            # Find anchor chunk with highest ABS sentiment score
            anchor = max(candidate_pool, key=lambda c: abs(float(c["sentiment_score"])))
            anchor_idx = anchor["chunk_index"]

            # Gather anchor + up to 1 chunk before and 1 after for context
            idx_set = {anchor_idx - 1, anchor_idx, anchor_idx + 1}
            passage_chunks = [c for c in chunks if c["chunk_index"] in idx_set]
            passage_chunks.sort(key=lambda c: c["chunk_index"])

            combined_text = " ".join(c["chunk_text"] for c in passage_chunks)
            avg_score = sum(float(c["sentiment_score"]) for c in passage_chunks) / len(passage_chunks)

            # Detect speaker type from first line of anchor chunk
            first_line = anchor.get("chunk_text", "").strip().split("\n")[0]
            if _re.match(r"^\s*(CEO|CFO|PRESIDENT|CHIEF EXECUTIVE|CHIEF FINANCIAL)", first_line, _re.IGNORECASE):
                speaker_type = "executive remarks"
            elif _re.match(r"^\s*(ANALYST|QUESTION|Q&A)", first_line, _re.IGNORECASE):
                speaker_type = "analyst Q&A"
            elif _re.match(r"^\s*(OPERATOR|MODERATOR)", first_line, _re.IGNORECASE):
                speaker_type = "operator/moderator"
            else:
                speaker_type = ""

            earnings_excerpts.append({
                "quarter": q,
                "earnings_date": ed,
                "text": combined_text,
                "score": round(avg_score, 4),
                "speaker_type": speaker_type,
            })

    # ── Composite score ───────────────────────────────────────────────
    sources = []  # type: List[tuple]
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

    # ── Time buckets + momentum ───────────────────────────────────────
    all_scored_rows = news_articles + all_reddit_rows
    # Use published_at for news, created_at for reddit
    combined_for_buckets = []
    for r in news_articles:
        combined_for_buckets.append({"sentiment_score": r.get("sentiment_score"), "ts": r.get("published_at", "")})
    for r in all_reddit_rows:
        combined_for_buckets.append({"sentiment_score": r.get("sentiment_score"), "ts": r.get("created_at", "")})

    time_buckets = _time_bucket_score(combined_for_buckets, "ts", now_ts)
    momentum = _derive_momentum(time_buckets)

    return clean({
        "news": {
            "articles": news_articles,
            "avg_score": news_avg,
            "recency_weighted_avg": news_recency_avg,
            "count": len(news_articles),
            "distribution": news_dist,
            "time_series": news_ts,
            "top_movers": news_top_movers,
        },
        "reddit": {
            "investor": {
                "items": investor_posts,
                "avg_score": investor_avg,
                "count": len(investor_posts),
                "distribution": _distribution(investor_posts),
            },
            "consumer": {
                "items": consumer_posts,
                "avg_score": consumer_avg,
                "count": len(consumer_posts),
                "distribution": _distribution(consumer_posts),
            },
            # Backward-compatible flat fields
            "posts": all_reddit_rows,
            "avg_score": reddit_avg,
            "count": len(all_reddit_rows),
            "time_series": reddit_ts,
        },
        "earnings": {
            "calls": earnings_calls,
            "avg_score": earnings_avg,
            "excerpts": earnings_excerpts,
        },
        "composite": {
            "score": round(composite_score, 4) if composite_score is not None else None,
            "label": composite_label,
            "momentum": momentum,
            "time_buckets": time_buckets,
        },
    })


@router.post("/{symbol}/sentiment/refresh")
def refresh_sentiment(symbol: str):
    """Trigger fresh ingestion of news, Reddit, and earnings transcripts."""
    symbol = validate_symbol(symbol)
    from ingestion.news import ingest_news
    from ingestion.reddit import ingest_reddit
    from ingestion.financials import ingest_earnings_transcripts

    news_count = 0
    reddit_count = 0
    transcript_count = 0

    try:
        news_count = ingest_news(symbol)
    except Exception as e:
        print(f"[sentiment] News ingestion failed for {symbol}: {e}")

    try:
        reddit_count = ingest_reddit(symbol)
    except Exception as e:
        print(f"[sentiment] Reddit ingestion failed for {symbol}: {e}")

    try:
        transcript_count = ingest_earnings_transcripts(symbol)
    except Exception as e:
        print(f"[sentiment] Transcript ingestion failed for {symbol}: {e}")

    return {
        "symbol": symbol,
        "news": news_count,
        "reddit": reddit_count,
        "transcripts": transcript_count,
    }
