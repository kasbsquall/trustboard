"""Siembra un historico de varias semanas para el dashboard (preparacion demo).

La semana actual usa el Trust Score REAL calculado por el Auditor. Las semanas
anteriores se derivan con una trayectoria por equipo que da una narrativa al
leaderboard: Marketing remontando (most improved), Engineering cayendo, el
resto subiendo suave. Se declara como preparacion del entorno de demo.

Uso:
    .venv/Scripts/python scripts/seed_history.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.auditor import audit_all_domains  # noqa: E402
from backend.database.repository import _monday_of, save_weekly_snapshot  # noqa: E402
from mcp_client.datahub_connection import get_graph  # noqa: E402

# Cuanto RESTAR al score actual en las semanas -3, -2, -1 (score = actual - offset).
# Offset positivo = venia mas abajo (subio). Negativo = venia mas alto (cayo).
TRAJECTORIES = {
    "Data Platform Team": [4.0, 3.0, 1.5],          # estable alto, leve subida
    "Ecommerce Operations": [10.0, 6.0, 2.5],       # subiendo
    "Engineering Division": [-7.0, -4.0, -3.0],     # cayo esta semana
    "E-Commerce": [5.0, 3.0, 1.5],                  # subiendo lento
    "Marketing": [14.0, 10.0, 6.0],                 # most improved
}
_DEFAULT = [8.0, 5.0, 2.0]


def _week_rows(scores: dict[str, float]) -> list[dict]:
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"domain_name": name, "trust_score": round(max(0.0, min(100.0, score)), 2), "rank_this_week": i}
        for i, (name, score) in enumerate(ranked, 1)
    ]


def main() -> None:
    graph = get_graph()
    results = audit_all_domains(graph)
    current = {a.info.name: a.score.score for a in results}
    urns = {a.info.name: a.info.urn for a in results}

    this_monday = _monday_of(date.today())

    # Semanas -3, -2, -1 (mas antigua primero para que rank_last_week se resuelva).
    for weeks_ago in (3, 2, 1):
        idx = 3 - weeks_ago  # 0,1,2 -> offset de esa semana
        scores = {
            name: current[name] - TRAJECTORIES.get(name, _DEFAULT)[idx]
            for name in current
        }
        week_of = this_monday - timedelta(days=7 * weeks_ago)
        rows = _week_rows(scores)
        save_weekly_snapshot(rows, week_of=week_of)
        print(f"  semana {week_of.isoformat()}: {[(r['domain_name'], r['trust_score']) for r in rows]}")

    # Semana actual con componentes reales.
    current_rows = []
    for rank, a in enumerate(sorted(results, key=lambda x: x.score.score, reverse=True), 1):
        comps = a.score.component_averages
        current_rows.append(
            {
                "domain_name": a.info.name,
                "domain_urn": urns[a.info.name],
                "trust_score": a.score.score,
                "assertions_passing_pct": comps.get("quality"),
                "freshness_score": comps.get("freshness"),
                "documentation_score": comps.get("documentation"),
                "ownership_score": comps.get("ownership"),
                "rank_this_week": rank,
            }
        )
    save_weekly_snapshot(current_rows, week_of=this_monday)
    print(f"  semana {this_monday.isoformat()} (actual, real): guardada")
    print("\nHistorico de 4 semanas sembrado.")


if __name__ == "__main__":
    main()
