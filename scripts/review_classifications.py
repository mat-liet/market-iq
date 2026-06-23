"""Quality-gate CLI (build step 3). Runs classification over a sample of stored
articles and prints results for manual accuracy scoring. READ-ONLY: does not
write classifications or mark articles processed.

Usage:
    python -m scripts.review_classifications [N]   # N = sample size (default 20)
"""
import sys

from google import genai

from app.config import Settings
from app.db.session import SessionLocal
from app.db.models import Article
from app.services.llm import build_prompt, parse_response, call_gemini, call_with_retry


def main(sample_size: int = 20) -> None:
    settings = Settings.from_env()
    client = genai.Client(api_key=settings.gemini_api_key)

    with SessionLocal() as session:
        articles = session.query(Article).limit(sample_size).all()

    if not articles:
        print("No articles in the database. Run ingestion first.")
        return

    for i, article in enumerate(articles, 1):
        prompt = build_prompt({"title": article.title, "body": article.body or ""})
        raw = call_with_retry(lambda: call_gemini(client, settings.gemini_model, prompt))
        parsed = parse_response(raw)

        print(f"\n{'=' * 70}\n[{i}/{len(articles)}] {article.title}\n{article.url}")
        print(f"{'-' * 70}")
        if parsed:
            print(f"Themes:     {parsed.get('themes')}")
            print(f"Companies:  {parsed.get('companies')}")
            print(f"Sentiment:  {parsed.get('sentiment')}   Importance: {parsed.get('importance')}")
            print(f"Reason:     {parsed.get('reason')}")
        else:
            print(f"PARSE FAILED. Raw response:\n{raw}")

    print(f"\n{'=' * 70}\nScore each as Correct / Partial / Wrong. "
          f"Target >85% correct before proceeding to Task 8.")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    main(n)
