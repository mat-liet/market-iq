import time
from datetime import datetime, timezone

import feedparser
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Article
from app.services.body_extractor import BodyExtractor

# Config-driven feeds. NOTE: these URLs are NOT guaranteed live — Reuters
# discontinued public RSS, and other paths shift. Verify with verify_feed()
# before relying on any of them; swap in working financial-news feeds as needed.
RSS_SOURCES = {
    "reuters": "https://feeds.reuters.com/reuters/businessNews",
    "yahoo": "https://finance.yahoo.com/rss/",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
}


def fetch_feed(feed_url: str) -> list[dict]:
    """Parse a feed URL into normalized entry dicts."""
    parsed = feedparser.parse(feed_url)
    entries = []
    for e in parsed.entries:
        published_at = None
        if getattr(e, "published_parsed", None):
            published_at = datetime.fromtimestamp(
                time.mktime(e.published_parsed), tz=timezone.utc
            )
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


def ingest_entries(session, entries, source, extractor: BodyExtractor, now=None) -> int:
    """Insert new articles, dedup by URL. Returns count of rows actually inserted."""
    now = now or datetime.now(timezone.utc)
    inserted = 0
    for entry in entries:
        url = entry["link"]
        if not url:
            continue
        body = extractor.extract(url) or entry.get("summary") or None
        published_at = entry.get("published_at") or now
        stmt = (
            insert(Article)
            .values(
                url=url,
                title=entry["title"],
                body=body,
                source=source,
                published_at=published_at,
                processed=False,
            )
            .on_conflict_do_nothing(index_elements=["url"])
        )
        result = session.execute(stmt)
        inserted += result.rowcount
    session.commit()
    return inserted
