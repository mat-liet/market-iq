from app.services.ingestion import RSS_SOURCES, fetch_feed


def test_three_sources_configured():
    # Equality (not superset) so an accidentally added/restored dead feed —
    # which verify_feed would hit on every ingestion run — fails the test.
    assert set(RSS_SOURCES) == {"cnbc", "yahoo", "marketwatch"}


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
