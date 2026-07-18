"""Orquestador del ciclo semanal de TrustBoard.

Corre el pipeline completo de los tres agentes de una sola vez:
  1. Auditor  -> calcula el Trust Score de cada equipo.
  2. Escriba  -> escribe los scores de vuelta a DataHub (property, tags,
                 descripcion, incidents).
  3. Snapshot -> guarda el resultado en el historico local (para tendencias).
  4. Heraldo  -> publica el leaderboard en Slack comparando vs la semana previa.

Uso:
    .venv/Scripts/python run_week.py
"""
from __future__ import annotations

from agents import herald, scribe
from agents.auditor import audit_all_domains
from backend.database.repository import (
    previous_week_scores,
    record_leaderboard_post,
    save_weekly_snapshot,
)
from mcp_client.datahub_connection import get_graph
from scoring.trust_score import trust_tier

from datetime import date


def _snapshot_rows(results) -> list[dict]:
    rows = []
    for rank, audited in enumerate(results, 1):
        comps = audited.score.component_averages
        rows.append(
            {
                "domain_name": audited.info.name,
                "domain_urn": audited.info.urn,
                "trust_score": audited.score.score,
                "assertions_passing_pct": comps.get("quality"),
                "freshness_score": comps.get("freshness"),
                "documentation_score": comps.get("documentation"),
                "rank_this_week": rank,
                "written_to_datahub": True,
            }
        )
    return rows


def main() -> None:
    graph = get_graph()

    print("[1/4] Auditor: calculando Trust Scores...")
    results = audit_all_domains(graph)
    for a in results:
        print(f"      {a.info.name:<24} {a.score.score:>5.1f}  {trust_tier(a.score.score)}")

    print("\n[2/4] Escriba: escribiendo de vuelta al grafo de DataHub...")
    scribe.write_all(graph, results=results)

    print("\n[3/4] Snapshot: guardando el historico semanal...")
    week = save_weekly_snapshot(_snapshot_rows(results))
    print(f"      snapshot guardado para la semana del {week.isoformat()}")

    print("\n[4/4] Heraldo: publicando el leaderboard...")
    previous = previous_week_scores()
    herald.publish_leaderboard(previous=previous, graph=graph)

    if results:
        top = max(results, key=lambda a: a.score.score).info.name
        record_leaderboard_post(date.today(), top_domain=top, most_improved=None)

    print("\nCiclo semanal completo.")


if __name__ == "__main__":
    main()
