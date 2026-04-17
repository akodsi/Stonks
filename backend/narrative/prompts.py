"""
Prompt templates for local LLM narrative generation.

Design principles:
- Each builder injects computed data so the LLM never invents numbers.
- Prompts force thesis-first structure and a banned-phrase list (see BANNED_PHRASES)
  to prevent corporate-hedge filler.
- Ratios are flagged by deviation from sector median so 7B attention stays focused
  on what's actually interesting, not the full 20+ ratio dump.
"""
from typing import Any, Dict, List, Optional, Tuple


# ── Style guardrails shared by every prompt ──────────────────────────────

BANNED_PHRASES = (
    "'well-positioned', 'robust', 'strong fundamentals', 'market leader', "
    "'innovative', 'cutting-edge', 'mixed signals', 'time will tell', "
    "'only time will tell', 'it remains to be seen', 'on the other hand'"
)

STYLE_RULES = (
    "Style rules:\n"
    "- Start with a single-sentence thesis in **bold** on its own line, "
    "beginning exactly with '**Thesis:**'. Commit to a direction. No hedge words.\n"
    "- Every claim must cite a specific number or named source from the DATA block. "
    "If the data doesn't support a claim, don't make it.\n"
    f"- Banned phrases (do NOT use any of these): {BANNED_PHRASES}.\n"
    "- Prefer concrete comparisons ('trades at 1.8x sector median P/E of 22x') over "
    "abstract ones ('trades at a premium').\n"
    "- No filler openers ('In conclusion', 'Overall', 'It is worth noting').\n"
    "- If the DATA block contains an 'SBC BURDEN' line, you MUST mention stock-based "
    "compensation and its effect on FCF when discussing cash generation. Do NOT "
    "describe FCF as positive without also citing the FCF ex-SBC figure."
)


# ── Formatting helpers ────────────────────────────────────────────────────

def _truncate(text: Optional[str], max_chars: int = 150) -> str:
    """Truncate text at a word boundary with ellipsis."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated + "..."


def _fmt_dollars(val: Any) -> str:
    """Format a number as a readable dollar amount (B/M/K)."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if abs(v) >= 1e12:
        return f"${v / 1e12:.1f}T"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.1f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:.2f}"


def _fmt_pct(val: Any) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val) * 100:.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_ratio(val: Any) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.1f}x"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_num(val: Any) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_series(records: List[Dict], key: str) -> str:
    """Format a multi-year series like '$120B -> $135B -> $148B'."""
    vals = [r.get(key) for r in records if r.get(key) is not None]
    if not vals:
        return "N/A"
    return " -> ".join(_fmt_dollars(v) for v in vals)


# ── Ratio extraction + deviation flagging ─────────────────────────────────

# Ratios we show in prompts, with a human-readable label, a formatter,
# and a "higher is better" flag used for deviation scoring.
_RATIO_SPECS: List[Tuple[str, str, str, bool]] = [
    # (field, label, fmt_kind, higher_is_better)
    ("pe_ratio", "P/E", "ratio", False),
    ("pb_ratio", "P/B", "ratio", False),
    ("ev_ebitda", "EV/EBITDA", "ratio", False),
    ("price_to_fcf", "P/FCF", "ratio", False),
    ("price_to_sales", "P/S", "ratio", False),
    ("gross_margin", "Gross margin", "pct", True),
    ("operating_margin", "Operating margin", "pct", True),
    ("net_margin", "Net margin", "pct", True),
    ("ebitda_margin", "EBITDA margin", "pct", True),
    ("fcf_margin", "FCF margin", "pct", True),
    ("fcf_margin_ex_sbc", "FCF margin ex-SBC", "pct", True),
    ("sbc_to_revenue", "SBC / revenue", "pct", False),
    ("roe", "ROE", "pct", True),
    ("roa", "ROA", "pct", True),
    ("roic", "ROIC", "pct", True),
    ("debt_to_equity", "D/E", "ratio", False),
    ("cash_to_debt", "Cash/Debt", "ratio", True),
    ("ocf_to_net_income", "OCF/NI", "ratio", True),
    ("revenue_growth", "Revenue growth", "pct", True),
    ("net_income_growth", "Net income growth", "pct", True),
    ("eps_growth", "EPS growth", "pct", True),
    ("fcf_growth", "FCF growth", "pct", True),
]

_FMT_MAP = {"ratio": _fmt_ratio, "pct": _fmt_pct, "num": _fmt_num}


def _deviation_score(co_val: Optional[float], peer_val: Optional[float]) -> float:
    """
    Return a unitless magnitude representing how far the company sits from the
    sector median. 0 means equal / missing; larger means a bigger deviation.
    Uses relative distance (|co - peer| / max(|peer|, epsilon)) so percent-based
    and ratio-based metrics are comparable.
    """
    if co_val is None or peer_val is None:
        return 0.0
    try:
        c = float(co_val)
        p = float(peer_val)
    except (TypeError, ValueError):
        return 0.0
    denom = max(abs(p), 0.001)
    return abs(c - p) / denom


def _flagged_ratios_block(tearsheet: Dict, top_n: int = 8) -> str:
    """
    Return the ratios block with the top-N deviating ratios highlighted first,
    followed by the remainder compressed on one line. Focuses 7B attention.
    """
    ratios_list = tearsheet.get("ratios", [])
    if not ratios_list:
        return "Ratios: not available"
    latest = ratios_list[0]
    peers = tearsheet.get("sector_medians", {})

    scored = []  # type: List[Tuple[float, str, Any, Any, bool]]
    for field, label, fmt_kind, hib in _RATIO_SPECS:
        co_val = latest.get(field)
        peer_val = peers.get(field)
        if co_val is None:
            continue
        dev = _deviation_score(co_val, peer_val)
        scored.append((dev, label, co_val, peer_val, hib, fmt_kind))

    # Sort: missing peer comparisons rank lower than real deviations
    scored.sort(key=lambda r: r[0], reverse=True)

    flagged = scored[:top_n]
    remainder = scored[top_n:]

    def _fmt_one(label: str, co_val, peer_val, hib: bool, fmt_kind: str) -> str:
        fmtf = _FMT_MAP[fmt_kind]
        co_s = fmtf(co_val)
        peer_s = fmtf(peer_val)
        if peer_val is None:
            return f"- **{label}: {co_s}** (no sector median)"
        try:
            c = float(co_val); p = float(peer_val)
        except (TypeError, ValueError):
            return f"- **{label}: {co_s}** vs sector {peer_s}"
        if p == 0:
            direction = ""
        else:
            diff = (c - p) / abs(p)
            better = (c > p) == hib
            arrow = "↑" if diff > 0 else "↓"
            verdict = " [favorable]" if better else " [unfavorable]"
            direction = f" ({arrow} {abs(diff) * 100:.0f}% vs sector {peer_s}){verdict}"
        return f"- **{label}: {co_s}**{direction}"

    lines = ["KEY RATIO DEVIATIONS (sorted by magnitude vs sector median):"]
    for _, label, co_val, peer_val, hib, fmt_kind in flagged:
        lines.append(_fmt_one(label, co_val, peer_val, hib, fmt_kind))

    if remainder:
        rem_strs = []
        for _, label, co_val, _peer, _hib, fmt_kind in remainder:
            rem_strs.append(f"{label} {_FMT_MAP[fmt_kind](co_val)}")
        lines.append("Other ratios (reference only): " + " | ".join(rem_strs))

    return "\n".join(lines)


def _company_header(tearsheet: Dict) -> str:
    co = tearsheet.get("company", {})
    ps = tearsheet.get("price_snapshot", {})
    desc = _truncate(co.get("description"), 200)
    header = (
        f"Company: {co.get('name', 'Unknown')} ({co.get('symbol', '?')})\n"
        f"Sector: {co.get('sector', 'N/A')} | Industry: {co.get('industry', 'N/A')}\n"
        f"Market Cap: {_fmt_dollars(co.get('market_cap'))}\n"
        f"Price: {_fmt_num(ps.get('price'))} | "
        f"52w Range: {_fmt_num(ps.get('low_52w'))} - {_fmt_num(ps.get('high_52w'))}"
    )
    if desc:
        header += f"\nBusiness: {desc}"
    return header


def _trend_block(tearsheet: Dict) -> str:
    trend = tearsheet.get("financials_trend", [])
    if not trend:
        return "Financial trend: not available"
    return (
        f"Revenue trend: {_fmt_series(trend, 'revenue')}\n"
        f"Net income trend: {_fmt_series(trend, 'net_income')}\n"
        f"EPS trend: {_fmt_series(trend, 'eps_diluted')}\n"
        f"FCF trend: {_fmt_series(trend, 'free_cash_flow')}"
    )


def _sbc_context_line(tearsheet: Dict) -> Optional[str]:
    """
    Emit an SBC-burden callout when SBC is >3% of revenue. Below that threshold
    SBC is noise (AAPL ~3%, MSFT ~4%, JPM <1%) and doesn't need flagging.
    For SBC-heavy names (SNAP, growth-stage SaaS) this line is the difference
    between 'FCF is healthy' and 'GAAP FCF masks real dilution cost'.
    """
    ratios = tearsheet.get("ratios", [])
    financials = tearsheet.get("financials_trend") or tearsheet.get("financials", [])
    if not ratios or not financials:
        return None

    latest_ratio = ratios[0]  # ratios returned newest-first

    # financials_trend is ordered oldest-first; match on period_date to pick
    # the financial row that aligns with the ratio (typically the last item).
    target_date = latest_ratio.get("period_date")
    latest_fin = next(
        (f for f in reversed(financials) if f.get("period_date") == target_date),
        financials[-1],
    )

    sbc_to_rev = latest_ratio.get("sbc_to_revenue")
    if sbc_to_rev is None or sbc_to_rev <= 0.03:
        return None

    sbc = latest_fin.get("sbc")
    fcf = latest_fin.get("free_cash_flow")
    fcf_ex_sbc = latest_ratio.get("fcf_ex_sbc")
    net_dil_rev = latest_ratio.get("net_dilution_to_revenue")

    parts = [
        f"SBC BURDEN: {_fmt_dollars(sbc)} ({_fmt_pct(sbc_to_rev)} of revenue)",
        f"GAAP FCF {_fmt_dollars(fcf)}",
        f"FCF ex-SBC {_fmt_dollars(fcf_ex_sbc)}",
    ]
    if net_dil_rev is not None:
        parts.append(f"net dilution {_fmt_pct(net_dil_rev)} of revenue")
    return " — ".join(parts)


def _data_block(tearsheet: Dict) -> str:
    """Common DATA block reused across tearsheet / bull-bear / risk prompts."""
    sbc_line = _sbc_context_line(tearsheet)
    sbc_section = f"\n\n{sbc_line}" if sbc_line else ""
    return (
        "DATA:\n"
        f"{_company_header(tearsheet)}\n\n"
        f"{_flagged_ratios_block(tearsheet)}"
        f"{sbc_section}\n\n"
        f"{_trend_block(tearsheet)}"
    )


# ── Tearsheet prompt (summary) ────────────────────────────────────────────

_TEARSHEET_EXAMPLE = (
    "EXAMPLE OUTPUT SHAPE (do NOT copy numbers or the company — this just shows style):\n"
    "**Thesis:** ExampleCo is a low-growth cash compounder priced like a growth story; the 34x P/E is unsupported by its 4% revenue CAGR.\n\n"
    "## Business & Positioning\n"
    "ExampleCo generates 82% of revenue from its mature widget segment (5yr revenue CAGR 4%). "
    "The stated AI pivot contributed $120M last year — under 3% of the $4.1B top line.\n\n"
    "## Valuation\n"
    "At **34x trailing P/E**, the stock sits 60% above the sector median of 21x. EV/EBITDA of 22x "
    "vs sector 14x compounds the problem. The 2.1% FCF yield implies buyers are funding the AI pivot at the PM's expense.\n\n"
    "## Profitability & Capital Returns\n"
    "ROIC of 11% narrowly beats the stated 9% cost of capital. Operating margin compressed "
    "from 19% to 16% over three years as SG&A scaled faster than revenue.\n\n"
    "## Growth Trajectory\n"
    "Revenue CAGR of 4% is half the sector's 8%. EPS growth of 6% is entirely buyback-driven: "
    "share count fell 2.5% annually while net income is flat."
)


def build_tearsheet_prompt(tearsheet: Dict) -> str:
    return (
        "Write an equity research tearsheet for the company below. "
        "Structure with ## headings: Business & Positioning, Valuation, "
        "Profitability & Capital Returns, Growth Trajectory. 3-5 sentences per section.\n\n"
        f"{STYLE_RULES}\n\n"
        f"{_data_block(tearsheet)}\n\n"
        f"{_TEARSHEET_EXAMPLE}\n\n"
        "Now write the tearsheet for the company in DATA above."
    )


# ── Bull / Bear prompt ────────────────────────────────────────────────────

_BULL_BEAR_EXAMPLE = (
    "EXAMPLE OUTPUT SHAPE (style only, numbers are made up):\n"
    "**Thesis:** The bull case hinges on margin expansion; the bear case on valuation.\n\n"
    "## Bull Case\n"
    "- **ROIC 18%** vs sector 11% — pricing power is real; capital compounds at 7 pts above cost of capital.\n"
    "- **FCF margin 24%** vs sector 9% — 2.6x sector-level cash conversion; buybacks are funded, not borrowed.\n"
    "- **Revenue growth 14%** vs sector 6% — share gain visible in the segment mix.\n\n"
    "## Bear Case\n"
    "- **P/E 42x** vs sector 19x — priced for 12% earnings growth in perpetuity; current EPS growth is 7%.\n"
    "- **D/E 2.1x** vs sector 0.7x — the buyback program runs on debt; interest coverage fell from 8x to 4x.\n"
    "- **Net income growth 3%** — revenue decelerated two quarters in a row; mix is shifting to lower-margin segments."
)


def build_bull_bear_prompt(tearsheet: Dict) -> str:
    return (
        "Write a bull case and a bear case for the company below. "
        "EXACTLY 3 bullets per side. Each bullet must:\n"
        "  1. Start with a **bolded metric name and value** ('- **ROIC 18%** ...').\n"
        "  2. Reference a different category than the other two bullets on its side "
        "(pick from: valuation, profitability, growth, leverage, cash quality).\n"
        "  3. Compare to the sector median or a prior-period number from the DATA.\n"
        "  4. Explain the *mechanism* in one sentence — why this number matters.\n\n"
        f"{STYLE_RULES}\n\n"
        f"{_data_block(tearsheet)}\n\n"
        f"{_BULL_BEAR_EXAMPLE}\n\n"
        "Now write Bull/Bear for the company in DATA above. "
        "Always open the Bull section with exactly `## Bull Case` and the Bear "
        "section with exactly `## Bear Case` — these heading strings are "
        "load-bearing for the UI's side-by-side compare view."
    )


# ── Risk prompt ───────────────────────────────────────────────────────────

_RISK_EXAMPLE = (
    "EXAMPLE OUTPUT SHAPE (style only):\n"
    "**Thesis:** The three risks that matter are leverage, margin compression, and customer concentration.\n\n"
    "### Margin Compression\n"
    "- **Magnitude:** material\n"
    "- **Timeframe:** 2-4 quarters\n"
    "- **Evidence:** Operating margin fell 19% → 16% over three years while gross margin held at 41%.\n"
    "- **Invalidating signal:** Operating margin stabilizes above 17% for two consecutive quarters.\n"
)


def build_risk_prompt(tearsheet: Dict) -> str:
    return (
        "Identify exactly 3 financial risks for the company below — the hardest "
        "ones, not generic risks. For each risk use this structure:\n"
        "  ### <Risk name>\n"
        "  - **Magnitude:** small | material | existential\n"
        "  - **Timeframe:** <quarters or years>\n"
        "  - **Evidence:** <cite the specific number(s) from DATA>\n"
        "  - **Invalidating signal:** <which specific metric move would retire this risk>\n\n"
        f"{STYLE_RULES}\n\n"
        f"{_data_block(tearsheet)}\n\n"
        f"{_RISK_EXAMPLE}\n\n"
        "Now write exactly 3 risks for the company in DATA above. "
        "Prefer risks the numbers actually support over textbook risks."
    )


# ── Sentiment prompt ──────────────────────────────────────────────────────

def _derive_trend(buckets: Dict) -> str:
    """Compare recent vs older sentiment to derive a trend label."""
    recent = buckets.get("last_7d", {}).get("avg_score")
    older = buckets.get("31_90d", {}).get("avg_score")
    if recent is None or older is None:
        return "insufficient data"
    diff = recent - older
    if diff > 0.1:
        return "improving"
    elif diff < -0.1:
        return "deteriorating"
    return "stable"


def _bucket_line(buckets: Dict, label: str) -> str:
    """Format a single source's temporal buckets into one line."""
    parts = []
    for period in ["last_7d", "8_30d", "31_90d"]:
        b = buckets.get(period, {})
        s = _fmt_num(b.get("avg_score"))
        c = b.get("count", 0)
        parts.append(f"{period}: {s} (n={c})")
    trend = _derive_trend(buckets)
    return f"{label}: {' | '.join(parts)} -> trend: {trend}"


def _distribution_line(dist: Optional[Dict], label: str, avg_score: Optional[float] = None) -> str:
    """Format a sentiment distribution dict as a readable line."""
    if not dist:
        return f"{label}: no distribution data"
    total = (dist.get("positive") or 0) + (dist.get("neutral") or 0) + (dist.get("negative") or 0)
    if total == 0:
        return f"{label}: no data"
    pos_pct = round((dist.get("positive", 0) / total) * 100)
    neu_pct = round((dist.get("neutral", 0) / total) * 100)
    neg_pct = 100 - pos_pct - neu_pct
    dist_str = f"{pos_pct}% positive / {neu_pct}% neutral / {neg_pct}% negative (n={total})"
    if avg_score is not None:
        sign = "+" if avg_score >= 0 else ""
        return f"{label}: avg {sign}{avg_score:.2f} | {dist_str}"
    return f"{label}: {dist_str}"


def _reddit_post_line(p: Dict) -> str:
    title = p.get("title", "")
    body_snip = _truncate(p.get("body"), 300)
    sub = p.get("subreddit", "")
    score_val = p.get("score", 0)
    comments = p.get("num_comments", 0)
    created = str(p.get("created_at", ""))[:10]
    engagement = p.get("engagement_label", "")
    sent_score = p.get("sentiment_score")
    comment_avg = p.get("comment_avg_score")
    comment_count = p.get("comment_count")

    engagement_str = f" — {engagement} engagement" if engagement else ""
    line = f"- [{created}] r/{sub} ({score_val} pts{engagement_str}, {comments} comments): {title}"
    if sent_score is not None:
        sign = "+" if float(sent_score) >= 0 else ""
        line += f" [post sentiment: {sign}{float(sent_score):.2f}]"
    if comment_avg is not None and comment_count:
        sign = "+" if float(comment_avg) >= 0 else ""
        line += f" [comment sentiment: {sign}{float(comment_avg):.2f} from {comment_count} comments]"
    if body_snip:
        line += f"\n  {body_snip}"
    return line


def build_sentiment_prompt(
    tearsheet: Dict,
    sentiment: Optional[Dict] = None,
) -> str:
    if sentiment is None:
        sentiment = {}

    co = tearsheet.get("company", {})
    comp = sentiment.get("composite", {})
    news = sentiment.get("news", {})
    reddit = sentiment.get("reddit", {})
    earnings = sentiment.get("earnings", {})

    investor_track = reddit.get("investor") or {}
    consumer_track = reddit.get("consumer") or {}

    momentum = comp.get("momentum", "stable")
    time_buckets = comp.get("time_buckets", {})

    bucket_lines = []
    for period in ["last_7d", "8_30d", "31_90d"]:
        b = time_buckets.get(period, {})
        s = _fmt_num(b.get("score"))
        c = b.get("count", 0)
        bucket_lines.append(f"{period}: {s} (n={c})")
    trend_block = " | ".join(bucket_lines) + f" -> trend: {momentum}"

    # News articles
    news_items = []
    for a in news.get("articles", [])[:10]:
        title = a.get("title", "")
        raw_text = a.get("full_text") or a.get("summary") or ""
        summary = _truncate(raw_text, 400)
        pub = str(a.get("published_at", ""))[:10]
        source = a.get("source", "")
        tier = a.get("source_tier")
        sent_score = a.get("sentiment_score")

        tier_str = f", T{tier}" if tier else ""
        source_str = f" ({source}{tier_str})" if source else ""
        line = f"- [{pub}] {title}{source_str}"
        if sent_score is not None:
            sign = "+" if float(sent_score) >= 0 else ""
            line += f" [sentiment: {sign}{float(sent_score):.2f}]"
        if summary:
            line += f"\n  {summary}"
        news_items.append(line)
    headlines_str = "\n".join(news_items) if news_items else "None available"

    # Top movers
    top_movers = news.get("top_movers", [])
    mover_lines = []
    for m in top_movers:
        pub = str(m.get("published_at", ""))[:10]
        title = m.get("title", "")
        sc = m.get("sentiment_score")
        source = m.get("source", "")
        tier = m.get("source_tier")
        tier_str = f", T{tier}" if tier else ""
        source_str = f" ({source}{tier_str})" if source else ""
        sign = "+" if sc and float(sc) >= 0 else ""
        score_str = f" — score {sign}{float(sc):.2f}" if sc is not None else ""
        mover_lines.append(f"- [{pub}] \"{title}\"{source_str}{score_str}")
    top_movers_str = "\n".join(mover_lines)

    # Reddit
    investor_items = [
        _reddit_post_line(p)
        for p in (investor_track.get("items") or reddit.get("posts", []))[:6]
    ]
    investor_str = "\n".join(investor_items) if investor_items else "None available"

    consumer_items = [
        _reddit_post_line(p)
        for p in (consumer_track.get("items") or [])[:6]
    ]
    consumer_str = "\n".join(consumer_items) if consumer_items else "None available"

    # Earnings
    excerpts = earnings.get("excerpts", [])
    excerpt_lines = []
    for ex in excerpts[:5]:
        q = ex.get("quarter", "?")
        s = _fmt_num(ex.get("score"))
        text = _truncate(ex.get("text"), 500)
        speaker = ex.get("speaker_type", "")
        speaker_str = f", {speaker}" if speaker else ""
        excerpt_lines.append(f"- [{q}{speaker_str}] (avg sentiment {s}):\n  \"{text}\"")
    earnings_str = "\n".join(excerpt_lines) if excerpt_lines else "No transcript excerpts available"

    news_dist = _distribution_line(
        news.get("distribution"), "News", news.get("avg_score")
    )
    investor_dist = _distribution_line(
        investor_track.get("distribution"), "Investor Reddit", investor_track.get("avg_score")
    )
    consumer_dist = _distribution_line(
        consumer_track.get("distribution"), "Consumer/Community Reddit", consumer_track.get("avg_score")
    )

    # Pre-compute divergence for deterministic instruction
    inv_avg = investor_track.get("avg_score")
    con_avg = consumer_track.get("avg_score")
    divergence_hint = ""
    if inv_avg is not None and con_avg is not None and abs(inv_avg - con_avg) > 0.2:
        more_pos = "investor" if inv_avg > con_avg else "consumer/community"
        divergence_hint = (
            f"\nNOTE: Investor vs consumer sentiment diverge by "
            f"{abs(inv_avg - con_avg):.2f}; {more_pos} is more positive. "
            "Explicitly name which side wins and hypothesize why in one sentence."
        )

    top_movers_block = (
        f"Highest-impact news items (biggest sentiment signal):\n{top_movers_str}\n\n"
        if top_movers_str else ""
    )

    return (
        f"Write a sentiment analysis for {co.get('name', 'this company')} "
        f"({co.get('symbol', '?')}). Structure with ## headings: "
        "Overall Tone, Key Drivers (name specific articles/posts by title), "
        "Investor vs Community Divergence, Momentum & Outlook.\n\n"
        "Required:\n"
        "  - Name the **top 2 article titles** driving positive signal AND the "
        "**top 2** driving negative signal. Cite their sentiment scores.\n"
        "  - Quote one complete sentence directly from an earnings excerpt "
        "(in double quotes) if excerpts exist.\n"
        "  - Identify the single strongest source of signal (news vs investor "
        "Reddit vs consumer Reddit vs earnings) and why.\n"
        f"{divergence_hint}\n\n"
        f"{STYLE_RULES}\n\n"
        "DATA:\n"
        f"Composite Sentiment: {_fmt_num(comp.get('score'))} ({comp.get('label', 'N/A')})\n"
        f"Momentum: {momentum}\n"
        f"Sentiment trend (7d / 30d / 90d): {trend_block}\n\n"
        "Sentiment distribution by source:\n"
        f"  {news_dist}\n"
        f"  {investor_dist}\n"
        f"  {consumer_dist}\n\n"
        f"Earnings Calls: avg score {_fmt_num(earnings.get('avg_score'))}\n\n"
        f"{top_movers_block}"
        "Recent news (T1=Bloomberg/Reuters/WSJ/CNBC, T2=SeekingAlpha/Motley Fool, T3=other):\n"
        f"{headlines_str}\n\n"
        f"Investor discussion (r/investing, r/stocks, r/wallstreetbets etc.):\n{investor_str}\n\n"
        f"Consumer & community discussion (company/industry subreddits):\n{consumer_str}\n\n"
        f"Earnings transcript excerpts:\n{earnings_str}"
    )
