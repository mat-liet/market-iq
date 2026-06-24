from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db.models import Theme


def wow_growth_pct(this_week: int, last_week: int) -> float:
    return round((this_week - last_week) / max(last_week, 1) * 100, 1)


def count_articles(session, theme_name: str, start: datetime, end: datetime) -> int:
    row = session.execute(text("""
        SELECT COUNT(DISTINCT a.id)
        FROM articles a
        JOIN article_themes at ON at.article_id = a.id
        JOIN themes t ON t.id = at.theme_id
        WHERE t.name = :theme
          AND a.published_at >= :start AND a.published_at < :end
    """), {"theme": theme_name, "start": start, "end": end}).scalar()
    return int(row or 0)


def top_companies(session, theme_name: str, start: datetime, end: datetime, limit: int = 5):
    rows = session.execute(text("""
        SELECT c.name, c.ticker, COUNT(*) AS mention_count
        FROM article_companies ac
        JOIN companies c ON c.id = ac.company_id
        JOIN article_themes at ON at.article_id = ac.article_id
        JOIN themes t ON t.id = at.theme_id
        JOIN articles a ON a.id = ac.article_id
        WHERE t.name = :theme
          AND a.published_at >= :start AND a.published_at < :end
        GROUP BY c.name, c.ticker
        ORDER BY mention_count DESC
        LIMIT :limit
    """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings()
    return [dict(r) for r in rows]


def emerging_associations(session, theme_name: str, now: datetime | None = None):
    """Companies associated with the theme in the last 7 days that had NO
    association in the prior 3 weeks (days 8–28)."""
    now = now or datetime.now(timezone.utc)
    rows = session.execute(text("""
        SELECT c.name, c.ticker, COUNT(*) AS mention_count
        FROM article_companies ac
        JOIN companies c ON c.id = ac.company_id
        JOIN article_themes at ON at.article_id = ac.article_id
        JOIN themes t ON t.id = at.theme_id
        WHERE t.name = :theme
          AND ac.article_id IN (
              SELECT id FROM articles WHERE published_at >= :recent_start
          )
          AND c.id NOT IN (
              SELECT ac2.company_id
              FROM article_companies ac2
              JOIN article_themes at2 ON at2.article_id = ac2.article_id
              JOIN themes t2 ON t2.id = at2.theme_id
              WHERE t2.name = :theme
                AND ac2.article_id IN (
                    SELECT id FROM articles
                    WHERE published_at < :recent_start
                      AND published_at >= :prior_start
                )
          )
        GROUP BY c.name, c.ticker
        ORDER BY mention_count DESC
    """), {
        "theme": theme_name,
        "recent_start": now - timedelta(days=7),
        "prior_start": now - timedelta(days=28),
    }).mappings()
    return [dict(r) for r in rows]


def top_articles(session, theme_name: str, start: datetime, end: datetime, limit: int = 3):
    # Group by article so a multi-company article appears once; importance is
    # per article_company row, so take the max across the article's companies.
    rows = session.execute(text("""
        SELECT a.title, a.url, MAX(ac.importance) AS importance
        FROM articles a
        JOIN article_themes at ON at.article_id = a.id
        JOIN themes t ON t.id = at.theme_id
        LEFT JOIN article_companies ac ON ac.article_id = a.id
        WHERE t.name = :theme
          AND a.published_at >= :start AND a.published_at < :end
        GROUP BY a.id, a.title, a.url
        ORDER BY MAX(ac.importance) DESC NULLS LAST
        LIMIT :limit
    """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings()
    return [dict(r) for r in rows]


def generate_report(session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    this_start, last_start = now - timedelta(days=7), now - timedelta(days=14)

    narratives = {}
    for theme in session.query(Theme).all():
        this_week = count_articles(session, theme.name, this_start, now)
        last_week = count_articles(session, theme.name, last_start, this_start)
        narratives[theme.name] = {
            "article_count": this_week,
            "wow_growth_pct": wow_growth_pct(this_week, last_week),
            "top_companies": top_companies(session, theme.name, this_start, now),
            "emerging_associations": emerging_associations(session, theme.name, now=now),
            "important_articles": top_articles(session, theme.name, this_start, now),
        }

    return {"generated_at": now.isoformat(), "narratives": narratives}
