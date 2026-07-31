"""Finding candidate datasets, and recording what an agent decided about one.

These exist because the Navigator needs to do two things the rest of TrustBoard
never had to. It has to discover assets it was not handed, since an agent given a
task in English does not start with a URN, and it has to leave its conclusion
somewhere the next reader inherits it. Both go through DataHub rather than through
any TrustBoard state, which is the point: what the Navigator learns, it learns
from the graph, and what it concludes, it returns to the graph.
"""
from __future__ import annotations

from mcp_client.datahub_connection import execute_graphql_retry, get_graph

_SEARCH = """
query s($q: String!, $count: Int!) {
  search(input: {type: DATASET, query: $q, start: 0, count: $count}) {
    total
    searchResults { entity {
      urn
      ... on Dataset {
        name
        properties { description }
        domain { domain { properties { name } } }
      }
    } }
  }
}
"""

_RAISE = """
mutation r($urn: String!, $title: String!, $desc: String!) {
  raiseIncident(input: {resourceUrn: $urn, type: OPERATIONAL, title: $title, description: $desc})
}
"""

_QUERY_INCIDENTS = """
query i($urn: String!) {
  entity(urn: $urn) { ... on Dataset {
    incidents(start: 0, count: 50) { incidents { urn title status { state } } }
  } }
}
"""

# The Navigator's own incidents are prefixed distinctly from the Scribe's, so a
# reader can tell "an agent refused to build on this" from "the weekly audit
# scored this below the line", and so the dedup guard on one never closes the
# other's tickets.
TITLE_PREFIX = "TrustBoard: an agent declined to use"


def find_datasets(query: str, limit: int = 8, graph=None) -> list[dict]:
    """Datasets matching a free-text query, with their team and description.

    The description travels with the result because the caller is choosing
    between assets by what they contain, not by URN. A search that returns bare
    identifiers forces a second round trip per candidate to learn anything.
    """
    graph = graph or get_graph()
    res = execute_graphql_retry(graph, _SEARCH, variables={"q": query, "count": limit})["search"]
    out = []
    for r in res.get("searchResults") or []:
        e = r["entity"]
        domain = ((e.get("domain") or {}).get("domain") or {}).get("properties") or {}
        out.append({
            "urn": e["urn"],
            "name": e.get("name"),
            "description": ((e.get("properties") or {}).get("description") or "")[:200] or None,
            "owning_team": domain.get("name"),
        })
    return out


def _active_navigator_incidents(graph, dataset_urn: str) -> list[str]:
    res = execute_graphql_retry(graph, _QUERY_INCIDENTS, variables={"urn": dataset_urn})
    incidents = (((res.get("entity") or {}).get("incidents")) or {}).get("incidents") or []
    return [
        i["urn"] for i in incidents
        if (i.get("title") or "").startswith(TITLE_PREFIX)
        and ((i.get("status") or {}).get("state") == "ACTIVE")
    ]


def record_refusal(dataset_urn: str, task: str, reason: str, graph=None) -> dict:
    """Writes an agent's refusal back onto the dataset as an incident.

    This is the half of the loop that was missing. TrustBoard wrote a score, a
    separate agent read it and refused to build on the data, and then the refusal
    evaporated into a log line: nothing downstream ever learned that anyone had
    declined. Recording it means the owning team opens their asset and finds
    "an agent declined to use this, for this task, for this reason", which is a
    far more legible signal than a number, and it means the NEXT agent inherits
    the fact that this asset is blocking real work.

    Deduplicated the same way the Scribe's incidents are, because an agent
    consulting the gate on a schedule would otherwise file the same refusal every
    run until somebody muted the channel.
    """
    graph = graph or get_graph()
    existing = _active_navigator_incidents(graph, dataset_urn)
    if existing:
        return {"recorded": False, "reason": "an open refusal is already on this asset",
                "incident_urn": existing[0]}

    short = dataset_urn.split(",")[1] if "," in dataset_urn else dataset_urn
    execute_graphql_retry(graph, _RAISE, variables={
        "urn": dataset_urn,
        "title": f"{TITLE_PREFIX} {short}",
        "desc": (
            f"An automated agent was asked to: {task}\n\n"
            f"It consulted the TrustBoard score for this dataset over MCP and declined "
            f"to use it. Reason given:\n\n{reason}\n\n"
            "This is real work that did not happen because of the state of this data. "
            "Raising the dataset's trust score clears it."
        ),
    })
    return {"recorded": True, "asset": short}
