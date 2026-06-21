import os
from app.config import Settings


def test_settings_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("GEMINI_API_KEY", "abc123")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql://u:p@localhost:5432/db"
    assert settings.gemini_api_key == "abc123"
    assert settings.gemini_model == "gemini-flash-latest"


def test_gemini_key_defaults_to_dummy_for_tests(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.gemini_api_key == "dummy-key-for-tests"
