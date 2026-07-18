"""Conexion a la base de datos local del historico de scores.

Soporta PostgreSQL (docker-compose) y SQLite (modo sin infraestructura),
resuelto automaticamente por la DATABASE_URL.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings

_settings = get_settings()

# check_same_thread solo aplica a SQLite; se ignora en Postgres.
_connect_args = (
    {"check_same_thread": False}
    if _settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(_settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Iterator[Session]:
    """Dependencia de FastAPI: entrega una sesion y la cierra al terminar."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Crea las tablas a partir de los modelos ORM si no existen."""
    from backend.database import models

    models.Base.metadata.create_all(bind=engine)
