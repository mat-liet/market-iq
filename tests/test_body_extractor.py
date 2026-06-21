from app.services.body_extractor import TrafilaturaExtractor


def test_returns_extracted_text(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url", lambda url: "<html>raw</html>"
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.extract", lambda html: "clean body"
    )
    assert TrafilaturaExtractor().extract("https://x.com") == "clean body"


def test_returns_none_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url", lambda url: None
    )
    assert TrafilaturaExtractor().extract("https://x.com") is None


def test_returns_none_when_extract_returns_nothing(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url", lambda url: "<html></html>"
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.extract", lambda html: None
    )
    assert TrafilaturaExtractor().extract("https://x.com") is None
