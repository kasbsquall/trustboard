"""Agent 3: The Herald.

Builds the weekly ranking by comparing against the previous week and publishes
it to Slack in scoreboard format: podium, "team of the week" and a mention of
the biggest improver. The gamification is the social hook that gets teams to
feed the graph; it builds on the real work already done by the Auditor and the
Scribe.

With no SLACK_WEBHOOK_URL configured, it prints the payload (useful for
examples/).

Usage:
    .venv/Scripts/python -m agents.herald
"""
from __future__ import annotations

import json

import requests

from agents import trust_lookup
from config import get_settings

_MEDALS = {0: "1st", 1: "2nd", 2: "3rd"}


def _delta_label(name: str, score: float, previous: dict[str, float] | None) -> str:
    if not previous or name not in previous:
        return "new"
    diff = score - previous[name]
    if abs(diff) < 0.05:
        return "steady"
    arrow = "up" if diff > 0 else "down"
    return f"{arrow} {abs(diff):.1f}"


def build_message(teams: list[dict], previous: dict[str, float] | None = None) -> dict:
    """Builds the Slack (Block Kit) payload for the weekly leaderboard."""
    if not teams:
        return {"text": "TrustBoard: no scores available yet."}

    top = teams[0]
    most_improved = None
    if previous:
        gains = [
            (t["name"], t["trust_score"] - previous[t["name"]])
            for t in teams
            if t["name"] in previous
        ]
        gains = [g for g in gains if g[1] > 0]
        if gains:
            most_improved = max(gains, key=lambda g: g[1])

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "TrustBoard Weekly"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Trust Score = quality + documentation + ownership + freshness, computed from DataHub and written back to the graph."}]},
        {"type": "divider"},
    ]

    lines = []
    for i, t in enumerate(teams):
        rank = _MEDALS.get(i, f"{i + 1}th")
        delta = _delta_label(t["name"], t["trust_score"], previous)
        tier = (t.get("trust_tier") or "").upper()
        lines.append(f"`{rank}`  *{t['name']}*  {t['trust_score']:.1f}  ({tier})  _{delta}_")
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})

    blocks.append({"type": "divider"})
    footer = f"*Team of the week:* {top['name']} ({top['trust_score']:.1f}, {(top.get('trust_tier') or '').upper()})"
    if most_improved:
        footer += f"\n*Most improved:* {most_improved[0]} (+{most_improved[1]:.1f} this week)"
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": footer}})

    fallback = f"TrustBoard Weekly. Team of the week: {top['name']} ({top['trust_score']:.1f})"
    return {"text": fallback, "blocks": blocks}


def post_to_slack(payload: dict) -> bool:
    """Posts the message to Slack through an Incoming Webhook. Returns whether it was sent."""
    webhook = get_settings().slack_webhook_url
    if not webhook:
        return False
    resp = requests.post(webhook, json=payload, timeout=10)
    resp.raise_for_status()
    return True


def publish_leaderboard(previous: dict[str, float] | None = None, graph=None) -> dict:
    """Reads the leaderboard from the graph, builds the message and publishes it (or prints it)."""
    teams = trust_lookup.leaderboard(graph=graph)
    payload = build_message(teams, previous=previous)

    if post_to_slack(payload):
        print("Leaderboard published to Slack.")
    else:
        print("SLACK_WEBHOOK_URL not configured. Generated payload:\n")
        print(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    publish_leaderboard()
