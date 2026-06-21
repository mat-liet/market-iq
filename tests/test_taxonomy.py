from app.services.taxonomy import TAXONOMY, seed_taxonomy
from app.db.models import Theme


def test_taxonomy_has_three_themes():
    assert set(TAXONOMY) == {"AI Infrastructure", "Nuclear Energy", "Defence Spending"}


def test_seed_inserts_themes(session):
    seed_taxonomy(session)
    names = {t.name for t in session.query(Theme).all()}
    assert names == {"AI Infrastructure", "Nuclear Energy", "Defence Spending"}


def test_seed_is_idempotent(session):
    seed_taxonomy(session)
    seed_taxonomy(session)
    assert session.query(Theme).count() == 3
