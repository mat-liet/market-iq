from app.db.models import Company


class CompanyRepository:
    """Data access for companies (lookup + insert)."""

    def __init__(self, session):
        self.session = session

    def find_by_ticker(self, ticker: str) -> Company | None:
        return self.session.query(Company).filter(Company.ticker == ticker).one_or_none()

    def find_by_normalized_name(self, normalized_name: str) -> Company | None:
        return (
            self.session.query(Company)
            .filter(Company.normalized_name == normalized_name)
            .one_or_none()
        )

    def add(self, company: Company) -> None:
        self.session.add(company)
        self.session.flush()  # populate the generated id for callers
