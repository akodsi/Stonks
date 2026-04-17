"""
Relevance filter shared by news and Reddit ingestion.

Decides whether a piece of text is actually about a specific ticker's company,
rather than a word that happens to overlap with the ticker or an alias. Built
around two acceptance paths: a hard-accept (cashtag or distinctive alias
phrase) and a soft-accept (bare ticker word + financial context). Common-word
tickers skip the soft path entirely.
"""
import re
from typing import List, Tuple

# Tickers that are English words or short enough to collide with other terms.
# For these, strict mode applies: bare ticker substring match is NOT enough.
_COMMON_WORD_TICKERS = {
    # Single letters (Ford, AT&T, Citigroup, US Steel, Visa, Agilent, Barnes, etc.)
    "F", "T", "C", "X", "V", "A", "B", "D", "E", "K", "O", "Q", "R", "S",
    "I", "L", "M", "N", "P", "U", "W", "Y", "Z",
    # Two-letter tickers
    "GM", "GE", "BE", "ON", "IT", "AI", "UP", "HE", "IS", "US", "MU", "GO",
    "BP", "AA", "HP", "IP", "MO", "SO", "WM",
    # Three- and four-letter tickers that are English words
    "NOW", "ALL", "KEY", "CAT", "DOW", "LOW", "FUN", "ICE", "AMP", "ONE",
    "WELL", "HOPE", "BEST", "OPEN", "ROKU", "ROOM", "FAST", "FIVE", "LAZY",
    "SNAP", "SHOP", "SEA", "SPY", "VOO", "LUNR",
}

# Words that imply genuine financial/stock coverage.
# Lowercase-matched against text — presence boosts confidence that a bare
# ticker word refers to the equity.
_FINANCIAL_CONTEXT = (
    "stock", "shares", "share", "earnings", "revenue", "quarter",
    "investor", "analyst", "ceo", "cfo", "coo", "layoff", "layoffs",
    "sec filing", "activist", "acquisition", "merger", "buyback",
    "dividend", "ipo", "guidance", "outlook", "forecast", "upgrade",
    "downgrade", "price target", "eps", "valuation", "market cap",
    "short seller", "short sellers", "options", "hedge fund", "13f",
    "nasdaq", "nyse", "s&p 500", "proxy",
)

# Stopwords / legal-entity noise we exclude from distinctive-alias pool.
_ALIAS_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "over",
    "about", "inc", "corp", "corporation", "company", "group", "holdings",
    "technologies", "systems", "services", "solutions", "international",
    "global", "ltd", "llc", "plc",
}


def is_common_word_ticker(symbol: str) -> bool:
    """True if the ticker is short/common enough to require strict matching."""
    sym = symbol.upper()
    if sym in _COMMON_WORD_TICKERS:
        return True
    if len(sym) <= 2:
        return True
    return False


def distinctive_aliases(aliases: List[str], symbol: str) -> List[str]:
    """
    Return the subset of aliases strong enough to anchor relevance on their
    own. Multi-word phrases always qualify. Single words must be ≥5 chars and
    not a stopword. The bare ticker is excluded (it has its own cashtag path).
    """
    result = []  # type: List[str]
    seen = set()  # type: set
    sym_lc = symbol.lower()
    for a in aliases or []:
        s = (a or "").strip()
        if not s:
            continue
        lc = s.lower()
        if lc == sym_lc or lc in seen:
            continue
        seen.add(lc)
        if " " in s:
            result.append(s)
            continue
        if len(s) >= 5 and lc not in _ALIAS_STOPWORDS:
            result.append(s)
    return result


def _has_financial_context(text_lc: str) -> bool:
    return any(c in text_lc for c in _FINANCIAL_CONTEXT)


def is_relevant(text: str, symbol: str, aliases: List[str]) -> Tuple[bool, str]:
    """
    Decide whether `text` is about the company identified by (symbol, aliases).
    Returns (accepted, reason_tag) — the tag is useful for ingestion stats
    logging ('cashtag', 'alias:<name>', 'ticker+context', or a rejection tag).

    Acceptance ladder:
      1. Hard: text contains `$TICKER` or `(TICKER)` — unambiguous cashtag form.
      2. Hard: text contains any distinctive alias phrase (e.g. "Snap Inc",
         "Snapchat", "Snapchat+").
      3. Soft (only when the symbol is NOT a common-word ticker): the bare
         ticker appears as a whole word AND at least one financial-context term
         is present anywhere in the text.
    """
    if not text:
        return (False, "empty")

    text_lc = text.lower()
    sym_lc = symbol.lower()
    sym_uc = symbol.upper()

    # 1. Cashtag / parenthesized ticker
    if f"${sym_lc}" in text_lc or f"({sym_uc})" in text:
        return (True, "cashtag")

    # 2. Distinctive alias phrase
    for a in distinctive_aliases(aliases, symbol):
        if a.lower() in text_lc:
            return (True, f"alias:{a}")

    # 3. Soft path — skip entirely for common-word tickers
    if is_common_word_ticker(symbol):
        return (False, "strict-no-match")

    if re.search(rf"\b{re.escape(sym_lc)}\b", text_lc):
        if _has_financial_context(text_lc):
            return (True, "ticker+context")
        return (False, "ticker-no-context")

    return (False, "no-match")
