from datetime import date

import httpx
import pytest

from app.services.prices import (
    TickerNotFound, YahooPriceSource, normalize_ticker, parse_chart,
)


@pytest.mark.parametrize("raw, expected", [
    ("MSFT", "MSFT"),
    (" msft ", "MSFT"),
    ("$AAPL", "AAPL"),
    ("NASDAQ:NVDA", "NVDA"),
    ("NYSE: BRK.B", "BRK-B"),
    ("LON:RR", "RR.L"),
    ("RR.L", "RR.L"),
    ("7203.T", "7203.T"),
    ("XYZ:ABC", None),      # unknown exchange prefix: don't guess a US symbol
    ("not a ticker", None),
    ("", None),
    (None, None),
])
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected


def _chart(timestamps, closes, adj=None, tz="America/New_York"):
    indicators = {"quote": [{"close": closes}]}
    if adj is not None:
        indicators["adjclose"] = [{"adjclose": adj}]
    return {"chart": {"result": [{
        "meta": {"exchangeTimezoneName": tz},
        "timestamp": timestamps,
        "indicators": indicators,
    }], "error": None}}


# 2026-11-16 and 2026-11-17, 09:30 New York (14:30 UTC)
TS = [1794843000, 1794929400]


def test_parse_chart_prefers_adjusted_closes_and_dates_in_exchange_time():
    series = parse_chart(_chart(TS, [10.0, 11.0], adj=[9.5, 10.5]))
    assert series.exchange_tz == "America/New_York"
    assert series.closes == [(date(2026, 11, 16), 9.5), (date(2026, 11, 17), 10.5)]


def test_parse_chart_skips_missing_closes():
    series = parse_chart(_chart(TS, [None, 11.0]))
    assert series.closes == [(date(2026, 11, 17), 11.0)]


def test_parse_chart_error_is_not_found():
    with pytest.raises(TickerNotFound):
        parse_chart({"chart": {"result": None, "error": {"code": "Not Found"}}})


def _source(status, payload=None):
    transport = httpx.MockTransport(lambda req: httpx.Response(status, json=payload or {}))
    return YahooPriceSource(httpx.Client(transport=transport))


def test_yahoo_404_is_not_found():
    with pytest.raises(TickerNotFound):
        _source(404).daily_closes("NOPE", date(2026, 11, 1), date(2026, 11, 20))


def test_yahoo_rate_limit_is_transient():
    with pytest.raises(httpx.HTTPStatusError):
        _source(429).daily_closes("MSFT", date(2026, 11, 1), date(2026, 11, 20))


def test_yahoo_success_parses():
    series = _source(200, _chart(TS, [10.0, 11.0])).daily_closes(
        "MSFT", date(2026, 11, 1), date(2026, 11, 20))
    assert [c for _, c in series.closes] == [10.0, 11.0]
