from datetime import datetime, timezone


class FakeExtractor:
    """Returns canned bodies keyed by URL; None means extraction failed."""

    def __init__(self, bodies: dict[str, str | None]):
        self.bodies = bodies

    def extract(self, url: str) -> str | None:
        return self.bodies.get(url)


def feed_entry(link, title, summary="", published_at=None):
    return {
        "link": link,
        "title": title,
        "summary": summary,
        "published_at": published_at,
    }


FIXED_NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
