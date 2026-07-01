import re

from app.db.models import Company

_LEGAL_SUFFIXES = {
    "corp", "corporation", "inc", "incorporated", "ltd", "limited",
    "plc", "co", "company", "llc", "sa", "ag", "nv", "group", "holdings",
}


def normalize_company_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", name.lower())
    tokens = [t for t in cleaned.split() if t not in _LEGAL_SUFFIXES]
    # If every token is a legal suffix (e.g. "Group Holdings"), stripping them
    # all would yield "" — which collapses unrelated companies under the
    # non-partial unique index on normalized_name. Keep the suffix tokens
    # rather than produce an empty key.
    if not tokens:
        tokens = cleaned.split()
    return " ".join(tokens).strip()


class CompanyService:
    """Business rules for resolving companies (find-or-create with dedup)."""

    def __init__(self, company_repo):
        self.company_repo = company_repo

    def upsert_company(self, name: str, ticker: str | None) -> Company:
        """Find or create a company. Match on ticker first (when present),
        then on normalized name. Prevents fragmentation of mention counts."""
        normalized = normalize_company_name(name)

        company = None
        if ticker:
            company = self.company_repo.find_by_ticker(ticker)
        if company is None:
            company = self.company_repo.find_by_normalized_name(normalized)
        if company is None:
            company = Company(name=name, ticker=ticker, normalized_name=normalized)
            self.company_repo.add(company)
        return company
