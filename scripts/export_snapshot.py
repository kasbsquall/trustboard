"""Exports the local history to the files the repo ships.

Two artifacts come out of a real weekly run and used to be maintained by hand,
which is how they drifted from the code:

  backend/database/seed_data.json  the snapshot the hosted dashboard loads when
                                   it starts with an empty database, so the demo
                                   works on a server with no DataHub reachable.
  examples/*.json                  sample outputs for anyone reading the repo
                                   without running it.

Run it after `python run_week.py` so both reflect the same run.

Usage:
    python scripts/export_snapshot.py
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from agents import trust_lookup  # noqa: E402
from agents.herald import build_message  # noqa: E402
from backend.database.connection import SessionLocal  # noqa: E402
from backend.database.models import DomainScore  # noqa: E402
from backend.database.repository import previous_week_scores  # noqa: E402
from backend.main import leaderboard  # noqa: E402

SEED_FILE = ROOT / "backend" / "database" / "seed_data.json"
EXAMPLES = ROOT / "examples"


def _plain(value):
    """Postgres NUMERIC columns come back as Decimal, which json cannot encode."""
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=_plain)
        fh.write("\n")
    print(f"  wrote {path.relative_to(ROOT)}")


def main() -> None:
    with SessionLocal() as session:
        rows = session.scalars(
            select(DomainScore).order_by(DomainScore.week_of, DomainScore.rank_this_week)
        ).all()

    if not rows:
        print("Nothing to export: the history is empty. Run run_week.py first.")
        return

    print(f"Exporting {len(rows)} rows across {len({r.week_of for r in rows})} weeks.")

    _write(
        SEED_FILE,
        {
            "domain_scores": [
                {
                    "domain_name": r.domain_name,
                    "domain_urn": r.domain_urn,
                    "week_of": r.week_of.isoformat(),
                    "trust_score": r.trust_score,
                    "assertions_passing_pct": r.assertions_passing_pct,
                    "freshness_score": r.freshness_score,
                    "documentation_score": r.documentation_score,
                    "ownership_score": r.ownership_score,
                    "signal_coverage": r.signal_coverage,
                    "score_version": r.score_version,
                    "dataset_count": r.dataset_count,
                    "rated_dataset_count": r.rated_dataset_count,
                    "rated": None if r.rated is None else bool(r.rated),
                    "rank_this_week": r.rank_this_week,
                    "rank_last_week": r.rank_last_week,
                    "written_to_datahub": bool(r.written_to_datahub),
                }
                for r in rows
            ]
        },
    )

    board = leaderboard()
    _write(EXAMPLES / "leaderboard.json", board)

    latest = max(r.week_of for r in rows)
    _write(
        EXAMPLES / "domain_scores.json",
        [
            {
                "domain_name": r.domain_name,
                "domain_urn": r.domain_urn,
                "week_of": r.week_of.isoformat(),
                "trust_score": r.trust_score,
                "quality": r.assertions_passing_pct,
                "documentation": r.documentation_score,
                "ownership": r.ownership_score,
                "freshness": r.freshness_score,
                "signal_coverage": r.signal_coverage,
                "score_version": r.score_version,
                "dataset_count": r.dataset_count,
                "rated_dataset_count": r.rated_dataset_count,
                "rated": None if r.rated is None else bool(r.rated),
                "rank_this_week": r.rank_this_week,
            }
            for r in rows
            if r.week_of == latest
        ],
    )

    # The Herald reads the standings back from DataHub rather than from the
    # local history, so the sample is generated the same way it is posted.
    _write(
        EXAMPLES / "slack_message.json",
        build_message(trust_lookup.leaderboard(), previous_week_scores()),
    )

    print("Done.")


if __name__ == "__main__":
    main()
