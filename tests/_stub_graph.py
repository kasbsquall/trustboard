"""A tiny in-process stand-in for DataHubGraph, for the MCP surface tests.

Only answers the three shapes trust_lookup asks for. It exists so those tests can
run in CI, where there is no GMS, since the defects they cover are precisely the
ones that appear on a different machine from the one the code was written on.
"""
from __future__ import annotations

_SCORED = "scored"
_UNRATED = "unrated"

_PROPS = {
    "trustScore": 91.5,
    "trustTier": "gold",
    "trustCoverage": 1.0,
    "trustScoreVersion": "2.1",
}


def _sp(values: dict) -> dict:
    out = []
    for name, v in values.items():
        urn = f"urn:li:structuredProperty:io.trustboard.{name}"
        value = {"numberValue": v} if isinstance(v, (int, float)) else {"stringValue": v}
        out.append({"structuredProperty": {"urn": urn}, "values": [value]})
    return {"properties": out}


def execute_graphql(query: str, variables: dict | None = None):
    variables = variables or {}
    urn = variables.get("urn", "")

    if "domain(" in query:
        return {"domain": {"properties": {"name": "Data Platform Team"},
                           **{"structuredProperties": _sp(_PROPS)}}}

    if "dataset(" in query:
        if _SCORED in urn:
            return {"dataset": {"exists": True, "name": "scored", "tags": {"tags": []},
                                "domain": None, "structuredProperties": _sp(_PROPS)}}
        if _UNRATED in urn:
            return {"dataset": {"exists": True, "name": "unrated", "tags": {"tags": []},
                                "domain": None,
                                "structuredProperties": _sp({"trustTier": "unrated",
                                                             "trustCoverage": 0.65,
                                                             "trustScoreVersion": "2.1"})}}
        return {"dataset": {"exists": False}}

    if "search(" in query:
        return {"search": {"total": 1, "searchResults": [
            {"entity": {"urn": "urn:li:domain:team", "properties": {"name": "Data Platform Team"},
                        "structuredProperties": _sp(_PROPS)}}
        ]}}

    return {}


class StubGraph:
    execute_graphql = staticmethod(execute_graphql)

    def test_connection(self):
        return True
