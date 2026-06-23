import socket
from ipaddress import ip_address
from typing import Protocol
from urllib.parse import urlparse

import trafilatura
from trafilatura.settings import use_config

ALLOWED_SCHEMES = frozenset({"http", "https"})
DOWNLOAD_TIMEOUT_SECONDS = 15

# Module-level trafilatura config that bounds how long a single download may
# block, so a slow or hostile origin cannot stall the ingestion worker.
_CONFIG = use_config()
_CONFIG.set("DEFAULT", "DOWNLOAD_TIMEOUT", str(DOWNLOAD_TIMEOUT_SECONDS))


class UnsafeURLError(Exception):
    """Raised when a URL is rejected before any network request is made."""


class BodyExtractor(Protocol):
    def extract(self, url: str) -> str | None:
        ...


def _is_blocked_address(ip_str: str) -> bool:
    """True for addresses that must never be fetched (SSRF targets)."""
    ip = ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url(url: str) -> None:
    """Reject URLs that could drive a server-side request forgery.

    Enforces an http/https scheme allowlist and resolves the host, rejecting
    the request if *any* resolved address is private, loopback, link-local,
    reserved, multicast, or unspecified. Raises UnsafeURLError on rejection.

    Deferred to Phase 2: this validates the host once, so it does not defend
    against DNS rebinding (a name that resolves safe here then re-resolves to
    an internal address at fetch time) or HTTP redirect hops to an internal
    target. Mitigating those requires controlling the socket connect and
    following redirects manually, which trafilatura does not expose.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme not allowed: {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")

    try:
        infos = socket.getaddrinfo(host, parsed.port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"could not resolve host: {host}") from exc

    for info in infos:
        address = info[4][0]
        if _is_blocked_address(address):
            raise UnsafeURLError(f"host resolves to blocked address: {address}")


class TrafilaturaExtractor:
    """Fetches and extracts full article text. Returns None on any failure —
    including a URL rejected by the SSRF guard — so callers can fall back to
    the RSS summary."""

    def extract(self, url: str) -> str | None:
        try:
            validate_url(url)
        except UnsafeURLError:
            return None
        downloaded = trafilatura.fetch_url(url, config=_CONFIG)
        if not downloaded:
            return None
        return trafilatura.extract(downloaded)
