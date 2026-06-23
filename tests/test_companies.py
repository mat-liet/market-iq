from app.services.companies import normalize_company_name, upsert_company
from app.db.models import Company


def test_normalization_strips_suffix_and_lowercases():
    assert normalize_company_name("NVIDIA Corp") == "nvidia"
    assert normalize_company_name("Nvidia") == "nvidia"
    assert normalize_company_name("Acme, Inc.") == "acme"


def test_normalization_keeps_tokens_when_all_are_suffixes():
    # An all-suffix name must not normalize to "" — that would silently merge
    # unrelated companies under the unique normalized_name index.
    assert normalize_company_name("Group Holdings") == "group holdings"
    assert normalize_company_name("Holdings") == "holdings"


def test_upsert_keeps_all_suffix_names_distinct(session):
    a = upsert_company(session, "Group Holdings", None)
    b = upsert_company(session, "Acme", None)
    session.flush()
    assert a.id != b.id
    assert session.query(Company).count() == 2


def test_upsert_dedups_by_ticker(session):
    a = upsert_company(session, "NVIDIA", "NVDA")
    b = upsert_company(session, "Nvidia Corporation", "NVDA")
    session.flush()
    assert a.id == b.id
    assert session.query(Company).count() == 1


def test_upsert_dedups_by_normalized_name_when_no_ticker(session):
    a = upsert_company(session, "NVIDIA Corp", None)
    b = upsert_company(session, "Nvidia", None)
    session.flush()
    assert a.id == b.id
    assert session.query(Company).count() == 1


def test_upsert_creates_distinct_companies(session):
    upsert_company(session, "NVIDIA", "NVDA")
    upsert_company(session, "Microsoft", "MSFT")
    session.flush()
    assert session.query(Company).count() == 2
