from db.connection import get_connection


SCHEMA_SQL = """
-- Company metadata
CREATE TABLE IF NOT EXISTS companies (
    symbol          VARCHAR PRIMARY KEY,
    name            VARCHAR,
    sector          VARCHAR,
    industry        VARCHAR,
    exchange        VARCHAR,
    market_cap      DOUBLE,
    country         VARCHAR,
    website         VARCHAR,
    description     TEXT,
    updated_at      TIMESTAMP DEFAULT current_timestamp
);

-- Daily OHLCV prices
CREATE TABLE IF NOT EXISTS prices (
    symbol          VARCHAR,
    date            DATE,
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE,
    adj_close       DOUBLE,
    volume          BIGINT,
    PRIMARY KEY (symbol, date)
);

-- Annual and quarterly financial statements (income, balance sheet, cash flow combined)
CREATE TABLE IF NOT EXISTS financials (
    symbol              VARCHAR,
    period_type         VARCHAR,   -- 'annual' | 'quarterly'
    period_date         DATE,
    -- Income Statement
    revenue             DOUBLE,
    gross_profit        DOUBLE,
    operating_income    DOUBLE,
    net_income          DOUBLE,
    ebitda              DOUBLE,
    eps                 DOUBLE,
    eps_diluted         DOUBLE,
    shares_outstanding  DOUBLE,
    -- Balance Sheet
    total_assets        DOUBLE,
    total_liabilities   DOUBLE,
    total_equity        DOUBLE,
    cash_and_equiv      DOUBLE,
    total_debt          DOUBLE,
    -- Cash Flow
    operating_cf        DOUBLE,
    capex               DOUBLE,
    free_cash_flow      DOUBLE,
    dividends_paid      DOUBLE,
    sbc                 DOUBLE,   -- stock-based compensation (non-cash add-back to OCF)
    buybacks            DOUBLE,   -- repurchase of capital stock (negative cash outflow)
    interest_paid       DOUBLE,
    depreciation_amortization DOUBLE,
    operating_leases    DOUBLE,   -- balance-sheet lease liability (ASC 842)
    short_term_investments DOUBLE,  -- separated from cash_and_equiv
    PRIMARY KEY (symbol, period_type, period_date)
);

-- Computed financial ratios (refreshed on new financials)
CREATE TABLE IF NOT EXISTS ratios (
    symbol              VARCHAR,
    period_type         VARCHAR,
    period_date         DATE,
    -- Valuation
    pe_ratio            DOUBLE,
    pb_ratio            DOUBLE,
    ev_ebitda           DOUBLE,
    price_to_fcf        DOUBLE,
    price_to_sales      DOUBLE,
    -- Profitability
    gross_margin        DOUBLE,
    operating_margin    DOUBLE,
    net_margin          DOUBLE,
    roe                 DOUBLE,
    roa                 DOUBLE,
    roic                DOUBLE,
    -- Leverage
    debt_to_equity      DOUBLE,
    interest_coverage   DOUBLE,
    current_ratio       DOUBLE,
    -- Growth (YoY)
    revenue_growth      DOUBLE,
    net_income_growth   DOUBLE,
    eps_growth          DOUBLE,
    fcf_growth          DOUBLE,
    -- SBC-aware + lease-aware (added after SNAP FCF-vs-net-loss discovery)
    fcf_ex_sbc          DOUBLE,
    fcf_margin_ex_sbc   DOUBLE,
    price_to_fcf_ex_sbc DOUBLE,
    sbc_to_revenue      DOUBLE,
    net_dilution_to_revenue DOUBLE,
    debt_incl_leases_to_equity DOUBLE,
    PRIMARY KEY (symbol, period_type, period_date)
);

-- News articles with sentiment scores
CREATE TABLE IF NOT EXISTS news (
    id              VARCHAR PRIMARY KEY,
    symbol          VARCHAR,
    title           TEXT,
    source          VARCHAR,
    url             TEXT,
    published_at    TIMESTAMP,
    summary         TEXT,
    sentiment_score DOUBLE,   -- -1.0 to 1.0
    sentiment_label VARCHAR,  -- 'positive' | 'neutral' | 'negative'
    fetched_at      TIMESTAMP DEFAULT current_timestamp
);

-- Reddit posts/comments mentioning the ticker
CREATE TABLE IF NOT EXISTS reddit_posts (
    id              VARCHAR PRIMARY KEY,
    symbol          VARCHAR,
    subreddit       VARCHAR,
    title           TEXT,
    body            TEXT,
    url             TEXT,
    score           INTEGER,
    num_comments    INTEGER,
    created_at      TIMESTAMP,
    sentiment_score DOUBLE,
    sentiment_label VARCHAR,
    fetched_at      TIMESTAMP DEFAULT current_timestamp
);

-- Earnings call transcripts (chunked)
CREATE TABLE IF NOT EXISTS earnings_transcripts (
    id              VARCHAR PRIMARY KEY,  -- symbol + date + chunk_index
    symbol          VARCHAR,
    earnings_date   DATE,
    quarter         VARCHAR,   -- e.g. 'Q3 2024'
    chunk_index     INTEGER,
    chunk_text      TEXT,
    sentiment_score DOUBLE,
    sentiment_label VARCHAR,
    fetched_at      TIMESTAMP DEFAULT current_timestamp
);

-- Saved custom screener templates
CREATE TABLE IF NOT EXISTS saved_screens (
    name            VARCHAR PRIMARY KEY,
    criteria_json   TEXT,
    created_at      TIMESTAMP DEFAULT current_timestamp,
    updated_at      TIMESTAMP DEFAULT current_timestamp
);

-- User watchlist
CREATE TABLE IF NOT EXISTS watchlist (
    symbol      VARCHAR PRIMARY KEY,
    added_at    TIMESTAMP DEFAULT current_timestamp
);

-- AI-generated narrative summaries (cached)
CREATE TABLE IF NOT EXISTS narratives (
    symbol          VARCHAR,
    narrative_type  VARCHAR,   -- 'tearsheet' | 'bull_bear' | 'risk' | 'sentiment_digest'
    generated_date  DATE,
    content         TEXT,
    model           VARCHAR,
    PRIMARY KEY (symbol, narrative_type, generated_date)
);
"""


MIGRATION_SQL = """
-- Add new ratio columns (idempotent — safe to re-run)
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS ebitda_margin DOUBLE;
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS fcf_margin DOUBLE;
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS cash_to_debt DOUBLE;
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS ocf_to_net_income DOUBLE;

-- Expanded company metadata for multi-name search and subreddit targeting
ALTER TABLE companies ADD COLUMN IF NOT EXISTS aliases JSON;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS subreddits JSON;

-- News quality tracking
ALTER TABLE news ADD COLUMN IF NOT EXISTS text_length INTEGER;

-- Reddit source type for investor vs consumer split
ALTER TABLE reddit_posts ADD COLUMN IF NOT EXISTS source_type VARCHAR;

-- News source credibility tier (1=Bloomberg/Reuters/WSJ, 2=SeekingAlpha/MF, 3=other)
ALTER TABLE news ADD COLUMN IF NOT EXISTS source_tier INTEGER DEFAULT 3;

-- Full article text (scraped via newspaper3k when available)
ALTER TABLE news ADD COLUMN IF NOT EXISTS full_text TEXT;

-- Cash-flow / balance-sheet rows needed for SBC-aware FCF and lease-aware leverage.
-- Existing rows will be NULL until the next /ingest call populates them.
ALTER TABLE financials ADD COLUMN IF NOT EXISTS sbc DOUBLE;
ALTER TABLE financials ADD COLUMN IF NOT EXISTS buybacks DOUBLE;
ALTER TABLE financials ADD COLUMN IF NOT EXISTS interest_paid DOUBLE;
ALTER TABLE financials ADD COLUMN IF NOT EXISTS depreciation_amortization DOUBLE;
ALTER TABLE financials ADD COLUMN IF NOT EXISTS operating_leases DOUBLE;
ALTER TABLE financials ADD COLUMN IF NOT EXISTS short_term_investments DOUBLE;

-- SBC-adjusted + lease-adjusted ratios
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS fcf_ex_sbc DOUBLE;
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS fcf_margin_ex_sbc DOUBLE;
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS price_to_fcf_ex_sbc DOUBLE;
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS sbc_to_revenue DOUBLE;
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS net_dilution_to_revenue DOUBLE;
ALTER TABLE ratios ADD COLUMN IF NOT EXISTS debt_incl_leases_to_equity DOUBLE;
"""


PORTFOLIO_TABLE_SQL = """
-- Portfolio holdings for tracking positions and benchmark comparison
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id              INTEGER PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    shares          DOUBLE NOT NULL,
    cost_basis      DOUBLE NOT NULL,       -- total cost (shares * avg price paid)
    purchase_date   DATE,
    notes           VARCHAR,
    added_at        TIMESTAMP DEFAULT current_timestamp
);

-- Portfolio-level settings (benchmark, etc.)
CREATE TABLE IF NOT EXISTS portfolio_settings (
    key             VARCHAR PRIMARY KEY,
    value           VARCHAR
);
"""

REDDIT_COMMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS reddit_comments (
    id              VARCHAR PRIMARY KEY,  -- post_id + '_' + comment_index
    post_id         VARCHAR,              -- references reddit_posts.id
    symbol          VARCHAR,
    body            TEXT,
    score           INTEGER,
    sentiment_score DOUBLE,
    sentiment_label VARCHAR,
    fetched_at      TIMESTAMP DEFAULT current_timestamp
);
"""


def init_schema():
    conn = get_connection()
    conn.execute(SCHEMA_SQL)
    conn.execute(MIGRATION_SQL)
    conn.execute(REDDIT_COMMENTS_TABLE_SQL)
    conn.execute(PORTFOLIO_TABLE_SQL)
    print("Schema initialized.")
