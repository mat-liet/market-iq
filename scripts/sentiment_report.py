"""Print how well stored sentiment matched what the stocks did next.

    python -m scripts.sentiment_report            # summary from stored outcomes
    python -m scripts.sentiment_report --evaluate  # fetch prices and score first

Returns are abnormal (stock minus SPY over the same dates). Horizon 0 is the
reaction around publication; 1d/5d/20d are the drift after the event day.
"""
import argparse

from app.db.session import SessionLocal
from app.repositories.outcome import OutcomeRepository
from app.services.outcomes import HORIZONS, OutcomeService
from app.services.prices import YahooPriceSource

SENTIMENTS = ("positive", "neutral", "negative")


def _label(h: int) -> str:
    return "reaction" if h == 0 else f"drift {h}d"


def _pct(x: float | None) -> str:
    return "    -" if x is None else f"{x * 100:+6.2f}%"


def _spread(stats, *prefix):
    pos, neg = stats.get((*prefix, "positive")), stats.get((*prefix, "negative"))
    return None if not (pos and neg) else pos.mean - neg.mean


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluate", action="store_true", help="fetch prices and score first")
    args = parser.parse_args()

    with SessionLocal() as session:
        service = OutcomeService(OutcomeRepository(session), session, YahooPriceSource())
        if args.evaluate:
            print(f"scored {service.evaluate()} new outcomes\n")
        s = service.summarize()

    c = s["coverage"]
    print(f"Mentions with sentiment: {c['mentions']}  scored: {c['scored']}  "
          f"waiting for prices: {c['pending']}")
    print(f"Not scorable: no ticker {c['no_ticker']}, unmapped ticker {c['unmapped_ticker']}, "
          f"unknown to price source {c['ticker_not_found']}\n")

    print("Overall (abnormal return vs SPY)")
    print(f"{'window':<10} {'sentiment':<9} {'n':>5} {'mean':>8} {'median':>8} {'hit rate':>9}")
    for h in HORIZONS:
        if not any((h, sentiment) in s["overall"] for sentiment in SENTIMENTS):
            continue  # nothing has matured this far yet
        for sentiment in SENTIMENTS:
            st = s["overall"].get((h, sentiment))
            if st:
                hit = "    -" if st.hit_rate is None else f"{st.hit_rate * 100:7.1f}%"
                print(f"{_label(h):<10} {sentiment:<9} {st.n:>5} {_pct(st.mean):>8} "
                      f"{_pct(st.median):>8} {hit:>9}")
        print(f"{'':<10} {'spread':<9} {'':>5} {_pct(_spread(s['overall'], h)):>8}  "
              "(positive mean - negative mean)")

    for name, title in (("importance", "By importance"), ("theme", "By theme")):
        print(f"\n{title}: positive-minus-negative spread (n positive / n negative)")
        groups = sorted({k[0] for k in s[name]})
        print(f"{'':<32}" + "".join(f"{_label(h):>20}" for h in HORIZONS))
        for g in groups:
            cells = []
            for h in HORIZONS:
                pos, neg = s[name].get((g, h, "positive")), s[name].get((g, h, "negative"))
                counts = f"({pos.n if pos else 0}/{neg.n if neg else 0})"
                cells.append(f"{_pct(_spread(s[name], g, h))} {counts:>9}")
            print(f"{g[:31]:<32}" + "".join(f"{cell:>20}" for cell in cells))


if __name__ == "__main__":
    main()
