import time

from app.db.models import Article, Theme, ArticleTheme, ArticleCompany, ClassificationLog
from app.services.companies import upsert_company
from app.services.llm import build_prompt, parse_response, call_gemini, call_with_retry


def store_classification(session, article: Article, result: dict) -> None:
    """Persist themes (known only), companies, and sentiment/importance."""
    for theme_entry in result.get("themes") or []:
        theme = session.query(Theme).filter_by(name=theme_entry.get("name")).one_or_none()
        if theme is None:
            continue  # unknown theme — skip (prompt forbids inventing themes)
        session.add(ArticleTheme(
            article_id=article.id,
            theme_id=theme.id,
            confidence=theme_entry.get("confidence"),
        ))

    sentiment = result.get("sentiment")
    importance = result.get("importance")
    for company_entry in result.get("companies") or []:
        name = company_entry.get("name")
        if not name:
            continue
        company = upsert_company(session, name, company_entry.get("ticker"))
        session.add(ArticleCompany(
            article_id=article.id,
            company_id=company.id,
            sentiment=sentiment,
            importance=importance,
        ))


def classify_batch(session, client, model: str, batch_size: int = 10,
                   sleep_s: float = 4.0, base_delay: float = 2.0,
                   sleeper=None) -> int:
    """Classify a batch of unprocessed articles.

    Returns the count of articles successfully processed (marked processed).
    If an article's LLM call fails after all retries, it is left unprocessed
    (no ClassificationLog written) so a later run can retry it.
    One bad article does not abort the batch.
    """
    sleeper = sleeper if sleeper is not None else time.sleep

    articles = (
        session.query(Article)
        .filter(Article.processed.is_(False))
        .limit(batch_size)
        .all()
    )
    processed_count = 0
    for article in articles:
        prompt = build_prompt({"title": article.title, "body": article.body or ""})
        try:
            raw = call_with_retry(
                lambda p=prompt: call_gemini(client, model, p),
                base_delay=base_delay,
                sleeper=sleeper,
            )
        except Exception:
            # Retries exhausted (persistent transient error or quota).
            # Leave article unprocessed so the next scheduled run retries it.
            # Do NOT write a ClassificationLog — no response was received.
            continue

        result = parse_response(raw)
        session.add(ClassificationLog(
            article_id=article.id, raw_response=raw, parsed_ok=result is not None,
        ))
        if result is not None:
            store_classification(session, article, result)
        article.processed = True
        session.commit()
        processed_count += 1
        sleeper(sleep_s)

    return processed_count
