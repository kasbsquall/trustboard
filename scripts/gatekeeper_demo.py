"""Runs the Gatekeeper against two real datasets, one trusted and one not.

The dataset picking lives here rather than in `agents/gatekeeper.py` on purpose.
Choosing which asset to test is stage direction, and it needs DataHub search to
find one dataset of each tier. The agent itself has no business knowing any of
that: its only import is the MCP transport, which is the whole claim.

    python -m scripts.gatekeeper_demo
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.gatekeeper import Decision, evaluate  # noqa: E402
from mcp_client.datahub_connection import execute_graphql_retry, get_graph  # noqa: E402

_BY_TAG = (
    'query s($tag: String!) { search(input: {type: DATASET, query: "*", '
    'orFilters: [{and: [{field: "tags", values: [$tag]}]}], start: 0, count: 1}) '
    "{ searchResults { entity { urn } } } }"
)


def find_dataset_by_tier(graph, tier: str) -> str | None:
    """First dataset carrying a given trust tier tag, or None."""
    try:
        res = execute_graphql_retry(graph, _BY_TAG, variables={"tag": f"urn:li:tag:trust.{tier}"})
        results = res["search"]["searchResults"]
        return results[0]["entity"]["urn"] if results else None
    except Exception:  # noqa: BLE001
        return None


def print_decision(d: Decision) -> None:
    mark = "GO " if d.allowed else "NO-GO"
    print(f"\n[{mark}] task: {d.task}")
    print(f"        dataset: {d.dataset_urn.split(',')[1] if ',' in d.dataset_urn else d.dataset_urn}")
    print(f"        reason: {d.reason}")
    if d.alternative:
        print(f"        suggestion: {d.alternative}")


def main() -> None:
    graph = get_graph()
    print("Gatekeeper agent: reads the Trust Score from DataHub before using data.")

    gold = find_dataset_by_tier(graph, "gold")
    risky = find_dataset_by_tier(graph, "at-risk") or find_dataset_by_tier(graph, "bronze")

    if gold:
        print_decision(evaluate(gold, "Build the executive revenue dashboard"))
    if risky:
        print_decision(evaluate(risky, "Train the churn prediction model"))


if __name__ == "__main__":
    main()
