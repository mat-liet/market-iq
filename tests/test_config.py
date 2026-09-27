import pytest

from app.config import Settings


def test_settings_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "abc123")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    monkeypatch.setenv("CLAUDE_EFFORT", "medium")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql://u:p@localhost:5432/db"
    assert settings.anthropic_api_key == "abc123"
    assert settings.claude_model == "claude-opus-5"
    assert settings.claude_effort == "medium"


def test_model_and_effort_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "abc123")
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_EFFORT", raising=False)

    settings = Settings.from_env()

    assert settings.claude_model == "claude-sonnet-5"
    assert settings.claude_effort == "low"


def test_empty_effort_means_omit(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "abc123")
    monkeypatch.setenv("CLAUDE_EFFORT", "")

    assert Settings.from_env().claude_effort is None


def test_anthropic_key_defaults_to_dummy_under_test_flag(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.anthropic_api_key == "dummy-key-for-tests"


def test_missing_anthropic_key_fails_fast_outside_test(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        Settings.from_env()
