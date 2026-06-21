from app.db.session import SessionLocal
from app.services.taxonomy import seed_taxonomy

if __name__ == "__main__":
    with SessionLocal() as session:
        seed_taxonomy(session)
        print("Taxonomy seeded.")
