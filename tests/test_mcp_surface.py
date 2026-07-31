"""Tests that spawn the real MCP server and call every tool it publishes.

Every other test in this suite stops at the Python function. That gap let two
defects reach the repo at once: `typing.TypedDict` instead of the
`typing_extensions` one pydantic demands below 3.12, which killed the server on
the Python version the README advertises, and two fields declared non-nullable
inside a `total=False` TypedDict, which made FastMCP emit a schema its own
responses violated so `get_trust_score` returned an error for every input,
including valid ones. Both were invisible to 84 passing tests because none of
them started the server.

These do. They talk to it over stdio against a stubbed graph, so they need no
DataHub and can run in CI, which is where the Python version differs from the
one this was written on.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# A graph with one scored dataset, one unrated, and nothing else. Injected into
# the server process by module path so the test needs no live GMS.
_STUB = ROOT / "tests" / "_stub_graph.py"

SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "mcp_server.trustboard_mcp"],
    cwd=str(ROOT),
    env={**os.environ, "TRUSTBOARD_STUB_GRAPH": str(_STUB)},
)

_SCORED = "urn:li:dataset:(urn:li:dataPlatform:dbt,scored,PROD)"
_UNRATED = "urn:li:dataset:(urn:li:dataPlatform:dbt,unrated,PROD)"
_MISSING = "urn:li:dataset:(urn:li:dataPlatform:dbt,missing,PROD)"


async def _call(tool: str, args: dict):
    async with stdio_client(SERVER) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await session.call_tool(tool, args)


async def _tools():
    async with stdio_client(SERVER) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return (await session.list_tools()).tools


def _run(coro):
    return asyncio.run(coro)


def test_the_server_publishes_everything_an_agent_needs_to_close_the_loop():
    """Discover, check, and write the refusal back, all over the protocol.

    The first three shipped alone, so a foreign agent could ask whether an asset
    was trustworthy and nothing else: it could not find candidates and could not
    record that it had declined one. The loop closed inside this repo rather than
    at the protocol boundary, which is the opposite of the point.
    """
    names = {t.name for t in _run(_tools())}

    assert names == {
        "get_trust_score", "is_trustworthy", "get_team_leaderboard",
        "find_datasets", "record_refusal",
    }


def test_every_tool_declares_an_output_schema():
    # Prose in a docstring tells a foreign model which tool to call. The schema is
    # what it needs to use the answer without guessing.
    for tool in _run(_tools()):
        assert tool.outputSchema is not None, f"{tool.name} publishes no output schema"


def test_the_tool_that_writes_says_so_and_the_rest_say_they_do_not():
    """A client that gates side effects behind human approval reads this flag.

    Marking the write read-only would have it slip through unprompted; marking
    the reads as writes would put a confirmation in front of every lookup and
    train the user to click through them.
    """
    by_name = {t.name: t for t in _run(_tools())}

    for name, tool in by_name.items():
        assert tool.annotations is not None, f"{name} has no annotations"

    assert by_name["record_refusal"].annotations.readOnlyHint is False
    for name in ("get_trust_score", "is_trustworthy", "get_team_leaderboard", "find_datasets"):
        assert by_name[name].annotations.readOnlyHint is True, f"{name} is not read-only"


def test_the_policy_arguments_declare_their_legal_values():
    gate = next(t for t in _run(_tools()) if t.name == "is_trustworthy")
    props = gate.inputSchema["properties"]

    assert "enum" in str(props["min_tier"]), "min_tier is a free string"
    assert "enum" in str(props["on_unrated"]), "on_unrated is a free string"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_trust_score", {"urn": _SCORED}),
        ("get_trust_score", {"urn": _UNRATED}),
        ("get_trust_score", {"urn": _MISSING}),
        ("get_trust_score", {"urn": "urn:li:corpuser:someone"}),
        ("is_trustworthy", {"urn": _SCORED}),
        ("is_trustworthy", {"urn": _UNRATED}),
        ("is_trustworthy", {"urn": _MISSING}),
        ("get_team_leaderboard", {}),
    ],
)
def test_no_tool_errors_on_a_case_it_is_meant_to_handle(tool, args):
    """The regression that shipped: a schema its own responses violated.

    An unknown asset and an unsupported entity type are answers, not failures, so
    they must come back as successful calls the caller can branch on.
    """
    result = _run(_call(tool, args))

    text = " ".join(getattr(b, "text", "") or "" for b in result.content)
    assert result.isError is False, f"{tool}{args} errored: {text[:200]}"


def test_an_invalid_argument_is_an_error_not_a_laxer_gate():
    # The one case that SHOULD error. A misspelled tier used to fall through to a
    # default, which hands a caller asking for gold a silver gate and no warning.
    result = _run(_call("is_trustworthy", {"urn": _SCORED, "min_tier": "platinum"}))

    assert result.isError is True
