"""Check every configured feed: is it live, and does its article text extract?

    python -m scripts.check_feeds

For each feed it parses the RSS, then runs the production body extractor on the
first few entries. Exits non-zero if any feed is dead, so it can gate a deploy.
A feed marked HEADLINES-ONLY works, but the classifier only sees the RSS
summary (usually a paywall or bot block on the article pages).
"""
import sys

from app.services.body_extractor import TrafilaturaExtractor
from app.services.ingestion import RSS_SOURCES, fetch_feed

SAMPLE = 3
MIN_BODY_CHARS = 500


def main() -> int:
    extractor = TrafilaturaExtractor()
    dead = 0
    for source, url in RSS_SOURCES.items():
        try:
            entries = fetch_feed(url)
        except Exception as exc:  # network errors, malformed XML
            entries, error = [], str(exc)
        else:
            error = None
        if not entries:
            dead += 1
            print(f"DEAD            {source:<22} {error or 'no entries'}")
            continue
        lengths = [len(extractor.extract(e["link"]) or "") for e in entries[:SAMPLE] if e["link"]]
        full = sum(n >= MIN_BODY_CHARS for n in lengths)
        status = "OK" if full else "HEADLINES-ONLY"
        print(f"{status:<15} {source:<22} entries={len(entries):<4} "
              f"full_text={full}/{len(lengths)} body_chars={lengths}")
    print(f"\n{len(RSS_SOURCES) - dead}/{len(RSS_SOURCES)} feeds live")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
