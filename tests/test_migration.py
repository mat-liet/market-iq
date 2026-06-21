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
