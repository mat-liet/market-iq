import os
import subprocess

from sqlalchemy import create_engine, inspect, text

TEST_DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://market:market@localhost:5432/market_narrative"
)


def _apply_migration():
    """Drop the schema and bring it up purely from the Alembic migration —
    the file the production database is actually built from."""
    eng = create_engine(TEST_DB_URL, future=True)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    result = subprocess.run(
        ["alembic", "upgrade", "head"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    return eng


def test_migration_applies_cleanly():
    eng = _apply_migration()
    tables = set(inspect(eng).get_table_names())
    assert {
        "articles", "themes", "companies",
        "article_themes", "article_companies", "classification_log",
    }.issubset(tables)


def test_migration_has_constraints_the_app_relies_on():
    """Guards against drift between the migration and the ORM models: the
    dedup/uniqueness/CHECK guarantees the workers and report depend on must
    exist in the migration-built schema, not only in models.py."""
    insp = inspect(_apply_migration())

    # Company dedup relies on these unique indexes.
    company_indexes = {ix["name"]: ix for ix in insp.get_indexes("companies")}
    assert company_indexes["idx_companies_normalized_name"]["unique"] is True
    assert company_indexes["idx_companies_ticker"]["unique"] is True

    # article.url uniqueness underpins ingestion's on-conflict dedup.
    url_unique = (
        any(c["column_names"] == ["url"] for c in insp.get_unique_constraints("articles"))
        or any(ix["column_names"] == ["url"] and ix["unique"]
               for ix in insp.get_indexes("articles"))
    )
    assert url_unique, "articles.url must be unique"

    # Composite primary keys on the association tables prevent duplicate links.
    assert set(insp.get_pk_constraint("article_companies")["constrained_columns"]) == {
        "article_id", "company_id"
    }
    assert set(insp.get_pk_constraint("article_themes")["constrained_columns"]) == {
        "article_id", "theme_id"
    }

    # CHECK constraints that bound sentiment/importance (the poison-pill guard
    # in store_classification mirrors these).
    check_names = {c["name"] for c in insp.get_check_constraints("article_companies")}
    assert {"ck_sentiment", "ck_importance"}.issubset(check_names)

    # Query-supporting indexes the report depends on.
    article_indexes = {ix["name"] for ix in insp.get_indexes("articles")}
    assert {"idx_articles_processed", "idx_articles_published"}.issubset(article_indexes)
