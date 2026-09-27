"""Quality-gate CLI (build step 3). Runs classification over a sample of stored
articles and prints results for manual accuracy scoring. READ-ONLY: does not
write classifications or mark articles processed.

Usage:
    python -m scripts.review_classifications [N]   # N = sample size (default 20)
"""
import sys

import anthropic

from app.config import Settings
from app.db.session import SessionLocal
from app.db.models import Article
from app.services.llm import call_claude, parse_response


def main(sample_size: int = 20) -> None:
    settings = Settings.from_env()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    with SessionLocal() as session:
        articles = session.query(Article).limit(sample_size).all()

    if not articles:
        print("No articles in the database. Run ingestion first.")
        return

    print(f"Model: {settings.claude_model}  Effort: {settings.claude_effort or '(default)'}")
    for i, article in enumerate(articles, 1):
        raw = call_claude(
            client, settings.claude_model, settings.claude_effort,
            {"title": article.title, "body": article.body or ""},
        )
        parsed = parse_response(raw)

        print(f"\n{'=' * 70}\n[{i}/{len(articles)}] {article.title}\n{article.url}")
        print(f"{'-' * 70}")
        if parsed:
            print(f"Themes:     {parsed.get('themes')}")
            print("Companies:")
            for c in parsed.get("companies") or []:
                print(f"  - {c.get('name')} ({c.get('ticker')}): "
                      f"{c.get('sentiment')}, importance {c.get('importance')}")
            print(f"Reason:     {parsed.get('reason')}")
        else:
            print(f"PARSE FAILED. Raw response:\n{raw}")

    print(f"\n{'=' * 70}\nScore each as Correct / Partial / Wrong. "
          f"Target >85% correct before proceeding to Task 8.")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    main(n)
