"""Connection to the local score-history database.

Supports PostgreSQL (docker-compose) and SQLite (no-infrastructure mode),
resolved automatically from the DATABASE_URL.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings

_settings = get_settings()

# check_same_thread only applies to SQLite; it is ignored on Postgres.
_connect_args = (
    {"check_same_thread": False}
    if _settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(_settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session and closes it when done."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Creates the tables from the ORM models if they do not exist."""
    from backend.database import models

    models.Base.metadata.create_all(bind=engine)
