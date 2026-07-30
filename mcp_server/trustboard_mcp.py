"""TrustBoard MCP server: exposes the Trust Score to the agent ecosystem.

TrustBoard keeps the score out of a private database. It writes it to the
DataHub graph and publishes it as MCP tools any other agent can consume before
acting, so an agent can ask whether a dataset is trustworthy without knowing
that TrustBoard exists.

Run (stdio):
    python -m mcp_server.trustboard_mcp

Register in an MCP client (for example Claude Code):
    claude mcp add trustboard -- <python> -m mcp_server.trustboard_mcp

Note: this module deliberately does NOT use `from __future__ import
annotations`. FastMCP inspects the real annotation objects when it registers a
tool, and postponed evaluation would hand it plain strings, which fails with
"issubclass() arg 1 must be a class".
"""
from typing import Literal

from mcp.server.fastmcp import FastMCP

# typing_extensions, not typing. Pydantic refuses `typing.TypedDict` on Python
# below 3.12, and FastMCP builds the tool schemas through pydantic, so on the
# 3.11 this project advertises the import raised PydanticUserError and the whole
# server died before it could serve anything. It worked locally on 3.12 and was
# broken everywhere else, which is the definition of a bug you only find by
# running what you ship.
from typing_extensions import TypedDict

from agents import trust_lookup

mcp = FastMCP("trustboard")

# The return shapes, declared rather than described.
#
# These tools were annotated `-> dict`, which FastMCP cannot turn into an
# outputSchema, so the contract this whole project rests on existed only as
# English in a docstring. A foreign agent had no machine-readable way to learn
# that `status` has three values, that `trust_score` is null on an asset we could
# not measure, or that `found` is the key to check first. Prose is what a model
# reads to choose WHICH tool to call; the schema is what it needs to use the
# answer without guessing. The nullable fields say so in the type, because the
# lookup layer returns an explicit None for anything it could not fill and a
# caller has to handle that either way.


class TrustInfo(TypedDict, total=False):
    """What TrustBoard knows about one asset. Check `found` before anything else."""

    urn: str
    found: bool
    kind: Literal["dataset", "domain"] | None
    name: str | None
    trust_score: float | None   # null when the asset is unrated
    trust_tier: Literal["gold", "silver", "bronze", "at-risk", "unrated"] | None
    coverage: float | None      # 0-1, share of the scoring weight backed by a real signal
    score_version: str | None   # scores from different versions are not comparable
    owning_team: str | None     # datasets only
    team_trust_score: float | None
    error: str | None           # only when the URN is an entity type we do not score


class Policy(TypedDict):
    min_tier: str
    on_unrated: str


class Verdict(TypedDict, total=False):
    """A gate decision. Read `status` before `trustworthy`.

    "rated" means we measured it and applied the policy. "unrated" means nobody
    has attached enough signal to judge it, which is a gap in the catalog and not
    evidence the data is bad. "not_found" means it is not in DataHub.
    """

    urn: str
    trustworthy: bool
    status: Literal["rated", "unrated", "not_found"]
    reason: str
    kind: Literal["dataset", "domain"] | None
    name: str | None
    found: bool
    trust_tier: str | None
    trust_score: float | None
    coverage: float | None
    score_version: str | None
    owning_team: str | None
    team_trust_score: float | None
    policy: Policy


class TeamScore(TypedDict, total=False):
    """One row of the weekly league, best first."""

    domain: str
    urn: str
    name: str | None
    trust_score: float | None
    trust_tier: str | None
    coverage: float | None
    score_version: str | None


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True})
def get_trust_score(urn: str) -> TrustInfo:
    """Get the TrustBoard trust score and tier for a DataHub domain or dataset URN.

    Returns the trust_score (0-100) and trust_tier that TrustBoard computed and
    wrote back to the DataHub graph, along with `coverage`, the share of the
    scoring weight backed by a signal that was actually present, and
    `score_version`, the scoring model that produced it. Tiers are gold (80+),
    silver (60-79), bronze (40-59), at-risk (below 40) and unrated, which means
    coverage was too low to judge and is not a bad grade. A score at low
    coverage rests on little evidence, so read the two together. For a dataset,
    also returns the owning team and the team's score.
    """
    return trust_lookup.read_trust(urn)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True})
def is_trustworthy(
    urn: str,
    min_tier: Literal["gold", "silver", "bronze", "at-risk"] = "silver",
    on_unrated: Literal["block", "allow", "warn"] = "block",
) -> Verdict:
    """Policy gate: does this DataHub asset meet a minimum trust tier?

    Use this before consuming a dataset in a pipeline, query or model. min_tier
    is one of gold, silver, bronze, at-risk. on_unrated decides what happens to
    an asset TrustBoard could not score, and is one of block (the default),
    allow or warn.

    Returns trustworthy (bool), a human-readable reason, and `status`: 'rated'
    when the boolean reflects a real score, 'unrated' when TrustBoard has no
    judgement about the asset, 'not_found' when the asset is not in the graph.
    Do not read a false at status 'unrated' as evidence the data is bad; it means
    nobody has attached enough signal to it to tell. The response carries every
    input to the decision, including the policy applied, so the call can be
    logged and audited.
    """
    return trust_lookup.is_trustworthy(urn, min_tier=min_tier, on_unrated=on_unrated)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True})
def get_team_leaderboard() -> list[TeamScore]:
    """Get the current TrustBoard leaderboard: teams ranked by trust score."""
    return trust_lookup.leaderboard()


if __name__ == "__main__":
    mcp.run()
