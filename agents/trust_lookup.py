"""Reading the Trust Score back from the DataHub graph.

Reads what the Scribe wrote back (domain-level structured property, dataset-level
tier tag). This is the foundation of the KILLER ANGLE: the MCP server and the
Gatekeeper agent consume these functions so that the trust knowledge TrustBoard
produced is inherited by other agents.
"""
from __future__ import annotations

from mcp_client.datahub_connection import execute_graphql_retry, get_graph

PROP_SCORE = "urn:li:structuredProperty:io.trustboard.trustScore"
PROP_TIER = "urn:li:structuredProperty:io.trustboard.trustTier"

_TIER_RANK = {"at-risk": 0, "bronze": 1, "silver": 2, "gold": 3}

_DOMAIN_SP = """
query d($urn: String!) {
  domain(urn: $urn) {
    properties { name }
    structuredProperties { properties {
      structuredProperty { urn }
      values { ... on NumberValue { numberValue } ... on StringValue { stringValue } }
    } }
  }
}
"""

_DATASET_TRUST = """
query ds($urn: String!) {
  dataset(urn: $urn) {
    name
    tags { tags { tag { urn } } }
    domain { domain { urn properties { name } } }
  }
}
"""

_LEADERBOARD = """
{ search(input: {type: DOMAIN, query: "*", start: 0, count: 100}) {
    searchResults { entity { urn ... on Domain {
      properties { name }
      structuredProperties { properties {
        structuredProperty { urn }
        values { ... on NumberValue { numberValue } ... on StringValue { stringValue } }
      } }
    } } }
} }
"""


def _extract_sp(structured_properties: dict | None) -> tuple[float | None, str | None]:
    if not structured_properties:
        return None, None
    score = tier = None
    for p in structured_properties.get("properties", []):
        purn = p["structuredProperty"]["urn"]
        values = p.get("values") or []
        if not values:
            continue
        if purn == PROP_SCORE and "numberValue" in values[0]:
            score = round(values[0]["numberValue"], 2)  # clean up the float precision
        elif purn == PROP_TIER and "stringValue" in values[0]:
            tier = values[0]["stringValue"]
    return score, tier


def read_domain_trust(urn: str, graph=None) -> dict:
    """Trust Score of a domain (team), read from its structured property."""
    graph = graph or get_graph()
    dom = execute_graphql_retry(graph, _DOMAIN_SP, variables={"urn": urn}).get("domain")
    if not dom:
        return {"urn": urn, "found": False}
    score, tier = _extract_sp(dom.get("structuredProperties"))
    return {
        "urn": urn,
        "kind": "domain",
        "name": (dom.get("properties") or {}).get("name"),
        "trust_score": score,
        "trust_tier": tier,
        "found": score is not None,
    }


def read_dataset_trust(urn: str, graph=None) -> dict:
    """Dataset trust: tier from its tag plus the score of the owning domain."""
    graph = graph or get_graph()
    ds = execute_graphql_retry(graph, _DATASET_TRUST, variables={"urn": urn}).get("dataset")
    if not ds:
        return {"urn": urn, "found": False}

    tier = None
    for t in ((ds.get("tags") or {}).get("tags") or []):
        tag_urn = t["tag"]["urn"]
        if tag_urn.startswith("urn:li:tag:trust."):
            tier = tag_urn.rsplit(".", 1)[-1]
            break

    domain_block = (ds.get("domain") or {}).get("domain") or {}
    domain_urn = domain_block.get("urn")
    domain_trust = read_domain_trust(domain_urn, graph=graph) if domain_urn else {}

    return {
        "urn": urn,
        "kind": "dataset",
        "name": ds.get("name"),
        "trust_tier": tier,
        "owning_team": domain_trust.get("name"),
        "team_trust_score": domain_trust.get("trust_score"),
        "found": tier is not None,
    }


def read_trust(urn: str, graph=None) -> dict:
    """Dispatches to domain or dataset depending on the urn type."""
    if urn.startswith("urn:li:domain:"):
        return read_domain_trust(urn, graph=graph)
    if urn.startswith("urn:li:dataset:"):
        return read_dataset_trust(urn, graph=graph)
    return {"urn": urn, "found": False, "error": "unsupported entity type"}


def is_trustworthy(urn: str, min_tier: str = "silver", graph=None) -> dict:
    """GO/NO-GO policy: does the asset reach the minimum trust tier?"""
    info = read_trust(urn, graph=graph)
    tier = info.get("trust_tier")
    if tier is None:
        return {"urn": urn, "trustworthy": False, "reason": "no TrustBoard score found", **info}
    ok = _TIER_RANK.get(tier, 0) >= _TIER_RANK.get(min_tier, 2)
    reason = (
        f"tier '{tier}' meets minimum '{min_tier}'"
        if ok
        else f"tier '{tier}' is below minimum '{min_tier}'"
    )
    return {"urn": urn, "trustworthy": ok, "reason": reason, **info}


def leaderboard(graph=None) -> list[dict]:
    """Team ranking by Trust Score, read from the graph."""
    graph = graph or get_graph()
    results = execute_graphql_retry(graph, _LEADERBOARD)["search"]["searchResults"]
    teams = []
    for r in results:
        e = r["entity"]
        score, tier = _extract_sp(e.get("structuredProperties"))
        if score is not None:
            teams.append(
                {"name": (e.get("properties") or {}).get("name"), "trust_score": score, "trust_tier": tier}
            )
    teams.sort(key=lambda t: t["trust_score"], reverse=True)
    return teams
