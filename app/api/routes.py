from fastapi import APIRouter, Depends

from app.db.session import SessionLocal
from app.repositories.report import ReportRepository
from app.repositories.theme import ThemeRepository
from app.services.report import ReportService

router = APIRouter()


def get_session():
    with SessionLocal() as session:
        yield session


def get_report_service(session=Depends(get_session)) -> ReportService:
    return ReportService(ReportRepository(session), ThemeRepository(session))


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/report/daily")
def report_daily(service: ReportService = Depends(get_report_service)):
    return service.generate_report()


@router.get("/report/{theme}")
def report_theme(theme: str, service: ReportService = Depends(get_report_service)):
    return service.theme_report(theme)


@router.get("/articles/{theme}")
def articles_for_theme(theme: str, service: ReportService = Depends(get_report_service)):
    return service.articles_for_theme(theme)


@router.get("/companies/{theme}")
def companies_for_theme(theme: str, service: ReportService = Depends(get_report_service)):
    return service.companies_for_theme(theme)
