from datetime import datetime, timedelta, timezone

from app.services.errors import UnknownThemeError


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


class ReportService:
    """Business logic for the narrative report: time windows, importance-weighted
    sentiment, dict shaping, and the theme-existence rule. All data access is
    delegated to the injected repositories."""

    def __init__(self, report_repo, theme_repo):
        self.report_repo = report_repo
        self.theme_repo = theme_repo

    # --- granular building blocks -------------------------------------------

    def count_articles(self, theme_name: str, start: datetime, end: datetime) -> int:
        return self.report_repo.count_articles(theme_name, start, end)

    def count_companies(self, theme_name: str, start: datetime, end: datetime) -> int:
        return self.report_repo.count_companies(theme_name, start, end)

    def top_companies(self, theme_name: str, start: datetime, end: datetime, limit: int = 5):
        rows = self.report_repo.top_companies(theme_name, start, end, limit)
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

    def emerging_associations(self, theme_name: str, now: datetime | None = None):
        """Companies associated with the theme in the last 7 days that had NO
        association in the prior 3 weeks (days 8–28). `first_seen` is the earliest
        article in the recent window that ties the company to this narrative."""
        now = now or datetime.now(timezone.utc)
        rows = self.report_repo.emerging_associations(
            theme_name,
            now=now,
            recent_start=now - timedelta(days=7),
            prior_start=now - timedelta(days=28),
        )
        return [{
            "company": r["company"],
            "ticker": r["ticker"],
            "first_seen": _iso(r["first_seen"]),
        } for r in rows]

    def top_articles(self, theme_name: str, start: datetime, end: datetime, limit: int = 3):
        rows = self.report_repo.top_articles(theme_name, start, end, limit)
        return [{
            "title": r["title"],
            "url": r["url"],
            "source": r["source"],
            "published_at": _iso(r["published_at"]),
            "importance": int(r["importance"]) if r["importance"] is not None else None,
            "sentiment": r["sentiment"],
        } for r in rows]

    # --- endpoint-level reports ---------------------------------------------

    def generate_report(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        this_start, last_start = now - timedelta(days=7), now - timedelta(days=14)

        narratives = {}
        for theme in self.theme_repo.list_all():
            this_week = self.count_articles(theme.name, this_start, now)
            last_week = self.count_articles(theme.name, last_start, this_start)
            narratives[theme.name] = {
                "article_count": this_week,
                "wow_growth_pct": wow_growth_pct(this_week, last_week),
                "top_companies": self.top_companies(theme.name, this_start, now),
                "emerging_associations": self.emerging_associations(theme.name, now=now),
                "important_articles": self.top_articles(theme.name, this_start, now),
            }

        return {"generated_at": now.isoformat(), "narratives": narratives}

    def theme_report(self, theme_name: str, now: datetime | None = None) -> dict:
        self._require_theme(theme_name)
        now = now or datetime.now(timezone.utc)
        start = now - timedelta(days=7)
        last_start = now - timedelta(days=14)
        this_week = self.count_articles(theme_name, start, now)
        last_week = self.count_articles(theme_name, last_start, start)
        return {
            "theme": theme_name,
            "article_count": this_week,
            "wow_growth_pct": wow_growth_pct(this_week, last_week),
            "company_count": self.count_companies(theme_name, start, now),
            "top_companies": self.top_companies(theme_name, start, now),
            "emerging_associations": self.emerging_associations(theme_name, now=now),
            "important_articles": self.top_articles(theme_name, start, now),
        }

    def articles_for_theme(self, theme_name: str, now: datetime | None = None) -> dict:
        self._require_theme(theme_name)
        now = now or datetime.now(timezone.utc)
        return {
            "theme": theme_name,
            "articles": self.top_articles(theme_name, now - timedelta(days=7), now, limit=50),
        }

    def companies_for_theme(self, theme_name: str, now: datetime | None = None) -> dict:
        self._require_theme(theme_name)
        now = now or datetime.now(timezone.utc)
        return {
            "theme": theme_name,
            "companies": self.top_companies(theme_name, now - timedelta(days=7), now, limit=50),
        }

    def _require_theme(self, theme_name: str) -> None:
        if self.theme_repo.get_by_name(theme_name) is None:
            raise UnknownThemeError(f"Unknown theme: {theme_name}")
