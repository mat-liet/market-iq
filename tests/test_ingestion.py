import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from app.services.ingestion import IngestionService, fetch_feed
from app.repositories.article import ArticleRepository
from app.db.models import Article
from tests.fixtures import FakeExtractor, feed_entry, FIXED_NOW


def _ingest(session, entries, source, extractor, now=FIXED_NOW):
    service = IngestionService(ArticleRepository(session), session)
    return service.ingest_entries(entries, source, extractor, now=now)


def test_inserts_new_article_with_extracted_body(session):
    extractor = FakeExtractor({"https://r.com/1": "full body text"})
    entries = [feed_entry("https://r.com/1", "Headline", summary="short")]

    inserted = _ingest(session, entries, "reuters", extractor)

    assert inserted == 1
    article = session.query(Article).one()
    assert article.body == "full body text"
    assert article.source == "reuters"
    assert article.processed is False


def test_falls_back_to_summary_when_extraction_fails(session):
    extractor = FakeExtractor({"https://r.com/1": None})
    entries = [feed_entry("https://r.com/1", "Headline", summary="summary text")]

    _ingest(session, entries, "reuters", extractor)

    assert session.query(Article).one().body == "summary text"


def test_duplicate_url_is_skipped(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    entries = [feed_entry("https://r.com/1", "Headline")]

    _ingest(session, entries, "reuters", extractor)
    inserted_second = _ingest(session, entries, "reuters", extractor)

    assert inserted_second == 0
    assert session.query(Article).count() == 1


def test_missing_published_at_backfilled_with_now(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    entries = [feed_entry("https://r.com/1", "Headline", published_at=None)]

    _ingest(session, entries, "reuters", extractor)

    assert session.query(Article).one().published_at == FIXED_NOW


def test_uses_feed_published_at_when_present(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    pub = datetime(2026, 6, 1, tzinfo=timezone.utc)
    entries = [feed_entry("https://r.com/1", "Headline", published_at=pub)]

    _ingest(session, entries, "reuters", extractor)

    assert session.query(Article).one().published_at == pub


def test_fetch_feed_struct_time_to_utc_datetime():
    """published_parsed UTC struct_time must produce an exact UTC datetime — not skewed by local TZ."""
    struct = time.struct_time((2026, 6, 1, 12, 0, 0, 0, 0, 0))
    fake_entry = {
        "link": "https://example.com/article",
        "title": "Test Article",
        "summary": "A summary",
        "published_parsed": struct,
    }
    fake_parsed = MagicMock()
    fake_parsed.entries = [fake_entry]

    with patch("app.services.ingestion.feedparser.parse", return_value=fake_parsed):
        entries = fetch_feed("https://example.com/feed")

    assert len(entries) == 1
    entry = entries[0]
    assert entry["link"] == "https://example.com/article"
    assert entry["title"] == "Test Article"
    assert entry["summary"] == "A summary"
    assert entry["published_at"] == datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_fetch_feed_no_published_parsed_yields_none():
    """An entry without published_parsed must yield published_at=None."""
    fake_entry = {
        "link": "https://example.com/article",
        "title": "No date",
        "summary": "",
        "published_parsed": None,
    }
    fake_parsed = MagicMock()
    fake_parsed.entries = [fake_entry]

    with patch("app.services.ingestion.feedparser.parse", return_value=fake_parsed):
        entries = fetch_feed("https://example.com/feed")

    assert entries[0]["published_at"] is None


def test_entry_without_link_is_skipped(session):
    """An entry with link=None must not be inserted."""
    extractor = FakeExtractor({})
    entries = [{"link": None, "title": "No link", "summary": "", "published_at": None}]

    inserted = _ingest(session, entries, "reuters", extractor)

    assert inserted == 0
    assert session.query(Article).count() == 0
