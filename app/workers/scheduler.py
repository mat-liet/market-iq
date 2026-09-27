import logging

from apscheduler.schedulers.background import BackgroundScheduler

import anthropic

from app.config import Settings
from app.db.session import SessionLocal
from app.repositories.article import ArticleRepository
from app.repositories.company import CompanyRepository
from app.repositories.theme import ThemeRepository
from app.services.body_extractor import TrafilaturaExtractor
from app.services.classification import ClassificationService
from app.services.companies import CompanyService
from app.services.ingestion import RSS_SOURCES, IngestionService, fetch_feed

logger = logging.getLogger(__name__)

_claude_client = None


def _get_claude_client(settings: Settings):
    """Lazily build a single Anthropic client and reuse it across runs so we
    don't leak a connection pool on every scheduled classification. The SDK
    retries 429/5xx/connection errors with backoff; allow a few more attempts
    than its default of 2 since classification is not latency-sensitive."""
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=4)
    return _claude_client


def run_ingestion() -> None:
    extractor = TrafilaturaExtractor()
    with SessionLocal() as session:
        service = IngestionService(ArticleRepository(session), session)
        for source, url in RSS_SOURCES.items():
            try:
                entries = fetch_feed(url)
                service.ingest_entries(entries, source, extractor)
            except Exception as exc:
                logger.warning("ingestion failed for source %s: %s", source, exc)


def run_classification() -> None:
    settings = Settings.from_env()
    client = _get_claude_client(settings)
    with SessionLocal() as session:
        service = ClassificationService(
            ArticleRepository(session),
            ThemeRepository(session),
            CompanyService(CompanyRepository(session)),
            session,
        )
        service.classify_batch(client, settings.claude_model, settings.claude_effort)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_ingestion, "interval", minutes=30, id="ingestion")
    scheduler.add_job(run_classification, "interval", minutes=15, id="classification")
    return scheduler
