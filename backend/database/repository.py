"""Persistence of the Trust Score history.

Stores a weekly snapshot per domain so trends can be shown and the "most
improved" of the week can be computed. It complements what lives in DataHub
(the graph holds the current state; the time series for the dashboard lives
here).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal, init_db
from backend.database.models import DomainRoster, DomainScore, LeaderboardPost

_SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_data.json")


def _monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def save_weekly_snapshot(rows: list[dict], week_of: date | None = None) -> date:
    """Saves (idempotently) the week's snapshot for each domain.

    rows: [{domain_name, trust_score, assertions_passing_pct, freshness_score,
            documentation_score, rank_this_week, domain_urn, written_to_datahub}]
    Re-running within the same week updates the values instead of duplicating.
    """
    init_db()
    week = _monday_of(week_of or date.today())

    with SessionLocal() as session:
        # previous week's rank per domain, for the delta.
        prev_week = week - timedelta(days=7)
        prev_ranks = _ranks_for_week(session, prev_week)

        for row in rows:
            existing = session.scalar(
                select(DomainScore).where(
                    DomainScore.domain_name == row["domain_name"],
                    DomainScore.week_of == week,
                )
            )
            target = existing or DomainScore(domain_name=row["domain_name"], week_of=week)
            target.domain_urn = row.get("domain_urn")
            target.trust_score = row["trust_score"]
            target.assertions_passing_pct = row.get("assertions_passing_pct")
            target.freshness_score = row.get("freshness_score")
            target.documentation_score = row.get("documentation_score")
            target.ownership_score = row.get("ownership_score")
            target.signal_coverage = row.get("signal_coverage")
            target.score_version = row.get("score_version")
            target.dataset_count = row.get("dataset_count")
            target.rated_dataset_count = row.get("rated_dataset_count")
            target.rated = row.get("rated")
            target.synthetic = row.get("synthetic", False)
            target.rank_this_week = row.get("rank_this_week")
            target.rank_last_week = prev_ranks.get(row["domain_name"])
            # Defaults to False. Defaulting to True meant a caller that never
            # wrote to DataHub still recorded that it had.
            target.written_to_datahub = row.get("written_to_datahub", False)
            target.datahub_property_urn = row.get("datahub_property_urn")
            if existing is None:
                session.add(target)
        session.commit()
    return week


def load_seed_if_empty() -> int:
    """Populates the DB from seed_data.json if it is empty (deploy without DataHub).

    Lets the dashboard run on a server where DataHub is not available: the
    already-computed history travels as versioned JSON and is loaded at startup.
    """
    init_db()
    with SessionLocal() as session:
        if session.scalar(select(DomainScore.id).limit(1)):
            return 0
        if not os.path.exists(_SEED_FILE):
            return 0
        with open(_SEED_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        count = 0
        for row in data.get("domain_scores", []):
            session.add(
                DomainScore(
                    domain_name=row["domain_name"],
                    domain_urn=row.get("domain_urn"),
                    week_of=date.fromisoformat(row["week_of"]),
                    trust_score=row["trust_score"],
                    assertions_passing_pct=row.get("assertions_passing_pct"),
                    freshness_score=row.get("freshness_score"),
                    documentation_score=row.get("documentation_score"),
                    ownership_score=row.get("ownership_score"),
                    signal_coverage=row.get("signal_coverage"),
                    score_version=row.get("score_version"),
                    dataset_count=row.get("dataset_count"),
                    rated_dataset_count=row.get("rated_dataset_count"),
                    rated=row.get("rated"),
                    synthetic=row.get("synthetic", False),
                    rank_this_week=row.get("rank_this_week"),
                    rank_last_week=row.get("rank_last_week"),
                    # The seed file is an export of a run that did write to
                    # DataHub, and it records that per row rather than assuming it.
                    written_to_datahub=row.get("written_to_datahub", False),
                )
            )
            count += 1
        session.commit()
        return count


def _ranks_for_week(session: Session, week: date) -> dict[str, int]:
    rows = session.scalars(
        select(DomainScore).where(DomainScore.week_of == week)
    ).all()
    return {r.domain_name: r.rank_this_week for r in rows if r.rank_this_week is not None}


def previous_week_scores(week_of: date | None = None) -> dict[str, float]:
    """{domain_name: trust_score} for the week before the one being displayed.

    The reference week defaults to the most recent snapshot in the history, not
    to today. Anchoring on today means that the moment the calendar moves past
    the last run, every comparison resolves to an empty week and the dashboard
    renders stale scores as if they were current, with no change at all.
    """
    init_db()
    with SessionLocal() as session:
        latest = session.scalar(select(DomainScore.week_of).order_by(DomainScore.week_of.desc()))
    if week_of is None and latest is None:
        return {}
    week = _monday_of(week_of) if week_of is not None else latest
    prev = week - timedelta(days=7)
    with SessionLocal() as session:
        rows = session.scalars(select(DomainScore).where(DomainScore.week_of == prev)).all()
        # Unrated rows are skipped rather than read as a score of 0.0. That zero
        # means "could not measure", so comparing against it manufactured a
        # 60-point gain for any team that went from unrated to silver, and the
        # dashboard headline reads "most improved" straight off this comparison.
        return {
            r.domain_name: float(r.trust_score)
            for r in rows
            if r.rated is not False
        }


def current_leaderboard() -> list[dict]:
    """Latest snapshot per domain, sorted by score (for the backend/API)."""
    init_db()
    with SessionLocal() as session:
        latest_week = session.scalar(select(DomainScore.week_of).order_by(DomainScore.week_of.desc()))
        if latest_week is None:
            return []
        rows = session.scalars(
            select(DomainScore).where(DomainScore.week_of == latest_week)
        ).all()
        result = [_row_to_dict(r) for r in rows]
        result.sort(key=lambda d: d["trust_score"], reverse=True)
        return result


def domain_history(domain_name: str) -> list[dict]:
    """Time series of a domain (for the trend chart)."""
    init_db()
    with SessionLocal() as session:
        rows = session.scalars(
            select(DomainScore)
            .where(DomainScore.domain_name == domain_name)
            .order_by(DomainScore.week_of.asc())
        ).all()
        return [_row_to_dict(r) for r in rows]


def record_leaderboard_post(week_of: date, top_domain: str, most_improved: str | None, ts: str | None = None) -> None:
    """Records that the week's leaderboard was published (one row per week).

    Upsert rather than insert. The weekly cycle is meant to be re-runnable, and
    an insert here meant every re-run added another row for the same week, so
    the posts table counted runs of the script instead of leaderboards posted.
    """
    init_db()
    week = _monday_of(week_of)
    with SessionLocal() as session:
        existing = session.scalar(
            select(LeaderboardPost).where(LeaderboardPost.week_of == week)
        )
        target = existing or LeaderboardPost(week_of=week)
        target.top_domain = top_domain
        target.most_improved_domain = most_improved
        target.slack_message_ts = ts
        if existing is None:
            session.add(target)
        session.commit()


def _row_to_dict(r: DomainScore) -> dict:
    return {
        "domain_name": r.domain_name,
        "domain_urn": r.domain_urn,
        "week_of": r.week_of.isoformat(),
        "trust_score": float(r.trust_score),
        "assertions_passing_pct": float(r.assertions_passing_pct) if r.assertions_passing_pct is not None else None,
        "freshness_score": float(r.freshness_score) if r.freshness_score is not None else None,
        "documentation_score": float(r.documentation_score) if r.documentation_score is not None else None,
        "ownership_score": float(r.ownership_score) if r.ownership_score is not None else None,
        "signal_coverage": float(r.signal_coverage) if r.signal_coverage is not None else None,
        "score_version": r.score_version,
        "dataset_count": r.dataset_count,
        "rated_dataset_count": r.rated_dataset_count,
        "rated": None if r.rated is None else bool(r.rated),
        "synthetic": bool(r.synthetic),
        "rank_this_week": r.rank_this_week,
        "rank_last_week": r.rank_last_week,
        "written_to_datahub": bool(r.written_to_datahub),
    }


def save_domain_roster(roster: dict[str, str], week_of: date | None = None) -> int:
    """Records which domain owned each dataset this week (idempotent per week)."""
    init_db()
    week = _monday_of(week_of or date.today())
    with SessionLocal() as session:
        session.query(DomainRoster).filter(DomainRoster.week_of == week).delete()
        for dataset_urn, domain_urn in sorted(roster.items()):
            session.add(DomainRoster(dataset_urn=dataset_urn, domain_urn=domain_urn, week_of=week))
        session.commit()
        return len(roster)


def previous_domain_roster(week_of: date | None = None) -> dict[str, str]:
    """Last week's dataset-to-domain map, for spotting datasets that left."""
    init_db()
    with SessionLocal() as session:
        latest = session.scalar(select(DomainRoster.week_of).order_by(DomainRoster.week_of.desc()))
    if latest is None:
        return {}
    week = _monday_of(week_of) if week_of is not None else latest
    with SessionLocal() as session:
        rows = session.scalars(select(DomainRoster).where(DomainRoster.week_of == week)).all()
        return {r.dataset_urn: r.domain_urn for r in rows}
