from app.services.config_files import load_taxonomy

# Narrative taxonomy, loaded from TAXONOMY_FILE (see app/services/config_files.py).
TAXONOMY = load_taxonomy()


class TaxonomyService:
    """Seeds the fixed narrative taxonomy (idempotent)."""

    def __init__(self, theme_repo, session):
        self.theme_repo = theme_repo
        self.session = session  # held only as the transaction boundary

    def seed_taxonomy(self) -> None:
        """Insert taxonomy themes. Idempotent — does nothing for names already present."""
        for name, keywords in TAXONOMY.items():
            self.theme_repo.upsert_ignore(name, keywords)
        self.session.commit()
