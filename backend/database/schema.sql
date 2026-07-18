-- TrustBoard: historico local de scores, complementario a lo que vive en DataHub.
-- Compatible con PostgreSQL 14+. Para SQLite ver nota al final.

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

-- Nota SQLite: reemplazar UUID por TEXT con hex(randomblob(16)),
-- DECIMAL por REAL y NOW() por CURRENT_TIMESTAMP. Los modelos de
-- backend/database/models.py generan ambas variantes via SQLAlchemy.
