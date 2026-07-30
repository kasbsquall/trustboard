"""Tests for the MCP boundary and the gate's behaviour when it cannot answer.

This file exists because the flagship path crashed. `trustboard_client` never
checked `isError` on the tool result, so a tool-level failure arrived as
`{"raw": "Error executing tool ..."}` and `gatekeeper.evaluate` indexed
`verdict["trustworthy"]` on it, raising a bare KeyError from inside the decision
logic. The server had been carefully built to hand an agent something actionable
and the client discarded it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import gatekeeper
from mcp_client import trustboard_client

_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,orders,PROD)"


class _Block:
    def __init__(self, text):
        self.text = text


class _Result:
    def __init__(self, blocks, is_error=False):
        self.content = [_Block(b) for b in blocks]
        self.isError = is_error


def test_a_tool_error_raises_instead_of_becoming_a_dict():
    result = _Result(["Error executing tool is_trustworthy: Cannot reach DataHub GMS"], is_error=True)

    with pytest.raises(trustboard_client.ToolError, match="Cannot reach DataHub GMS"):
        trustboard_client._payload(result)


def test_a_tool_error_with_no_message_still_raises():
    with pytest.raises(trustboard_client.ToolError):
        trustboard_client._payload(_Result([], is_error=True))


def test_a_list_result_keeps_every_item():
    # Reading only the first block would truncate a leaderboard to its winner.
    result = _Result(['{"name": "A"}', '{"name": "B"}', '{"name": "C"}'])

    assert trustboard_client._payload(result) == [{"name": "A"}, {"name": "B"}, {"name": "C"}]


def test_the_gate_refuses_and_explains_when_it_cannot_be_consulted(monkeypatch):
    def boom(tool, **args):
        raise trustboard_client.ToolError("Cannot reach DataHub GMS at http://localhost:8080")

    monkeypatch.setattr(gatekeeper.trustboard_client, "call_tool", boom)

    d = gatekeeper.evaluate(_URN, "Build the revenue dashboard")

    assert d.allowed is False
    assert d.status == "unavailable"
    assert "Cannot reach DataHub GMS" in d.reason
    assert d.alternative  # tells the caller what to do rather than dying
    d.audit_line()  # must not raise on the degraded path either


def test_a_below_bar_verdict_names_the_owning_team(monkeypatch):
    calls = []

    def fake(tool, **args):
        calls.append(tool)
        if tool == "is_trustworthy":
            return {
                "trustworthy": False, "status": "rated", "trust_tier": "at-risk",
                "trust_score": 21.0, "coverage": 1.0, "score_version": "2.1",
                "owning_team": "Marketing", "reason": "tier 'at-risk' is below minimum 'silver'",
                "policy": {"min_tier": "silver", "on_unrated": "block"},
            }
        return [{"name": "Data Platform Team", "trust_score": 84.0}]

    monkeypatch.setattr(gatekeeper.trustboard_client, "call_tool", fake)

    d = gatekeeper.evaluate(_URN, "Train the churn model")

    assert d.allowed is False
    assert d.status == "rated"
    assert "Marketing" in d.alternative
    assert "at-risk" in d.audit_line()
    assert "min_tier:silver" in d.audit_line()


def test_an_unrated_refusal_does_not_blame_the_data(monkeypatch):
    monkeypatch.setattr(
        gatekeeper.trustboard_client, "call_tool",
        lambda tool, **a: {
            "trustworthy": False, "status": "unrated", "trust_tier": "unrated",
            "coverage": 0.65, "reason": "TrustBoard could not judge this asset.",
            "policy": {"min_tier": "silver", "on_unrated": "block"},
        },
    )

    d = gatekeeper.evaluate(_URN, "Join a table from a ticket")

    assert d.allowed is False
    assert d.status == "unrated"
    assert "gap in the catalog" in d.reason
    assert "quality check" in d.alternative
