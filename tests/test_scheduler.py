from unittest.mock import MagicMock, patch

from app.workers.scheduler import build_scheduler, run_ingestion


def test_scheduler_registers_two_jobs():
    sched = build_scheduler()
    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {"ingestion", "classification"}


def test_job_intervals():
    sched = build_scheduler()
    intervals = {job.id: job.trigger.interval.total_seconds() for job in sched.get_jobs()}
    assert intervals["ingestion"] == 30 * 60
    assert intervals["classification"] == 15 * 60


def test_run_ingestion_isolates_failing_feed():
    """One failing feed must not prevent remaining feeds from being ingested."""
    fake_sources = {
        "bad_source": "http://bad.example.com/rss",
        "good_source": "http://good.example.com/rss",
    }

    def fake_fetch_feed(url):
        if url == "http://bad.example.com/rss":
            raise RuntimeError("boom")
        return [{"link": "http://good.example.com/article/1", "title": "Good", "summary": ""}]

    ingest_calls = []

    def fake_ingest_entries(session, entries, source, extractor):
        ingest_calls.append(source)

    mock_session = MagicMock()

    with (
        patch("app.workers.scheduler.RSS_SOURCES", fake_sources),
        patch("app.workers.scheduler.fetch_feed", side_effect=fake_fetch_feed),
        patch("app.workers.scheduler.ingest_entries", side_effect=fake_ingest_entries),
        patch("app.workers.scheduler.SessionLocal", return_value=mock_session),
        patch("app.workers.scheduler.TrafilaturaExtractor", return_value=MagicMock()),
    ):
        # Must not raise even though the first feed fails
        run_ingestion()

    # The good source must still have reached ingest_entries
    assert "good_source" in ingest_calls
    # The bad source must NOT have reached ingest_entries (it raised before that)
    assert "bad_source" not in ingest_calls
