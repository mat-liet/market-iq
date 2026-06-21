from sqlalchemy.dialects.postgresql import insert

from app.db.models import Theme

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


def seed_taxonomy(session) -> None:
    """Insert taxonomy themes. Idempotent — does nothing for names already present."""
    for name, keywords in TAXONOMY.items():
        stmt = (
            insert(Theme)
            .values(name=name, keywords=keywords)
            .on_conflict_do_nothing(index_elements=["name"])
        )
        session.execute(stmt)
    session.commit()
