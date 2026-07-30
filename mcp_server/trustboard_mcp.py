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
from mcp.server.fastmcp import FastMCP

from agents import trust_lookup

mcp = FastMCP("trustboard")


@mcp.tool()
def get_trust_score(urn: str) -> dict:
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


@mcp.tool()
def is_trustworthy(urn: str, min_tier: str = "silver", on_unrated: str = "block") -> dict:
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


@mcp.tool()
def get_team_leaderboard() -> list[dict]:
    """Get the current TrustBoard leaderboard: teams ranked by trust score."""
    return trust_lookup.leaderboard()


if __name__ == "__main__":
    mcp.run()
