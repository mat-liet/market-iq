import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.services.classification import ClassificationService
from app.repositories.article import ArticleRepository
from app.repositories.company import CompanyRepository
from app.repositories.theme import ThemeRepository
from app.services.companies import CompanyService
from app.db.models import (
    Article, Company, ArticleTheme, ArticleCompany, ClassificationLog,
)
from tests.fixtures import FakeClaudeClient, seed_taxonomy


def _service(session):
    return ClassificationService(
        ArticleRepository(session),
        ThemeRepository(session),
        CompanyService(CompanyRepository(session)),
        session,
    )


def _add_article(session, url="https://a.com/1"):
    article = Article(url=url, title="AI news", body="NVIDIA datacentre expansion",
                      source="reuters", published_at=datetime.now(timezone.utc))
    session.add(article)
    session.flush()
    return article


GOOD = json.dumps({
    "themes": [{"name": "AI Infrastructure", "confidence": 0.92}],
    "companies": [
        {"name": "NVIDIA", "ticker": "NVDA", "sentiment": "positive", "importance": 8},
    ],
    "reason": "Datacentre expansion increases AI chip demand.",
})


def test_classifies_and_marks_processed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    client = FakeClaudeClient([GOOD])

    n = _service(session).classify_batch(client, "claude-sonnet-5", "low")

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
        "themes": [],
        "companies": [{"name": "Nvidia Corp", "ticker": "NVDA",
                       "sentiment": "neutral", "importance": 3}],
        "reason": "x",
    })
    client = FakeClaudeClient([GOOD, variant])

    _service(session).classify_batch(client, "m", "low")

    assert session.query(Company).filter_by(ticker="NVDA").count() == 1


def test_unknown_theme_is_skipped(session):
    seed_taxonomy(session)
    _add_article(session)
    payload = json.dumps({
        "themes": [{"name": "Crypto Mania", "confidence": 0.9}],
        "companies": [], "reason": "x",
    })
    client = FakeClaudeClient([payload])

    _service(session).classify_batch(client, "m", "low")

    assert session.query(ArticleTheme).count() == 0  # unknown theme not stored


def test_malformed_response_logged_but_article_processed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    client = FakeClaudeClient(["this is not json"])

    _service(session).classify_batch(client, "m", "low")

    assert session.get(Article, article.id).processed is True
    log = session.query(ClassificationLog).one()
    assert log.parsed_ok is False
    assert session.query(ArticleTheme).count() == 0


def test_each_company_gets_its_own_sentiment_and_importance(session):
    seed_taxonomy(session)
    article = _add_article(session)
    payload = json.dumps({
        "themes": [{"name": "AI Infrastructure", "confidence": 0.9}],
        "companies": [
            {"name": "NVIDIA", "ticker": "NVDA", "sentiment": "positive", "importance": 9},
            {"name": "AMD", "ticker": "AMD", "sentiment": "negative", "importance": 5},
        ],
        "reason": "NVIDIA takes share from AMD.",
    })
    client = FakeClaudeClient([payload])

    _service(session).classify_batch(client, "m", "low")

    rows = {
        c.ticker: (ac.sentiment, ac.importance)
        for ac, c in session.query(ArticleCompany, Company)
        .join(Company, Company.id == ArticleCompany.company_id)
        .filter(ArticleCompany.article_id == article.id)
    }
    assert rows == {"NVDA": ("positive", 9), "AMD": ("negative", 5)}


def test_log_records_classifying_model(session):
    seed_taxonomy(session)
    _add_article(session)
    client = FakeClaudeClient([GOOD])

    _service(session).classify_batch(client, "claude-sonnet-5", "low")

    assert session.query(ClassificationLog).one().model == "claude-sonnet-5"


def test_empty_response_logged_but_article_processed(session):
    """A response with no text (e.g. a refusal) is logged as unparsed and the
    article is not re-selected forever."""
    seed_taxonomy(session)
    article = _add_article(session)
    client = FakeClaudeClient([None])

    _service(session).classify_batch(client, "m", "low")

    assert session.get(Article, article.id).processed is True
    assert session.query(ClassificationLog).one().parsed_ok is False


def test_only_processes_unprocessed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    article.processed = True
    session.flush()
    client = FakeClaudeClient([])

    n = _service(session).classify_batch(client, "m", "low")

    assert n == 0


# Part B Fix 3: per-article error isolation
def test_call_failure_isolates_article(session):
    seed_taxonomy(session)
    _add_article(session, "https://a.com/1")
    _add_article(session, "https://a.com/2")
    # article 1's call fails (the SDK has already exhausted its retries),
    # then article 2 succeeds
    client = FakeClaudeClient([GOOD], error={"times": 1, "message": "overloaded"})

    n = _service(session).classify_batch(client, "m", "low")

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
            {"name": "NVIDIA", "ticker": "NVDA", "sentiment": "positive", "importance": 7},
            {"name": "Nvidia Corp", "ticker": "NVDA",  # same company
             "sentiment": "positive", "importance": 7},
        ],
        "reason": "x",
    })
    client = FakeClaudeClient([payload])

    n = _service(session).classify_batch(client, "m", "low")

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
        "companies": [], "reason": "x",
    })
    client = FakeClaudeClient([payload])

    n = _service(session).classify_batch(client, "m", "low")

    assert n == 1
    assert session.get(Article, article.id).processed is True
    assert session.query(ArticleTheme).count() == 1


def test_out_of_range_importance_is_dropped(session):
    seed_taxonomy(session)
    article = _add_article(session)
    payload = json.dumps({
        "themes": [],
        "companies": [{"name": "NVIDIA", "ticker": "NVDA",
                       "sentiment": "positive", "importance": 12}],  # > 10
        "reason": "x",
    })
    client = FakeClaudeClient([payload])

    n = _service(session).classify_batch(client, "m", "low")

    assert n == 1
    assert session.get(Article, article.id).processed is True
    row = session.query(ArticleCompany).one()
    assert row.importance is None  # invalid value dropped, not persisted


def test_invalid_sentiment_is_dropped(session):
    seed_taxonomy(session)
    article = _add_article(session)
    payload = json.dumps({
        "themes": [],
        "companies": [{"name": "NVIDIA", "ticker": "NVDA",
                       "sentiment": "mixed", "importance": 6}],  # not in enum
        "reason": "x",
    })
    client = FakeClaudeClient([payload])

    n = _service(session).classify_batch(client, "m", "low")

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
        real_store = ClassificationService.store_classification

        def flaky_store(self, art, result):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("simulated persistence failure")
            return real_store(self, art, result)

        monkeypatch.setattr(ClassificationService, "store_classification", flaky_store)
        client = FakeClaudeClient([GOOD, GOOD])

        n = _service(sess).classify_batch(client, "m", "low")

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
