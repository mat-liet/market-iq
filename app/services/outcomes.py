"""Scores stored sentiment against what each stock did after the article.

For every company mention with a ticker, once enough trading days have passed:

- event day: the first trading day whose close comes after publication
  (an article published after 16:00 exchange time belongs to the next session);
- horizon 0, the reaction: close before publication -> close of the event day;
- horizon n > 0, the drift: close of the event day -> close n trading days later.

Each return is taken relative to the benchmark (SPY) over the same dates, so a
market-wide move doesn't count as a right or wrong call.
"""
import logging
import statistics
import time as time_module
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.prices import PriceSource, TickerNotFound, normalize_ticker

logger = logging.getLogger(__name__)

HORIZONS = (0, 1, 5, 20)
BENCHMARK = "SPY"
MARKET_CLOSE = time(16, 0)          # approximation: most exchanges close 15:30-17:30
LOOKBACK = timedelta(days=10)        # history fetched before the earliest article
NOT_FOUND_RECHECK = timedelta(days=7)
REQUEST_PAUSE_SECONDS = 0.5          # be gentle with the (unofficial) price source

IMPORTANCE_BANDS = (("1-3", 1, 3), ("4-7", 4, 7), ("8-10", 8, 10))


def event_index(dates: list[date], published_local: datetime) -> int | None:
    """Index of the event day: the first trading day whose close is after publication."""
    after_close = published_local.time() >= MARKET_CLOSE
    pub = published_local.date()
    for i, d in enumerate(dates):
        if d > pub or (d == pub and not after_close):
            return i
    return None


def window(day0: int, horizon: int, n_bars: int) -> tuple[int, int] | None:
    """(start, end) bar indexes for a horizon, or None if not yet available."""
    start, end = (day0 - 1, day0) if horizon == 0 else (day0, day0 + horizon)
    if start < 0 or end >= n_bars:
        return None
    return start, end


def close_on_or_before(dates: list[date], closes: list[float], d: date) -> float | None:
    i = bisect_right(dates, d) - 1
    return closes[i] if i >= 0 else None


@dataclass(frozen=True)
class Stats:
    n: int
    mean: float
    median: float
    hit_rate: float | None  # share of calls the abnormal return agreed with; None for neutral


def _stats(sentiment: str, returns: list[float]) -> Stats:
    hits = None
    if sentiment == "positive":
        hits = sum(r > 0 for r in returns) / len(returns)
    elif sentiment == "negative":
        hits = sum(r < 0 for r in returns) / len(returns)
    return Stats(len(returns), statistics.fmean(returns), statistics.median(returns), hits)


def _band(importance: int | None) -> str | None:
    for label, lo, hi in IMPORTANCE_BANDS:
        if importance is not None and lo <= importance <= hi:
            return label
    return None


class OutcomeService:
    def __init__(self, outcome_repo, session, prices: PriceSource,
                 pause=lambda: time_module.sleep(REQUEST_PAUSE_SECONDS)):
        self.repo = outcome_repo
        self.session = session  # held only as the transaction boundary
        self.prices = prices
        self.pause = pause

    # --- scoring ---------------------------------------------------------

    def evaluate(self, now: datetime | None = None) -> int:
        """Fetch prices and write every outcome that has matured. Returns rows written."""
        now = now or datetime.now(timezone.utc)
        mentions = self.repo.pending_mentions(len(HORIZONS), now - timedelta(days=1))
        by_symbol = defaultdict(list)
        for m in mentions:
            symbol = normalize_ticker(m["ticker"])
            if symbol:
                by_symbol[symbol].append(m)
        if not by_symbol:
            return 0

        earliest = min(m["published_at"] for m in mentions).date() - LOOKBACK
        statuses = self.repo.ticker_statuses([*by_symbol, BENCHMARK])
        benchmark_tz = self._refresh(BENCHMARK, earliest, now)
        if benchmark_tz is None:
            logger.warning("benchmark %s unavailable; skipping outcome run", BENCHMARK)
            return 0
        bench = self.repo.get_bars(BENCHMARK)
        bench_dates, bench_closes = [d for d, _ in bench], [c for _, c in bench]

        written = 0
        for symbol, items in by_symbol.items():
            status = statuses.get(symbol)
            if (status and status.status == "not_found"
                    and now - status.checked_at < NOT_FOUND_RECHECK):
                continue
            start = min(m["published_at"] for m in items).date() - LOOKBACK
            tz = self._refresh(symbol, start, now)
            if tz is None:
                continue
            written += self._score(symbol, ZoneInfo(tz), items, bench_dates, bench_closes)
            self.session.commit()
        return written

    def _refresh(self, symbol: str, start: date, now: datetime) -> str | None:
        """Fetch and cache bars for a symbol. Returns its exchange timezone, or
        None if it is unknown or the fetch failed (retried on the next run)."""
        self.pause()
        try:
            series = self.prices.daily_closes(symbol, start, now.date())
        except TickerNotFound:
            self.repo.set_ticker(symbol, "not_found", None, now)
            self.session.commit()
            return None
        except Exception as exc:
            logger.warning("price fetch failed for %s: %s", symbol, exc)
            return None
        # Today's bar may still be moving; only store sessions that have finished.
        today = now.astimezone(ZoneInfo(series.exchange_tz)).date()
        self.repo.upsert_bars(symbol, [(d, c) for d, c in series.closes if d < today])
        self.repo.set_ticker(symbol, "ok", series.exchange_tz, now)
        self.session.commit()
        return series.exchange_tz

    def _score(self, symbol, zone, mentions, bench_dates, bench_closes) -> int:
        bars = self.repo.get_bars(symbol)
        dates, closes = [d for d, _ in bars], [c for _, c in bars]
        written = 0
        for m in mentions:
            day0 = event_index(dates, m["published_at"].astimezone(zone))
            if day0 is None:
                continue
            for horizon in set(HORIZONS) - set(m["done"]):
                w = window(day0, horizon, len(dates))
                if w is None:
                    continue
                s, e = w
                b_start = close_on_or_before(bench_dates, bench_closes, dates[s])
                b_end = close_on_or_before(bench_dates, bench_closes, dates[e])
                if b_start is None or b_end is None:
                    continue
                stock_return = closes[e] / closes[s] - 1
                benchmark_return = b_end / b_start - 1
                self.repo.add_outcome(
                    article_id=m["article_id"], company_id=m["company_id"],
                    horizon=horizon, symbol=symbol, event_date=dates[day0],
                    start_date=dates[s], end_date=dates[e],
                    stock_return=stock_return, benchmark_return=benchmark_return,
                    abnormal_return=stock_return - benchmark_return,
                )
                written += 1
        return written

    # --- reporting -------------------------------------------------------

    def summarize(self) -> dict:
        """Abnormal-return stats by horizon x sentiment, overall, by importance
        band and by theme, plus how many mentions could be scored at all."""
        rows = self.repo.scored_mentions()
        themes = self.repo.themes_for_articles({r["article_id"] for r in rows})
        groups = {"overall": defaultdict(list), "importance": defaultdict(list),
                  "theme": defaultdict(list)}
        for r in rows:
            key = (r["horizon"], r["sentiment"])
            groups["overall"][key].append(r["abnormal_return"])
            band = _band(r["importance"])
            if band:
                groups["importance"][(band, *key)].append(r["abnormal_return"])
            for theme in themes.get(r["article_id"], []):
                groups["theme"][(theme, *key)].append(r["abnormal_return"])
        result = {
            name: {k: _stats(k[-1], v) for k, v in sorted(g.items())}
            for name, g in groups.items()
        }
        result["coverage"] = self._coverage()
        return result

    def _coverage(self) -> dict:
        statuses = self.repo.all_ticker_statuses()
        counts = {"mentions": 0, "no_ticker": 0, "unmapped_ticker": 0,
                  "ticker_not_found": 0, "scored": 0, "pending": 0}
        for m in self.repo.mention_coverage():
            counts["mentions"] += 1
            symbol = normalize_ticker(m["ticker"])
            if not m["ticker"]:
                counts["no_ticker"] += 1
            elif symbol is None:
                counts["unmapped_ticker"] += 1
            elif statuses.get(symbol) == "not_found":
                counts["ticker_not_found"] += 1
            elif m["scored"]:
                counts["scored"] += 1
            else:
                counts["pending"] += 1
        return counts
