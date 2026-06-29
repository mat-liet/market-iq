from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.db.models import Theme
from app.db.session import SessionLocal
from app.services.report import (
    count_articles,
    count_companies,
    emerging_associations,
    generate_report,
    top_articles,
    top_companies,
    wow_growth_pct,
)

router = APIRouter()


def get_session():
    with SessionLocal() as session:
        yield session


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/report/daily")
def report_daily(session=Depends(get_session)):
    return generate_report(session)


@router.get("/report/{theme}")
def report_theme(theme: str, session=Depends(get_session)):
    if session.query(Theme).filter_by(name=theme).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Unknown theme: {theme}")
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    last_start = now - timedelta(days=14)
    this_week = count_articles(session, theme, start, now)
    last_week = count_articles(session, theme, last_start, start)
    return {
        "theme": theme,
        "article_count": this_week,
        "wow_growth_pct": wow_growth_pct(this_week, last_week),
        "company_count": count_companies(session, theme, start, now),
        "top_companies": top_companies(session, theme, start, now),
        "emerging_associations": emerging_associations(session, theme, now=now),
        "important_articles": top_articles(session, theme, start, now),
    }


@router.get("/articles/{theme}")
def articles_for_theme(theme: str, session=Depends(get_session)):
    if session.query(Theme).filter_by(name=theme).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Unknown theme: {theme}")
    now = datetime.now(timezone.utc)
    return {
        "theme": theme,
        "articles": top_articles(session, theme, now - timedelta(days=7), now, limit=50),
    }


@router.get("/companies/{theme}")
def companies_for_theme(theme: str, session=Depends(get_session)):
    if session.query(Theme).filter_by(name=theme).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Unknown theme: {theme}")
    now = datetime.now(timezone.utc)
    return {
        "theme": theme,
        "companies": top_companies(session, theme, now - timedelta(days=7), now, limit=50),
    }
