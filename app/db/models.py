from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Text, Boolean, Float, Integer, Date, DateTime, ForeignKey, ForeignKeyConstraint,
    CheckConstraint, Index, func, text,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    __table_args__ = (
        Index("idx_articles_processed", "processed"),
        Index("idx_articles_published", "published_at"),
    )


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text))


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str | None] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_companies_ticker", "ticker", unique=True, postgresql_where=text("ticker IS NOT NULL")),
        Index("idx_companies_normalized_name", "normalized_name", unique=True),
    )


class ArticleTheme(Base):
    __tablename__ = "article_themes"

    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    theme_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("themes.id"), primary_key=True)
    confidence: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("idx_article_themes_theme", "theme_id"),)


class ArticleCompany(Base):
    __tablename__ = "article_companies"

    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    sentiment: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("sentiment IN ('positive', 'negative', 'neutral')", name="ck_sentiment"),
        CheckConstraint("importance BETWEEN 1 AND 10", name="ck_importance"),
        Index("idx_article_companies_company", "company_id"),
    )


class ClassificationLog(Base):
    __tablename__ = "classification_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"))
    raw_response: Mapped[str | None] = mapped_column(Text)
    parsed_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceTicker(Base):
    """A price symbol the outcome worker has looked up: whether the price source
    knows it, and the exchange timezone its daily bars are dated in."""
    __tablename__ = "price_tickers"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    exchange_tz: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('ok', 'not_found')", name="ck_price_ticker_status"),
    )


class PriceBar(Base):
    """Daily (split/dividend-adjusted) close for a symbol, dated in exchange time."""
    __tablename__ = "price_bars"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)


class SentimentOutcome(Base):
    """How a company's stock moved after an article mentioned it, relative to the
    benchmark. horizon 0 is the reaction (close before publication -> close of
    the event day); horizon n > 0 is the drift from the event-day close to the
    close n trading days later."""
    __tablename__ = "sentiment_outcomes"

    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    horizon: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    stock_return: Mapped[float] = mapped_column(Float, nullable=False)
    benchmark_return: Mapped[float] = mapped_column(Float, nullable=False)
    abnormal_return: Mapped[float] = mapped_column(Float, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["article_id", "company_id"],
            ["article_companies.article_id", "article_companies.company_id"],
        ),
        CheckConstraint("horizon >= 0", name="ck_outcome_horizon"),
        Index("idx_sentiment_outcomes_event", "company_id", "event_date"),
    )
