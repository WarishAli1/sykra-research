from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession, sessionmaker

from app.config import settings
from app.db.models import Base

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[DBSession, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)