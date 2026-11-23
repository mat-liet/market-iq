from datetime import datetime, timezone

import feedparser

from app.services.body_extractor import BodyExtractor
from app.services.config_files import load_feeds

# Feed list, loaded from FEEDS_FILE (see app/services/config_files.py). Feed paths
# shift over time: run `python -m scripts.check_feeds` to confirm each one is live
# and yields extractable article text.
RSS_SOURCES = load_feeds()


def fetch_feed(feed_url: str) -> list[dict]:
    """Parse a feed URL into normalized entry dicts."""
    parsed = feedparser.parse(feed_url)
    entries = []
    for e in parsed.entries:
        published_at = None
        if e.get("published_parsed"):
            published_at = datetime(*e.get("published_parsed")[:6], tzinfo=timezone.utc)
        entries.append({
            "link": e.get("link"),
            "title": e.get("title"),
            "summary": e.get("summary", ""),
            "published_at": published_at,
        })
    return entries


def verify_feed(feed_url: str) -> bool:
    """Return True if the feed parses and yields at least one entry."""
    return len(fetch_feed(feed_url)) > 0


class IngestionService:
    """Ingests feed entries into articles, deduplicating by URL."""

    def __init__(self, article_repo, session):
        self.article_repo = article_repo
        self.session = session  # held only as the transaction boundary

    def ingest_entries(self, entries, source, extractor: BodyExtractor, now=None) -> int:
        """Insert new articles, dedup by URL. Returns count of rows actually inserted."""
        now = now or datetime.now(timezone.utc)
        inserted = 0
        for entry in entries:
            url = entry["link"]
            if not url:
                continue
            body = extractor.extract(url) or entry.get("summary") or None
            published_at = entry.get("published_at") or now
            inserted += self.article_repo.insert_ignore({
                "url": url,
                "title": entry["title"],
                "body": body,
                "source": source,
                "published_at": published_at,
                "processed": False,
            })
        self.session.commit()
        return inserted
