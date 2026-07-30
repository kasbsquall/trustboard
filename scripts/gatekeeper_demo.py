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

from agents.gatekeeper import Decision, evaluate
from mcp_client.datahub_connection import cli, execute_graphql_retry, get_graph

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
    # What a calling system would write to its own log. A bare boolean is not
    # auditable six months later; this line names the tier, the score, the
    # coverage behind it, the model version and the policy that was applied.
    print(f"        audit: {d.audit_line()}")


# A dataset nobody has ingested. Included so the third outcome is visible: the
# gate does not answer an unknown asset the same way it answers a bad one,
# because "we have no record of this" is a problem with the request rather than
# with somebody's data.
_UNKNOWN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,does.not.exist,PROD)"


def main() -> None:
    graph = get_graph()
    print("Gatekeeper agent: reads the Trust Score from DataHub before using data.")

    gold = find_dataset_by_tier(graph, "gold")
    risky = find_dataset_by_tier(graph, "at-risk") or find_dataset_by_tier(graph, "bronze")
    unrated = find_dataset_by_tier(graph, "unrated")

    if gold:
        print_decision(evaluate(gold, "Build the executive revenue dashboard"))
    if risky:
        print_decision(evaluate(risky, "Train the churn prediction model"))
    # The case the whole three-outcome verdict exists for. A refusal here is not
    # an accusation: nobody has checked this table, so the honest answer is that
    # TrustBoard cannot vouch for it, and the suggestion says how to fix that
    # rather than telling a team its data is bad.
    if unrated:
        print_decision(evaluate(unrated, "Backfill the customer 360 table"))
    print_decision(evaluate(_UNKNOWN, "Join against a table someone mentioned in a ticket"))


if __name__ == "__main__":
    cli(main)
