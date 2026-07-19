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

    Returns the trust_score (0-100) and trust_tier (gold/silver/bronze/at-risk)
    that TrustBoard computed and wrote back to the DataHub graph. For a dataset,
    also returns the owning team and the team's score.
    """
    return trust_lookup.read_trust(urn)


@mcp.tool()
def is_trustworthy(urn: str, min_tier: str = "silver") -> dict:
    """Policy gate: does this DataHub asset meet a minimum trust tier?

    Use this before consuming a dataset in a pipeline, query or model. min_tier
    is one of gold, silver, bronze, at-risk. Returns trustworthy (bool) and a
    human-readable reason.
    """
    return trust_lookup.is_trustworthy(urn, min_tier=min_tier)


@mcp.tool()
def get_team_leaderboard() -> list[dict]:
    """Get the current TrustBoard leaderboard: teams ranked by trust score."""
    return trust_lookup.leaderboard()


if __name__ == "__main__":
    mcp.run()
