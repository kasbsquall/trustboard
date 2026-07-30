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


def _add_missing_columns() -> None:
    """Adds columns the models declare and an existing table does not have.

    `create_all` creates missing TABLES and silently ignores missing COLUMNS, so
    adding a field to a model left every existing database broken: the next query
    selected a column that was not there and the whole weekly run died on
    `no such column`. That is not only a local annoyance. The hosted dashboard
    keeps its database on a persistent volume, so a deploy carrying a model
    change would have hit exactly the same error with no local sign of it.

    Deliberately additive and nothing else. It never drops or retypes a column,
    because a real migration tool is the right answer the moment this project
    needs one, and a homemade one that quietly rewrites columns is worse than
    none. This only closes the gap between a model gaining a nullable field and
    a database that predates it.
    """
    from sqlalchemy import inspect, text

    from backend.database import models

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in models.Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present or not column.nullable:
                    continue
                ddl = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {ddl}'))


def init_db() -> None:
    """Creates the tables from the ORM models, and adds any missing columns."""
    from backend.database import models

    models.Base.metadata.create_all(bind=engine)
    _add_missing_columns()
