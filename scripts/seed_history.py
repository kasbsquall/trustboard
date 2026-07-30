"""Seeds a multi-week history for the dashboard (demo preparation).

The current week uses the REAL Trust Score computed by the Auditor. Earlier
weeks are derived from a per-team trajectory that gives the leaderboard a
narrative: Marketing climbing back (most improved), Engineering falling, the
rest rising gently. It is declared as demo environment preparation.

Usage:
    python scripts/seed_history.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.auditor import audit_all_domains
from backend.database.repository import _monday_of, save_weekly_snapshot
from mcp_client.datahub_connection import cli, get_graph
from scoring.trust_score import SCORE_VERSION

# How much to SUBTRACT from the current score on weeks -3, -2, -1
# (score = current - offset). A positive offset means it came from lower (it
# went up). A negative one means it came from higher (it fell).
TRAJECTORIES = {
    "Data Platform Team": [4.0, 3.0, 1.5],          # steady high, slight rise
    "Ecommerce Operations": [10.0, 6.0, 2.5],       # rising
    "Engineering Division": [-7.0, -4.0, -3.0],     # fell this week
    "E-Commerce": [5.0, 3.0, 1.5],                  # rising slowly
    "Marketing": [14.0, 10.0, 6.0],                 # most improved
}
_DEFAULT = [8.0, 5.0, 2.0]


def _week_rows(scores: dict[str, float], version: str) -> list[dict]:
    """Rows for one authored week.

    They carry the model version they were derived from, and a synthetic flag.
    Without the version, the dashboard compared a real v2.1 score against a row
    with no version at all and printed the difference as if it meant something,
    which is exactly the cross-version comparison the README warns about. Without
    the flag, invented history sat in the same chart as a measured score with
    nothing to tell them apart.
    """
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {
            "domain_name": name,
            "trust_score": round(max(0.0, min(100.0, score)), 2),
            "rank_this_week": i,
            "score_version": version,
            "synthetic": True,
            # These weeks were authored, so nothing was written to DataHub for
            # them and the row says so.
            "written_to_datahub": False,
        }
        for i, (name, score) in enumerate(ranked, 1)
    ]


def main() -> None:
    graph = get_graph()
    results = audit_all_domains(graph)
    current = {a.info.name: a.score.score for a in results}
    urns = {a.info.name: a.info.urn for a in results}

    this_monday = _monday_of(date.today())

    # Weeks -3, -2, -1 (oldest first so that rank_last_week resolves).
    for weeks_ago in (3, 2, 1):
        idx = 3 - weeks_ago  # 0,1,2 -> that week's offset
        scores = {
            name: current[name] - TRAJECTORIES.get(name, _DEFAULT)[idx]
            for name in current
        }
        week_of = this_monday - timedelta(days=7 * weeks_ago)
        rows = _week_rows(scores, SCORE_VERSION)
        save_weekly_snapshot(rows, week_of=week_of)
        print(f"  week {week_of.isoformat()}: {[(r['domain_name'], r['trust_score']) for r in rows]}")

    # Current week with real components.
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
                "signal_coverage": a.score.coverage,
                "score_version": a.score.score_version,
                "dataset_count": a.score.dataset_count,
                "rated_dataset_count": a.score.rated_dataset_count,
                "rated": a.score.rated,
                "rank_this_week": rank,
                "synthetic": False,
                # This week's row came from a real audit that also wrote to the
                # graph. Omitting the key let repository.save_weekly_snapshot
                # default it to False and clobber what run_week.py had recorded,
                # so the shipped snapshot said nothing was ever written while the
                # graph plainly held the writes. The one field built to record
                # whether the project did what it claims was recording the
                # opposite.
                "written_to_datahub": True,
            }
        )
    save_weekly_snapshot(current_rows, week_of=this_monday)
    print(f"  week {this_monday.isoformat()} (current, real): saved")
    print("\n4-week history seeded.")


if __name__ == "__main__":
    cli(main)
