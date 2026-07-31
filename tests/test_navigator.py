"""Tests for the Navigator's loop, without spending a token.

The model is stubbed, so what these check is the harness around it: that a tool
call reaches the right function, that a refusal reaches the graph with the task
the caller actually asked for rather than one the model invented, that a broken
tool is reported back to the model instead of crashing the run, and that a
missing key degrades rather than dies.

What they deliberately do not test is the model's judgement. Asserting that a
particular prompt picks a particular dataset would pin the one thing that is
supposed to be free to change, and it would pass or fail for reasons that have
nothing to do with this code.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import navigator
from agents.navigator import ModelUnavailable, Plan, navigate

_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,orders,PROD)"


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _use(name, args, call_id="c1"):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=call_id)


class FakeModel:
    """Replays a scripted sequence of assistant turns and records what it saw."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        # Snapshot the message list. It is passed by reference and keeps growing
        # after the call returns, so storing it directly would have every
        # recorded turn show the final state of the conversation.
        self.seen.append({**kwargs, "messages": list(kwargs["messages"])})
        return SimpleNamespace(content=self.turns.pop(0))


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(
        navigator, "get_settings",
        lambda: SimpleNamespace(anthropic_api_key="test-key", trustboard_agent_model="test-model"),
    )


def test_no_key_degrades_instead_of_dying(monkeypatch):
    monkeypatch.setattr(
        navigator, "get_settings",
        lambda: SimpleNamespace(anthropic_api_key="", trustboard_agent_model="m"),
    )

    with pytest.raises(ModelUnavailable, match="everything else"):
        navigate("anything")


def test_a_search_reaches_the_catalog_and_the_result_goes_back_to_the_model(with_key, monkeypatch):
    calls = []
    monkeypatch.setattr(navigator.asset_search, "find_datasets",
                        lambda q, limit=8, graph=None: calls.append(q) or [{"urn": _URN, "name": "orders"}])
    model = FakeModel([
        [_use("find_datasets", {"query": "orders"})],
        [_use("submit_plan", {"chosen_urn": _URN, "summary": "picked orders"}, "c2")],
    ])
    monkeypatch.setattr(navigator, "Anthropic", lambda api_key: model)

    plan = navigate("build something")

    assert calls == ["orders"]
    assert plan.chosen_urn == _URN
    # The tool result has to reach the model, or the loop is a monologue.
    last = model.seen[-1]["messages"][-1]
    assert last["role"] == "user"
    assert "orders" in str(last["content"])


def test_the_trust_check_goes_over_mcp_not_through_an_import(with_key, monkeypatch):
    """The Navigator must learn trust from the graph, like any foreign agent."""
    seen = {}
    monkeypatch.setattr(navigator.trustboard_client, "call_tool",
                        lambda tool, **kw: seen.update({"tool": tool, **kw}) or
                        {"status": "rated", "trustworthy": True, "trust_tier": "gold"})
    model = FakeModel([
        [_use("check_trust", {"urn": _URN})],
        [_use("submit_plan", {"chosen_urn": _URN, "summary": "ok"}, "c2")],
    ])
    monkeypatch.setattr(navigator, "Anthropic", lambda api_key: model)

    navigate("build something")

    assert seen["tool"] == "is_trustworthy"
    assert seen["urn"] == _URN


def test_a_refusal_is_filed_under_the_task_the_caller_asked_for(with_key, monkeypatch):
    """Not under one the model made up.

    The task is the caller's, so it is passed from the outer call rather than
    taken from tool input. A model that hallucinated a different task would
    otherwise write that hallucination onto somebody's dataset.
    """
    recorded = {}

    def fake_record(urn, task, reason, graph=None):
        recorded.update(urn=urn, task=task, reason=reason)
        return {"recorded": True, "asset": "orders"}

    monkeypatch.setattr(navigator.asset_search, "record_refusal", fake_record)
    model = FakeModel([
        [_use("record_refusal", {"urn": _URN, "reason": "at-risk"})],
        [_use("submit_plan", {"chosen_urn": None, "summary": "nothing usable"}, "c2")],
    ])
    monkeypatch.setattr(navigator, "Anthropic", lambda api_key: model)

    plan = navigate("Train the churn model")

    assert recorded["task"] == "Train the churn model"
    assert recorded["urn"] == _URN
    assert plan.refusals_recorded == 1
    assert plan.chosen_urn is None


def test_a_duplicate_refusal_is_not_counted_as_written(with_key, monkeypatch):
    monkeypatch.setattr(navigator.asset_search, "record_refusal",
                        lambda *a, **k: {"recorded": False, "reason": "already open"})
    model = FakeModel([
        [_use("record_refusal", {"urn": _URN, "reason": "at-risk"})],
        [_use("submit_plan", {"summary": "done"}, "c2")],
    ])
    monkeypatch.setattr(navigator, "Anthropic", lambda api_key: model)

    assert navigate("t").refusals_recorded == 0


def test_a_failing_tool_is_reported_to_the_model_rather_than_crashing(with_key, monkeypatch):
    """The agent gets to decide what to do about it, which is the point of one."""
    def boom(*a, **k):
        raise RuntimeError("GMS is down")

    monkeypatch.setattr(navigator.asset_search, "find_datasets", boom)
    model = FakeModel([
        [_use("find_datasets", {"query": "orders"})],
        [_use("submit_plan", {"summary": "could not search"}, "c2")],
    ])
    monkeypatch.setattr(navigator, "Anthropic", lambda api_key: model)

    plan = navigate("t")

    assert "GMS is down" in str(model.seen[-1]["messages"][-1]["content"])
    assert any("failed" in s.result for s in plan.steps)


def test_the_run_is_bounded(with_key, monkeypatch):
    # A model that never submits must not loop forever against a paid API.
    monkeypatch.setattr(navigator.asset_search, "find_datasets", lambda *a, **k: [])
    model = FakeModel([[_use("find_datasets", {"query": "x"}, f"c{i}")]
                       for i in range(navigator.MAX_TURNS + 5)])
    monkeypatch.setattr(navigator, "Anthropic", lambda api_key: model)

    plan = navigate("t")

    assert isinstance(plan, Plan)
    assert len(model.seen) <= navigator.MAX_TURNS


def test_every_step_is_recorded_for_the_audit_trail(with_key, monkeypatch):
    monkeypatch.setattr(navigator.asset_search, "find_datasets", lambda *a, **k: [{"urn": _URN}])
    monkeypatch.setattr(navigator.trustboard_client, "call_tool",
                        lambda tool, **kw: {"status": "rated", "trustworthy": True, "trust_tier": "gold"})
    model = FakeModel([
        [_text("looking"), _use("find_datasets", {"query": "orders"})],
        [_use("check_trust", {"urn": _URN}, "c2")],
        [_use("submit_plan", {"chosen_urn": _URN, "summary": "done"}, "c3")],
    ])
    monkeypatch.setattr(navigator, "Anthropic", lambda api_key: model)

    lines = navigate("t").audit_lines()

    assert any("find_datasets" in line for line in lines)
    assert any("check_trust" in line for line in lines)
    assert any("submit_plan" in line for line in lines)
