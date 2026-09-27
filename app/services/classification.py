import logging

from app.db.models import Article
from app.services.llm import call_claude, parse_response

logger = logging.getLogger(__name__)


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


class ClassificationService:
    """Turns LLM responses into stored themes/companies/sentiment and drives the
    batch-classification loop. Owns the per-article transaction boundary."""

    def __init__(self, article_repo, theme_repo, company_service, session):
        self.article_repo = article_repo
        self.theme_repo = theme_repo
        self.company_service = company_service
        self.session = session  # held as the per-article transaction boundary

    def store_classification(self, article: Article, result: dict) -> None:
        """Persist themes (known only), companies, and each company's
        sentiment/importance.

        The LLM output is untrusted: a plausible response can repeat the same
        theme/company within one article (→ PK violation) or return an
        out-of-range importance / unknown sentiment (→ CHECK violation). We dedup
        within the article and drop invalid scalars so a single bad response can't
        poison the commit and stall the queue.
        """
        seen_themes: set = set()
        for theme_entry in result.get("themes") or []:
            theme = self.theme_repo.get_by_name(theme_entry.get("name"))
            if theme is None:
                continue  # unknown theme — skip (prompt forbids inventing themes)
            if theme.id in seen_themes:
                continue  # duplicate theme in one response — store once
            seen_themes.add(theme.id)
            self.article_repo.add_theme_link(article.id, theme.id, theme_entry.get("confidence"))

        seen_companies: set = set()
        for company_entry in result.get("companies") or []:
            name = company_entry.get("name")
            if not name:
                continue
            company = self.company_service.upsert_company(name, company_entry.get("ticker"))
            if company.id in seen_companies:
                continue  # two names resolved to the same company — store once
            seen_companies.add(company.id)
            self.article_repo.add_company_link(
                article.id, company.id,
                _clean_sentiment(company_entry.get("sentiment")),
                _clean_importance(company_entry.get("importance")),
            )

    def classify_batch(self, client, model: str, effort: str | None,
                       batch_size: int = 10) -> int:
        """Classify a batch of unprocessed articles.

        Returns the count of articles successfully processed (marked processed).
        If an article's LLM call fails after the SDK's retries, it is left
        unprocessed (no ClassificationLog written) so a later run can retry it.
        One bad article does not abort the batch.
        """
        articles = self.article_repo.list_unprocessed(batch_size)
        processed_count = 0
        for article in articles:
            try:
                raw = call_claude(
                    client, model, effort,
                    {"title": article.title, "body": article.body or ""},
                )
            except Exception as exc:
                # Retries exhausted (persistent transient error) or a request
                # error. Leave article unprocessed so the next scheduled run
                # retries it. Do NOT write a ClassificationLog — no response.
                logger.warning("classification call failed for article %s: %s", article.id, exc)
                continue

            result = parse_response(raw)
            try:
                self.article_repo.add_classification_log(article.id, raw, result is not None, model)
                if result is not None:
                    self.store_classification(article, result)
                self.article_repo.mark_processed(article)
                self.session.commit()
            except Exception:
                # Persistence failed (e.g. an unforeseen constraint violation).
                # Roll back the partial writes, then record the failure and mark
                # the article processed in a fresh transaction so it is NOT
                # re-selected forever (a poison pill that would stall the queue).
                self.session.rollback()
                self.article_repo.add_classification_log(article.id, raw, False, model)
                self.article_repo.mark_processed(article)
                self.session.commit()
            processed_count += 1

        return processed_count
