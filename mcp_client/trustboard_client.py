"""MCP client for the TrustBoard server.

The Gatekeeper uses this to reach the Trust Score the way any other agent in the
ecosystem would: over the Model Context Protocol, talking to a server process it
spawns, with no Python import of TrustBoard's own modules and no shared
database. Calling `agents.trust_lookup` in-process would give the same answer,
but it would prove nothing about interoperability, which is the whole claim.

The server is launched over stdio, exactly as an MCP client config would:

    claude mcp add trustboard -- <python> -m mcp_server.trustboard_mcp
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent

SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "mcp_server.trustboard_mcp"],
    cwd=str(ROOT),
)


@asynccontextmanager
async def _session():
    async with stdio_client(SERVER) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


class ToolError(Exception):
    """The MCP server reported the tool call as failed.

    Raised rather than returned. MCP signals failure through `isError` on the
    result, with the message in the content blocks, and the previous version of
    this module never looked at that flag: an unreachable DataHub or a rejected
    argument arrived as `{"raw": "Error executing tool ..."}`, and the first
    caller to index a field it expected got a bare KeyError from inside its own
    decision logic. The server was carefully built to hand an agent something
    actionable, and the client threw it away.
    """


def _text_of(result) -> str:
    return " ".join(
        t for t in (getattr(b, "text", None) for b in result.content) if t
    ).strip()


def _payload(result):
    """Parses a tool result out of FastMCP's content blocks.

    A tool returning a list arrives as one block per item, so reading only the
    first block would silently truncate a leaderboard to its winner.
    """
    if getattr(result, "isError", False):
        raise ToolError(_text_of(result) or "the tool reported an error with no message")

    items = []
    for block in result.content:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            items.append(json.loads(text))
        except json.JSONDecodeError:
            items.append({"raw": text})
    if not items:
        return {}
    return items[0] if len(items) == 1 else items


async def _call(tool: str, args: dict):
    """Returns the raw tool result. Parsing happens in the sync caller.

    Deliberately not parsed here. Raising inside the session's task group gets
    the exception wrapped in an anyio ExceptionGroup on the way out, so a caller
    writing `except ToolError` catches nothing and sees a BaseExceptionGroup
    instead. The error has to leave the async machinery before it is raised.
    """
    async with _session() as session:
        return await session.call_tool(tool, args)


async def _tool_names() -> list[str]:
    async with _session() as session:
        return [t.name for t in (await session.list_tools()).tools]


def call_tool(tool: str, **args) -> dict:
    """Calls one TrustBoard MCP tool and returns its parsed result.

    Raises ToolError if the server reported the call as failed.
    """
    return _payload(asyncio.run(_call(tool, args)))


def list_tools() -> list[str]:
    """Names of the tools the TrustBoard MCP server publishes."""
    return asyncio.run(_tool_names())


if __name__ == "__main__":
    print("TrustBoard MCP server tools:", ", ".join(list_tools()))
