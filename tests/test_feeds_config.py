import json

import pytest

from app.services.config_files import CONFIG_DIR, load_feeds, load_taxonomy
from app.services.ingestion import fetch_feed


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_example_files_are_valid():
    assert load_feeds(CONFIG_DIR / "feeds.example.json")
    assert load_taxonomy(CONFIG_DIR / "taxonomy.example.json")


def test_loads_feeds_from_env_path(tmp_path, monkeypatch):
    path = _write(tmp_path, "feeds.json", {"src": "https://example.com/rss"})
    monkeypatch.setenv("FEEDS_FILE", str(path))
    assert load_feeds() == {"src": "https://example.com/rss"}


def test_loads_taxonomy_from_env_path(tmp_path, monkeypatch):
    path = _write(tmp_path, "taxonomy.json", {"Theme": ["kw"]})
    monkeypatch.setenv("TAXONOMY_FILE", str(path))
    assert load_taxonomy() == {"Theme": ["kw"]}


def test_missing_config_fails_fast_outside_tests(tmp_path, monkeypatch):
    monkeypatch.setenv("FEEDS_FILE", str(tmp_path / "absent.json"))
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(RuntimeError, match="FEEDS_FILE"):
        load_feeds()


def test_missing_config_uses_example_under_test_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAXONOMY_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("APP_ENV", "test")
    assert load_taxonomy() == load_taxonomy(CONFIG_DIR / "taxonomy.example.json")


@pytest.mark.parametrize("data", [{}, [], {"src": "ftp://x"}, {"src": 3}])
def test_rejects_malformed_feeds(tmp_path, data):
    with pytest.raises(ValueError):
        load_feeds(_write(tmp_path, "feeds.json", data))


@pytest.mark.parametrize("data", [{}, {"Theme": []}, {"Theme": "kw"}, {"Theme": [1]}])
def test_rejects_malformed_taxonomy(tmp_path, data):
    with pytest.raises(ValueError):
        load_taxonomy(_write(tmp_path, "taxonomy.json", data))


def test_parses_a_static_feed(monkeypatch):
    # fetch_feed normalizes feedparser output; verify shape with a fake parse result.
    class _Entry(dict):
        def __getattr__(self, k):
            return self.get(k)

    fake = type("P", (), {"entries": [
        _Entry(link="https://x.com/1", title="T", summary="S", published_parsed=None)
    ]})()
    monkeypatch.setattr("app.services.ingestion.feedparser.parse", lambda url: fake)

    entries = fetch_feed("https://whatever")
    assert entries[0]["link"] == "https://x.com/1"
    assert entries[0]["title"] == "T"
    assert entries[0]["published_at"] is None
