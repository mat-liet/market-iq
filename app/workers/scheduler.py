import logging

from apscheduler.schedulers.background import BackgroundScheduler

from google import genai

from app.config import Settings
from app.db.session import SessionLocal
from app.workers.ingestion import RSS_SOURCES, fetch_feed, ingest_entries
from app.workers.classification import classify_batch
from app.services.body_extractor import TrafilaturaExtractor

logger = logging.getLogger(__name__)

_gemini_client = None


def _get_gemini_client(settings: Settings):
    """Lazily build a single google-genai client and reuse it across runs so we
    don't leak an httpx connection pool on every scheduled classification."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    return _gemini_client


def run_ingestion() -> None:
    extractor = TrafilaturaExtractor()
    with SessionLocal() as session:
        for source, url in RSS_SOURCES.items():
            try:
                entries = fetch_feed(url)
                ingest_entries(session, entries, source, extractor)
            except Exception as exc:
                logger.warning("ingestion failed for source %s: %s", source, exc)


def run_classification() -> None:
    settings = Settings.from_env()
    client = _get_gemini_client(settings)
    with SessionLocal() as session:
        classify_batch(session, client, settings.gemini_model)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_ingestion, "interval", minutes=30, id="ingestion")
    scheduler.add_job(run_classification, "interval", minutes=15, id="classification")
    return scheduler
