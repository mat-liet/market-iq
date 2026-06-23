import re

from app.db.models import Company

_LEGAL_SUFFIXES = {
    "corp", "corporation", "inc", "incorporated", "ltd", "limited",
    "plc", "co", "company", "llc", "sa", "ag", "nv", "group", "holdings",
}


def normalize_company_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", name.lower())
    tokens = [t for t in cleaned.split() if t not in _LEGAL_SUFFIXES]
    return " ".join(tokens).strip()


def upsert_company(session, name: str, ticker: str | None) -> Company:
    """Find or create a company. Match on ticker first (when present),
    then on normalized name. Prevents fragmentation of mention counts."""
    normalized = normalize_company_name(name)

    company = None
    if ticker:
        company = session.query(Company).filter(Company.ticker == ticker).one_or_none()
    if company is None:
        company = (
            session.query(Company)
            .filter(Company.normalized_name == normalized)
            .one_or_none()
        )
    if company is None:
        company = Company(name=name, ticker=ticker, normalized_name=normalized)
        session.add(company)
        session.flush()
    return company
