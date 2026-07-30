-- TrustBoard: local score history, complementary to what lives in DataHub.
-- Compatible with PostgreSQL 14+. For SQLite see the note at the end.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS domain_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_name VARCHAR(200) NOT NULL,
    domain_urn VARCHAR(300),
    week_of DATE NOT NULL,
    trust_score DECIMAL(5,2) NOT NULL,
    assertions_passing_pct DECIMAL(5,2),
    freshness_score DECIMAL(5,2),
    documentation_score DECIMAL(5,2),
    ownership_score DECIMAL(5,2),
    -- Share of the scoring weight backed by a signal that was actually present.
    -- Kept with the score: a 78 at 0.45 coverage is not the same claim as a 78
    -- at 1.00, and reading either without the other is how a thin catalog turns
    -- into a confident number.
    signal_coverage DECIMAL(4,3),
    -- Scoring model that produced the row. Rows from different versions are not
    -- comparable, so a trend chart needs to know.
    score_version VARCHAR(16),
    dataset_count INT,
    -- How many of those datasets had enough signal to judge, and whether the
    -- team's score means anything at all.
    rated_dataset_count INT,
    rated BOOLEAN,
    -- True when the row was authored to give the demo a trend, not measured.
    synthetic BOOLEAN,
    rank_this_week INT,
    rank_last_week INT,
    written_to_datahub BOOLEAN DEFAULT false,
    datahub_property_urn VARCHAR(300),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (domain_name, week_of)
);

CREATE TABLE IF NOT EXISTS leaderboard_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_of DATE NOT NULL,
    slack_message_ts VARCHAR(100),
    top_domain VARCHAR(200),
    most_improved_domain VARCHAR(200),
    posted_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_domain_scores_week ON domain_scores (week_of);
CREATE INDEX IF NOT EXISTS idx_domain_scores_domain ON domain_scores (domain_name);

-- SQLite note: replace UUID with TEXT using hex(randomblob(16)), DECIMAL with
-- REAL and NOW() with CURRENT_TIMESTAMP. The models in
-- backend/database/models.py generate both variants through SQLAlchemy.
