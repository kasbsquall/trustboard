"""Second agent: the Gatekeeper.

Stands in for "the next agent" in the ecosystem: before using a dataset for a
task (building a dashboard, training a model, running a query), it reads the
Trust Score that TrustBoard wrote to the graph and decides GO/NO-GO. If the
dataset is not trustworthy, it refuses to use it.

It reaches that score over MCP, spawning the TrustBoard MCP server as its own
process and calling `is_trustworthy`. Reading `agents.trust_lookup` in-process
would return the same answer in less code and would prove nothing, so the only
TrustBoard module this file imports is the MCP transport itself. The verdict
crosses a process boundary. Nothing else is shared: no database, no run, no
in-process call.

This closes the loop: the Auditor computes, the Scribe writes to the graph, and
a different agent picks it up from there.

Demo:
    python -m scripts.gatekeeper_demo
"""
from __future__ import annotations

from dataclasses import dataclass

from mcp_client import trustboard_client


@dataclass(frozen=True)
class Decision:
    task: str
    dataset_urn: str
    allowed: bool
    reason: str
    alternative: str | None = None


def evaluate(dataset_urn: str, task: str, min_tier: str = "silver") -> Decision:
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
            f"Escalate to the team that owns this dataset. For reference, "
            f"'{best_team}' leads the league this week."
            if best_team
            else None
        ),
    )
