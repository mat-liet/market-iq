from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.db.session import SessionLocal
from app.api.routes import get_session
from app.services.taxonomy import seed_taxonomy
from app.workers.classification import store_classification
from app.db.models import Article


@pytest.fixture
def client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_daily_report(client, session):
    seed_taxonomy(session)
    art = Article(url="u1", title="AI", body="b", source="r",
                  published_at=datetime.now(timezone.utc))
    session.add(art)
    session.flush()
    store_classification(session, art, {
        "themes": [{"name": "AI Infrastructure", "confidence": 0.9}],
        "companies": [{"name": "NVIDIA", "ticker": "NVDA"}],
        "sentiment": "positive", "importance": 8,
    })

    resp = client.get("/report/daily")
    assert resp.status_code == 200
    assert "AI Infrastructure" in resp.json()["narratives"]


def test_single_theme_report(client, session):
    seed_taxonomy(session)
    resp = client.get("/report/AI Infrastructure")
    assert resp.status_code == 200
    assert resp.json()["theme"] == "AI Infrastructure"


def test_unknown_theme_returns_404(client, session):
    seed_taxonomy(session)
    resp = client.get("/report/Nonexistent Theme")
    assert resp.status_code == 404


def test_scheduler_starts_and_stops_with_lifespan(monkeypatch):
    """Lifespan fires on 'with TestClient(app) as c:' — verify start/shutdown."""
    fake_scheduler = MagicMock()
    monkeypatch.setattr("app.main.build_scheduler", lambda: fake_scheduler)
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")

    app = create_app()
    with TestClient(app) as client:
        fake_scheduler.start.assert_called_once()

    fake_scheduler.shutdown.assert_called_once_with(wait=False)


def test_scheduler_disabled_when_env_false(monkeypatch):
    """When ENABLE_SCHEDULER=false, build_scheduler must never be called."""
    mock_build = MagicMock()
    monkeypatch.setattr("app.main.build_scheduler", mock_build)
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")

    app = create_app()
    with TestClient(app) as client:
        client.get("/health")

    mock_build.assert_not_called()
