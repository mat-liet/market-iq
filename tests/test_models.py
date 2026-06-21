import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

from app.db.models import Article, Company


def test_article_round_trips(session):
    article = Article(
        url="https://example.com/a",
        title="Test",
        body="body",
        source="reuters",
        published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    session.add(article)
    session.flush()
    assert article.id is not None
    assert article.processed is False


def test_duplicate_url_rejected(session):
    session.add(Article(url="https://dup.com", title="A",
                        published_at=datetime.now(timezone.utc)))
    session.flush()
    session.add(Article(url="https://dup.com", title="B",
                        published_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        session.flush()


def test_duplicate_ticker_rejected(session):
    session.add(Company(name="NVIDIA", ticker="NVDA", normalized_name="nvidia"))
    session.flush()
    session.add(Company(name="Nvidia Corp", ticker="NVDA", normalized_name="nvidia corp"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_null_ticker_allows_multiple(session):
    session.add(Company(name="Acme", ticker=None, normalized_name="acme"))
    session.add(Company(name="Globex", ticker=None, normalized_name="globex"))
    session.flush()  # partial unique index ignores NULL tickers
