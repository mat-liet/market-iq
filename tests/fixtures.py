from datetime import datetime, timezone

from app.repositories.article import ArticleRepository
from app.repositories.company import CompanyRepository
from app.repositories.theme import ThemeRepository
from app.services.classification import ClassificationService
from app.services.companies import CompanyService
from app.services.taxonomy import TaxonomyService


def seed_taxonomy(session):
    """Seed the taxonomy for a test, via the real TaxonomyService."""
    TaxonomyService(ThemeRepository(session), session).seed_taxonomy()


def upsert_company(session, name, ticker):
    """Find-or-create a company for test setup, via the real CompanyService."""
    return CompanyService(CompanyRepository(session)).upsert_company(name, ticker)


def store_classification(session, article, result):
    """Persist a classification result for test setup, via the real service."""
    service = ClassificationService(
        ArticleRepository(session),
        ThemeRepository(session),
        CompanyService(CompanyRepository(session)),
        session,
    )
    service.store_classification(article, result)


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


class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)] if text is not None else []


class _FakeMessages:
    def __init__(self, responses, error=None):
        self._responses = list(responses)
        self._error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None and len(self.calls) <= self._error["times"]:
            raise RuntimeError(self._error["message"])
        return _FakeMessage(self._responses.pop(0))


class FakeClaudeClient:
    """Mimics anthropic.Anthropic: exposes .messages.create.
    `responses` is a list of raw text strings returned in order (None = a
    response with no text block, e.g. a refusal). `error` optionally raises for
    the first N calls, standing in for an error the SDK gave up retrying, e.g.
    {"times": 1, "message": "overloaded"}. Each call's kwargs are recorded in
    `.messages.calls`."""

    def __init__(self, responses, error=None):
        self.messages = _FakeMessages(responses, error)
