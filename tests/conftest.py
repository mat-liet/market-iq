import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base

# Mark the whole suite as the test environment so Settings.from_env() may use a
# dummy Anthropic key; production has no APP_ENV=test and must supply a real key.
os.environ.setdefault("APP_ENV", "test")

# Run against the committed example feeds/taxonomy, never a deployment's private
# config that happens to sit in config/ on this machine.
_CONFIG = os.path.join(os.path.dirname(__file__), "..", "config")
os.environ.setdefault("FEEDS_FILE", os.path.join(_CONFIG, "feeds.example.json"))
os.environ.setdefault("TAXONOMY_FILE", os.path.join(_CONFIG, "taxonomy.example.json"))

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
