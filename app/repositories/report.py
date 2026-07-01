from datetime import datetime

from sqlalchemy import text


class ReportRepository:
    """Raw read queries backing the narrative report. Returns unshaped rows and
    scalars; ReportService applies the business logic (windows, weighted
    sentiment, dict shaping)."""

    def __init__(self, session):
        self.session = session

    def count_articles(self, theme_name: str, start: datetime, end: datetime) -> int:
        row = self.session.execute(text("""
            SELECT COUNT(DISTINCT a.id)
            FROM articles a
            JOIN article_themes at ON at.article_id = a.id
            JOIN themes t ON t.id = at.theme_id
            WHERE t.name = :theme
              AND a.published_at >= :start AND a.published_at < :end
        """), {"theme": theme_name, "start": start, "end": end}).scalar()
        return int(row or 0)

    def count_companies(self, theme_name: str, start: datetime, end: datetime) -> int:
        row = self.session.execute(text("""
            SELECT COUNT(DISTINCT ac.company_id)
            FROM article_companies ac
            JOIN article_themes at ON at.article_id = ac.article_id
            JOIN themes t ON t.id = at.theme_id
            JOIN articles a ON a.id = ac.article_id
            WHERE t.name = :theme
              AND a.published_at >= :start AND a.published_at < :end
        """), {"theme": theme_name, "start": start, "end": end}).scalar()
        return int(row or 0)

    def top_companies(self, theme_name: str, start: datetime, end: datetime, limit: int):
        return self.session.execute(text("""
            SELECT c.name, c.ticker,
                   COUNT(*) AS mentions,
                   ROUND(AVG(ac.importance) FILTER (WHERE ac.importance IS NOT NULL), 1) AS avg_importance,
                   array_agg(ac.sentiment ORDER BY ac.article_id, ac.company_id) AS sentiments,
                   array_agg(ac.importance ORDER BY ac.article_id, ac.company_id) AS importances
            FROM article_companies ac
            JOIN companies c ON c.id = ac.company_id
            JOIN article_themes at ON at.article_id = ac.article_id
            JOIN themes t ON t.id = at.theme_id
            JOIN articles a ON a.id = ac.article_id
            WHERE t.name = :theme
              AND a.published_at >= :start AND a.published_at < :end
            GROUP BY c.name, c.ticker
            ORDER BY mentions DESC
            LIMIT :limit
        """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings().all()

    def emerging_associations(self, theme_name: str, now: datetime,
                              recent_start: datetime, prior_start: datetime):
        return self.session.execute(text("""
            SELECT c.name AS company, c.ticker, MIN(a.published_at) AS first_seen
            FROM article_companies ac
            JOIN companies c ON c.id = ac.company_id
            JOIN article_themes at ON at.article_id = ac.article_id
            JOIN themes t ON t.id = at.theme_id
            JOIN articles a ON a.id = ac.article_id
            WHERE t.name = :theme
              AND a.published_at >= :recent_start AND a.published_at < :now
              AND c.id NOT IN (
                  SELECT ac2.company_id
                  FROM article_companies ac2
                  JOIN article_themes at2 ON at2.article_id = ac2.article_id
                  JOIN themes t2 ON t2.id = at2.theme_id
                  JOIN articles a2 ON a2.id = ac2.article_id
                  WHERE t2.name = :theme
                    AND a2.published_at < :recent_start
                    AND a2.published_at >= :prior_start
              )
            GROUP BY c.name, c.ticker
            ORDER BY first_seen DESC
        """), {
            "theme": theme_name,
            "now": now,
            "recent_start": recent_start,
            "prior_start": prior_start,
        }).mappings().all()

    def top_articles(self, theme_name: str, start: datetime, end: datetime, limit: int):
        return self.session.execute(text("""
            SELECT title, url, source, published_at, importance, sentiment
            FROM (
                SELECT DISTINCT ON (a.id)
                       a.id, a.title AS title, a.url AS url, a.source AS source,
                       a.published_at AS published_at,
                       ac.importance AS importance, ac.sentiment AS sentiment
                FROM articles a
                JOIN article_themes at ON at.article_id = a.id
                JOIN themes t ON t.id = at.theme_id
                LEFT JOIN article_companies ac ON ac.article_id = a.id
                LEFT JOIN companies c ON c.id = ac.company_id
                WHERE t.name = :theme
                  AND a.published_at >= :start AND a.published_at < :end
                ORDER BY a.id, ac.importance DESC NULLS LAST, c.name ASC
            ) sub
            ORDER BY importance DESC NULLS LAST
            LIMIT :limit
        """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings().all()
