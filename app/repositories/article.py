from sqlalchemy.dialects.postgresql import insert

from app.db.models import Article, ArticleTheme, ArticleCompany, ClassificationLog


class ArticleRepository:
    """Data access for articles and their per-article association rows."""

    def __init__(self, session):
        self.session = session

    def insert_ignore(self, values: dict) -> int:
        """Insert an article, skipping duplicates by URL. Returns rows inserted (0 or 1)."""
        stmt = (
            insert(Article)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["url"])
        )
        return self.session.execute(stmt).rowcount

    def list_unprocessed(self, limit: int) -> list[Article]:
        return (
            self.session.query(Article)
            .filter(Article.processed.is_(False))
            .limit(limit)
            .all()
        )

    def mark_processed(self, article: Article) -> None:
        article.processed = True

    def add_theme_link(self, article_id, theme_id, confidence) -> None:
        self.session.add(ArticleTheme(
            article_id=article_id, theme_id=theme_id, confidence=confidence,
        ))

    def add_company_link(self, article_id, company_id, sentiment, importance) -> None:
        self.session.add(ArticleCompany(
            article_id=article_id, company_id=company_id,
            sentiment=sentiment, importance=importance,
        ))

    def add_classification_log(self, article_id, raw_response, parsed_ok) -> None:
        self.session.add(ClassificationLog(
            article_id=article_id, raw_response=raw_response, parsed_ok=parsed_ok,
        ))
