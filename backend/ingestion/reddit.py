"""
Fetches Reddit posts via the public JSON API (no auth, no PRAW) and scores with FinBERT.

Two-track coverage model:
  - DD / analytical subs (r/stocks, r/investing, r/SecurityAnalysis, ...) are
    searched with the *company name and distinctive aliases* — these communities
    talk about "Snapchat" and "Ford Motor" rather than tickers.
  - Speculative / trading subs (r/wallstreetbets, r/options, ...) are searched
    primarily by cashtag ($TICKER) because that's the dominant linguistic form.

Posts are de-duped across subs, merged from `sort=top` (week) and `sort=new`
to catch both cooked discussions and fresh breaking-news threads, and accepted
via the shared ingestion.relevance.is_relevant ladder so a bare "snap" doesn't
masquerade as coverage of Snap Inc.
"""
import json
import time
import requests
import pandas as pd
from collections import Counter
from typing import List, Optional, Tuple
from urllib.parse import quote
from db.connection import get_connection
from sentiment.finbert import score_texts
from ingestion.relevance import (
    is_relevant,
    is_common_word_ticker,
    distinctive_aliases,
)

USER_AGENT = "StockAnalyzer/1.0"

# Post score or comment count that promotes a post to comment-level scoring.
# Lowered from 100 → 50 because many high-quality DD threads on smaller subs
# (r/SecurityAnalysis, r/ValueInvesting) rarely cross 100 upvotes but still
# carry dense analytical comment threads worth scoring.
_HIGH_ENGAGEMENT_SCORE = 50
_HIGH_ENGAGEMENT_COMMENTS = 50

# Analytical subs — prefer name / alias queries. These communities use the
# company's brand, not cashtags.
DD_SUBREDDITS = [
    "stocks",
    "investing",
    "SecurityAnalysis",
    "ValueInvesting",
    "StockMarket",
    "DueDiligence",
    "dividends",
]

# Speculative / trading subs — prefer cashtag queries. r/frugal and r/RobinHood
# were removed: r/frugal is coupon-hunting and r/RobinHood is app-support chatter.
SPECULATIVE_SUBREDDITS = [
    "wallstreetbets",
    "options",
    "thetagang",
    "pennystocks",
    "Daytrading",
]

SECTOR_SUBREDDITS = {
    "Technology": ["technology", "gadgets", "hardware"],
    "Consumer Cyclical": ["BuyItForLife", "personalfinance"],
    "Consumer Defensive": ["personalfinance"],
    "Healthcare": ["medicine", "HealthcareWorkers", "pharmacy"],
    "Financial Services": ["personalfinance", "financialindependence", "banking"],
    "Energy": ["energy", "RenewableEnergy", "oil"],
    "Communication Services": ["technology", "media", "streaming"],
    "Industrials": ["engineering", "manufacturing"],
    "Basic Materials": ["investing"],
    "Real Estate": ["realestateinvesting", "RealEstate"],
    "Utilities": ["investing"],
}


def _get_company_data(symbol: str) -> dict:
    """Return name, aliases (list), subreddits (list), sector from DB."""
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT name, aliases, subreddits, sector FROM companies WHERE symbol = ?",
            [symbol.upper()],
        ).fetchone()
        if not row:
            return {}
        name, aliases_json, subreddits_json, sector = row
        aliases = json.loads(aliases_json) if aliases_json else []
        subreddits = json.loads(subreddits_json) if subreddits_json else []
        return {"name": name, "aliases": aliases, "subreddits": subreddits, "sector": sector or ""}
    except Exception:
        return {}


def _get_sector_subreddits(sector: str) -> List[str]:
    """Map a GICS sector string to relevant community subreddits."""
    for key, subs in SECTOR_SUBREDDITS.items():
        if key.lower() in sector.lower():
            return subs
    return []


def _queries_for_track(
    track: str, symbol: str, company_name: str, aliases: List[str],
) -> List[str]:
    """
    Pick the right search queries per track.

    DD subs: use the company name and distinctive aliases — users on r/stocks
    talk about "Snap" and "Snapchat", not "$SNAP". A cashtag is added as a
    safety net for symbols that aren't common-word tickers.

    Speculative subs: cashtag is the dominant form on WSB and options subs.
    The name is added only when the ticker is a common word so we still catch
    posts that avoid the ambiguous cashtag (e.g. "Ford layoffs" on WSB).
    """
    distinct = distinctive_aliases(aliases, symbol)
    sym = symbol.upper()

    if track == "dd" or track == "company" or track == "industry":
        queries = []
        if company_name:
            queries.append(company_name)
        for a in distinct[:2]:
            if a.lower() != (company_name or "").lower():
                queries.append(a)
        # Only add a bare-ticker query for multi-char, non-common tickers;
        # a bare "F" or "T" search on r/stocks returns noise.
        if len(sym) >= 3 and not is_common_word_ticker(sym):
            queries.append(f"${sym}")
        return list(dict.fromkeys(queries))

    # speculative
    queries = [f"${sym}"]
    if is_common_word_ticker(sym) and company_name:
        queries.append(company_name)
    elif len(sym) >= 3:
        queries.append(sym)
    return list(dict.fromkeys(queries))


def _reddit_get(
    session: requests.Session, url: str, retries: int = 1,
) -> Optional[dict]:
    """
    GET with one polite retry on HTTP 429. Returns parsed JSON or None on error.
    Reddit's public JSON endpoint rate-limits aggressively when unauthenticated,
    but a 5-second backoff is usually enough to recover without dropping a sub.
    """
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            if resp.status_code == 429 and attempt < retries:
                time.sleep(5)
                continue
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception:
            return None
    return None


def _fetch_subreddit(
    session: requests.Session,
    sub: str,
    queries: List[str],
    symbol: str,
    aliases: List[str],
    limit: int,
    reason_counts: Counter,
) -> List[dict]:
    """
    Fetch posts from a single subreddit using multiple queries and two sort
    orders (top/week + new), merged + de-duped by post id.

    Relevance is gated through the shared is_relevant ladder so a substring
    match on "snap" alone won't pass — we require cashtag, a distinctive alias,
    or ticker+financial-context.
    """
    seen_ids = set()  # type: set
    posts = []  # type: List[dict]

    for query in queries:
        for sort_mode in ("top&t=week", "new"):
            url = (
                f"https://www.reddit.com/r/{sub}/search.json"
                f"?q={quote(query)}&restrict_sr=1&sort={sort_mode}&limit={limit}"
            )
            payload = _reddit_get(session, url, retries=1)
            if payload is None:
                reason_counts["fetch-error"] += 1
                time.sleep(0.5)
                continue

            children = payload.get("data", {}).get("children", [])
            for c in children:
                if c.get("kind") != "t3":
                    continue
                p = c["data"]
                pid = p.get("id", "")
                if not pid or pid in seen_ids:
                    continue

                combined = f"{p.get('title', '')} {p.get('selftext', '')}"
                accepted, reason = is_relevant(combined, symbol, aliases)
                if not accepted:
                    reason_counts[f"reject:{reason}"] += 1
                    continue

                reason_counts[f"accept:{reason}"] += 1
                seen_ids.add(pid)
                posts.append(p)

            time.sleep(0.5)

    return posts


def _fetch_top_comments(
    permalink: str, session: requests.Session, limit: int = 20,
) -> List[str]:
    """
    Fetch top-level comments from a Reddit post via the public JSON API.
    Returns a list of comment body strings.
    """
    url = f"https://www.reddit.com{permalink}.json?limit={limit}&sort=top"
    payload = _reddit_get(session, url, retries=1)
    if payload is None:
        return []
    # Response is [post_listing, comments_listing]
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    children = payload[1].get("data", {}).get("children", [])
    comments = []
    for c in children:
        if c.get("kind") != "t1":
            continue
        body = (c.get("data", {}).get("body") or "").strip()
        if len(body) >= 20 and body != "[deleted]" and body != "[removed]":
            comments.append(body[:500])
    return comments


def ingest_reddit(symbol: str, limit: int = 50) -> int:
    """
    Fetch Reddit posts mentioning symbol from DD, speculative, company-specific,
    and industry/sector subreddits. Tags each post with source_type, scores with
    FinBERT, upserts into reddit_posts. Fetches top comments for high-engagement
    posts and scores those too.
    """
    company = _get_company_data(symbol)
    aliases = company.get("aliases") or []  # type: List[str]
    company_subreddits = company.get("subreddits") or []  # type: List[str]
    sector = company.get("sector") or ""
    company_name = company.get("name") or symbol

    sector_subs = _get_sector_subreddits(sector)

    # Each group carries its own query style. See _queries_for_track() for why.
    subreddit_groups = [
        ("dd",          DD_SUBREDDITS,         "dd"),
        ("speculative", SPECULATIVE_SUBREDDITS,"speculative"),
        ("company",     company_subreddits,    "company"),
        ("industry",    sector_subs,           "industry"),
    ]  # type: List[Tuple[str, List[str], str]]

    all_rows = []  # type: List[dict]
    global_seen = set()  # type: set
    high_engagement_posts = []  # type: List[Tuple[str, str]]
    per_track_stats = {}  # type: dict

    session = requests.Session()
    try:
        for source_type, subs, track in subreddit_groups:
            if not subs:
                continue

            queries = _queries_for_track(track, symbol, company_name, aliases)
            if not queries:
                continue

            reason_counts = Counter()  # type: Counter
            group_kept = 0

            for sub in subs:
                fetched = _fetch_subreddit(
                    session, sub, queries, symbol, aliases, limit, reason_counts,
                )
                texts = []  # type: List[str]
                valid_posts = []  # type: List[dict]

                for p in fetched:
                    pid = p.get("id", "")
                    if pid in global_seen:
                        reason_counts["dup-global"] += 1
                        continue
                    global_seen.add(pid)
                    title = p.get("title", "") or ""
                    body = (p.get("selftext", "") or "")[:500]
                    texts.append(f"{title}. {body}".strip())
                    valid_posts.append(p)

                if not texts:
                    continue

                scores = score_texts(texts)

                for p, sc in zip(valid_posts, scores):
                    created_utc = p.get("created_utc", 0)
                    try:
                        created_at = pd.Timestamp(created_utc, unit="s", tz="UTC")
                    except Exception:
                        created_at = pd.Timestamp.now(tz="UTC")

                    post_db_id = f"reddit_{p.get('id', '')}"
                    post_score = p.get("score", 0) or 0
                    num_comments = p.get("num_comments", 0) or 0

                    all_rows.append({
                        "id": post_db_id,
                        "symbol": symbol.upper(),
                        "subreddit": sub,
                        "title": p.get("title", ""),
                        "body": (p.get("selftext", "") or "")[:2000],
                        "url": f"https://www.reddit.com{p.get('permalink', '')}",
                        "score": post_score,
                        "num_comments": num_comments,
                        "created_at": created_at,
                        "sentiment_score": sc["sentiment_score"],
                        "sentiment_label": sc["sentiment_label"],
                        "source_type": source_type,
                        "fetched_at": pd.Timestamp.now(),
                    })
                    group_kept += 1

                    if (post_score >= _HIGH_ENGAGEMENT_SCORE
                            or num_comments >= _HIGH_ENGAGEMENT_COMMENTS):
                        permalink = p.get("permalink", "")
                        if permalink:
                            high_engagement_posts.append((post_db_id, permalink))

                # Polite pause between subreddits
                time.sleep(1)

            per_track_stats[track] = {
                "kept": group_kept,
                "breakdown": dict(reason_counts),
            }

        common_flag = "strict" if is_common_word_ticker(symbol) else "normal"
        print(
            f"[reddit] {symbol}: total={len(all_rows)} mode={common_flag} "
            f"tracks={per_track_stats}"
        )

        if not all_rows:
            return 0

        df = pd.DataFrame(all_rows)
        conn = get_connection()
        conn.register("reddit_staging", df)
        conn.execute("""
            INSERT OR REPLACE INTO reddit_posts
                (id, symbol, subreddit, title, body, url, score, num_comments,
                 created_at, sentiment_score, sentiment_label, source_type, fetched_at)
            SELECT id, symbol, subreddit, title, body, url, score, num_comments,
                   created_at, sentiment_score, sentiment_label, source_type, fetched_at
            FROM reddit_staging
        """)
        conn.unregister("reddit_staging")
        print(f"[reddit] {symbol}: {len(all_rows)} posts ingested.")

        # Fetch and score comments for high-engagement posts
        comment_rows = []  # type: List[dict]
        for post_db_id, permalink in high_engagement_posts[:10]:
            comments = _fetch_top_comments(permalink, session)
            if not comments:
                continue
            comment_scores = score_texts(comments)
            for i, (body, sc) in enumerate(zip(comments, comment_scores)):
                comment_rows.append({
                    "id": f"{post_db_id}_c{i}",
                    "post_id": post_db_id,
                    "symbol": symbol.upper(),
                    "body": body,
                    "score": 0,
                    "sentiment_score": sc["sentiment_score"],
                    "sentiment_label": sc["sentiment_label"],
                    "fetched_at": pd.Timestamp.now(),
                })
            time.sleep(0.5)

        if comment_rows:
            cdf = pd.DataFrame(comment_rows)
            conn.register("comments_staging", cdf)
            conn.execute("""
                INSERT OR REPLACE INTO reddit_comments
                    (id, post_id, symbol, body, score, sentiment_score, sentiment_label, fetched_at)
                SELECT id, post_id, symbol, body, score, sentiment_score, sentiment_label, fetched_at
                FROM comments_staging
            """)
            conn.unregister("comments_staging")
            print(f"[reddit] {symbol}: {len(comment_rows)} comments ingested.")

        return len(all_rows)
    finally:
        session.close()
