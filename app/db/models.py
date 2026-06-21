from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Text, Boolean, Float, Integer, DateTime, ForeignKey,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
