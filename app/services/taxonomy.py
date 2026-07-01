TAXONOMY = {
    "AI Infrastructure": [
        "artificial intelligence", "LLM", "large language model",
        "GPU", "datacentre", "data center", "inference",
        "foundation model", "AI chips", "NVIDIA", "accelerator",
    ],
    "Nuclear Energy": [
        "uranium", "SMR", "small modular reactor",
        "nuclear power", "reactor", "nuclear energy",
        "enriched uranium", "nuclear plant",
    ],
    "Defence Spending": [
        "defence budget", "defense budget", "military spending",
        "missile systems", "defence contracts", "defense contracts",
        "NATO spending", "military procurement", "arms",
    ],
}


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
