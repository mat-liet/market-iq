# Market Narrative Intelligence Platform — Phase 1 Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 backend — ingest financial news, classify it into narratives/companies via Gemini Flash, and serve a daily narrative report over a REST API. No UI.

**Architecture:** Decoupled ingestion and classification workers communicating through a `processed` boolean queue in PostgreSQL. Ingestion (feedparser + trafilatura, summary fallback) stores raw articles; a classification worker calls Gemini via the `google-genai` SDK, upserts companies with ticker-first dedup, and writes structured signals. A report generator aggregates per-theme trends, and FastAPI exposes them. Built as an incremental vertical slice with a manual quality-gate STOP after the first source flows end-to-end.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0, Alembic, PostgreSQL 15, FastAPI, APScheduler, feedparser, trafilatura, `google-genai`, pytest, Docker Compose.

**Spec:** `docs/phase-one-design.md` (authoritative), `docs/market-narrative-architecture.md`, `docs/market-narrative-cicd.md`.

---

## File Structure

```
market-iq/
├── docker-compose.yml          # app + postgres:15
├── Dockerfile                  # python:3.11-slim image
├── requirements.txt
├── .env.example                # documents required env vars
├── .gitignore
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
├── app/
│   ├── __init__.py
│   ├── config.py               # Settings from env
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy 2.0 models (single source of schema truth)
│   │   └── session.py          # engine + SessionLocal
│   ├── services/
│   │   ├── __init__.py
│   │   ├── taxonomy.py         # TAXONOMY dict + seed_taxonomy()
│   │   ├── body_extractor.py   # full-text extraction, summary fallback
│   │   ├── llm.py              # prompt builder, parse_response, call_gemini, retry
│   │   ├── companies.py        # normalize_company_name, upsert_company
│   │   └── report.py           # aggregation queries + generate_report
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── ingestion.py        # fetch_feed, verify_feed, ingest_entries
│   │   ├── classification.py   # classify_batch, store_classification
│   │   └── scheduler.py        # APScheduler wiring
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py           # FastAPI router
│   └── main.py                 # FastAPI app factory
├── scripts/
│   ├── seed_taxonomy.py        # CLI wrapper for seed_taxonomy()
│   └── review_classifications.py  # quality-gate CLI (STOP checkpoint tool)
└── tests/
    ├── __init__.py
    ├── conftest.py             # engine + session fixtures
    ├── fixtures.py             # fake feed entries, fake Gemini client
    ├── test_models.py
    ├── test_migration.py
    ├── test_taxonomy.py
    ├── test_body_extractor.py
    ├── test_ingestion.py
    ├── test_llm.py
    ├── test_companies.py
    ├── test_classification.py
    ├── test_report.py
    └── test_api.py
```

**Design notes for the implementer:**
- `app/db/models.py` is the single source of schema truth. Tests build the schema from `Base.metadata.create_all` for speed; one dedicated test (`test_migration.py`) proves the Alembic migration applies cleanly so the two never drift.
- All DB-touching tests run inside a transaction that rolls back after each test (see `conftest.py`), so tests are isolated and order-independent.
- External services are never called in tests: feedparser entries, trafilatura, and the Gemini client are all injected and faked.

**Running the tests:** `app/db/session.py` calls `Settings.from_env()` at import, so `DATABASE_URL` **must be set in the environment before running `pytest`** (otherwise collection fails with `KeyError: 'DATABASE_URL'`). Start the DB and export it once per shell:

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://market:market@localhost:5432/market_narrative
pytest -v
```

The CI workflow in `docs/market-narrative-cicd.md` already sets `DATABASE_URL` for its pytest step, so CI needs no change.

---

## Task 1: Project scaffold + Docker Compose

**Files:**
- Create: `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`
- Create: `app/__init__.py`, `app/config.py`, `app/db/__init__.py`, `app/db/session.py`
- Create: `tests/__init__.py`, `tests/test_config.py`

- [ ] **Step 1: Create `requirements.txt`**

```
sqlalchemy==2.0.36
alembic==1.14.0
psycopg2-binary==2.9.10
fastapi==0.115.5
uvicorn==0.32.1
apscheduler==3.11.0
feedparser==6.0.11
trafilatura==2.0.0
google-genai==1.0.0
pytest==8.3.4
httpx==0.28.1
```

> `httpx` is for FastAPI's `TestClient`. Pin `google-genai` to whatever the current release is at build time; `1.0.0` is a placeholder floor — verify on install.

- [ ] **Step 2: Create `.gitignore`**

```
.env
deploy_key
deploy_key.pub
__pycache__/
*.pyc
.pytest_cache/
.venv/
```

- [ ] **Step 3: Create `.env.example`**

```
DATABASE_URL=postgresql://market:market@localhost:5432/market_narrative
GEMINI_API_KEY=your_key_from_aistudio.google.com
GEMINI_MODEL=gemini-flash-latest
```

- [ ] **Step 4: Write the failing test for config**

`tests/test_config.py`:

```python
import os
from app.config import Settings


def test_settings_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("GEMINI_API_KEY", "abc123")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql://u:p@localhost:5432/db"
    assert settings.gemini_api_key == "abc123"
    assert settings.gemini_model == "gemini-flash-latest"


def test_gemini_key_defaults_to_dummy_for_tests(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.gemini_api_key == "dummy-key-for-tests"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 6: Implement `app/config.py`**

```python
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    gemini_api_key: str
    gemini_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "dummy-key-for-tests"),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
        )
```

- [ ] **Step 7: Create empty package files**

Create `app/__init__.py`, `app/db/__init__.py`, `tests/__init__.py` (all empty).

- [ ] **Step 8: Implement `app/db/session.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import Settings

settings = Settings.from_env()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
```

- [ ] **Step 9: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 10: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 11: Create `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8000:8000"
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: market
      POSTGRES_PASSWORD: market
      POSTGRES_DB: market_narrative
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "market"]
      interval: 10s
      timeout: 5s
      retries: 5
```

- [ ] **Step 12: Commit**

```bash
git add requirements.txt Dockerfile docker-compose.yml .env.example .gitignore app/ tests/
git commit -m "chore: project scaffold, config, docker compose"
```

---

## Task 2: SQLAlchemy models + Alembic migration

**Files:**
- Create: `app/db/models.py`
- Create: `tests/conftest.py`, `tests/test_models.py`, `tests/test_migration.py`
- Create: `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial_schema.py`

- [ ] **Step 1: Implement `app/db/models.py`**

```python
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
```

- [ ] **Step 2: Implement `tests/conftest.py`**

```python
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base

TEST_DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://market:market@localhost:5432/market_narrative"
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL, future=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    connection = engine.connect()
    trans = connection.begin()
    Session = sessionmaker(bind=connection, future=True, expire_on_commit=False)
    sess = Session()
    yield sess
    sess.close()
    trans.rollback()
    connection.close()
```

> `gen_random_uuid()` is built into PostgreSQL 13+, so no extension setup is needed on PG15.

- [ ] **Step 3: Write the failing test for models**

`tests/test_models.py`:

```python
import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

from app.db.models import Article, Company


def test_article_round_trips(session):
    article = Article(
        url="https://example.com/a",
        title="Test",
        body="body",
        source="reuters",
        published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    session.add(article)
    session.flush()
    assert article.id is not None
    assert article.processed is False


def test_duplicate_url_rejected(session):
    session.add(Article(url="https://dup.com", title="A",
                        published_at=datetime.now(timezone.utc)))
    session.flush()
    session.add(Article(url="https://dup.com", title="B",
                        published_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        session.flush()


def test_duplicate_ticker_rejected(session):
    session.add(Company(name="NVIDIA", ticker="NVDA", normalized_name="nvidia"))
    session.flush()
    session.add(Company(name="Nvidia Corp", ticker="NVDA", normalized_name="nvidia corp"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_null_ticker_allows_multiple(session):
    session.add(Company(name="Acme", ticker=None, normalized_name="acme"))
    session.add(Company(name="Globex", ticker=None, normalized_name="globex"))
    session.flush()  # partial unique index ignores NULL tickers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 passed). Requires a running Postgres at `DATABASE_URL` (start with `docker compose up -d postgres`).

- [ ] **Step 5: Create `alembic.ini`**

```ini
[alembic]
script_location = alembic
sqlalchemy.url =

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 6: Implement `alembic/env.py`**

```python
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

from app.db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
```

- [ ] **Step 7: Implement `alembic/versions/0001_initial_schema.py`**

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-21
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE articles (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        url           TEXT UNIQUE NOT NULL,
        title         TEXT NOT NULL,
        body          TEXT,
        source        TEXT,
        published_at  TIMESTAMPTZ NOT NULL,
        ingested_at   TIMESTAMPTZ DEFAULT NOW(),
        processed     BOOLEAN DEFAULT FALSE
    );

    CREATE TABLE themes (
        id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name      TEXT UNIQUE NOT NULL,
        keywords  TEXT[]
    );

    CREATE TABLE companies (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name            TEXT NOT NULL,
        ticker          TEXT,
        normalized_name TEXT NOT NULL
    );

    CREATE TABLE article_themes (
        article_id   UUID REFERENCES articles(id),
        theme_id     UUID REFERENCES themes(id),
        confidence   FLOAT,
        PRIMARY KEY (article_id, theme_id)
    );

    CREATE TABLE article_companies (
        article_id  UUID REFERENCES articles(id),
        company_id  UUID REFERENCES companies(id),
        sentiment   TEXT CHECK (sentiment IN ('positive', 'negative', 'neutral')),
        importance  INT CHECK (importance BETWEEN 1 AND 10),
        PRIMARY KEY (article_id, company_id)
    );

    CREATE TABLE classification_log (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        article_id   UUID REFERENCES articles(id),
        raw_response TEXT,
        parsed_ok    BOOLEAN NOT NULL,
        created_at   TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX idx_articles_processed ON articles(processed);
    CREATE INDEX idx_articles_published ON articles(published_at);
    CREATE INDEX idx_article_themes_theme ON article_themes(theme_id);
    CREATE INDEX idx_article_companies_company ON article_companies(company_id);
    CREATE UNIQUE INDEX idx_companies_ticker ON companies(ticker) WHERE ticker IS NOT NULL;
    CREATE UNIQUE INDEX idx_companies_normalized_name ON companies(normalized_name);
    """)


def downgrade():
    op.execute("""
    DROP TABLE IF EXISTS classification_log;
    DROP TABLE IF EXISTS article_companies;
    DROP TABLE IF EXISTS article_themes;
    DROP TABLE IF EXISTS companies;
    DROP TABLE IF EXISTS themes;
    DROP TABLE IF EXISTS articles;
    """)
```

- [ ] **Step 8: Write the failing test for the migration**

`tests/test_migration.py`:

```python
import os
import subprocess

from sqlalchemy import create_engine, inspect, text

TEST_DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://market:market@localhost:5432/market_narrative"
)


def test_migration_applies_cleanly():
    eng = create_engine(TEST_DB_URL, future=True)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    result = subprocess.run(
        ["alembic", "upgrade", "head"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr

    tables = set(inspect(eng).get_table_names())
    assert {
        "articles", "themes", "companies",
        "article_themes", "article_companies", "classification_log",
    }.issubset(tables)
```

- [ ] **Step 9: Run migration test to verify it passes**

Run: `pytest tests/test_migration.py -v`
Expected: PASS (1 passed)

> This test drops and recreates the `public` schema. It assumes a disposable dev/CI database — never point `DATABASE_URL` at anything precious when running tests.

- [ ] **Step 10: Commit**

```bash
git add app/db/models.py tests/conftest.py tests/test_models.py tests/test_migration.py alembic.ini alembic/
git commit -m "feat: schema models + initial alembic migration"
```

---

## Task 3: Taxonomy module + seed

**Files:**
- Create: `app/services/__init__.py`, `app/services/taxonomy.py`
- Create: `scripts/seed_taxonomy.py`
- Create: `tests/test_taxonomy.py`

- [ ] **Step 1: Write the failing test**

`tests/test_taxonomy.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_taxonomy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.taxonomy'`

- [ ] **Step 3: Implement `app/services/taxonomy.py`**

```python
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Theme

TAXONOMY = {
    "AI Infrastructure": [
        "artificial intelligence", "LLM", "large language model",
        "GPU", "datacentre", "data center", "inference",
        "foundation model", "AI chips", "NVIDIA", "accelerator",
    ],
    "Nuclear Energy": [
        "uranium", "SMR", "small modular reactor",
        "nuclear power", "reactor", "nuclear energy",
        "enriched uranium", "nuclear plant",
    ],
    "Defence Spending": [
        "defence budget", "defense budget", "military spending",
        "missile systems", "defence contracts", "defense contracts",
        "NATO spending", "military procurement", "arms",
    ],
}


def seed_taxonomy(session) -> None:
    """Insert taxonomy themes. Idempotent — does nothing for names already present."""
    for name, keywords in TAXONOMY.items():
        stmt = (
            insert(Theme)
            .values(name=name, keywords=keywords)
            .on_conflict_do_nothing(index_elements=["name"])
        )
        session.execute(stmt)
    session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_taxonomy.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Implement `scripts/seed_taxonomy.py`**

```python
from app.db.session import SessionLocal
from app.services.taxonomy import seed_taxonomy

if __name__ == "__main__":
    with SessionLocal() as session:
        seed_taxonomy(session)
        print("Taxonomy seeded.")
```

- [ ] **Step 6: Commit**

```bash
git add app/services/__init__.py app/services/taxonomy.py scripts/seed_taxonomy.py tests/test_taxonomy.py
git commit -m "feat: narrative taxonomy + idempotent seed"
```

---

## Task 4: Body extractor (with summary fallback)

**Files:**
- Create: `app/services/body_extractor.py`
- Create: `tests/test_body_extractor.py`

- [ ] **Step 1: Write the failing test**

`tests/test_body_extractor.py`:

```python
from app.services.body_extractor import TrafilaturaExtractor


def test_returns_extracted_text(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url", lambda url: "<html>raw</html>"
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.extract", lambda html: "clean body"
    )
    assert TrafilaturaExtractor().extract("https://x.com") == "clean body"


def test_returns_none_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url", lambda url: None
    )
    assert TrafilaturaExtractor().extract("https://x.com") is None


def test_returns_none_when_extract_returns_nothing(monkeypatch):
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.fetch_url", lambda url: "<html></html>"
    )
    monkeypatch.setattr(
        "app.services.body_extractor.trafilatura.extract", lambda html: None
    )
    assert TrafilaturaExtractor().extract("https://x.com") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_body_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.body_extractor'`

- [ ] **Step 3: Implement `app/services/body_extractor.py`**

```python
from typing import Protocol

import trafilatura


class BodyExtractor(Protocol):
    def extract(self, url: str) -> str | None:
        ...


class TrafilaturaExtractor:
    """Fetches and extracts full article text. Returns None on any failure
    so callers can fall back to the RSS summary."""

    def extract(self, url: str) -> str | None:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        return trafilatura.extract(downloaded)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_body_extractor.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/body_extractor.py tests/test_body_extractor.py
git commit -m "feat: body extractor with graceful failure"
```

---

## Task 5: Ingestion worker (Reuters first)

**Files:**
- Create: `app/workers/__init__.py`, `app/workers/ingestion.py`
- Create: `tests/fixtures.py`, `tests/test_ingestion.py`

- [ ] **Step 1: Create `tests/fixtures.py` with a fake extractor and feed entries**

```python
from datetime import datetime, timezone


class FakeExtractor:
    """Returns canned bodies keyed by URL; None means extraction failed."""

    def __init__(self, bodies: dict[str, str | None]):
        self.bodies = bodies

    def extract(self, url: str) -> str | None:
        return self.bodies.get(url)


def feed_entry(link, title, summary="", published_at=None):
    return {
        "link": link,
        "title": title,
        "summary": summary,
        "published_at": published_at,
    }


FIXED_NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
```

- [ ] **Step 2: Write the failing test**

`tests/test_ingestion.py`:

```python
from datetime import datetime, timezone

from app.workers.ingestion import ingest_entries
from app.db.models import Article
from tests.fixtures import FakeExtractor, feed_entry, FIXED_NOW


def test_inserts_new_article_with_extracted_body(session):
    extractor = FakeExtractor({"https://r.com/1": "full body text"})
    entries = [feed_entry("https://r.com/1", "Headline", summary="short")]

    inserted = ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert inserted == 1
    article = session.query(Article).one()
    assert article.body == "full body text"
    assert article.source == "reuters"
    assert article.processed is False


def test_falls_back_to_summary_when_extraction_fails(session):
    extractor = FakeExtractor({"https://r.com/1": None})
    entries = [feed_entry("https://r.com/1", "Headline", summary="summary text")]

    ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert session.query(Article).one().body == "summary text"


def test_duplicate_url_is_skipped(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    entries = [feed_entry("https://r.com/1", "Headline")]

    ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)
    inserted_second = ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert inserted_second == 0
    assert session.query(Article).count() == 1


def test_missing_published_at_backfilled_with_now(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    entries = [feed_entry("https://r.com/1", "Headline", published_at=None)]

    ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert session.query(Article).one().published_at == FIXED_NOW


def test_uses_feed_published_at_when_present(session):
    extractor = FakeExtractor({"https://r.com/1": "body"})
    pub = datetime(2026, 6, 1, tzinfo=timezone.utc)
    entries = [feed_entry("https://r.com/1", "Headline", published_at=pub)]

    ingest_entries(session, entries, "reuters", extractor, now=FIXED_NOW)

    assert session.query(Article).one().published_at == pub
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_ingestion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workers.ingestion'`

- [ ] **Step 4: Implement `app/workers/ingestion.py`**

```python
import time
from datetime import datetime, timezone

import feedparser
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Article
from app.services.body_extractor import BodyExtractor

# Config-driven feeds. NOTE: these URLs are NOT guaranteed live — Reuters
# discontinued public RSS, and other paths shift. Verify with verify_feed()
# before relying on any of them; swap in working financial-news feeds as needed.
RSS_SOURCES = {
    "reuters": "https://feeds.reuters.com/reuters/businessNews",
    "yahoo": "https://finance.yahoo.com/rss/",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
}


def fetch_feed(feed_url: str) -> list[dict]:
    """Parse a feed URL into normalized entry dicts."""
    parsed = feedparser.parse(feed_url)
    entries = []
    for e in parsed.entries:
        published_at = None
        if getattr(e, "published_parsed", None):
            published_at = datetime.fromtimestamp(
                time.mktime(e.published_parsed), tz=timezone.utc
            )
        entries.append({
            "link": e.get("link"),
            "title": e.get("title"),
            "summary": e.get("summary", ""),
            "published_at": published_at,
        })
    return entries


def verify_feed(feed_url: str) -> bool:
    """Return True if the feed parses and yields at least one entry."""
    return len(fetch_feed(feed_url)) > 0


def ingest_entries(session, entries, source, extractor: BodyExtractor, now=None) -> int:
    """Insert new articles, dedup by URL. Returns count of rows actually inserted."""
    now = now or datetime.now(timezone.utc)
    inserted = 0
    for entry in entries:
        url = entry["link"]
        if not url:
            continue
        body = extractor.extract(url) or entry.get("summary") or None
        published_at = entry.get("published_at") or now
        stmt = (
            insert(Article)
            .values(
                url=url,
                title=entry["title"],
                body=body,
                source=source,
                published_at=published_at,
                processed=False,
            )
            .on_conflict_do_nothing(index_elements=["url"])
        )
        result = session.execute(stmt)
        inserted += result.rowcount
    session.commit()
    return inserted
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_ingestion.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add app/workers/__init__.py app/workers/ingestion.py tests/fixtures.py tests/test_ingestion.py
git commit -m "feat: ingestion worker with dedup, summary fallback, date backfill"
```

---

## Task 6: LLM service (prompt, parse, call, retry)

**Files:**
- Create: `app/services/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test (TDD — focus on parsing edge cases)**

`tests/test_llm.py`:

```python
from app.services.llm import build_prompt, parse_response, call_with_retry


def test_prompt_includes_all_taxonomy_themes():
    prompt = build_prompt({"title": "T", "body": "B"})
    assert "AI Infrastructure" in prompt
    assert "Nuclear Energy" in prompt
    assert "Defence Spending" in prompt
    assert "T" in prompt and "B" in prompt


def test_parse_plain_json():
    raw = '{"themes": [], "companies": [], "sentiment": "neutral", "importance": 1}'
    assert parse_response(raw)["sentiment"] == "neutral"


def test_parse_strips_markdown_fences():
    raw = '```json\n{"sentiment": "positive"}\n```'
    assert parse_response(raw)["sentiment"] == "positive"


def test_parse_returns_none_on_garbage():
    assert parse_response("not json at all") is None


def test_parse_returns_none_on_non_object():
    assert parse_response("[1, 2, 3]") is None


def test_parse_returns_none_on_none():
    assert parse_response(None) is None


def test_retry_succeeds_after_429():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return "ok"

    sleeps = []
    result = call_with_retry(flaky, retries=3, base_delay=2.0, sleeper=sleeps.append)

    assert result == "ok"
    assert calls["n"] == 3
    assert sleeps == [2.0, 4.0]  # exponential backoff before attempts 2 and 3


def test_retry_reraises_non_rate_limit_errors_immediately():
    def boom():
        raise ValueError("bad request")

    sleeps = []
    try:
        call_with_retry(boom, retries=3, sleeper=sleeps.append)
        assert False, "should have raised"
    except ValueError:
        pass
    assert sleeps == []  # no backoff for non-429 errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.llm'`

- [ ] **Step 3: Implement `app/services/llm.py`**

```python
import json
import re
import time
from typing import Callable

from app.services.taxonomy import TAXONOMY


def build_prompt(article: dict) -> str:
    taxonomy_str = "\n".join(
        f"- {name}: {', '.join(keywords)}" for name, keywords in TAXONOMY.items()
    )
    return f"""
You are a financial news analyst. Extract structured information from the article below.

Available narratives — only assign from this list, do not invent new ones:
{taxonomy_str}

Return JSON only. No explanation, no markdown, no preamble.

{{
  "themes": [
    {{"name": "<narrative name>", "confidence": <0.0-1.0>}}
  ],
  "companies": [
    {{"name": "<company name>", "ticker": "<ticker or null>"}}
  ],
  "sentiment": "<positive|negative|neutral>",
  "importance": <1-10>,
  "reason": "<one sentence: why this article matters>"
}}

Rules:
- Only assign a theme if the article is substantively about it, not a passing mention.
- Confidence > 0.7 means the theme is central to the article.
- Importance 8-10 = major announcement or policy shift. 1-3 = routine or minor.
- If no themes match, return an empty themes array.

Article title: {article['title']}
Article body: {article['body']}
"""


def parse_response(raw: str | None) -> dict | None:
    """Parse the LLM response into a dict, tolerating markdown fences.
    Returns None if the response is missing, malformed, or not a JSON object."""
    if not raw:
        return None
    cleaned = re.sub(r"```json|```", "", raw).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


def call_with_retry(fn: Callable[[], str], retries: int = 3,
                    base_delay: float = 2.0, sleeper: Callable[[float], None] = time.sleep) -> str:
    """Call fn, retrying with exponential backoff only on rate-limit (429) errors."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:
            if _is_rate_limit(exc) and attempt < retries:
                sleeper(base_delay * (2 ** attempt))
                continue
            raise


def call_gemini(client, model: str, prompt: str) -> str:
    """Invoke the google-genai client and return the raw text response."""
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=300),
    )
    return response.text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/llm.py tests/test_llm.py
git commit -m "feat: LLM prompt builder, defensive parser, rate-limit retry"
```

---

## Task 7: Company normalization + upsert; Quality-gate CLI

**Files:**
- Create: `app/services/companies.py`
- Create: `tests/test_companies.py`
- Create: `scripts/review_classifications.py`

- [ ] **Step 1: Write the failing test (TDD — dedup protects every count)**

`tests/test_companies.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_companies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.companies'`

- [ ] **Step 3: Implement `app/services/companies.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_companies.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Implement the quality-gate CLI `scripts/review_classifications.py`**

```python
"""Quality-gate CLI (build step 3). Runs classification over a sample of stored
articles and prints results for manual accuracy scoring. READ-ONLY: does not
write classifications or mark articles processed.

Usage:
    python -m scripts.review_classifications [N]   # N = sample size (default 20)
"""
import sys

from google import genai

from app.config import Settings
from app.db.session import SessionLocal
from app.db.models import Article
from app.services.llm import build_prompt, parse_response, call_gemini, call_with_retry


def main(sample_size: int = 20) -> None:
    settings = Settings.from_env()
    client = genai.Client(api_key=settings.gemini_api_key)

    with SessionLocal() as session:
        articles = session.query(Article).limit(sample_size).all()

    if not articles:
        print("No articles in the database. Run ingestion first.")
        return

    for i, article in enumerate(articles, 1):
        prompt = build_prompt({"title": article.title, "body": article.body or ""})
        raw = call_with_retry(lambda: call_gemini(client, settings.gemini_model, prompt))
        parsed = parse_response(raw)

        print(f"\n{'=' * 70}\n[{i}/{len(articles)}] {article.title}\n{article.url}")
        print(f"{'-' * 70}")
        if parsed:
            print(f"Themes:     {parsed.get('themes')}")
            print(f"Companies:  {parsed.get('companies')}")
            print(f"Sentiment:  {parsed.get('sentiment')}   Importance: {parsed.get('importance')}")
            print(f"Reason:     {parsed.get('reason')}")
        else:
            print(f"PARSE FAILED. Raw response:\n{raw}")

    print(f"\n{'=' * 70}\nScore each as Correct / Partial / Wrong. "
          f"Target >85% correct before proceeding to Task 8.")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    main(n)
```

- [ ] **Step 6: Commit**

```bash
git add app/services/companies.py tests/test_companies.py scripts/review_classifications.py
git commit -m "feat: company dedup upsert + quality-gate review CLI"
```

---

## 🛑 STOP — QUALITY GATE

**Do not proceed to Task 8 until this passes.**

1. Start Postgres and apply the schema:
   ```bash
   docker compose up -d postgres
   DATABASE_URL=postgresql://market:market@localhost:5432/market_narrative alembic upgrade head
   DATABASE_URL=... python -m scripts.seed_taxonomy
   ```
2. Ingest a sample. If the Reuters feed is dead (likely), substitute a working financial-news RSS URL in `RSS_SOURCES` and confirm with `verify_feed()` first. Run a one-off ingest of ~20–30 articles.
3. Run the review CLI against real data with a real `GEMINI_API_KEY`:
   ```bash
   DATABASE_URL=... GEMINI_API_KEY=<real> python -m scripts.review_classifications 20
   ```
4. Hand-score each: **Correct / Partial / Wrong**. Compute % correct.
5. **Gate:** ≥85% correct → proceed. Below that → fix the prompt in `build_prompt` (and/or swap feeds for better-quality articles) and re-run before building the automated worker. There is no point scaling a classifier that is wrong.

---

## Task 8: Classification worker

**Files:**
- Create: `app/workers/classification.py`
- Modify: `tests/fixtures.py` (add fake Gemini client)
- Create: `tests/test_classification.py`

- [ ] **Step 1: Add a fake Gemini client to `tests/fixtures.py`**

Append to `tests/fixtures.py`:

```python
class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, responses, error=None):
        self._responses = list(responses)
        self._error = error
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        if self._error is not None and self.calls <= self._error["times"]:
            raise RuntimeError(self._error["message"])
        return _FakeResponse(self._responses.pop(0))


class FakeGeminiClient:
    """Mimics google.genai.Client: exposes .models.generate_content.
    `responses` is a list of raw text strings returned in order.
    `error` optionally raises for the first N calls, e.g.
    {"times": 1, "message": "429 RESOURCE_EXHAUSTED"}."""

    def __init__(self, responses, error=None):
        self.models = _FakeModels(responses, error)
```

- [ ] **Step 2: Write the failing test**

`tests/test_classification.py`:

```python
import json
from datetime import datetime, timezone

from app.workers.classification import classify_batch
from app.services.taxonomy import seed_taxonomy
from app.db.models import (
    Article, Company, ArticleTheme, ArticleCompany, ClassificationLog,
)
from tests.fixtures import FakeGeminiClient


def _add_article(session, url="https://a.com/1"):
    article = Article(url=url, title="AI news", body="NVIDIA datacentre expansion",
                      source="reuters", published_at=datetime.now(timezone.utc))
    session.add(article)
    session.flush()
    return article


GOOD = json.dumps({
    "themes": [{"name": "AI Infrastructure", "confidence": 0.92}],
    "companies": [{"name": "NVIDIA", "ticker": "NVDA"}],
    "sentiment": "positive",
    "importance": 8,
    "reason": "Datacentre expansion increases AI chip demand.",
})


def test_classifies_and_marks_processed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    client = FakeGeminiClient([GOOD])

    n = classify_batch(session, client, "gemini-flash-latest", sleeper=lambda s: None)

    assert n == 1
    assert session.get(Article, article.id).processed is True
    assert session.query(ArticleTheme).count() == 1
    assert session.query(ArticleCompany).count() == 1
    assert session.query(Company).filter_by(ticker="NVDA").count() == 1
    log = session.query(ClassificationLog).one()
    assert log.parsed_ok is True


def test_company_dedup_across_articles(session):
    seed_taxonomy(session)
    _add_article(session, "https://a.com/1")
    _add_article(session, "https://a.com/2")
    variant = json.dumps({
        "themes": [], "companies": [{"name": "Nvidia Corp", "ticker": "NVDA"}],
        "sentiment": "neutral", "importance": 3, "reason": "x",
    })
    client = FakeGeminiClient([GOOD, variant])

    classify_batch(session, client, "m", sleeper=lambda s: None)

    assert session.query(Company).filter_by(ticker="NVDA").count() == 1


def test_unknown_theme_is_skipped(session):
    seed_taxonomy(session)
    _add_article(session)
    payload = json.dumps({
        "themes": [{"name": "Crypto Mania", "confidence": 0.9}],
        "companies": [], "sentiment": "neutral", "importance": 2, "reason": "x",
    })
    client = FakeGeminiClient([payload])

    classify_batch(session, client, "m", sleeper=lambda s: None)

    assert session.query(ArticleTheme).count() == 0  # unknown theme not stored


def test_malformed_response_logged_but_article_processed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    client = FakeGeminiClient(["this is not json"])

    classify_batch(session, client, "m", sleeper=lambda s: None)

    assert session.get(Article, article.id).processed is True
    log = session.query(ClassificationLog).one()
    assert log.parsed_ok is False
    assert session.query(ArticleTheme).count() == 0


def test_rate_limit_retried_then_succeeds(session):
    seed_taxonomy(session)
    _add_article(session)
    client = FakeGeminiClient([GOOD], error={"times": 1, "message": "429 RESOURCE_EXHAUSTED"})

    classify_batch(session, client, "m", base_delay=0.0, sleeper=lambda s: None)

    assert session.query(ArticleTheme).count() == 1
    assert client.models.calls == 2  # one failure + one success


def test_only_processes_unprocessed(session):
    seed_taxonomy(session)
    article = _add_article(session)
    article.processed = True
    session.flush()
    client = FakeGeminiClient([])

    n = classify_batch(session, client, "m", sleeper=lambda s: None)

    assert n == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_classification.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workers.classification'`

- [ ] **Step 4: Implement `app/workers/classification.py`**

```python
from app.db.models import Article, Theme, ArticleTheme, ArticleCompany, ClassificationLog
from app.services.companies import upsert_company
from app.services.llm import build_prompt, parse_response, call_gemini, call_with_retry


def store_classification(session, article: Article, result: dict) -> None:
    """Persist themes (known only), companies, and sentiment/importance."""
    for theme_entry in result.get("themes") or []:
        theme = session.query(Theme).filter_by(name=theme_entry.get("name")).one_or_none()
        if theme is None:
            continue  # unknown theme — skip (prompt forbids inventing themes)
        session.add(ArticleTheme(
            article_id=article.id,
            theme_id=theme.id,
            confidence=theme_entry.get("confidence"),
        ))

    sentiment = result.get("sentiment")
    importance = result.get("importance")
    for company_entry in result.get("companies") or []:
        name = company_entry.get("name")
        if not name:
            continue
        company = upsert_company(session, name, company_entry.get("ticker"))
        session.add(ArticleCompany(
            article_id=article.id,
            company_id=company.id,
            sentiment=sentiment,
            importance=importance,
        ))


def classify_batch(session, client, model: str, batch_size: int = 10,
                   sleep_s: float = 4.0, base_delay: float = 2.0,
                   sleeper=None) -> int:
    """Classify a batch of unprocessed articles. Returns the count processed."""
    import time
    sleeper = sleeper if sleeper is not None else time.sleep

    articles = (
        session.query(Article)
        .filter(Article.processed.is_(False))
        .limit(batch_size)
        .all()
    )
    for article in articles:
        prompt = build_prompt({"title": article.title, "body": article.body or ""})
        raw = call_with_retry(
            lambda: call_gemini(client, model, prompt),
            base_delay=base_delay,
            sleeper=sleeper,
        )
        result = parse_response(raw)
        session.add(ClassificationLog(
            article_id=article.id, raw_response=raw, parsed_ok=result is not None,
        ))
        if result is not None:
            store_classification(session, article, result)
        article.processed = True
        session.commit()
        sleeper(sleep_s)

    return len(articles)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_classification.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add app/workers/classification.py tests/fixtures.py tests/test_classification.py
git commit -m "feat: classification worker with dedup, unknown-theme skip, retry"
```

---

## Task 9: Add remaining feeds (config + verification)

**Files:**
- Modify: `app/workers/ingestion.py` (already config-driven from Task 5 — confirm feeds)
- Create: `tests/test_feeds_config.py`

- [ ] **Step 1: Write the test asserting all configured sources are verifiable**

`tests/test_feeds_config.py`:

```python
from app.workers.ingestion import RSS_SOURCES, fetch_feed


def test_three_sources_configured():
    assert set(RSS_SOURCES) >= {"reuters", "yahoo", "marketwatch"}


def test_parses_a_static_feed(monkeypatch):
    # fetch_feed normalizes feedparser output; verify shape with a fake parse result.
    class _Entry(dict):
        def __getattr__(self, k):
            return self.get(k)

    fake = type("P", (), {"entries": [
        _Entry(link="https://x.com/1", title="T", summary="S", published_parsed=None)
    ]})()
    monkeypatch.setattr("app.workers.ingestion.feedparser.parse", lambda url: fake)

    entries = fetch_feed("https://whatever")
    assert entries[0]["link"] == "https://x.com/1"
    assert entries[0]["published_at"] is None
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/test_feeds_config.py -v`
Expected: PASS if `RSS_SOURCES` already has the three keys from Task 5; otherwise FAIL → add the missing keys.

- [ ] **Step 3: Manually verify each live feed (operational, not a unit test)**

Run a one-off check and replace any dead URL in `RSS_SOURCES` with a working financial-news feed:

```bash
python -c "from app.workers.ingestion import RSS_SOURCES, verify_feed; \
print({k: verify_feed(v) for k, v in RSS_SOURCES.items()})"
```

Expected: `{'reuters': True/False, 'yahoo': ..., 'marketwatch': ...}`. Any `False` → swap that URL for a live feed and re-run until all `True`.

- [ ] **Step 4: Commit**

```bash
git add app/workers/ingestion.py tests/test_feeds_config.py
git commit -m "feat: confirm multi-source feed config + verification helper"
```

---

## Task 10: APScheduler wiring

**Files:**
- Create: `app/workers/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scheduler.py`:

```python
from app.workers.scheduler import build_scheduler


def test_scheduler_registers_two_jobs():
    sched = build_scheduler()
    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {"ingestion", "classification"}


def test_job_intervals():
    sched = build_scheduler()
    intervals = {job.id: job.trigger.interval.total_seconds() for job in sched.get_jobs()}
    assert intervals["ingestion"] == 30 * 60
    assert intervals["classification"] == 15 * 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workers.scheduler'`

- [ ] **Step 3: Implement `app/workers/scheduler.py`**

```python
from apscheduler.schedulers.background import BackgroundScheduler

from google import genai

from app.config import Settings
from app.db.session import SessionLocal
from app.workers.ingestion import RSS_SOURCES, fetch_feed, ingest_entries
from app.workers.classification import classify_batch
from app.services.body_extractor import TrafilaturaExtractor


def run_ingestion() -> None:
    extractor = TrafilaturaExtractor()
    with SessionLocal() as session:
        for source, url in RSS_SOURCES.items():
            entries = fetch_feed(url)
            ingest_entries(session, entries, source, extractor)


def run_classification() -> None:
    settings = Settings.from_env()
    client = genai.Client(api_key=settings.gemini_api_key)
    with SessionLocal() as session:
        classify_batch(session, client, settings.gemini_model)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_ingestion, "interval", minutes=30, id="ingestion")
    scheduler.add_job(run_classification, "interval", minutes=15, id="classification")
    return scheduler
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/workers/scheduler.py tests/test_scheduler.py
git commit -m "feat: APScheduler wiring for ingestion + classification"
```

---

## Task 11: Report generator

**Files:**
- Create: `app/services/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: Write the failing test (TDD — emerging query + WoW math are the tricky bits)**

`tests/test_report.py`:

```python
from datetime import datetime, timedelta, timezone

from app.services.taxonomy import seed_taxonomy
from app.services.report import wow_growth_pct, count_articles, emerging_associations, generate_report
from app.workers.classification import store_classification
from app.db.models import Article

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def test_wow_growth_basic():
    assert wow_growth_pct(this_week=128, last_week=100) == 28.0


def test_wow_growth_handles_zero_last_week():
    assert wow_growth_pct(this_week=5, last_week=0) == 500.0  # divides by max(0,1)


def _article(session, url, days_ago, theme="AI Infrastructure",
             company=("NVIDIA", "NVDA")):
    art = Article(url=url, title="t", body="b", source="reuters",
                  published_at=NOW - timedelta(days=days_ago))
    session.add(art)
    session.flush()
    store_classification(session, art, {
        "themes": [{"name": theme, "confidence": 0.9}],
        "companies": [{"name": company[0], "ticker": company[1]}],
        "sentiment": "positive", "importance": 7,
    })
    return art


def test_count_articles_in_window(session):
    seed_taxonomy(session)
    _article(session, "u1", days_ago=1)
    _article(session, "u2", days_ago=2)
    _article(session, "u3", days_ago=10)  # outside the 7-day window

    count = count_articles(session, "AI Infrastructure", NOW - timedelta(days=7), NOW)
    assert count == 2


def test_emerging_association_excludes_prior_companies(session):
    seed_taxonomy(session)
    # NVIDIA appeared 14 days ago (prior window) -> NOT emerging
    _article(session, "old", days_ago=14, company=("NVIDIA", "NVDA"))
    # Eaton appears this week only -> emerging
    _article(session, "new", days_ago=1, company=("Eaton", "ETN"))

    emerging = emerging_associations(session, "AI Infrastructure", now=NOW)
    names = {row["name"] for row in emerging}
    assert "Eaton" in names
    assert "NVIDIA" not in names


def test_generate_report_shape(session):
    seed_taxonomy(session)
    _article(session, "u1", days_ago=1)

    report = generate_report(session, now=NOW)
    assert "AI Infrastructure" in report["narratives"]
    ai = report["narratives"]["AI Infrastructure"]
    assert ai["article_count"] == 1
    assert "wow_growth_pct" in ai
    assert "top_companies" in ai
    assert "emerging_associations" in ai
    assert "important_articles" in ai
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.report'`

- [ ] **Step 3: Implement `app/services/report.py`**

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db.models import Theme


def wow_growth_pct(this_week: int, last_week: int) -> float:
    return round((this_week - last_week) / max(last_week, 1) * 100, 1)


def count_articles(session, theme_name: str, start: datetime, end: datetime) -> int:
    row = session.execute(text("""
        SELECT COUNT(DISTINCT a.id)
        FROM articles a
        JOIN article_themes at ON at.article_id = a.id
        JOIN themes t ON t.id = at.theme_id
        WHERE t.name = :theme
          AND a.published_at >= :start AND a.published_at < :end
    """), {"theme": theme_name, "start": start, "end": end}).scalar()
    return int(row or 0)


def top_companies(session, theme_name: str, start: datetime, end: datetime, limit: int = 5):
    rows = session.execute(text("""
        SELECT c.name, c.ticker, COUNT(*) AS mention_count
        FROM article_companies ac
        JOIN companies c ON c.id = ac.company_id
        JOIN article_themes at ON at.article_id = ac.article_id
        JOIN themes t ON t.id = at.theme_id
        JOIN articles a ON a.id = ac.article_id
        WHERE t.name = :theme
          AND a.published_at >= :start AND a.published_at < :end
        GROUP BY c.name, c.ticker
        ORDER BY mention_count DESC
        LIMIT :limit
    """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings()
    return [dict(r) for r in rows]


def emerging_associations(session, theme_name: str, now: datetime | None = None):
    """Companies associated with the theme in the last 7 days that had NO
    association in the prior 3 weeks (days 8–28)."""
    now = now or datetime.now(timezone.utc)
    rows = session.execute(text("""
        SELECT c.name, c.ticker, COUNT(*) AS mention_count
        FROM article_companies ac
        JOIN companies c ON c.id = ac.company_id
        JOIN article_themes at ON at.article_id = ac.article_id
        JOIN themes t ON t.id = at.theme_id
        WHERE t.name = :theme
          AND ac.article_id IN (
              SELECT id FROM articles WHERE published_at >= :recent_start
          )
          AND c.id NOT IN (
              SELECT ac2.company_id
              FROM article_companies ac2
              JOIN article_themes at2 ON at2.article_id = ac2.article_id
              JOIN themes t2 ON t2.id = at2.theme_id
              WHERE t2.name = :theme
                AND ac2.article_id IN (
                    SELECT id FROM articles
                    WHERE published_at < :recent_start
                      AND published_at >= :prior_start
                )
          )
        GROUP BY c.name, c.ticker
        ORDER BY mention_count DESC
    """), {
        "theme": theme_name,
        "recent_start": now - timedelta(days=7),
        "prior_start": now - timedelta(days=28),
    }).mappings()
    return [dict(r) for r in rows]


def top_articles(session, theme_name: str, start: datetime, end: datetime, limit: int = 3):
    rows = session.execute(text("""
        SELECT DISTINCT a.title, a.url, ac.importance
        FROM articles a
        JOIN article_themes at ON at.article_id = a.id
        JOIN themes t ON t.id = at.theme_id
        LEFT JOIN article_companies ac ON ac.article_id = a.id
        WHERE t.name = :theme
          AND a.published_at >= :start AND a.published_at < :end
        ORDER BY ac.importance DESC NULLS LAST
        LIMIT :limit
    """), {"theme": theme_name, "start": start, "end": end, "limit": limit}).mappings()
    return [dict(r) for r in rows]


def generate_report(session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    this_start, last_start = now - timedelta(days=7), now - timedelta(days=14)

    narratives = {}
    for theme in session.query(Theme).all():
        this_week = count_articles(session, theme.name, this_start, now)
        last_week = count_articles(session, theme.name, last_start, this_start)
        narratives[theme.name] = {
            "article_count": this_week,
            "wow_growth_pct": wow_growth_pct(this_week, last_week),
            "top_companies": top_companies(session, theme.name, this_start, now),
            "emerging_associations": emerging_associations(session, theme.name, now=now),
            "important_articles": top_articles(session, theme.name, this_start, now),
        }

    return {"generated_at": now.isoformat(), "narratives": narratives}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/report.py tests/test_report.py
git commit -m "feat: report generator with WoW growth + emerging associations"
```

---

## Task 12: FastAPI endpoints

**Files:**
- Create: `app/api/__init__.py`, `app/api/routes.py`, `app/main.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api.py`:

```python
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.db.session import SessionLocal
from app.api.routes import get_session
from app.services.taxonomy import seed_taxonomy
from app.workers.classification import store_classification
from app.db.models import Article


@pytest.fixture
def client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_daily_report(client, session):
    seed_taxonomy(session)
    art = Article(url="u1", title="AI", body="b", source="r",
                  published_at=datetime.now(timezone.utc))
    session.add(art)
    session.flush()
    store_classification(session, art, {
        "themes": [{"name": "AI Infrastructure", "confidence": 0.9}],
        "companies": [{"name": "NVIDIA", "ticker": "NVDA"}],
        "sentiment": "positive", "importance": 8,
    })

    resp = client.get("/report/daily")
    assert resp.status_code == 200
    assert "AI Infrastructure" in resp.json()["narratives"]


def test_single_theme_report(client, session):
    seed_taxonomy(session)
    resp = client.get("/report/AI Infrastructure")
    assert resp.status_code == 200
    assert resp.json()["theme"] == "AI Infrastructure"


def test_unknown_theme_returns_404(client, session):
    seed_taxonomy(session)
    resp = client.get("/report/Nonexistent Theme")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement `app/api/routes.py`**

```python
from fastapi import APIRouter, Depends, HTTPException

from app.db.session import SessionLocal
from app.db.models import Theme
from app.services.report import (
    generate_report, count_articles, top_companies,
    emerging_associations, top_articles,
)
from datetime import datetime, timedelta, timezone

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
    return {
        "theme": theme,
        "article_count": count_articles(session, theme, start, now),
        "top_companies": top_companies(session, theme, start, now),
        "emerging_associations": emerging_associations(session, theme, now=now),
        "important_articles": top_articles(session, theme, start, now),
    }


@router.get("/articles/{theme}")
def articles_for_theme(theme: str, session=Depends(get_session)):
    if session.query(Theme).filter_by(name=theme).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Unknown theme: {theme}")
    now = datetime.now(timezone.utc)
    return {"theme": theme,
            "articles": top_articles(session, theme, now - timedelta(days=7), now, limit=50)}


@router.get("/companies/{theme}")
def companies_for_theme(theme: str, session=Depends(get_session)):
    if session.query(Theme).filter_by(name=theme).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Unknown theme: {theme}")
    now = datetime.now(timezone.utc)
    return {"theme": theme,
            "companies": top_companies(session, theme, now - timedelta(days=7), now, limit=50)}
```

- [ ] **Step 4: Implement `app/main.py`**

```python
from fastapi import FastAPI

from app.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Market Narrative Intelligence — Phase 1")
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 5: Create `app/api/__init__.py`** (empty file).

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/api/ app/main.py tests/test_api.py
git commit -m "feat: FastAPI report endpoints + app factory"
```

---

## Definition of Done

- [ ] `pytest -v` passes the full suite against a live Postgres.
- [ ] `alembic upgrade head` applies cleanly to a fresh database (`test_migration.py`).
- [ ] Quality gate cleared: ≥85% classification accuracy on a hand-scored sample.
- [ ] At least one live RSS feed verified via `verify_feed()`.
- [ ] `docker compose up` brings up app + postgres; `GET /health` returns `{"status": "ok"}`.
- [ ] `GET /report/daily` returns a narrative report shaped like the spec's example.

## Notes / Deferred (out of Phase 1 backend scope)

- React dashboard (build step 8).
- The CI/CD workflow already exists in `docs/market-narrative-cicd.md`; wiring `.github/workflows/deploy.yml` is a deploy task, not part of this backend plan.
- Message queues, vector search, acceleration metrics — explicitly Phase 2+.
```

