"""Daily stock prices for scoring sentiment against what the stock did next.

`PriceSource` is the seam: `YahooPriceSource` uses Yahoo Finance's public chart
endpoint (no key, but unofficial, so it can change or rate-limit without notice).
A keyed provider can replace it by implementing the same one method.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

# Exchange prefixes the model sometimes puts on tickers ("NASDAQ:NVDA"). US venues
# map to the bare symbol; others to Yahoo's suffix. An unknown prefix is dropped
# from scoring rather than guessed, since a bare symbol could be a different US stock.
_PREFIX_SUFFIX = {
    "NASDAQ": "", "NYSE": "", "NYSEARCA": "", "NYSEAMERICAN": "", "AMEX": "",
    "BATS": "", "OTC": "", "OTCMKTS": "",
    "LON": ".L", "LSE": ".L", "TYO": ".T", "TSE": ".TO", "TSX": ".TO",
    "ETR": ".DE", "XETRA": ".DE", "FRA": ".F", "EPA": ".PA", "AMS": ".AS",
    "HKG": ".HK", "HKEX": ".HK", "ASX": ".AX", "KRX": ".KS", "SWX": ".SW",
}
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,14}")


def normalize_ticker(raw: str | None) -> str | None:
    """Map a model-supplied ticker to a Yahoo symbol, or None if it can't be
    mapped safely. "NYSE: BRK.B" -> "BRK-B", "LON:RR" -> "RR.L"."""
    if not raw:
        return None
    t = raw.strip().upper().lstrip("$")
    if ":" in t:
        prefix, _, t = (part.strip() for part in t.partition(":"))
        if prefix not in _PREFIX_SUFFIX:
            return None
        t += _PREFIX_SUFFIX[prefix]
    if re.fullmatch(r"[A-Z]+\.[ABC]", t):  # US share classes: BRK.B -> BRK-B
        t = t.replace(".", "-")
    return t if _SYMBOL.fullmatch(t) else None


class TickerNotFound(Exception):
    """The price source has no such symbol (as opposed to a transient failure)."""


@dataclass(frozen=True)
class PriceSeries:
    exchange_tz: str
    closes: list[tuple[date, float]]  # ascending by date


class PriceSource(Protocol):
    def daily_closes(self, symbol: str, start: date, end: date) -> PriceSeries:
        ...


def parse_chart(data: dict) -> PriceSeries:
    """Parse a Yahoo chart response into adjusted daily closes dated in the
    exchange's own timezone. Raises TickerNotFound for an unknown symbol."""
    chart = data.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        raise TickerNotFound(str(chart.get("error")))
    result = chart["result"][0]
    tz = result.get("meta", {}).get("exchangeTimezoneName") or "UTC"
    zone = ZoneInfo(tz)
    indicators = result.get("indicators", {})
    adj = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    closes = adj or (indicators.get("quote") or [{}])[0].get("close") or []
    bars = [
        (datetime.fromtimestamp(ts, zone).date(), float(c))
        for ts, c in zip(result.get("timestamp") or [], closes)
        if c is not None
    ]
    return PriceSeries(tz, sorted(bars))


def _epoch(d: date) -> int:
    return int(datetime.combine(d, time.min, tzinfo=timezone.utc).timestamp())


class YahooPriceSource:
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            timeout=15, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True,
        )

    def daily_closes(self, symbol: str, start: date, end: date) -> PriceSeries:
        resp = self.client.get(
            self.URL.format(symbol=quote(symbol, safe="")),
            params={"period1": _epoch(start), "period2": _epoch(end) + 86400,
                    "interval": "1d", "events": "div,splits"},
        )
        if resp.status_code == 404:
            raise TickerNotFound(symbol)
        resp.raise_for_status()  # 429/5xx are transient: retried on the next run
        return parse_chart(resp.json())
