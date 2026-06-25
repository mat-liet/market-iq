import time

from app.db.models import Article, Theme, ArticleTheme, ArticleCompany, ClassificationLog
from app.services.companies import upsert_company
from app.services.llm import build_prompt, parse_response, call_gemini, call_with_retry


_VALID_SENTIMENTS = frozenset({"positive", "negative", "neutral"})


def _clean_sentiment(value) -> str | None:
    """Drop any sentiment outside the column's CHECK enum."""
    return value if value in _VALID_SENTIMENTS else None


def _clean_importance(value) -> int | None:
    """Coerce importance to an int in 1..10, else drop it (CHECK enforces the
    range; a model returning 12 or "high" must not abort the whole commit)."""
    if isinstance(value, bool):  # bool is an int subclass — reject it
        return None
    if isinstance(value, (int, float)):
        ivalue = int(value)
        if 1 <= ivalue <= 10:
            return ivalue
    return None


def store_classification(session, article: Article, result: dict) -> None:
    """Persist themes (known only), companies, and sentiment/importance.

    The LLM output is untrusted: a plausible response can repeat the same
    theme/company within one article (→ PK violation) or return an
    out-of-range importance / unknown sentiment (→ CHECK violation). We dedup
    within the article and drop invalid scalars so a single bad response can't
    poison the commit and stall the queue.
    """
    seen_themes: set = set()
    for theme_entry in result.get("themes") or []:
        theme = session.query(Theme).filter_by(name=theme_entry.get("name")).one_or_none()
        if theme is None:
            continue  # unknown theme — skip (prompt forbids inventing themes)
        if theme.id in seen_themes:
            continue  # duplicate theme in one response — store once
        seen_themes.add(theme.id)
        session.add(ArticleTheme(
            article_id=article.id,
            theme_id=theme.id,
            confidence=theme_entry.get("confidence"),
        ))

    sentiment = _clean_sentiment(result.get("sentiment"))
    importance = _clean_importance(result.get("importance"))
    seen_companies: set = set()
    for company_entry in result.get("companies") or []:
        name = company_entry.get("name")
        if not name:
            continue
        company = upsert_company(session, name, company_entry.get("ticker"))
        if company.id in seen_companies:
            continue  # two names resolved to the same company — store once
        seen_companies.add(company.id)
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
        try:
            session.add(ClassificationLog(
                article_id=article.id, raw_response=raw, parsed_ok=result is not None,
            ))
            if result is not None:
                store_classification(session, article, result)
            article.processed = True
            session.commit()
        except Exception:
            # Persistence failed (e.g. an unforeseen constraint violation).
            # Roll back the partial writes, then record the failure and mark
            # the article processed in a fresh transaction so it is NOT
            # re-selected forever (a poison pill that would stall the queue).
            session.rollback()
            session.add(ClassificationLog(
                article_id=article.id, raw_response=raw, parsed_ok=False,
            ))
            article.processed = True
            session.commit()
        processed_count += 1
        sleeper(sleep_s)

    return processed_count
