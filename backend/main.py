"""Backend FastAPI de TrustBoard.

Expone el leaderboard actual y el historico de tendencia por dominio para el
dashboard Next.js. Lee del historico local (repository), que se puebla en cada
ciclo semanal (run_week.py).
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.database.repository import (
    current_leaderboard,
    domain_history,
    init_db,
    previous_week_scores,
)

app = FastAPI(title="TrustBoard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/leaderboard")
def leaderboard() -> dict:
    """Leaderboard de la semana mas reciente, con rank actual y anterior."""
    teams = current_leaderboard()
    previous = previous_week_scores()
    for t in teams:
        prev = previous.get(t["domain_name"])
        t["score_last_week"] = round(prev, 2) if prev is not None else None
    top = teams[0]["domain_name"] if teams else None
    most_improved = _most_improved(teams)
    return {"teams": teams, "team_of_the_week": top, "most_improved": most_improved}


@app.get("/api/domains/{domain_name}/history")
def history(domain_name: str) -> dict:
    """Serie temporal del Trust Score de un dominio."""
    rows = domain_history(domain_name)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No history for domain '{domain_name}'")
    return {"domain_name": domain_name, "history": rows}


def _most_improved(teams: list[dict]) -> dict | None:
    """El equipo con mayor subida de Trust Score respecto a la semana anterior."""
    previous = previous_week_scores()
    best = None
    for t in teams:
        prev = previous.get(t["domain_name"])
        if prev is None:
            continue
        delta = t["trust_score"] - prev
        if best is None or delta > best["score_delta"]:
            best = {
                "domain_name": t["domain_name"],
                "score_delta": round(delta, 2),
                "trust_score": t["trust_score"],
            }
    return best if best and best["score_delta"] > 0 else None
