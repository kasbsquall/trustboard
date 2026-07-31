"""ORM models for the local score history.

Mirrors backend/database/schema.sql. SQLAlchemy generates DDL compatible with
both PostgreSQL and SQLite. UUIDs are stored as text for portability across the
two engines.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

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
    # Share of the scoring weight backed by a signal that was actually present.
    # Stored with the score because the two only mean something together: a 78
    # at 0.45 coverage and a 78 at 1.0 are not the same claim.
    signal_coverage: Mapped[float | None] = mapped_column(Numeric(4, 3))
    # Scoring model that produced the row. Without it, a history chart silently
    # plots numbers from two different models on one line.
    score_version: Mapped[str | None] = mapped_column(String(16))
    dataset_count: Mapped[int | None] = mapped_column(Integer)
    # How many of those datasets had enough signal to judge, and whether the
    # team's score means anything at all.
    rated_dataset_count: Mapped[int | None] = mapped_column(Integer)
    rated: Mapped[bool | None] = mapped_column(Boolean)
    # True when the row was authored by scripts/seed_history.py to give the demo
    # a trend, rather than measured by an audit. The dashboard says so on screen:
    # presenting invented history next to a real score, in the same chart, with no
    # mark, is the one thing that would make every honest claim here look staged.
    synthetic: Mapped[bool | None] = mapped_column(Boolean)
    rank_this_week: Mapped[int | None] = mapped_column(Integer)
    rank_last_week: Mapped[int | None] = mapped_column(Integer)
    written_to_datahub: Mapped[bool] = mapped_column(Boolean, default=False)
    datahub_property_urn: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class LeaderboardPost(Base):
    __tablename__ = "leaderboard_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    week_of: Mapped[date] = mapped_column(Date, nullable=False)
    slack_message_ts: Mapped[str | None] = mapped_column(String(100))
    top_domain: Mapped[str | None] = mapped_column(String(200))
    most_improved_domain: Mapped[str | None] = mapped_column(String(200))
    posted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class DomainRoster(Base):
    """Which team owned which dataset, as of a given week.

    Exists because unassigning a domain was a one-click way to raise a score.
    A dataset with no domain was skipped outright, so a team could take its three
    worst tables out of the catalog's ownership model and gain twenty points, which
    is a worse outcome than the problem this project set out to solve: the metric
    was paying people to orphan data.

    Keeping last week's roster means a dataset that leaves is still counted against
    the team that let it go, as unrated, until somebody else claims it.
    """

    __tablename__ = "domain_roster"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_urn: Mapped[str] = mapped_column(String(500), index=True)
    domain_urn: Mapped[str] = mapped_column(String(300))
    week_of: Mapped[date] = mapped_column(Date, index=True)
