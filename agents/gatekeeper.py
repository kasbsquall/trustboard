"""Second agent: the Gatekeeper.

Stands in for "the next agent" in the ecosystem: before using a dataset for a
task (building a dashboard, training a model, running a query), it reads the
Trust Score that TrustBoard wrote to the graph and decides GO/NO-GO. If the
dataset is not trustworthy, it refuses to use it.

It reaches that score over MCP, by spawning the TrustBoard MCP server as a
separate process and calling its `is_trustworthy` tool. Importing
`agents.trust_lookup` in-process would return the same answer in less code, and
would prove nothing: the point is that an agent which shares no database, no
run and no import with TrustBoard can still inherit what it knows, because the
score lives in the graph and is published through a standard protocol.

This closes the loop: the Auditor computes, the Scribe writes to the graph, and
a different agent picks it up from there.

Demo:
    python -m agents.gatekeeper
"""
from __future__ import annotations

from dataclasses import dataclass

from agents import trust_lookup
from mcp_client import trustboard_client
from mcp_client.datahub_connection import execute_graphql_retry, get_graph


@dataclass(frozen=True)
class Decision:
    task: str
    dataset_urn: str
    allowed: bool
    reason: str
    alternative: str | None = None


def evaluate(dataset_urn: str, task: str, min_tier: str = "silver", graph=None) -> Decision:
    """Decides whether an agent may use a dataset based on its Trust Score.

    The verdict comes back over MCP. Nothing about TrustBoard is imported to get
    it beyond the transport itself.
    """
    verdict = trustboard_client.call_tool(
        "is_trustworthy", urn=dataset_urn, min_tier=min_tier
    )

    if verdict["trustworthy"]:
        return Decision(
            task=task,
            dataset_urn=dataset_urn,
            allowed=True,
            reason=(
                f"Dataset is '{verdict.get('trust_tier')}' (team "
                f"{verdict.get('owning_team')} scored {verdict.get('team_trust_score')}). "
                f"{verdict['reason']}. Proceeding."
            ),
        )

    # NO-GO. The suggestion names the team to talk to, not a substitute dataset:
    # a churn table has no equivalent in another domain, so offering one would be
    # advice nobody can act on.
    board = trustboard_client.call_tool("get_team_leaderboard")
    teams = board if isinstance(board, list) else [board]
    best_team = teams[0]["name"] if teams else None

    return Decision(
        task=task,
        dataset_urn=dataset_urn,
        allowed=False,
        reason=(
            f"Refusing to use this dataset: {verdict['reason']}. "
            "Using untrusted data would propagate quality issues downstream."
        ),
        alternative=(
            f"Escalate to the owning team. '{best_team}' leads the league this week "
            "and its datasets clear the bar."
            if best_team
            else None
        ),
    )


def _find_dataset_by_tier(graph, tier: str) -> str | None:
    """Finds a dataset tagged with a given tier (for the demo)."""
    q = (
        'query s($tag: String!) { search(input: {type: DATASET, query: "*", '
        'orFilters: [{and: [{field: "tags", values: [$tag]}]}], start: 0, count: 1}) '
        "{ searchResults { entity { urn } } } }"
    )
    try:
        res = execute_graphql_retry(graph, q, variables={"tag": f"urn:li:tag:trust.{tier}"})
        results = res["search"]["searchResults"]
        return results[0]["entity"]["urn"] if results else None
    except Exception:  # noqa: BLE001
        return None


def _print_decision(d: Decision) -> None:
    mark = "GO " if d.allowed else "NO-GO"
    print(f"\n[{mark}] task: {d.task}")
    print(f"        dataset: {d.dataset_urn.split(',')[1] if ',' in d.dataset_urn else d.dataset_urn}")
    print(f"        reason: {d.reason}")
    if d.alternative:
        print(f"        suggestion: {d.alternative}")


def _demo() -> None:
    graph = get_graph()
    print("Gatekeeper agent: reads the Trust Score from DataHub before using data.")

    gold = _find_dataset_by_tier(graph, "gold")
    risky = _find_dataset_by_tier(graph, "at-risk") or _find_dataset_by_tier(graph, "bronze")

    if gold:
        _print_decision(evaluate(gold, "Build the executive revenue dashboard", graph=graph))
    if risky:
        _print_decision(evaluate(risky, "Train the churn prediction model", graph=graph))


if __name__ == "__main__":
    _demo()
