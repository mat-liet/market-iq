from app.services.taxonomy import TAXONOMY, TaxonomyService
from app.repositories.theme import ThemeRepository
from app.db.models import Theme


def _seed(session):
    TaxonomyService(ThemeRepository(session), session).seed_taxonomy()


def test_taxonomy_is_non_empty():
    assert TAXONOMY and all(TAXONOMY.values())


def test_seed_inserts_themes(session):
    _seed(session)
    names = {t.name for t in session.query(Theme).all()}
    assert names == set(TAXONOMY)


def test_seed_is_idempotent(session):
    _seed(session)
    _seed(session)
    assert session.query(Theme).count() == len(TAXONOMY)
