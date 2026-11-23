from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.db.models import PriceBar, PriceTicker, SentimentOutcome


class OutcomeRepository:
    """Data access for price data and sentiment outcomes. Never commits;
    OutcomeService owns the transaction boundary."""

    def __init__(self, session):
        self.session = session

    def pending_mentions(self, horizon_count: int, published_before: datetime):
        """Company mentions with a ticker and sentiment that still lack an
        outcome for at least one horizon, with the horizons already scored."""
        return self.session.execute(text("""
            SELECT ac.article_id, ac.company_id, c.ticker, a.published_at,
                   COALESCE(array_agg(o.horizon) FILTER (WHERE o.horizon IS NOT NULL),
                            '{}') AS done
            FROM article_companies ac
            JOIN companies c ON c.id = ac.company_id
            JOIN articles a ON a.id = ac.article_id
            LEFT JOIN sentiment_outcomes o
                   ON o.article_id = ac.article_id AND o.company_id = ac.company_id
            WHERE c.ticker IS NOT NULL AND ac.sentiment IS NOT NULL
              AND a.published_at < :before
            GROUP BY ac.article_id, ac.company_id, c.ticker, a.published_at
            HAVING COUNT(o.horizon) < :n
        """), {"before": published_before, "n": horizon_count}).mappings().all()

    def ticker_statuses(self, symbols) -> dict[str, PriceTicker]:
        rows = self.session.query(PriceTicker).filter(PriceTicker.symbol.in_(list(symbols))).all()
        return {r.symbol: r for r in rows}

    def all_ticker_statuses(self) -> dict[str, str]:
        return dict(self.session.execute(text("SELECT symbol, status FROM price_tickers")).all())

    def set_ticker(self, symbol: str, status: str, exchange_tz: str | None,
                   checked_at: datetime) -> None:
        values = {"symbol": symbol, "status": status, "exchange_tz": exchange_tz,
                  "checked_at": checked_at}
        stmt = insert(PriceTicker).values(**values)
        self.session.execute(stmt.on_conflict_do_update(
            index_elements=["symbol"],
            set_={k: stmt.excluded[k] for k in ("status", "exchange_tz", "checked_at")},
        ))

    def upsert_bars(self, symbol: str, closes: list[tuple[date, float]]) -> None:
        if not closes:
            return
        stmt = insert(PriceBar).values(
            [{"symbol": symbol, "trade_date": d, "close": c} for d, c in closes]
        )
        # Adjusted closes are restated after dividends/splits; keep the latest.
        self.session.execute(stmt.on_conflict_do_update(
            index_elements=["symbol", "trade_date"], set_={"close": stmt.excluded.close},
        ))

    def get_bars(self, symbol: str) -> list[tuple[date, float]]:
        return [tuple(r) for r in self.session.execute(text(
            "SELECT trade_date, close FROM price_bars WHERE symbol = :s ORDER BY trade_date"
        ), {"s": symbol}).all()]

    def add_outcome(self, **values) -> None:
        self.session.execute(insert(SentimentOutcome).values(**values).on_conflict_do_nothing())

    def scored_mentions(self):
        """One row per (company, event day, horizon): when several articles
        mention the same company on the same day they share one price move, so
        only the highest-importance mention counts (ties broken by article id)."""
        return self.session.execute(text("""
            SELECT DISTINCT ON (o.company_id, o.event_date, o.horizon)
                   o.article_id, o.horizon, o.abnormal_return, ac.sentiment, ac.importance
            FROM sentiment_outcomes o
            JOIN article_companies ac
              ON ac.article_id = o.article_id AND ac.company_id = o.company_id
            ORDER BY o.company_id, o.event_date, o.horizon,
                     ac.importance DESC NULLS LAST, o.article_id
        """)).mappings().all()

    def themes_for_articles(self, article_ids) -> dict:
        if not article_ids:
            return {}
        rows = self.session.execute(text("""
            SELECT at.article_id, t.name
            FROM article_themes at JOIN themes t ON t.id = at.theme_id
            WHERE at.article_id = ANY(:ids)
        """), {"ids": list(article_ids)}).all()
        out: dict = {}
        for article_id, name in rows:
            out.setdefault(article_id, []).append(name)
        return out

    def mention_coverage(self):
        """Every mention with a sentiment: its raw ticker and whether any outcome exists."""
        return self.session.execute(text("""
            SELECT c.ticker,
                   EXISTS (SELECT 1 FROM sentiment_outcomes o
                           WHERE o.article_id = ac.article_id
                             AND o.company_id = ac.company_id) AS scored
            FROM article_companies ac
            JOIN companies c ON c.id = ac.company_id
            WHERE ac.sentiment IS NOT NULL
        """)).mappings().all()
