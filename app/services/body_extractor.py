from typing import Protocol

import trafilatura


class BodyExtractor(Protocol):
    def extract(self, url: str) -> str | None:
        ...


class TrafilaturaExtractor:
    """Fetches and extracts full article text. Returns None on any failure
    so callers can fall back to the RSS summary."""

    def extract(self, url: str) -> str | None:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        return trafilatura.extract(downloaded)
