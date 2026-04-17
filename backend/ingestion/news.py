"""
Fetches news articles from NewsAPI + RSS feeds and scores them with FinBERT.
Relevance filtering is delegated to ingestion.relevance.is_relevant so the
same acceptance ladder used by Reddit ingestion also governs news.
"""
import json
import os
import hashlib
import requests
import pandas as pd
from collections import Counter
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus
from db.connection import get_connection
from sentiment.finbert import score_texts
from ingestion.relevance import (
    is_relevant,
    is_common_word_ticker,
    distinctive_aliases,
)


NEWSAPI_URL = "https://newsapi.org/v2/everything"
_MIN_TEXT_LENGTH = 40  # skip FinBERT scoring for title-only stubs below this length

# Financial-context words used to tighten the NewsAPI query for common/ambiguous
# tickers. Adding an AND clause with these dramatically cuts irrelevant matches
# (e.g. SNAP the verb, TGT the abbreviation) while still surfacing the kind of
# material events we care about: activist stakes, layoffs, earnings, M&A, etc.
_FINANCIAL_CONTEXT_TERMS = (
    "stock", "shares", "earnings", "revenue", "quarter", "investor",
    "analyst", "CEO", "layoff", "layoffs", "activist", "acquisition",
    "merger", "buyback", "dividend", "IPO", "guidance", "upgrade",
    "downgrade", "SEC filing", "short seller",
)

# Source credibility tiers for news quality weighting
_TIER1_SOURCES = {
    "bloomberg", "reuters", "wall street journal", "wsj", "financial times",
    "ft.com", "cnbc", "associated press", "ap news", "the economist",
    "barron's", "barronsmagazine", "ft", "marketwatch",
}
_TIER2_SOURCES = {
    "seeking alpha", "seekingalpha", "motley fool", "fool.com", "investopedia",
    "yahoo finance", "business insider", "businessinsider", "fortune",
    "forbes", "thestreet", "benzinga", "zacks",
}

# Press release / low-quality sources to filter out
_PRESS_RELEASE_SOURCES = {
    "pr newswire", "prnewswire", "business wire", "businesswire",
    "globe newswire", "globenewswire", "accesswire", "cision",
    "prnews", "einpresswire", "prweb", "marketscreener",
    "simply wall st", "talkmarkets", "insider monkey",
}

# Static RSS feeds (general financial news, not symbol-specific).
_RSS_FEEDS = [
    {"url": "https://feeds.reuters.com/reuters/businessNews", "source": "Reuters", "tier": 1},
    {"url": "https://feeds.reuters.com/reuters/companyNews", "source": "Reuters", "tier": 1},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml", "source": "BBC Business", "tier": 1},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "source": "CNBC", "tier": 1},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories/", "source": "MarketWatch", "tier": 1},
    {"url": "https://seekingalpha.com/market_currents.xml", "source": "Seeking Alpha", "tier": 2},
]

# Symbol-specific RSS feeds (URL takes a %s query placeholder).
# Google News's search RSS is the single biggest source of symbol-targeted
# coverage — it aggregates hundreds of outlets and supports the same boolean
# syntax as web search, so we can reuse the NewsAPI-style query.
_SYMBOL_RSS_FEEDS = [
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US",
     "source": "Yahoo Finance", "tier": 2, "query_style": "symbol"},
    {"url": "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en",
     "source": "Google News", "tier": 2, "query_style": "boolean"},
]


def _source_tier(source_name: str) -> int:
    """Classify a news source as Tier 1 (top financial), Tier 2 (financial), or Tier 3 (other)."""
    s = source_name.lower()
    if any(t in s for t in _TIER1_SOURCES):
        return 1
    if any(t in s for t in _TIER2_SOURCES):
        return 2
    return 3


def _get_company_data(symbol: str) -> dict:
    """Return name and aliases list from DB."""
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT name, aliases FROM companies WHERE symbol = ?", [symbol.upper()]
        ).fetchone()
        if not row:
            return {}
        name, aliases_json = row
        aliases = json.loads(aliases_json) if aliases_json else []
        return {"name": name, "aliases": aliases}
    except Exception:
        return {}


def _build_boolean_query(aliases: List[str], symbol: str) -> str:
    """
    Build a boolean query suitable for NewsAPI or Google News RSS.

    Shape: `(<alias1> OR <alias2> OR $TICKER) AND (stock OR shares OR earnings OR ...)`

    The AND clause is what separates "SNAP the company" from "snap" as a verb:
    without it, NewsAPI returns TikTok trend articles and Hollywood headlines
    alongside the activist-stake / layoffs news we actually want. For very
    distinctive names (JPMorgan, Coca-Cola) it's redundant but cheap; for
    ambiguous names it's load-bearing.
    """
    # Left side: prefer distinctive aliases (multi-word phrases + long single
    # words) so we don't poison the query with stopword-heavy legal names.
    distinct = distinctive_aliases(aliases, symbol)
    alias_terms = [f'"{a}"' for a in distinct[:3]]
    # Always include the cashtag form — Google News indexes it, NewsAPI tolerates it.
    alias_terms.append(f'"${symbol.upper()}"')
    if not distinct:
        # Fall back to the bare symbol only when we have no better signal.
        alias_terms.append(f'"{symbol.upper()}"')

    alias_clause = " OR ".join(alias_terms)
    context_clause = " OR ".join(_FINANCIAL_CONTEXT_TERMS)
    return f"({alias_clause}) AND ({context_clause})"


def _extract_text(article: dict) -> str:
    """
    Extract the richest available text from a NewsAPI article.
    Hierarchy: content (stripped of truncation marker) > description > title only.
    """
    title = article.get("title", "") or ""
    desc = article.get("description", "") or ""
    content_raw = article.get("content", "") or ""
    # Strip NewsAPI's truncation marker "[+N chars]"
    content_clean = content_raw.split("[+")[0].strip()

    body = content_clean if len(content_clean) > len(desc) else desc
    if body:
        return f"{title}. {body}".strip()
    return title.strip()


def _is_press_release(source_name: str, title: str) -> bool:
    """Return True if article appears to be a press release or from a low-quality source."""
    s = source_name.lower()
    if any(pr in s for pr in _PRESS_RELEASE_SOURCES):
        return True
    t = title.lower()
    # Common press release title patterns
    if t.startswith("press release:") or t.startswith("pr:"):
        return True
    pr_phrases = [
        "announces quarterly results",
        "reports first quarter",
        "reports second quarter",
        "reports third quarter",
        "reports fourth quarter",
        "declares dividend",
        "to present at",
        "to participate in",
        "to host conference call",
    ]
    return any(phrase in t for phrase in pr_phrases)


def _fetch_rss_articles(
    symbol: str, aliases: List[str],
) -> List[Dict[str, Any]]:
    """
    Fetch articles from RSS feeds relevant to the given symbol.
    Returns list of article dicts in the same shape as NewsAPI articles.
    """
    try:
        import feedparser  # type: ignore
    except ImportError:
        print("[news] feedparser not installed — skipping RSS feeds.")
        return []

    articles = []  # type: List[Dict[str, Any]]
    seen_urls = set()  # type: set

    boolean_query = _build_boolean_query(aliases, symbol)

    feed_configs = list(_RSS_FEEDS)
    for feed in _SYMBOL_RSS_FEEDS:
        url_tmpl = feed["url"]
        if feed.get("query_style") == "boolean":
            url = url_tmpl % quote_plus(boolean_query)
        else:
            url = url_tmpl % symbol.upper()
        feed_configs.append({**feed, "url": url})

    for feed_cfg in feed_configs:
        feed_url = feed_cfg["url"]
        source = feed_cfg["source"]

        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[news] RSS parse failed for {source}: {e}")
            continue

        for entry in parsed.entries[:40]:
            url = entry.get("link", "")
            if not url or url in seen_urls:
                continue

            title = entry.get("title", "") or ""
            summary = entry.get("summary", "") or ""
            combined = f"{title} {summary}"

            accepted, _ = is_relevant(combined, symbol, aliases)
            if not accepted:
                continue
            if _is_press_release(source, title):
                continue

            seen_urls.add(url)

            # Parse published date
            published = entry.get("published", "") or ""
            try:
                pub_ts = pd.Timestamp(published)
            except Exception:
                pub_ts = pd.Timestamp.now()

            articles.append({
                "title": title,
                "description": summary,
                "url": url,
                "publishedAt": str(pub_ts),
                "source": {"name": source},
                "content": "",
                "_rss_tier": feed_cfg["tier"],
            })

    return articles


def _fetch_full_text(url: str) -> Optional[str]:
    """
    Attempt to scrape full article text via newspaper3k.
    Returns up to 3000 chars of body text, or None on failure/paywall.
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        from newspaper import Article  # type: ignore
        article = Article(url, fetch_images=False, request_timeout=10)
        article.download()
        article.parse()
        text = (article.text or "").strip()
        return text[:3000] if len(text) > 100 else None
    except Exception:
        return None


def ingest_news(symbol: str, page_size: int = 30) -> int:
    """
    Fetch recent news articles for a symbol from NewsAPI + RSS feeds,
    score with FinBERT, upsert into news table.
    Returns row count.
    """
    company_data = _get_company_data(symbol)
    aliases = company_data.get("aliases") or []  # type: List[str]

    articles = []  # type: List[Dict[str, Any]]
    fetched_total = 0

    # ── NewsAPI source ──
    api_key = os.getenv("NEWS_API_KEY", "")
    if api_key:
        query = _build_boolean_query(aliases, symbol)
        try:
            resp = requests.get(
                NEWSAPI_URL,
                params={
                    "q": query,
                    "sortBy": "publishedAt",
                    "pageSize": page_size,
                    "language": "en",
                    "apiKey": api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            newsapi_articles = data.get("articles", [])
            fetched_total += len(newsapi_articles)
            articles.extend(newsapi_articles)
        except Exception as e:
            # Scrub the api key from the exception message — requests includes
            # the full URL (with query params) in HTTPError messages.
            msg = str(e).replace(api_key, "***REDACTED***")
            print(f"[news] NewsAPI fetch failed for {symbol}: {msg}")
    else:
        print("[news] NEWS_API_KEY not set — using RSS feeds only.")

    # ── RSS feed source ──
    rss_articles = _fetch_rss_articles(symbol, aliases)
    fetched_total += len(rss_articles)
    articles.extend(rss_articles)

    # ── Filter: relevance, duplicates, press releases ──
    # finance.yahoo.com URLs are kept now because they often appear as the
    # canonical link for Google News results; only drop if we can't extract body.
    seen_urls = set()  # type: set
    filtered = []  # type: List[Dict[str, Any]]
    reason_counts = Counter()  # type: Counter
    for a in articles:
        url = a.get("url", "")
        if not url or url in seen_urls:
            reason_counts["dup"] += 1
            continue
        source_name = (a.get("source") or {}).get("name", "")
        title = a.get("title", "") or ""
        if _is_press_release(source_name, title):
            reason_counts["press-release"] += 1
            continue

        # RSS articles were already relevance-checked, but re-run so the reason
        # tag lands in stats; it's cheap and keeps the accept path uniform.
        text_for_rel = f"{title} {a.get('description', '')}"
        accepted, reason = is_relevant(text_for_rel, symbol, aliases)
        if not accepted:
            reason_counts[f"reject:{reason}"] += 1
            continue

        reason_counts[f"accept:{reason}"] += 1
        seen_urls.add(url)
        filtered.append(a)

    articles = filtered
    # Stats line — makes it easy to diagnose "why didn't we catch X?" cases.
    common_flag = "strict" if is_common_word_ticker(symbol) else "normal"
    print(
        f"[news] {symbol}: fetched={fetched_total} kept={len(articles)} "
        f"mode={common_flag} breakdown={dict(reason_counts)}"
    )
    if not articles:
        return 0

    # Attempt to scrape full article text for richer FinBERT input.
    # Only scrape T1/T2 sources (high success rate); skip T3 to limit latency.
    full_texts = []  # type: List[Optional[str]]
    for a in articles:
        url = a.get("url", "")
        source_name = (a.get("source") or {}).get("name", "")
        # RSS articles carry a pre-computed tier; NewsAPI articles derive it
        tier = a.get("_rss_tier") or _source_tier(source_name)
        if url and tier <= 2:
            ft = _fetch_full_text(url)
        else:
            ft = None
        full_texts.append(ft)

    # Build texts and their lengths for FinBERT (prefer full text over summary)
    texts = []  # type: List[str]
    text_lengths = []  # type: List[int]
    for i, a in enumerate(articles):
        text = full_texts[i] or _extract_text(a)
        texts.append(text)
        text_lengths.append(len(text))

    # Score only articles with sufficient text; stub articles get None
    score_indices = [i for i, tl in enumerate(text_lengths) if tl >= _MIN_TEXT_LENGTH]
    texts_to_score = [texts[i] for i in score_indices]
    scores_list = score_texts(texts_to_score) if texts_to_score else []
    score_map = {i: scores_list[j] for j, i in enumerate(score_indices)}

    rows = []
    for idx, a in enumerate(articles):
        url = a.get("url", "")
        article_id = hashlib.md5(url.encode()).hexdigest()
        published = a.get("publishedAt", "")

        try:
            published_at = pd.Timestamp(published)
        except Exception:
            published_at = pd.Timestamp.now()

        sc = score_map.get(idx)
        source_name = (a.get("source") or {}).get("name", "")
        tier = a.get("_rss_tier") or _source_tier(source_name)
        rows.append({
            "id": article_id,
            "symbol": symbol.upper(),
            "title": a.get("title", ""),
            "source": source_name,
            "url": url,
            "published_at": published_at,
            "summary": a.get("description", ""),
            "sentiment_score": sc["sentiment_score"] if sc else None,
            "sentiment_label": sc["sentiment_label"] if sc else "unknown",
            "text_length": text_lengths[idx],
            "fetched_at": pd.Timestamp.now(),
            "source_tier": tier,
            "full_text": full_texts[idx],
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    conn = get_connection()
    conn.register("news_staging", df)
    conn.execute("""
        INSERT OR REPLACE INTO news
            (id, symbol, title, source, url, published_at, summary,
             sentiment_score, sentiment_label, text_length, fetched_at,
             source_tier, full_text)
        SELECT id, symbol, title, source, url, published_at, summary,
               sentiment_score, sentiment_label, text_length, fetched_at,
               source_tier, full_text
        FROM news_staging
    """)
    conn.unregister("news_staging")
    print(f"[news] {symbol}: {len(rows)} articles ingested.")
    return len(rows)
