from app.db.session import SessionLocal
from app.repositories.theme import ThemeRepository
from app.services.taxonomy import TaxonomyService

if __name__ == "__main__":
    with SessionLocal() as session:
        TaxonomyService(ThemeRepository(session), session).seed_taxonomy()
        print("Taxonomy seeded.")
