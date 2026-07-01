from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db.models import Theme


def wow_growth_pct(this_week: int, last_week: int) -> float:
    return round((this_week - last_week) / max(last_week, 1) * 100, 1)


_SENTIMENT_VALUE = {"positive": 1, "negative": -1, "neutral": 0}
_NEUTRAL_DEADBAND = 0.15


def weighted_sentiment(pairs) -> tuple[float | None, str | None]:
    """Importance-weighted net sentiment for a set of mentions.

    `pairs` is an iterable of (sentiment, importance). Each sentiment maps to
    +1/0/-1 (positive/neutral/negative) and is weighted by its importance.
    Mentions with a null/unknown sentiment or null importance are ignored.

    Returns (score, label):
      score — net value in [-1.0, 1.0] rounded to 3 dp, or None if no usable mentions
      label — 'positive'/'negative'/'neutral' from the score (deadband), or None
    """
    numerator = 0.0
    weight = 0.0
    for sentiment, importance in pairs:
        if importance is None:
            continue
        value = _SENTIMENT_VALUE.get(sentiment)
        if value is None:
            continue
        numerator += value * importance
        weight += importance
    if weight == 0:
        return None, None
    score = round(numerator / weight, 3)
    if score > _NEUTRAL_DEADBAND:
        label = "positive"
    elif score < -_NEUTRAL_DEADBAND:
        label = "negative"
    else:
        label = "neutral"
    return score, label


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


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


def count_companies(session, theme_name: str, start: datetime, end: datetime) -> int:
    row = session.execute(text("""
        SELECT COUNT(DISTINCT ac.company_id)
        FROM article_companies ac
        JOIN article_themes at ON at.article_id = ac.article_id
        JOIN themes t ON t.id = at.theme_id
        JOIN articles a ON a.id = ac.article_id
        WHERE t.name = :theme
          AND a.published_at >= :start AND a.published_at < :end
    """), {"theme": theme_name, "start": start, "end": end}).scalar()
    return int(row or 0)


def top_companies(session, theme_name: str, start: datetime, end: datetime, limit: int = 5):
    rows = session.execute(text("""
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
    """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings()
    result = []
    for r in rows:
        score, label = weighted_sentiment(zip(r["sentiments"] or [], r["importances"] or []))
        result.append({
            "name": r["name"],
            "ticker": r["ticker"],
            "mentions": int(r["mentions"]),
            "avg_importance": float(r["avg_importance"]) if r["avg_importance"] is not None else None,
            "avg_sentiment": label,
            "sentiment_score": score,
        })
    return result


def emerging_associations(session, theme_name: str, now: datetime | None = None):
    """Companies associated with the theme in the last 7 days that had NO
    association in the prior 3 weeks (days 8–28). `first_seen` is the earliest
    article in the recent window that ties the company to this narrative."""
    now = now or datetime.now(timezone.utc)
    rows = session.execute(text("""
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
        "recent_start": now - timedelta(days=7),
        "prior_start": now - timedelta(days=28),
    }).mappings()
    return [{
        "company": r["company"],
        "ticker": r["ticker"],
        "first_seen": _iso(r["first_seen"]),
    } for r in rows]


def top_articles(session, theme_name: str, start: datetime, end: datetime, limit: int = 3):
    # One row per article: its single highest-importance mention drives both the
    # importance and the sentiment, so the two describe the same company. Ties on
    # importance are broken deterministically by company name.
    rows = session.execute(text("""
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
    """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings()
    return [{
        "title": r["title"],
        "url": r["url"],
        "source": r["source"],
        "published_at": _iso(r["published_at"]),
        "importance": int(r["importance"]) if r["importance"] is not None else None,
        "sentiment": r["sentiment"],
    } for r in rows]


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
