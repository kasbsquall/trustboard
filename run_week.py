"""Orchestrator for the TrustBoard weekly cycle.

Runs the full three-agent pipeline in one go:
  1. Auditor  -> computes each team's Trust Score.
  2. Scribe   -> writes the scores back to DataHub (property, tags,
                 description, incidents).
  3. Snapshot -> stores the result in the local history (for trends).
  4. Herald   -> publishes the leaderboard to Slack, comparing against the
                 previous week.

Usage:
    .venv/Scripts/python run_week.py
"""
from __future__ import annotations

from datetime import date

from agents import herald, scribe
from agents.auditor import audit_all_domains
from backend.database.repository import (
    previous_week_scores,
    record_leaderboard_post,
    save_weekly_snapshot,
)
from mcp_client.datahub_connection import cli, get_graph
from scoring.trust_score import trust_tier


def _snapshot_rows(results, written_urns: set[str]) -> list[dict]:
    """Turns the audit into history rows.

    written_urns comes from the Scribe, so written_to_datahub records what
    actually happened rather than being pinned to True on every row.
    """
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
                "ownership_score": comps.get("ownership"),
                "signal_coverage": audited.score.coverage,
                "score_version": audited.score.score_version,
                "dataset_count": audited.score.dataset_count,
                "rated_dataset_count": audited.score.rated_dataset_count,
                "rated": audited.score.rated,
                "rank_this_week": rank,
                "written_to_datahub": audited.info.urn in written_urns,
            }
        )
    return rows


def main() -> None:
    graph = get_graph()

    print("[1/4] Auditor: computing Trust Scores...")
    results = audit_all_domains(graph)
    for a in results:
        print(
            f"      {a.info.name:<24} {a.score.score:>5.1f}  "
            f"{trust_tier(a.score.score, a.score.rated):<8} "
            f"coverage {a.score.coverage:.0%}"
        )
    print_quality_sources(results)

    print("\n[2/4] Scribe: writing back to the DataHub graph...")
    write_report = scribe.write_all(graph, results=results)

    print("\n[3/4] Snapshot: saving the weekly history...")
    week = save_weekly_snapshot(_snapshot_rows(results, write_report.written_urns))
    print(f"      snapshot saved for the week of {week.isoformat()}")

    print("\n[4/4] Herald: publishing the leaderboard...")
    previous = previous_week_scores()
    herald.publish_leaderboard(previous=previous, graph=graph)

    if results:
        top = max(results, key=lambda a: a.score.score).info.name
        record_leaderboard_post(date.today(), top_domain=top, most_improved=None)

    print("\nWeekly cycle complete.")


if __name__ == "__main__":
    cli(main)
