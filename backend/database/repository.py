"""Persistencia del historico de Trust Scores.

Guarda un snapshot semanal por dominio para poder mostrar tendencias y
calcular el "most improved" de la semana. Complementa lo que vive en DataHub
(el grafo tiene el estado actual; aqui vive la serie temporal para el
dashboard).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal, init_db
from backend.database.models import DomainScore, LeaderboardPost

_SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_data.json")


def _monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def save_weekly_snapshot(rows: list[dict], week_of: date | None = None) -> date:
    """Guarda (idempotente) el snapshot de la semana para cada dominio.

    rows: [{domain_name, trust_score, assertions_passing_pct, freshness_score,
            documentation_score, rank_this_week, domain_urn, written_to_datahub}]
    Re-ejecutar en la misma semana actualiza los valores en vez de duplicar.
    """
    init_db()
    week = _monday_of(week_of or date.today())

    with SessionLocal() as session:
        # rank de la semana anterior por dominio, para el delta.
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
            target.rank_this_week = row.get("rank_this_week")
            target.rank_last_week = prev_ranks.get(row["domain_name"])
            target.written_to_datahub = row.get("written_to_datahub", True)
            target.datahub_property_urn = row.get("datahub_property_urn")
            if existing is None:
                session.add(target)
        session.commit()
    return week


def load_seed_if_empty() -> int:
    """Puebla la DB desde seed_data.json si esta vacia (deploy sin DataHub).

    Permite que el dashboard corra en un servidor donde no hay DataHub: el
    historico ya calculado viaja como JSON versionado y se carga al arrancar.
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
                    rank_this_week=row.get("rank_this_week"),
                    rank_last_week=row.get("rank_last_week"),
                    written_to_datahub=True,
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
    """{domain_name: trust_score} de la semana anterior (para el 'most improved')."""
    init_db()
    week = _monday_of(week_of or date.today())
    prev = week - timedelta(days=7)
    with SessionLocal() as session:
        rows = session.scalars(select(DomainScore).where(DomainScore.week_of == prev)).all()
        return {r.domain_name: float(r.trust_score) for r in rows}


def current_leaderboard() -> list[dict]:
    """Ultimo snapshot por dominio, ordenado por score (para el backend/API)."""
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
    """Serie temporal de un dominio (para el grafico de tendencia)."""
    init_db()
    with SessionLocal() as session:
        rows = session.scalars(
            select(DomainScore)
            .where(DomainScore.domain_name == domain_name)
            .order_by(DomainScore.week_of.asc())
        ).all()
        return [_row_to_dict(r) for r in rows]


def record_leaderboard_post(week_of: date, top_domain: str, most_improved: str | None, ts: str | None = None) -> None:
    init_db()
    with SessionLocal() as session:
        session.add(
            LeaderboardPost(
                week_of=_monday_of(week_of),
                top_domain=top_domain,
                most_improved_domain=most_improved,
                slack_message_ts=ts,
            )
        )
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
        "rank_this_week": r.rank_this_week,
        "rank_last_week": r.rank_last_week,
    }
