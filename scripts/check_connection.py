"""Step 3 smoke test: verifies the authenticated connection to DataHub.

Checks end to end that the SDK can:
  - authenticate with the token from .env,
  - list the domains (the leaderboard "teams"),
  - count datasets,
  - read a dataset's testResults aspect (the quality signal of the score).

Usage:
    .venv/Scripts/python scripts/check_connection.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allows running the script directly (adds the project root to the path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.metadata.schema_classes import TestResultsClass  # noqa: E402

from mcp_client.datahub_connection import get_graph  # noqa: E402

DOMAINS_QUERY = """
{ listDomains(input: {start: 0, count: 50}) {
    total
    domains { urn properties { name } }
} }
"""

DATASET_COUNT_QUERY = """
{ search(input: {type: DATASET, query: "*", start: 0, count: 0}) { total } }
"""


def main() -> None:
    graph = get_graph()
    print("Connected. Actor:", graph.execute_graphql("{ me { corpUser { username } } }")["me"]["corpUser"]["username"])

    domains = graph.execute_graphql(DOMAINS_QUERY)["listDomains"]
    print(f"\nDomains ({domains['total']}):")
    for d in domains["domains"]:
        name = (d.get("properties") or {}).get("name") or d["urn"]
        print(f"  - {name}")

    total_datasets = graph.execute_graphql(DATASET_COUNT_QUERY)["search"]["total"]
    print(f"\nTotal datasets: {total_datasets}")

    # Read testResults from a sample dataset to confirm the quality signal.
    sample = graph.execute_graphql(
        '{ search(input: {type: DATASET, query: "*", start: 0, count: 5}) '
        "{ searchResults { entity { urn } } } }"
    )["search"]["searchResults"]

    print("\ntestResults per dataset (sample):")
    found = 0
    for r in sample:
        urn = r["entity"]["urn"]
        tr = graph.get_aspect(urn, TestResultsClass)
        if tr is not None:
            passing = len(tr.passing or [])
            failing = len(tr.failing or [])
            print(f"  - {urn.split(',')[1] if ',' in urn else urn}: {passing} pass / {failing} fail")
            found += 1
    if found == 0:
        print("  (no dataset in the sample has testResults; others will show up when walking all of them)")

    print("\nOK: authenticated connection and signal reading verified.")


if __name__ == "__main__":
    main()
