from app.services.taxonomy import TAXONOMY, TaxonomyService
from app.repositories.theme import ThemeRepository
from app.db.models import Theme


def _seed(session):
    TaxonomyService(ThemeRepository(session), session).seed_taxonomy()


def test_taxonomy_has_three_themes():
    assert set(TAXONOMY) == {"AI Infrastructure", "Nuclear Energy", "Defence Spending"}


def test_seed_inserts_themes(session):
    _seed(session)
    names = {t.name for t in session.query(Theme).all()}
    assert names == {"AI Infrastructure", "Nuclear Energy", "Defence Spending"}


def test_seed_is_idempotent(session):
    _seed(session)
    _seed(session)
    assert session.query(Theme).count() == 3
