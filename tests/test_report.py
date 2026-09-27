from datetime import datetime, timedelta, timezone

import pytest

from app.services.report import wow_growth_pct, weighted_sentiment, ReportService
from app.services.errors import UnknownThemeError
from app.repositories.report import ReportRepository
from app.repositories.theme import ThemeRepository
from app.db.models import Article, Theme, ArticleTheme, ArticleCompany
from tests.fixtures import seed_taxonomy, upsert_company, store_classification

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def report_service(session):
    return ReportService(ReportRepository(session), ThemeRepository(session))


def test_wow_growth_basic():
    assert wow_growth_pct(this_week=128, last_week=100) == 28.0


def test_wow_growth_handles_zero_last_week():
    assert wow_growth_pct(this_week=5, last_week=0) == 500.0  # divides by max(0,1)


def test_weighted_sentiment_importance_dominates():
    # one high-importance negative outweighs several low-importance positives
    score, label = weighted_sentiment([("positive", 2), ("positive", 2), ("negative", 9)])
    assert score == -0.385          # (2 + 2 - 9) / 13
    assert label == "negative"


def test_weighted_sentiment_deadband_is_neutral():
    score, label = weighted_sentiment([("positive", 8), ("negative", 8)])  # net 0
    assert score == 0.0
    assert label == "neutral"


def test_weighted_sentiment_all_positive():
    score, label = weighted_sentiment([("positive", 5), ("positive", 7)])
    assert score == 1.0
    assert label == "positive"


def test_weighted_sentiment_skips_nulls_and_empty():
    assert weighted_sentiment([]) == (None, None)
    assert weighted_sentiment([(None, 5), ("positive", None)]) == (None, None)


def _article(session, url, days_ago, theme="AI Infrastructure",
             company=("NVIDIA", "NVDA")):
    art = Article(url=url, title="t", body="b", source="reuters",
                  published_at=NOW - timedelta(days=days_ago))
    session.add(art)
    session.flush()
    store_classification(session, art, {
        "themes": [{"name": theme, "confidence": 0.9}],
        "companies": [{"name": company[0], "ticker": company[1], "sentiment": "positive", "importance": 7}],
    })
    # store_classification adds ArticleTheme/ArticleCompany rows without
    # flushing; raw text() queries don't autoflush, so flush here so the
    # report SQL sees them.
    session.flush()
    return art


def _tag(session, url, days_ago, theme_name, companies, source="cnbc"):
    """Create an article tagged to a theme with explicit per-company
    sentiment/importance (store_classification only allows one sentiment for the
    whole article, which these aggregate tests need to vary)."""
    art = Article(url=url, title=f"title {url}", body="b", source=source,
                  published_at=NOW - timedelta(days=days_ago))
    session.add(art)
    session.flush()
    theme = session.query(Theme).filter_by(name=theme_name).one()
    session.add(ArticleTheme(article_id=art.id, theme_id=theme.id, confidence=0.9))
    for name, ticker, sentiment, importance in companies:
        company = upsert_company(session, name, ticker)
        session.add(ArticleCompany(article_id=art.id, company_id=company.id,
                                   sentiment=sentiment, importance=importance))
    session.flush()
    return art


def test_count_articles_in_window(session, report_service):
    seed_taxonomy(session)
    _article(session, "u1", days_ago=1)
    _article(session, "u2", days_ago=2)
    _article(session, "u3", days_ago=10)  # outside the 7-day window

    count = report_service.count_articles("AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert count == 2


def test_emerging_association_excludes_prior_companies(session, report_service):
    seed_taxonomy(session)
    # NVIDIA appeared 14 days ago (prior window) -> NOT emerging
    _article(session, "old", days_ago=14, company=("NVIDIA", "NVDA"))
    # Eaton appears this week only -> emerging
    _article(session, "new", days_ago=1, company=("Eaton", "ETN"))

    emerging = report_service.emerging_associations("AI Infrastructure", now=NOW)
    names = {row["company"] for row in emerging}
    assert "Eaton" in names
    assert "NVIDIA" not in names


def test_top_companies_includes_avg_sentiment_and_importance(session, report_service):
    seed_taxonomy(session)
    _tag(session, "a1", 1, "AI Infrastructure", [("NVIDIA", "NVDA", "positive", 8)])
    _tag(session, "a2", 2, "AI Infrastructure", [("NVIDIA", "NVDA", "positive", 6)])

    rows = report_service.top_companies("AI Infrastructure", NOW - timedelta(days=7), NOW)
    nvda = next(r for r in rows if r["ticker"] == "NVDA")
    assert nvda["mentions"] == 2
    assert nvda["avg_importance"] == 7.0       # (8 + 6) / 2
    assert nvda["avg_sentiment"] == "positive"
    assert nvda["sentiment_score"] == 1.0      # all positive -> +1


def test_top_companies_sentiment_is_importance_weighted(session, report_service):
    seed_taxonomy(session)
    # equal-but-opposite importance nets to zero -> neutral (within deadband)
    _tag(session, "a1", 1, "AI Infrastructure", [("NVIDIA", "NVDA", "positive", 8)])
    _tag(session, "a2", 2, "AI Infrastructure", [("NVIDIA", "NVDA", "negative", 8)])

    rows = report_service.top_companies("AI Infrastructure", NOW - timedelta(days=7), NOW)
    nvda = next(r for r in rows if r["ticker"] == "NVDA")
    assert nvda["sentiment_score"] == 0.0
    assert nvda["avg_sentiment"] == "neutral"


def test_emerging_includes_first_seen_and_company(session, report_service):
    seed_taxonomy(session)
    _tag(session, "e1", 3, "AI Infrastructure", [("Eaton", "ETN", "positive", 6)])

    emerging = report_service.emerging_associations("AI Infrastructure", now=NOW)
    eaton = next(r for r in emerging if r["ticker"] == "ETN")
    assert eaton["company"] == "Eaton"
    assert eaton["first_seen"].startswith("2026-06-18")  # NOW - 3 days


def test_count_companies_distinct_in_window(session, report_service):
    seed_taxonomy(session)
    _tag(session, "c1", 1, "AI Infrastructure",
         [("NVIDIA", "NVDA", "positive", 8), ("Eaton", "ETN", "neutral", 5)])
    _tag(session, "c2", 2, "AI Infrastructure", [("NVIDIA", "NVDA", "positive", 7)])

    n = report_service.count_companies("AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert n == 2  # NVIDIA + Eaton, counted once each


def test_top_articles_includes_source_published_and_sentiment(session, report_service):
    seed_taxonomy(session)
    _tag(session, "art1", 1, "AI Infrastructure",
         [("NVIDIA", "NVDA", "positive", 8)], source="cnbc")

    rows = report_service.top_articles("AI Infrastructure", NOW - timedelta(days=7), NOW)
    r = rows[0]
    assert r["source"] == "cnbc"
    assert r["published_at"].startswith("2026-06-20")  # NOW - 1 day
    assert r["sentiment"] == "positive"
    assert r["importance"] == 8


def test_top_articles_sentiment_from_driving_mention(session, report_service):
    seed_taxonomy(session)
    # NVIDIA is the highest-importance mention -> it drives BOTH importance and sentiment
    _tag(session, "art1", 1, "AI Infrastructure",
         [("NVIDIA", "NVDA", "positive", 9), ("Eaton", "ETN", "negative", 3)])

    rows = report_service.top_articles("AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert rows[0]["importance"] == 9
    assert rows[0]["sentiment"] == "positive"   # from NVIDIA, not a majority vote


def test_top_articles_importance_tie_broken_by_company_name(session, report_service):
    seed_taxonomy(session)
    # equal importance -> deterministic tiebreak by company name ASC (Eaton < NVIDIA)
    _tag(session, "art1", 1, "AI Infrastructure",
         [("NVIDIA", "NVDA", "positive", 8), ("Eaton", "ETN", "negative", 8)])

    rows = report_service.top_articles("AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert rows[0]["importance"] == 8
    assert rows[0]["sentiment"] == "negative"   # Eaton wins the tie


def test_top_articles_dedups_multi_company_article(session, report_service):
    # An article tied to several companies must appear once, not once per company.
    seed_taxonomy(session)
    art = Article(url="multi", title="t", body="b", source="reuters",
                  published_at=NOW - timedelta(days=1))
    session.add(art)
    session.flush()
    store_classification(session, art, {
        "themes": [{"name": "AI Infrastructure", "confidence": 0.9}],
        "companies": [{"name": "NVIDIA", "ticker": "NVDA", "sentiment": "positive", "importance": 7},
                      {"name": "Eaton", "ticker": "ETN", "sentiment": "positive", "importance": 7}],
    })
    session.flush()

    rows = report_service.top_articles("AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert [r["url"] for r in rows] == ["multi"]
    assert rows[0]["importance"] == 7


def test_theme_report_unknown_theme_raises(session, report_service):
    seed_taxonomy(session)
    with pytest.raises(UnknownThemeError):
        report_service.theme_report("Nonexistent Theme")


def test_generate_report_shape(session, report_service):
    seed_taxonomy(session)
    _article(session, "u1", days_ago=1)

    report = report_service.generate_report(now=NOW)
    assert "AI Infrastructure" in report["narratives"]
    ai = report["narratives"]["AI Infrastructure"]
    assert ai["article_count"] == 1
    assert "wow_growth_pct" in ai
    assert "top_companies" in ai
    assert "emerging_associations" in ai
    assert "important_articles" in ai
