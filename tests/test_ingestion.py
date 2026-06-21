from datetime import datetime, timezone

from app.workers.ingestion import ingest_entries
from app.db.models import Article
from tests.fixtures import FakeExtractor, feed_entry, FIXED_NOW


def test_inserts_new_article_with_extracted_body(session):
    extractor = FakeExtractor({"https://r.com/1": "full body text"})
    entries = [feed_entry("https://r.com/1", "Headline", summary="short")]

    inserted = ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert inserted == 1
    article = session.query(Article).one()
    assert article.body == "full body text"
    assert article.source == "reuters"
    assert article.processed is False


def test_falls_back_to_summary_when_extraction_fails(session):
    extractor = FakeExtractor({"https://r.com/1": None})
    entries = [feed_entry("https://r.com/1", "Headline", summary="summary text")]

    ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert session.query(Article).one().body == "summary text"


def test_duplicate_url_is_skipped(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    entries = [feed_entry("https://r.com/1", "Headline")]

    ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)
    inserted_second = ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert inserted_second == 0
    assert session.query(Article).count() == 1


def test_missing_published_at_backfilled_with_now(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    entries = [feed_entry("https://r.com/1", "Headline", published_at=None)]

    ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert session.query(Article).one().published_at == FIXED_NOW


def test_uses_feed_published_at_when_present(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    pub = datetime(2026, 6, 1, tzinfo=timezone.utc)
    entries = [feed_entry("https://r.com/1", "Headline", published_at=pub)]

    ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert session.query(Article).one().published_at == pub
