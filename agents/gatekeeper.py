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

A refusal names which of three things happened, because they call for different
responses from whoever is on the other end. Data that scored below the bar is a
problem for the owning team. Data TrustBoard could not judge is a problem with
the catalog, and the honest thing is to say so instead of implying the data is
bad. An asset that is not in the graph at all is a problem with the request. The
full verdict travels on the Decision so the calling system can log a choice
somebody can audit later rather than a bare boolean.

Demo:
    python -m scripts.gatekeeper_demo
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mcp_client import trustboard_client


@dataclass(frozen=True)
class Decision:
    task: str
    dataset_urn: str
    allowed: bool
    reason: str
    alternative: str | None = None
    # rated | unrated | not_found | unavailable
    status: str = "rated"
    # Everything the policy saw, kept for the audit log.
    verdict: dict = field(default_factory=dict)

    def audit_line(self) -> str:
        """One line naming the decision and every input behind it."""
        policy = self.verdict.get("policy") or {}
        return (
            f"{'GO' if self.allowed else 'NO-GO'} status={self.status} "
            f"task={self.task!r} asset={self.dataset_urn} "
            f"tier={self.verdict.get('trust_tier')} "
            f"score={self.verdict.get('trust_score')} "
            f"coverage={self.verdict.get('coverage')} "
            f"model=v{self.verdict.get('score_version')} "
            f"policy=min_tier:{policy.get('min_tier')},on_unrated:{policy.get('on_unrated')}"
        )


def evaluate(
    dataset_urn: str,
    task: str,
    min_tier: str = "silver",
    on_unrated: str = "block",
) -> Decision:
    """Decides whether an agent may use a dataset based on its Trust Score.

    The verdict comes back over MCP. Nothing about TrustBoard is imported to get
    it beyond the transport itself.
    """
    try:
        verdict = trustboard_client.call_tool(
            "is_trustworthy", urn=dataset_urn, min_tier=min_tier, on_unrated=on_unrated
        )
    except trustboard_client.ToolError as err:
        # The gate could not be consulted, so nothing is allowed through. A
        # governance check whose answer to a broken dependency is a traceback is
        # not a check: the calling pipeline sees a crash it will be tempted to
        # retry past, instead of a refusal it has to handle.
        return Decision(
            task=task,
            dataset_urn=dataset_urn,
            allowed=False,
            reason=f"Could not consult TrustBoard, so nothing is approved: {err}",
            alternative=(
                "Fix the TrustBoard lookup and re-run. Until it answers, treat "
                "every asset as unverified."
            ),
            status="unavailable",
            verdict={"error": str(err), "policy": {"min_tier": min_tier, "on_unrated": on_unrated}},
        )

    status = verdict.get("status", "rated")

    if verdict["trustworthy"]:
        if status == "unrated":
            reason = (
                f"{verdict['reason']} Proceeding because the policy allows "
                "unrated assets, with no evidence either way about this data."
            )
        else:
            reason = (
                f"Dataset is '{verdict.get('trust_tier')}' at "
                f"{verdict.get('trust_score')}/100 with "
                f"{_pct(verdict.get('coverage'))} signal coverage "
                f"(team {verdict.get('owning_team')} scored "
                f"{verdict.get('team_trust_score')}). {verdict['reason']}. Proceeding."
            )
        return Decision(
            task=task,
            dataset_urn=dataset_urn,
            allowed=True,
            reason=reason,
            status=status,
            verdict=verdict,
        )

    if status == "not_found":
        return Decision(
            task=task,
            dataset_urn=dataset_urn,
            allowed=False,
            reason=f"Cannot evaluate this asset: {verdict['reason']}.",
            alternative="Check the URN, or ingest the asset into DataHub first.",
            status=status,
            verdict=verdict,
        )

    if status == "unrated":
        return Decision(
            task=task,
            dataset_urn=dataset_urn,
            allowed=False,
            reason=(
                f"Holding off: {verdict['reason']} This is a gap in the catalog "
                "rather than a finding about the data."
            ),
            alternative=(
                "Add a quality check, an owner or a freshness signal to this "
                "dataset and TrustBoard can score it on the next run."
            ),
            status=status,
            verdict=verdict,
        )

    # Rated below the bar. The suggestion names the team to talk to, not a
    # substitute dataset: a churn table has no equivalent in another domain, so
    # offering one would be advice nobody can act on.
    # Guarded like the first call. This one only enriches the suggestion, so a
    # failure here must not cost the caller the refusal it already earned: the
    # gate answered, and losing the answer because the leaderboard was
    # unreachable would turn a correct NO-GO into an exception.
    try:
        board = trustboard_client.call_tool("get_team_leaderboard")
        teams = board if isinstance(board, list) else [board]
        best_team = teams[0]["name"] if teams else None
    except trustboard_client.ToolError:
        best_team = None

    return Decision(
        task=task,
        dataset_urn=dataset_urn,
        allowed=False,
        reason=(
            f"Refusing to use this dataset: {verdict['reason']}. "
            "Using untrusted data would propagate quality issues downstream."
        ),
        alternative=(
            f"Escalate to {verdict.get('owning_team') or 'the team that owns this dataset'}. "
            f"For reference, '{best_team}' leads the league this week."
            if best_team
            else None
        ),
        status=status,
        verdict=verdict,
    )


def _pct(value) -> str:
    return f"{value:.0%}" if isinstance(value, (int, float)) else "unknown"
