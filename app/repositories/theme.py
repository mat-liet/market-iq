from sqlalchemy.dialects.postgresql import insert

from app.db.models import Theme


class ThemeRepository:
    """Data access for the narrative taxonomy (themes)."""

    def __init__(self, session):
        self.session = session

    def get_by_name(self, name: str) -> Theme | None:
        return self.session.query(Theme).filter_by(name=name).one_or_none()

    def list_all(self) -> list[Theme]:
        return self.session.query(Theme).all()

    def upsert_ignore(self, name: str, keywords) -> None:
        """Insert a theme, doing nothing if the name already exists."""
        stmt = (
            insert(Theme)
            .values(name=name, keywords=keywords)
            .on_conflict_do_nothing(index_elements=["name"])
        )
        self.session.execute(stmt)
