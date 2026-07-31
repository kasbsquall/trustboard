"""Runs the Navigator against a task written in English.

    python -m scripts.navigator_demo "Build the executive revenue dashboard"
    python -m scripts.navigator_demo "Train a churn model on customer behaviour"

Nothing here tells it which datasets exist or which one to pick. The whole point
is that the answer is not in this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.navigator import ModelUnavailable, navigate
from mcp_client.datahub_connection import cli

_DEFAULT = "Build the executive revenue dashboard for the quarterly board pack"


def main() -> None:
    task = " ".join(sys.argv[1:]) or _DEFAULT
    print(f"Task: {task}\n")
    print("The Navigator has no URN and no shortlist. It searches, checks trust")
    print("over MCP, and decides.\n")

    try:
        plan = navigate(task)
    except ModelUnavailable as err:
        raise SystemExit(f"{err}") from None

    print("What it did:")
    for line in plan.audit_lines():
        print(f"  {line}")

    print(f"\nChose: {plan.chosen_urn or 'nothing usable'}")
    print(f"Why:   {plan.summary}")
    if plan.rejected:
        print("\nTurned down:")
        for r in plan.rejected:
            short = r.get("urn", "").split(",")[1] if "," in r.get("urn", "") else r.get("urn")
            print(f"  {short}: {r.get('why')}")
    if plan.refusals_recorded:
        print(f"\nWrote {plan.refusals_recorded} refusal(s) back to DataHub, so the")
        print("owning team sees that an agent declined to build on their data.")


if __name__ == "__main__":
    cli(main)
