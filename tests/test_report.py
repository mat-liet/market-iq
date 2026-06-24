from datetime import datetime, timedelta, timezone

from app.services.taxonomy import seed_taxonomy
from app.services.report import (
    wow_growth_pct, count_articles, emerging_associations, top_articles, generate_report,
)
from app.workers.classification import store_classification
from app.db.models import Article

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def test_wow_growth_basic():
    assert wow_growth_pct(this_week=128, last_week=100) == 28.0


def test_wow_growth_handles_zero_last_week():
    assert wow_growth_pct(this_week=5, last_week=0) == 500.0  # divides by max(0,1)


def _article(session, url, days_ago, theme="AI Infrastructure",
             company=("NVIDIA", "NVDA")):
    art = Article(url=url, title="t", body="b", source="reuters",
                  published_at=NOW - timedelta(days=days_ago))
    session.add(art)
    session.flush()
    store_classification(session, art, {
        "themes": [{"name": theme, "confidence": 0.9}],
        "companies": [{"name": company[0], "ticker": company[1]}],
        "sentiment": "positive", "importance": 7,
    })
    # store_classification adds ArticleTheme/ArticleCompany rows without
    # flushing; raw text() queries don't autoflush, so flush here so the
    # report SQL sees them.
    session.flush()
    return art


def test_count_articles_in_window(session):
    seed_taxonomy(session)
    _article(session, "u1", days_ago=1)
    _article(session, "u2", days_ago=2)
    _article(session, "u3", days_ago=10)  # outside the 7-day window

    count = count_articles(session, "AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert count == 2


def test_emerging_association_excludes_prior_companies(session):
    seed_taxonomy(session)
    # NVIDIA appeared 14 days ago (prior window) -> NOT emerging
    _article(session, "old", days_ago=14, company=("NVIDIA", "NVDA"))
    # Eaton appears this week only -> emerging
    _article(session, "new", days_ago=1, company=("Eaton", "ETN"))

    emerging = emerging_associations(session, "AI Infrastructure", now=NOW)
    names = {row["name"] for row in emerging}
    assert "Eaton" in names
    assert "NVIDIA" not in names


def test_top_articles_dedups_multi_company_article(session):
    # An article tied to several companies must appear once, not once per company.
    seed_taxonomy(session)
    art = Article(url="multi", title="t", body="b", source="reuters",
                  published_at=NOW - timedelta(days=1))
    session.add(art)
    session.flush()
    store_classification(session, art, {
        "themes": [{"name": "AI Infrastructure", "confidence": 0.9}],
        "companies": [{"name": "NVIDIA", "ticker": "NVDA"},
                      {"name": "Eaton", "ticker": "ETN"}],
        "sentiment": "positive", "importance": 7,
    })
    session.flush()

    rows = top_articles(session, "AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert [r["url"] for r in rows] == ["multi"]
    assert rows[0]["importance"] == 7


def test_generate_report_shape(session):
    seed_taxonomy(session)
    _article(session, "u1", days_ago=1)

    report = generate_report(session, now=NOW)
    assert "AI Infrastructure" in report["narratives"]
    ai = report["narratives"]["AI Infrastructure"]
    assert ai["article_count"] == 1
    assert "wow_growth_pct" in ai
    assert "top_companies" in ai
    assert "emerging_associations" in ai
    assert "important_articles" in ai
