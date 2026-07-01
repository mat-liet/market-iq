import json
from datetime import datetime, timezone

from sqlalchemy import text

import app.workers.classification as classification
from app.workers.classification import classify_batch, store_classification
from app.db.models import (
    Article, Company, ArticleTheme, ArticleCompany, ClassificationLog,
)
from tests.fixtures import FakeGeminiClient, seed_taxonomy


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

    n = classify_batch(session, client, "gemini-2.5-flash-lite", sleeper=lambda s: None)

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


# Final-review Critical #1: malformed-but-plausible LLM output must not poison
# the queue. The model can return duplicate companies/themes within one article
# or out-of-range scalars; persisting these naively raises IntegrityError on
# commit, leaving the article unprocessed and re-selected forever.

def test_duplicate_company_in_one_article_stored_once(session):
    seed_taxonomy(session)
    article = _add_article(session)
    payload = json.dumps({
        "themes": [],
        "companies": [
            {"name": "NVIDIA", "ticker": "NVDA"},
            {"name": "Nvidia Corp", "ticker": "NVDA"},  # same company
        ],
        "sentiment": "positive", "importance": 7, "reason": "x",
    })
    client = FakeGeminiClient([payload])

    n = classify_batch(session, client, "m", sleeper=lambda s: None)

    assert n == 1
    assert session.get(Article, article.id).processed is True
    assert session.query(ArticleCompany).count() == 1
    assert session.query(Company).filter_by(ticker="NVDA").count() == 1


def test_duplicate_theme_in_one_article_stored_once(session):
    seed_taxonomy(session)
    article = _add_article(session)
    payload = json.dumps({
        "themes": [
            {"name": "AI Infrastructure", "confidence": 0.9},
            {"name": "AI Infrastructure", "confidence": 0.5},  # repeated
        ],
        "companies": [], "sentiment": "neutral", "importance": 5, "reason": "x",
    })
    client = FakeGeminiClient([payload])

    n = classify_batch(session, client, "m", sleeper=lambda s: None)

    assert n == 1
    assert session.get(Article, article.id).processed is True
    assert session.query(ArticleTheme).count() == 1


def test_out_of_range_importance_is_dropped(session):
    seed_taxonomy(session)
    article = _add_article(session)
    payload = json.dumps({
        "themes": [],
        "companies": [{"name": "NVIDIA", "ticker": "NVDA"}],
        "sentiment": "positive", "importance": 12, "reason": "x",  # > 10
    })
    client = FakeGeminiClient([payload])

    n = classify_batch(session, client, "m", sleeper=lambda s: None)

    assert n == 1
    assert session.get(Article, article.id).processed is True
    row = session.query(ArticleCompany).one()
    assert row.importance is None  # invalid value dropped, not persisted


def test_invalid_sentiment_is_dropped(session):
    seed_taxonomy(session)
    article = _add_article(session)
    payload = json.dumps({
        "themes": [],
        "companies": [{"name": "NVIDIA", "ticker": "NVDA"}],
        "sentiment": "mixed", "importance": 6, "reason": "x",  # not in enum
    })
    client = FakeGeminiClient([payload])

    n = classify_batch(session, client, "m", sleeper=lambda s: None)

    assert n == 1
    assert session.get(Article, article.id).processed is True
    row = session.query(ArticleCompany).one()
    assert row.sentiment is None


def test_persist_failure_isolates_article(engine, monkeypatch):
    """If persistence still raises (e.g. an unforeseen IntegrityError), the
    article must be marked processed and logged parsed_ok=False — never left
    to be retried forever — and the batch must continue.

    This uses a dedicated real-transaction session (not the shared savepoint
    fixture) because the behaviour under test is exactly that classify_batch's
    in-loop rollback discards only the failed article's writes while rows
    committed earlier survive — which the connection-bound savepoint fixture
    cannot represent (its rollback unwinds the whole outer transaction)."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    sess = Session()
    try:
        seed_taxonomy(sess)
        bad = _add_article(sess, "https://iso.com/1")
        _add_article(sess, "https://iso.com/2")
        sess.commit()  # durable, like articles committed by the ingestion worker

        calls = {"n": 0}
        real_store = classification.store_classification

        def flaky_store(s, art, result):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("simulated persistence failure")
            return real_store(s, art, result)

        monkeypatch.setattr(classification, "store_classification", flaky_store)
        client = FakeGeminiClient([GOOD, GOOD])

        n = classify_batch(sess, client, "m", sleeper=lambda s: None)

        assert n == 2  # both articles end up processed; batch not aborted
        assert sess.get(Article, bad.id).processed is True
        bad_log = sess.query(ClassificationLog).filter_by(article_id=bad.id).one()
        assert bad_log.parsed_ok is False  # failure recorded, not retried forever
    finally:
        # Real commits above — purge all rows so other tests start clean.
        sess.rollback()
        for tbl in ("article_companies", "article_themes", "classification_log",
                    "companies", "themes", "articles"):
            sess.execute(text(f"DELETE FROM {tbl}"))
        sess.commit()
        sess.close()
