import pytest

from app.config import Settings


def test_settings_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("GEMINI_API_KEY", "abc123")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql://u:p@localhost:5432/db"
    assert settings.gemini_api_key == "abc123"
    assert settings.gemini_model == "gemini-flash-latest"


def test_gemini_key_defaults_to_dummy_under_test_flag(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.gemini_api_key == "dummy-key-for-tests"


def test_missing_gemini_key_fails_fast_outside_test(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        Settings.from_env()
