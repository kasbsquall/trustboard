"""Agent 5: the Navigator.

The first thing in this repository that actually reasons.

Everything else here is deterministic on purpose, and the README says so. The
Auditor computes, the Scribe writes, the Herald posts, and the Gatekeeper applies
a policy to one URN it was handed. All four are functions with role names, and
none of them decides anything a person did not decide first.

The Navigator is given a task in English and nothing else. No URN, no shortlist,
no expected answer. It has to work out what data the task needs, find candidates
in DataHub, ask TrustBoard about each one over MCP, and then make a call:
proceed, pick something else, or refuse and say why. Which datasets it looks at,
how many, in what order, and what it settles on are not written down anywhere in
this file. That is the difference between a pipeline with a policy check and an
agent, and it is the difference this hackathon is actually about.

It closes the loop, too. A refusal is written back onto the dataset as an
incident, so the team that owns the data finds out that an agent declined to
build on it and why. TrustBoard's score becomes context a second agent consumes,
and that agent's conclusion becomes context for whoever comes next:
graph to agent to graph.

Every call it makes goes over the MCP transport, including the searches and the
write-back. It imports no scoring code, no lookup module and no database, exactly
like the Gatekeeper, so what it knows about trust it learned from the graph rather
than from being in the same process as the thing that computed it. That matters
beyond tidiness: it means this agent is doing nothing another team's agent could
not do after one `claude mcp add`, which is the difference between a loop this
project closes for itself and one the ecosystem can close.

    python -m scripts.navigator_demo "Build the executive revenue dashboard"
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from anthropic import Anthropic, APIStatusError

from config import get_settings
from mcp_client import trustboard_client

DEFAULT_MODEL = "claude-sonnet-5"
MAX_TURNS = 12

_SYSTEM = """You are a data engineer's assistant with access to a data catalog.

You are given a task. Work out which dataset in the catalog the task needs, then
check whether that data can be trusted before committing to it.

How to work:
- Search for candidates. Your first search will often be wrong; the catalog names
  things the way its owners named them, not the way the task describes them. If a
  search returns nothing useful, try different words.
- Check the trust of any dataset you are seriously considering, before you settle
  on it. Never recommend a dataset you have not checked.
- A dataset can come back rated below the bar, or unrated, and these are
  different. Below the bar means somebody measured it and it is in poor shape.
  Unrated means nobody has attached enough signal to judge it, which is a gap in
  the catalog and not evidence the data is bad. Say which one you hit.
- If your best candidate fails the check, look for an alternative that serves the
  same task. Only give up if there genuinely isn't one.
- When you refuse a dataset that was a real candidate, record that refusal so the
  team that owns it finds out their data blocked a piece of work.

Finish by calling `submit_plan` exactly once. Be concrete and brief. Do not
recommend a dataset whose trust you did not verify."""

_TOOLS = [
    {
        "name": "find_datasets",
        "description": (
            "Search the DataHub catalog for datasets by free text. Matches names, "
            "descriptions and column names. Returns the URN, name, description and "
            "owning team of each match. Try several phrasings if the first returns "
            "nothing relevant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search, e.g. 'orders revenue'"},
                "limit": {"type": "integer", "description": "Max results, default 8"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_trust",
        "description": (
            "Ask TrustBoard whether a dataset is trustworthy enough to build on. "
            "Returns `status` as one of 'rated' (measured, and `trustworthy` says "
            "whether it clears the bar), 'unrated' (nobody has attached enough "
            "signal to judge it, which is NOT evidence the data is bad), or "
            "'not_found'. Also returns the trust score, the signal coverage behind "
            "it and the owning team. Call this before recommending anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "urn": {"type": "string", "description": "The dataset URN from find_datasets"},
                "min_tier": {
                    "type": "string",
                    "enum": ["gold", "silver", "bronze", "at-risk"],
                    "description": "Minimum acceptable tier, default silver",
                },
            },
            "required": ["urn"],
        },
    },
    {
        "name": "record_refusal",
        "description": (
            "Write a refusal back onto a dataset in DataHub as an incident, so the "
            "owning team learns that an agent declined to use their data for real "
            "work. Use this when you rejected a dataset that was a genuine "
            "candidate for the task. Do not use it for datasets you merely browsed "
            "past."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "urn": {"type": "string"},
                "reason": {"type": "string", "description": "Why you declined, in one or two sentences"},
            },
            "required": ["urn", "reason"],
        },
    },
    {
        "name": "submit_plan",
        "description": "Report your conclusion. Call exactly once, at the end.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chosen_urn": {
                    "type": ["string", "null"],
                    "description": "The dataset you settled on, or null if none was usable",
                },
                "summary": {"type": "string", "description": "What you decided and why, in 2-3 sentences"},
                "rejected": {
                    "type": "array",
                    "description": "Datasets you considered and turned down, with the reason",
                    "items": {
                        "type": "object",
                        "properties": {"urn": {"type": "string"}, "why": {"type": "string"}},
                    },
                },
            },
            "required": ["summary"],
        },
    },
]


@dataclass
class Step:
    """One thing the agent did, for the audit trail."""

    tool: str
    detail: str
    result: str


@dataclass
class Plan:
    task: str
    chosen_urn: str | None
    summary: str
    rejected: list[dict] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    refusals_recorded: int = 0

    def audit_lines(self) -> list[str]:
        return [f"{s.tool}: {s.detail} -> {s.result}" for s in self.steps]


class ModelUnavailable(Exception):
    """The model could not be reached: no key, no credit, or the API refused.

    A plain Exception so a caller can degrade rather than die, and deliberately
    not fatal at import: this is the only module in TrustBoard that needs a model,
    and the other four have to keep working on a machine that has no key, which
    is most machines this will be run on.

    It covers billing as well as configuration because those are the same problem
    from the caller's side. An empty balance arrived as a raw
    anthropic.BadRequestError and a twenty-line traceback out of the SDK's guts,
    which tells a reader nothing about what to do.
    """


def _run_tool(name: str, args: dict, graph, min_tier: str) -> tuple[object, str]:
    """Executes one tool call and returns (payload, one-line summary)."""
    if name == "find_datasets":
        found = trustboard_client.call_tool(
            "find_datasets", query=args["query"], limit=args.get("limit", 8)
        )
        found = found if isinstance(found, list) else [found] if found else []
        return found, f"{len(found)} match(es) for {args['query']!r}"

    if name == "check_trust":
        verdict = trustboard_client.call_tool(
            "is_trustworthy", urn=args["urn"], min_tier=args.get("min_tier", min_tier)
        )
        short = args["urn"].split(",")[1] if "," in args["urn"] else args["urn"]
        return verdict, (
            f"{short}: {verdict.get('status')}, "
            f"trustworthy={verdict.get('trustworthy')}, "
            f"tier={verdict.get('trust_tier')}"
        )

    if name == "record_refusal":
        # The task is not passed by the model. It is the one the caller actually
        # asked for, so a refusal cannot be filed under a task nobody requested.
        raise AssertionError("record_refusal is handled by the caller")

    raise ValueError(f"unknown tool {name}")


def navigate(task: str, min_tier: str = "silver", model: str | None = None, graph=None) -> Plan:
    """Works out which dataset a task needs, checks it, and decides.

    Raises ModelUnavailable when no API key is configured.
    """
    settings = get_settings()
    key = settings.anthropic_api_key
    if not key:
        raise ModelUnavailable(
            "The Navigator needs ANTHROPIC_API_KEY. It is the only part of "
            "TrustBoard that calls a model; everything else runs without one."
        )

    client = Anthropic(api_key=key)
    model = model or settings.trustboard_agent_model or DEFAULT_MODEL

    messages: list[dict] = [{"role": "user", "content": f"Task: {task}"}]
    plan = Plan(task=task, chosen_urn=None, summary="")

    for _ in range(MAX_TURNS):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=_SYSTEM,
                tools=_TOOLS,
                messages=messages,
            )
        except APIStatusError as err:
            detail = str(err)
            if "credit balance" in detail.lower():
                raise ModelUnavailable(
                    "The Anthropic account has no credit left, so the Navigator "
                    "cannot run. Everything else in TrustBoard works without it."
                ) from None
            raise ModelUnavailable(f"The model API refused the request: {detail[:200]}") from None
        messages.append({"role": "assistant", "content": response.content})

        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            plan.summary = plan.summary or "".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            break

        results = []
        for call in calls:
            if call.name == "submit_plan":
                plan.chosen_urn = call.input.get("chosen_urn")
                plan.summary = call.input.get("summary", "")
                plan.rejected = call.input.get("rejected") or []
                plan.steps.append(Step("submit_plan", "final answer", plan.summary[:80]))
                return plan

            if call.name == "record_refusal":
                # The task comes from the caller, not from the model. A model that
                # hallucinated a different task would otherwise write that
                # hallucination onto somebody's dataset.
                outcome = trustboard_client.call_tool(
                    "record_refusal", urn=call.input["urn"], task=task,
                    reason=call.input["reason"],
                )
                plan.refusals_recorded += int(bool(outcome.get("recorded")))
                summary = (
                    "written to the graph" if outcome.get("recorded")
                    else f"skipped, {outcome.get('reason')}"
                )
                plan.steps.append(Step("record_refusal", call.input["urn"].split(",")[-2:][0], summary))
                results.append({"type": "tool_result", "tool_use_id": call.id,
                                "content": json.dumps(outcome)})
                continue

            try:
                payload, summary = _run_tool(call.name, call.input, graph, min_tier)
            except Exception as err:  # noqa: BLE001 - the agent decides what to do about it
                payload, summary = {"error": str(err)}, f"failed: {type(err).__name__}"
            plan.steps.append(Step(call.name, str(call.input)[:70], summary))
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": json.dumps(payload, default=str)[:6000]})

        messages.append({"role": "user", "content": results})

    return plan
