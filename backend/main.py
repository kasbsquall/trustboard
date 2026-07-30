"""TrustBoard FastAPI backend.

Exposes the current leaderboard and the per-domain trend history for the
Next.js dashboard. Reads from the local history (repository), which is populated
on every weekly cycle (run_week.py).
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.database.repository import (
    current_leaderboard,
    domain_history,
    init_db,
    load_seed_if_empty,
    previous_week_scores,
)

app = FastAPI(title="TrustBoard API", version="1.0.0")

# The dashboard is read-only and carries no sensitive data, so any origin is
# allowed to keep the deploy simple. Adjustable through env if needed.
_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    load_seed_if_empty()  # deploy without DataHub: load the versioned history


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/model")
def model() -> dict:
    """The scoring model itself: weights, tier cut-offs and the coverage floor.

    Served rather than hardcoded in the dashboard so the numbers that govern
    every badge on the screen come from the same place the scores do. A rule
    that only exists in the code is a rule the people being ranked by it cannot
    check.
    """
    from scoring.trust_score import (
        AT_RISK_THRESHOLD,
        BREADTH_TARGET,
        FRESHNESS_WINDOW_DAYS,
        MIN_COVERAGE,
        QUALITY_REQUIRED,
        SCORE_VERSION,
        TIERS,
        WEIGHTS,
    )

    return {
        "version": SCORE_VERSION,
        "weights": WEIGHTS,
        "tiers": [{"name": name, "min_score": floor} for name, floor in TIERS],
        "min_coverage": MIN_COVERAGE,
        "incident_threshold": AT_RISK_THRESHOLD,
        "quality_required": QUALITY_REQUIRED,
        "breadth_target": BREADTH_TARGET,
        "freshness_window_days": FRESHNESS_WINDOW_DAYS,
    }


@app.get("/api/leaderboard")
def leaderboard() -> dict:
    """Leaderboard for the most recent week, with current and previous rank."""
    teams = current_leaderboard()
    previous = previous_week_scores()
    for t in teams:
        prev = previous.get(t["domain_name"])
        t["score_last_week"] = round(prev, 2) if prev is not None else None
        # Short series for the sparkline on each leaderboard row.
        t["spark"] = [round(p["trust_score"], 2) for p in domain_history(t["domain_name"])][-8:]
    top = teams[0]["domain_name"] if teams else None
    most_improved = _most_improved(teams)
    return {"teams": teams, "team_of_the_week": top, "most_improved": most_improved}


@app.get("/api/domains/{domain_name}/history")
def history(domain_name: str) -> dict:
    """Time series of a domain's Trust Score."""
    rows = domain_history(domain_name)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No history for domain '{domain_name}'")
    return {"domain_name": domain_name, "history": rows}


def _most_improved(teams: list[dict]) -> dict | None:
    """The team with the largest Trust Score gain over the previous week."""
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
