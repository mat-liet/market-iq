from app.services.companies import normalize_company_name, upsert_company
from app.db.models import Company


def test_normalization_strips_suffix_and_lowercases():
    assert normalize_company_name("NVIDIA Corp") == "nvidia"
    assert normalize_company_name("Nvidia") == "nvidia"
    assert normalize_company_name("Acme, Inc.") == "acme"


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
