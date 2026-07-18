"""Servidor MCP de TrustBoard: expone el Trust Score al ecosistema de agentes.

Este es el ANGULO KILLER del proyecto. TrustBoard no deja el score en una base
de datos privada: lo escribe al grafo de DataHub Y lo expone como herramientas
MCP que CUALQUIER otro agente puede consumir antes de actuar. Cierra el loop
"el proximo agente hereda el conocimiento": un agente pregunta si un dataset es
confiable, sin saber siquiera que TrustBoard existe.

Ejecutar (stdio):
    .venv/Scripts/python -m mcp_server.trustboard_mcp

Registrar en un cliente MCP (p.ej. Claude Code):
    claude mcp add trustboard -- <python> -m mcp_server.trustboard_mcp
"""
from __future__ import annotations

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
