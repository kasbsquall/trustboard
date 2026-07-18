"""ORM models for the local score history.

Mirrors backend/database/schema.sql. SQLAlchemy generates DDL compatible with
both PostgreSQL and SQLite. UUIDs are stored as text for portability across the
two engines.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class DomainScore(Base):
    __tablename__ = "domain_scores"
    __table_args__ = (UniqueConstraint("domain_name", "week_of", name="uq_domain_week"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    domain_name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain_urn: Mapped[str | None] = mapped_column(String(300))
    week_of: Mapped[date] = mapped_column(Date, nullable=False)
    trust_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    assertions_passing_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    freshness_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    documentation_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    ownership_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    rank_this_week: Mapped[int | None] = mapped_column(Integer)
    rank_last_week: Mapped[int | None] = mapped_column(Integer)
    written_to_datahub: Mapped[bool] = mapped_column(Boolean, default=False)
    datahub_property_urn: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LeaderboardPost(Base):
    __tablename__ = "leaderboard_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    week_of: Mapped[date] = mapped_column(Date, nullable=False)
    slack_message_ts: Mapped[str | None] = mapped_column(String(100))
    top_domain: Mapped[str | None] = mapped_column(String(200))
    most_improved_domain: Mapped[str | None] = mapped_column(String(200))
    posted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
