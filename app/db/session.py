from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import Settings

settings = Settings.from_env()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
