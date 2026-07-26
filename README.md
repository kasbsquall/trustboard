# TrustBoard

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)

**Demo video (1:49): https://youtu.be/6aZ8X2LyaNQ**
**Live demo: https://trustboard.duckdns.org** (a saved snapshot of a real run, see below)

**TrustBoard turns data governance into a weekly sport.** A multi-agent system reads quality
signals from DataHub, computes a Trust Score for every data team, writes it back to the graph as
first-class metadata, opens incidents on the datasets that drag a team down, and posts a gamified
leaderboard to Slack. The score does not live in a private database: it lives inside DataHub, where
the next person, pipeline or agent inherits it.

Built for **Build with DataHub: The Agent Hackathon** (2026), track **Agents That Do Real Work**.

## Why it matters

DataHub aims to be a universal data registry for centralized compliance and policy enforcement. But
keeping metadata healthy is the chore nobody wants to do, and quality reports are dashboards nobody
opens. TrustBoard flips that: it makes the health of your metadata a weekly competition teams *want*
to win, and turns the resulting score into a trust signal that other agents consult before they act.

## What it does

Three specialized agents, plus a fourth that proves the point:

1. **The Auditor** connects to DataHub through the acryl-datahub SDK, walks every dataset by domain,
   and computes a composite Trust Score from four signals: quality (passing data tests),
   documentation, ownership and update freshness. Missing signals are renormalized, never counted
   as silent zeros.
2. **The Scribe** writes the score *back to the graph*: a structured property on each domain, a
   scorecard in the domain description, a Gold/Silver/Bronze/At-Risk tier tag on every dataset, and an
   **operational incident** opened (and later resolved) on datasets that fall below the trust
   threshold. Every write is idempotent.
3. **The Herald** builds the weekly ranking against last week and posts it to Slack as a sports
   scoreboard: podium, tiers, "team of the week", and the "most improved" comeback story.
4. **The Gatekeeper** is a *separate* agent that consults the Trust Score before using a dataset. A
   gold dataset gets a GO; an at-risk one gets a NO-GO and is escalated to the team that owns it.
   It reaches the score **over MCP**, spawning the TrustBoard MCP server as its own process and
   calling `is_trustworthy`. It imports nothing from TrustBoard and shares no database with it, so
   what it inherits, it inherits from the graph. This closes the loop: agent to graph to agent.

A web dashboard (FastAPI + Next.js) shows the current league and each team's trend over time.

## How TrustBoard contributes back to the graph

This is the heart of the project. TrustBoard does not just read metadata, it enriches it. After a
run you can open DataHub and see, on each domain and dataset:

| What is written | Where it lands in DataHub | Who inherits it |
| --- | --- | --- |
| `io.trustboard.trustScore` (0-100) | Structured property on the domain | Anyone filtering or querying the catalog |
| `io.trustboard.trustTier` (gold/silver/bronze/at-risk) | Structured property on the domain | Governance dashboards, search facets |
| Scorecard with component breakdown | Domain description (idempotent block) | Any human opening the asset |
| `Trust: Gold/Silver/Bronze/At-Risk` tag | Global tag on each dataset | "Show me every at-risk dataset" in search |
| Operational incident | Incident on low-trust datasets | On-call, data owners, the DataHub UI |
| `get_trust_score`, `is_trustworthy`, `get_team_leaderboard` | Custom MCP tools | Any other AI agent in the ecosystem |

## How the Trust Score is computed

A weighted average of four components, each 0-100:

```
Trust Score = 0.35 * quality        (passing data tests / total tests)
            + 0.25 * documentation  (description + field docs + glossary terms)
            + 0.20 * ownership      (has an assigned owner)
            + 0.20 * freshness      (how recently the dataset was updated)
```

If a signal is absent for a dataset (for example no tests), its weight is removed and the remaining
weights are renormalized, so a missing signal is visible as reduced coverage rather than a hidden
zero. A domain's score is the average of its datasets. Tiers: gold >= 80, silver >= 60, bronze >= 40,
at-risk below 40. The scoring logic is pure and unit-tested (`scoring/trust_score.py`), which is why
it can be packaged as a reusable DataHub Skill.

Renormalization has a trade-off worth stating plainly: a team with no tests at all is scored on the
three components it does have, so it can outrank a team that runs tests and fails them. Scoring a
missing signal as zero was the worse failure mode here, because it punishes teams for gaps the
catalog cannot see. Coverage is reported alongside the score for that reason, and a production
deployment should set a minimum coverage below which a team is left unrated instead of scored.

## Architecture

```
DataHub (GMS :8080)
     | reads tests, docs, ownership, recency             writes property, tags, incident
     v                                                          ^
  Auditor  --scores-->  local history (SQLite)  ------------>  Scribe  -->  DataHub
                              |                                               |
                              v                                              exposes
                          Herald  -->  Slack (weekly leaderboard)         MCP tools
                              |                                               |
                              v                                               v
                     FastAPI backend  -->  Next.js dashboard          Gatekeeper agent
                                                                   (GO / NO-GO on datasets)
```

## Quickstart

Requires Docker (8 GB for DataHub), Python 3.11+, and Node 20+.

### 1. DataHub with the demo data

```bash
pip install --upgrade acryl-datahub
datahub docker quickstart
datahub init                              # user datahub / password datahub
datahub datapack load showcase-ecommerce --force
# On Windows that command fails (see upstream issue below); use this instead:
# python scripts/load_datapack.py showcase-ecommerce --force
```

DataHub UI at http://localhost:9002 (login `datahub` / `datahub`). Generate a personal access token
in Settings > Access Tokens (enable token auth first if the quickstart ships it off).

### 2. TrustBoard

```bash
cp .env.example .env          # paste your DATAHUB_GMS_TOKEN and SLACK_WEBHOOK_URL
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/check_connection.py  # confirms GMS is reachable and the token works
python scripts/seed_demo.py       # prepares the demo scenario (see the note below)
python scripts/seed_history.py    # seeds a few weeks of history for the trend charts
python run_week.py                # runs the full weekly cycle: audit, write-back, snapshot, publish
```

### Where the demo numbers come from

Be clear about this before reading the leaderboard. DataHub's showcase datapack ships with no
quality signals attached, so there would be nothing to score. `scripts/seed_demo.py` writes them:
it assigns datasets to domains and emits ownership, descriptions, glossary terms, a `lastModified`
timestamp and synthetic `testResults` following a health profile per team. That profile is what
produces the spread between a gold team and an at-risk one, and `scripts/seed_history.py` does the
same for the previous weeks behind the trend charts.

So the *inputs* are fabricated. What runs on top of them is not: the Auditor reads those aspects
back through the SDK with no knowledge of the seeder, the scoring is the real model, and the Scribe
writes the results into DataHub as metadata you can open in the UI. Point TrustBoard at an instance
with real assertions and the same pipeline scores it unchanged.

The hosted demo at trustboard.duckdns.org serves a saved snapshot of one of these runs. It is not
connected to a live DataHub instance.

### 3. Dashboard

```bash
uvicorn backend.main:app --port 8000 --reload      # API
cd frontend && npm install && npm run dev          # dashboard at http://localhost:3000
```

### The Gatekeeper demo: agent to graph to agent

```bash
python -m scripts.gatekeeper_demo  # a second agent consumes the score over MCP and decides GO / NO-GO
python -m mcp_server.trustboard_mcp   # or run the MCP server for other agents to consume
```

## Project structure

```
trustboard/
├── agents/            auditor, scribe, incidents, herald, gatekeeper, trust_lookup
├── scoring/           pure Trust Score logic
├── tests/             unit tests for the scoring model
├── mcp_client/        authenticated DataHub connection (SDK, retry with backoff)
├── mcp_server/        FastMCP server exposing get_trust_score to other agents
├── backend/           FastAPI + SQLite history
├── frontend/          Next.js dashboard
├── scripts/           datapack loader, demo seed, history seed, write-back probe
├── datahub-skill-contribution/   the datahub-trust-score skill, as submitted upstream
├── examples/          sample outputs (leaderboard, Slack payload, domain scores)
└── run_week.py        weekly orchestrator
```

## How it maps to the judging criteria

- **Use of DataHub:** reads the context graph (tests, ownership, docs, update recency) and writes back six
  kinds of metadata: structured properties, tier tags, descriptions, incidents, and an MCP tool.
- **Technical Execution:** idempotent writes, retry with backoff on transient GMS errors,
  renormalized scoring with no silent zeros, unit tests, runs end to end.
- **Originality:** the score becomes shared context that a second agent consumes, and governance is
  framed as a competitive league. Not another read-only quality dashboard.
- **Real-World Usefulness:** a data team sees exactly what drags their score, gets an actionable
  quest, and downstream agents refuse to build on untrusted data.
- **Submission Quality:** reproducible quickstart, sample outputs, a [2-minute demo
  video](https://youtu.be/6aZ8X2LyaNQ), and a live board at trustboard.duckdns.org.

## Open source contributions

Both contributions are open upstream:

- **[datahub-skills#39](https://github.com/datahub-project/datahub-skills/pull/39)** —
  a `datahub-trust-score` skill that generalizes this project's pattern: compose signals
  into a score per domain, write it back as structured properties and tier tags, and raise
  incidents on the assets dragging a domain down. It complements the existing
  `datahub-quality` skill rather than duplicating it.
- **[datahub#18479](https://github.com/datahub-project/datahub/pull/18479)** — a fix for a
  real Windows bug in the DataHub CLI. `get_path_schema()` parsed the drive letter of
  `C:\dataile.json` as a URI scheme, so any local ingestion on Windows failed with
  `KeyError: Did not find a registered class for c`. Shipped with a regression test.
  The workaround lives in `scripts/load_datapack.py`, which is how this project could load
  its own demo data.

## Pre-existing code

None. All code was written during the submission period (July 6 to August 10, 2026), per the
"New Projects Only" rule. Third-party libraries are listed in `requirements.txt` and
`frontend/package.json`.

## License

Apache License 2.0. See [LICENSE](LICENSE).
