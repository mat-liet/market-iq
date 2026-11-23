"""price cache and sentiment outcomes

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE price_tickers (
        symbol       TEXT PRIMARY KEY,
        status       TEXT NOT NULL CONSTRAINT ck_price_ticker_status
                         CHECK (status IN ('ok', 'not_found')),
        exchange_tz  TEXT,
        checked_at   TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE price_bars (
        symbol      TEXT NOT NULL,
        trade_date  DATE NOT NULL,
        close       DOUBLE PRECISION NOT NULL,
        PRIMARY KEY (symbol, trade_date)
    );

    CREATE TABLE sentiment_outcomes (
        article_id        UUID NOT NULL,
        company_id        UUID NOT NULL,
        horizon           INTEGER NOT NULL CONSTRAINT ck_outcome_horizon CHECK (horizon >= 0),
        symbol            TEXT NOT NULL,
        event_date        DATE NOT NULL,
        start_date        DATE NOT NULL,
        end_date          DATE NOT NULL,
        stock_return      DOUBLE PRECISION NOT NULL,
        benchmark_return  DOUBLE PRECISION NOT NULL,
        abnormal_return   DOUBLE PRECISION NOT NULL,
        evaluated_at      TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (article_id, company_id, horizon),
        FOREIGN KEY (article_id, company_id)
            REFERENCES article_companies (article_id, company_id)
    );

    CREATE INDEX idx_sentiment_outcomes_event ON sentiment_outcomes (company_id, event_date);
    """)


def downgrade():
    op.execute("""
    DROP TABLE sentiment_outcomes;
    DROP TABLE price_bars;
    DROP TABLE price_tickers;
    """)
