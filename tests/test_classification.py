import json
from datetime import datetime, timezone

from app.workers.classification import classify_batch
from app.services.taxonomy import seed_taxonomy
from app.db.models import (
    Article, Company, ArticleTheme, ArticleCompany, ClassificationLog,
)
from tests.fixtures import FakeGeminiClient


def _add_article(session, url="https://a.com/1"):
    article = Article(url=url, title="AI news", body="NVIDIA datacentre expansion",
                      source="reuters", published_at=datetime.now(timezone.utc))
    session.add(article)
    session.flush()
    return article


GOOD = json.dumps({
    "themes": [{"name": "AI Infrastructure", "confidence": 0.92}],
    "companies": [{"name": "NVIDIA", "ticker": "NVDA"}],
    "sentiment": "positive",
    "importance": 8,
    "reason": "Datacentre expansion increases AI chip demand.",
})


def test_classifies_and_marks_processed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    client = FakeGeminiClient([GOOD])

    n = classify_batch(session, client, "gemini-flash-latest", sleeper=lambda s: None)

    assert n == 1
    assert session.get(Article, article.id).processed is True
    assert session.query(ArticleTheme).count() == 1
    assert session.query(ArticleCompany).count() == 1
    assert session.query(Company).filter_by(ticker="NVDA").count() == 1
    log = session.query(ClassificationLog).one()
    assert log.parsed_ok is True


def test_company_dedup_across_articles(session):
    seed_taxonomy(session)
    _add_article(session, "https://a.com/1")
    _add_article(session, "https://a.com/2")
    variant = json.dumps({
        "themes": [], "companies": [{"name": "Nvidia Corp", "ticker": "NVDA"}],
        "sentiment": "neutral", "importance": 3, "reason": "x",
    })
    client = FakeGeminiClient([GOOD, variant])

    classify_batch(session, client, "m", sleeper=lambda s: None)

    assert session.query(Company).filter_by(ticker="NVDA").count() == 1


def test_unknown_theme_is_skipped(session):
    seed_taxonomy(session)
    _add_article(session)
    payload = json.dumps({
        "themes": [{"name": "Crypto Mania", "confidence": 0.9}],
        "companies": [], "sentiment": "neutral", "importance": 2, "reason": "x",
    })
    client = FakeGeminiClient([payload])

    classify_batch(session, client, "m", sleeper=lambda s: None)

    assert session.query(ArticleTheme).count() == 0  # unknown theme not stored


def test_malformed_response_logged_but_article_processed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    client = FakeGeminiClient(["this is not json"])

    classify_batch(session, client, "m", sleeper=lambda s: None)

    assert session.get(Article, article.id).processed is True
    log = session.query(ClassificationLog).one()
    assert log.parsed_ok is False
    assert session.query(ArticleTheme).count() == 0


def test_rate_limit_retried_then_succeeds(session):
    seed_taxonomy(session)
    _add_article(session)
    client = FakeGeminiClient([GOOD], error={"times": 1, "message": "429 RESOURCE_EXHAUSTED"})

    classify_batch(session, client, "m", base_delay=0.0, sleeper=lambda s: None)

    assert session.query(ArticleTheme).count() == 1
    assert client.models.calls == 2  # one failure + one success


def test_only_processes_unprocessed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    article.processed = True
    session.flush()
    client = FakeGeminiClient([])

    n = classify_batch(session, client, "m", sleeper=lambda s: None)

    assert n == 0


# Part B Fix 3: per-article error isolation
def test_call_failure_isolates_article(session):
    seed_taxonomy(session)
    _add_article(session, "https://a.com/1")
    _add_article(session, "https://a.com/2")
    # error for first 4 calls (all retries for article 1 exhausted), then article 2 succeeds
    client = FakeGeminiClient([GOOD], error={"times": 4, "message": "503 UNAVAILABLE"})

    n = classify_batch(session, client, "m", base_delay=0.0, sleeper=lambda s: None)

    articles = session.query(Article).order_by(Article.url).all()
    article1 = next(a for a in articles if a.url == "https://a.com/1")
    article2 = next(a for a in articles if a.url == "https://a.com/2")

    assert n == 1
    assert article1.processed is False
    assert article2.processed is True
    assert session.query(ClassificationLog).count() == 1
    assert session.query(ArticleTheme).count() == 1
