"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-21
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE articles (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        url           TEXT UNIQUE NOT NULL,
        title         TEXT NOT NULL,
        body          TEXT,
        source        TEXT,
        published_at  TIMESTAMPTZ NOT NULL,
        ingested_at   TIMESTAMPTZ DEFAULT NOW(),
        processed     BOOLEAN DEFAULT FALSE
    );

    CREATE TABLE themes (
        id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name      TEXT UNIQUE NOT NULL,
        keywords  TEXT[]
    );

    CREATE TABLE companies (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name            TEXT NOT NULL,
        ticker          TEXT,
        normalized_name TEXT NOT NULL
    );

    CREATE TABLE article_themes (
        article_id   UUID REFERENCES articles(id),
        theme_id     UUID REFERENCES themes(id),
        confidence   FLOAT,
        PRIMARY KEY (article_id, theme_id)
    );

    CREATE TABLE article_companies (
        article_id  UUID REFERENCES articles(id),
        company_id  UUID REFERENCES companies(id),
        sentiment   TEXT CONSTRAINT ck_sentiment CHECK (sentiment IN ('positive', 'negative', 'neutral')),
        importance  INT CONSTRAINT ck_importance CHECK (importance BETWEEN 1 AND 10),
        PRIMARY KEY (article_id, company_id)
    );

    CREATE TABLE classification_log (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        article_id   UUID REFERENCES articles(id),
        raw_response TEXT,
        parsed_ok    BOOLEAN NOT NULL,
        created_at   TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX idx_articles_processed ON articles(processed);
    CREATE INDEX idx_articles_published ON articles(published_at);
    CREATE INDEX idx_article_themes_theme ON article_themes(theme_id);
    CREATE INDEX idx_article_companies_company ON article_companies(company_id);
    CREATE UNIQUE INDEX idx_companies_ticker ON companies(ticker) WHERE ticker IS NOT NULL;
    CREATE UNIQUE INDEX idx_companies_normalized_name ON companies(normalized_name);
    """)


def downgrade():
    op.execute("""
    DROP TABLE IF EXISTS classification_log;
    DROP TABLE IF EXISTS article_companies;
    DROP TABLE IF EXISTS article_themes;
    DROP TABLE IF EXISTS companies;
    DROP TABLE IF EXISTS themes;
    DROP TABLE IF EXISTS articles;
    """)
