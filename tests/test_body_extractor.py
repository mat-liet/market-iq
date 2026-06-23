import socket

import pytest

from app.services.body_extractor import (
    TrafilaturaExtractor,
    UnsafeURLError,
    validate_url,
)


def _fake_getaddrinfo(ip):
    """Return a getaddrinfo stub that resolves any host to a single IP."""
    return lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))
    ]


def test_returns_extracted_text(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.socket.getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url",
        lambda url, config=None: "<html>raw</html>",
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.extract", lambda html: "clean body"
    )
    assert TrafilaturaExtractor().extract("https://x.com") == "clean body"


def test_returns_none_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.socket.getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url", lambda url, config=None: None
    )
    assert TrafilaturaExtractor().extract("https://x.com") is None


def test_returns_none_when_extract_returns_nothing(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.socket.getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url",
        lambda url, config=None: "<html></html>",
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.extract", lambda html: None
    )
    assert TrafilaturaExtractor().extract("https://x.com") is None


# --- SSRF guard ---


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "gopher://example.com",
        "//example.com/no-scheme",
    ],
)
def test_validate_url_rejects_non_http_schemes(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",        # loopback
        "10.0.0.5",         # private
        "192.168.1.10",     # private
        "172.16.0.1",       # private
        "169.254.169.254",  # link-local (cloud metadata endpoint)
        "0.0.0.0",          # unspecified
        "224.0.0.1",        # multicast
        "::1",              # loopback v6
        "fd00::1",          # private v6
    ],
)
def test_validate_url_rejects_internal_addresses(monkeypatch, ip):
    monkeypatch.setattr(
        "app.services.body_extractor.socket.getaddrinfo", _fake_getaddrinfo(ip)
    )
    with pytest.raises(UnsafeURLError):
        validate_url("https://internal.example.com")


def test_validate_url_rejects_when_any_resolved_address_is_internal(monkeypatch):
    def mixed(host, port, *a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port or 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port or 0)),
        ]

    monkeypatch.setattr("app.services.body_extractor.socket.getaddrinfo", mixed)
    with pytest.raises(UnsafeURLError):
        validate_url("https://sneaky.example.com")


def test_validate_url_rejects_unresolvable_host(monkeypatch):
    def boom(host, port, *a, **k):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr("app.services.body_extractor.socket.getaddrinfo", boom)
    with pytest.raises(UnsafeURLError):
        validate_url("https://does-not-exist.example.com")


def test_validate_url_allows_public_address(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.socket.getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )
    # Does not raise.
    validate_url("https://example.com/article")


def test_extract_returns_none_for_blocked_url(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.socket.getaddrinfo", _fake_getaddrinfo("127.0.0.1")
    )

    def fetch_must_not_run(url, config=None):
        raise AssertionError("fetch_url must not be called for a blocked URL")

    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url", fetch_must_not_run
    )
    assert TrafilaturaExtractor().extract("https://metadata.example.com") is None
