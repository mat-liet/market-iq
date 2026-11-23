from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.db.models import Article, ArticleCompany, ArticleTheme, PriceBar, PriceTicker, SentimentOutcome, Theme
from app.repositories.outcome import OutcomeRepository
from app.services.outcomes import OutcomeService, event_index, window
from app.services.prices import PriceSeries, TickerNotFound
from tests.fixtures import seed_taxonomy, upsert_company

NY = ZoneInfo("America/New_York")
# Monday evening after the US close.
NOW = datetime(2026, 11, 23, 23, 0, tzinfo=timezone.utc)


def _weekdays(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


DAYS = _weekdays(date(2026, 10, 12), date(2026, 11, 23))  # includes "today", 11-23


def _series(daily_growth: float) -> PriceSeries:
    return PriceSeries("America/New_York",
                       [(d, 100 * (1 + daily_growth) ** i) for i, d in enumerate(DAYS)])


class FakePrices:
    def __init__(self, series):
        self.series = series
        self.calls = []

    def daily_closes(self, symbol, start, end):
        self.calls.append(symbol)
        value = self.series.get(symbol)
        if value is None:
            raise TickerNotFound(symbol)
        if isinstance(value, Exception):
            raise value
        return value


def _service(session, prices):
    return OutcomeService(OutcomeRepository(session), session, prices, pause=lambda: None)


def _mention(session, url, published_at, name, ticker, sentiment="positive",
             importance=5, theme=None):
    art = Article(url=url, title="t", body="b", source="x", published_at=published_at)
    session.add(art)
    session.flush()
    company = upsert_company(session, name, ticker)
    session.add(ArticleCompany(article_id=art.id, company_id=company.id,
                               sentiment=sentiment, importance=importance))
    if theme:
        theme_row = session.query(Theme).filter_by(name=theme).one()
        session.add(ArticleTheme(article_id=art.id, theme_id=theme_row.id, confidence=0.9))
    session.flush()
    return art


def _outcomes(session):
    return {o.horizon: o for o in session.query(SentimentOutcome).all()}


# --- pure window logic ----------------------------------------------------

def test_event_day_is_publication_day_before_the_close():
    dates = [date(2026, 11, 16), date(2026, 11, 17)]
    assert event_index(dates, datetime(2026, 11, 16, 10, 0, tzinfo=NY)) == 0


def test_article_after_the_close_belongs_to_next_session():
    dates = [date(2026, 11, 16), date(2026, 11, 17)]
    assert event_index(dates, datetime(2026, 11, 16, 17, 30, tzinfo=NY)) == 1


def test_weekend_article_belongs_to_monday():
    dates = [date(2026, 11, 13), date(2026, 11, 16)]  # Fri, Mon
    assert event_index(dates, datetime(2026, 11, 14, 12, 0, tzinfo=NY)) == 1


def test_no_session_after_publication_yet():
    assert event_index([date(2026, 11, 13)], datetime(2026, 11, 14, 12, 0, tzinfo=NY)) is None


def test_windows():
    assert window(day0=3, horizon=0, n_bars=10) == (2, 3)    # reaction
    assert window(day0=3, horizon=5, n_bars=10) == (3, 8)    # drift
    assert window(day0=0, horizon=0, n_bars=10) is None      # no close before the article
    assert window(day0=3, horizon=20, n_bars=10) is None     # not matured yet


# --- scoring --------------------------------------------------------------

def test_evaluate_scores_matured_horizons_against_benchmark(session):
    # Tue 2026-10-27, 10:00 New York: event day is 10-27, prior close 10-26.
    _mention(session, "a1", datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc), "Microsoft", "MSFT")
    prices = FakePrices({"MSFT": _series(0.01), "SPY": _series(0.005)})

    written = _service(session, prices).evaluate(now=NOW)

    rows = _outcomes(session)
    # Bars run to Fri 11-20 (today's bar is never stored): 18 sessions after 10-27,
    # so 0/1/5 have matured and 20 has not.
    assert written == 3 and set(rows) == {0, 1, 5}
    assert rows[0].start_date == date(2026, 10, 26) and rows[0].end_date == date(2026, 10, 27)
    assert rows[0].event_date == date(2026, 10, 27)
    assert rows[0].stock_return == pytest.approx(0.01)
    assert rows[0].abnormal_return == pytest.approx(0.01 - 0.005)
    assert rows[5].start_date == date(2026, 10, 27) and rows[5].end_date == date(2026, 11, 3)
    assert rows[5].abnormal_return == pytest.approx(1.01 ** 5 - 1.005 ** 5)


def test_todays_bar_is_not_stored(session):
    _mention(session, "a1", datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc), "Microsoft", "MSFT")
    _service(session, FakePrices({"MSFT": _series(0.01), "SPY": _series(0.0)})).evaluate(now=NOW)
    last = max(b.trade_date for b in session.query(PriceBar).filter_by(symbol="MSFT"))
    assert last == date(2026, 11, 20)


def test_evaluate_is_incremental(session):
    _mention(session, "a1", datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc), "Microsoft", "MSFT")
    service = _service(session, FakePrices({"MSFT": _series(0.01), "SPY": _series(0.0)}))
    assert service.evaluate(now=NOW) == 3
    assert service.evaluate(now=NOW) == 0


def test_unknown_ticker_is_marked_and_not_refetched_for_a_week(session):
    _mention(session, "a1", datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc), "Ghost Co", "ZZZZ")
    prices = FakePrices({"SPY": _series(0.0)})
    service = _service(session, prices)

    service.evaluate(now=NOW)
    assert session.get(PriceTicker, "ZZZZ").status == "not_found"

    prices.calls.clear()
    service.evaluate(now=NOW + timedelta(days=1))
    assert "ZZZZ" not in prices.calls
    service.evaluate(now=NOW + timedelta(days=8))
    assert "ZZZZ" in prices.calls


def test_transient_failure_is_retried_not_marked(session):
    _mention(session, "a1", datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc), "Microsoft", "MSFT")
    prices = FakePrices({"MSFT": RuntimeError("timeout"), "SPY": _series(0.0)})
    assert _service(session, prices).evaluate(now=NOW) == 0
    assert session.get(PriceTicker, "MSFT") is None


def test_no_benchmark_means_no_outcomes(session):
    _mention(session, "a1", datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc), "Microsoft", "MSFT")
    prices = FakePrices({"MSFT": _series(0.01), "SPY": RuntimeError("down")})
    assert _service(session, prices).evaluate(now=NOW) == 0
    assert "MSFT" not in prices.calls


def test_recent_articles_wait(session):
    _mention(session, "a1", NOW - timedelta(hours=3), "Microsoft", "MSFT")
    prices = FakePrices({"MSFT": _series(0.01), "SPY": _series(0.0)})
    assert _service(session, prices).evaluate(now=NOW) == 0
    assert prices.calls == []


# --- summary --------------------------------------------------------------

def test_summary_dedups_same_day_mentions_and_reports_hit_rates(session):
    seed_taxonomy(session)
    published = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)
    # Same company, same day: the importance-8 positive call counts, the
    # importance-3 negative one does not.
    _mention(session, "a1", published, "Microsoft", "MSFT", "positive", 8, theme="Cloud Software")
    _mention(session, "a2", published, "Microsoft", "MSFT", "negative", 3, theme="Cloud Software")
    _mention(session, "a3", published, "Snowflake", "SNOW", "negative", 6, theme="Cloud Software")
    _mention(session, "a4", published, "Private Co", None, "positive", 5)
    prices = FakePrices({"MSFT": _series(0.01), "SNOW": _series(-0.01), "SPY": _series(0.0)})
    service = _service(session, prices)
    service.evaluate(now=NOW)

    s = service.summarize()

    pos, neg = s["overall"][(0, "positive")], s["overall"][(0, "negative")]
    assert pos.n == 1 and pos.hit_rate == 1.0 and pos.mean == pytest.approx(0.01)
    assert neg.n == 1 and neg.hit_rate == 1.0 and neg.mean == pytest.approx(-0.01)
    assert s["importance"][("8-10", 0, "positive")].n == 1
    assert ("1-3", 0, "negative") not in s["importance"]
    assert s["theme"][("Cloud Software", 5, "negative")].n == 1
    assert s["coverage"] == {"mentions": 4, "no_ticker": 1, "unmapped_ticker": 0,
                             "ticker_not_found": 0, "scored": 3, "pending": 0}
