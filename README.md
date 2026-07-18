# TrustBoard

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)

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

1. **The Auditor** connects to DataHub through the SDK / MCP Server, walks every dataset by domain,
   and computes a composite Trust Score from four signals: quality (passing data tests),
   documentation, ownership and lineage freshness. Missing signals are renormalized, never counted
   as silent zeros.
2. **The Scribe** writes the score *back to the graph*: a structured property on each domain, a
   scorecard in the domain description, a Gold/Silver/Bronze tier tag on every dataset, and an
   **operational incident** opened (and later resolved) on datasets that fall below the trust
   threshold. Every write is idempotent.
3. **The Herald** builds the weekly ranking against last week and posts it to Slack as a sports
   scoreboard: podium, tiers, "team of the week", and the "most improved" comeback story.
4. **The Gatekeeper** is a *separate* agent that consults the Trust Score before using a dataset. A
   gold dataset gets a GO; an at-risk dataset gets a NO-GO with a safer alternative. It never
   integrates with TrustBoard, it just reads DataHub. This closes the loop: agent to graph to agent.

A web dashboard (FastAPI + Next.js) shows the current league and each team's trend over time.

## How TrustBoard contributes back to the graph

This is the heart of the project. TrustBoard does not just read metadata, it enriches it. After a
run you can open DataHub and see, on each domain and dataset:

| What is written | Where it lands in DataHub | Who inherits it |
| --- | --- | --- |
| `io.trustboard.trustScore` (0-100) | Structured property on the domain | Anyone filtering or querying the catalog |
| `io.trustboard.trustTier` (gold/silver/bronze/at-risk) | Structured property on the domain | Governance dashboards, search facets |
| Scorecard with component breakdown | Domain description (idempotent block) | Any human opening the asset |
| `Trust: Gold/Silver/Bronze` tag | Global tag on each dataset | "Show me all Bronze datasets" in search |
| Operational incident | Incident on low-trust datasets | On-call, data owners, the DataHub UI |
| `get_trust_score` / `is_trustworthy` | Custom MCP tools | Any other AI agent in the ecosystem |

## How the Trust Score is computed

A weighted average of four components, each 0-100:

```
Trust Score = 0.35 * quality        (passing data tests / total tests)
            + 0.25 * documentation  (description + field docs + glossary terms)
            + 0.20 * ownership      (has an assigned owner)
            + 0.20 * freshness      (recency of lineage / last update)
```

If a signal is absent for a dataset (for example no tests), its weight is removed and the remaining
weights are renormalized, so a missing signal is visible as reduced coverage rather than a hidden
zero. A domain's score is the average of its datasets. Tiers: gold >= 80, silver >= 60, bronze >= 40,
at-risk below 40. The scoring logic is pure and unit-tested (`scoring/trust_score.py`), which is why
it can be packaged as a reusable DataHub Skill.

## Architecture

```
DataHub (GMS :8080)
     | reads tests, docs, ownership, lineage           writes property, tags, incident
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
python scripts/load_datapack.py showcase-ecommerce --force   # Windows-safe datapack loader
```

DataHub UI at http://localhost:9002 (login `datahub` / `datahub`). Generate a personal access token
in Settings > Access Tokens (enable token auth first if the quickstart ships it off).

### 2. TrustBoard

```bash
cp .env.example .env          # paste your DATAHUB_GMS_TOKEN and SLACK_WEBHOOK_URL
python -m venv .venv && .venv/Scripts/activate   # Windows; use source .venv/bin/activate elsewhere
pip install -r requirements.txt

python scripts/seed_demo.py       # prepares the demo scenario (assigns datasets, seeds signals)
python scripts/seed_history.py    # seeds a few weeks of history for the trend charts
python run_week.py                # runs the full weekly cycle: audit, write-back, snapshot, publish
```

### 3. Dashboard

```bash
uvicorn backend.main:app --port 8000 --reload      # API
cd frontend && npm install && npm run dev          # dashboard at http://localhost:3000
```

### The Gatekeeper demo (the killer angle)

```bash
python -m agents.gatekeeper        # a second agent consumes the score and decides GO / NO-GO
python -m mcp_server.trustboard_mcp   # or run the MCP server for other agents to consume
```

## Project structure

```
trustboard/
├── agents/            auditor, scribe, incidents, herald, gatekeeper, trust_lookup
├── scoring/           pure Trust Score logic (+ tests) and historical tracking
├── mcp_client/        authenticated DataHub connection (SDK + Agent Context Kit)
├── mcp_server/        FastMCP server exposing get_trust_score to other agents
├── backend/           FastAPI + SQLite history
├── frontend/          Next.js dashboard (Data Trust League)
├── scripts/           datapack loader, demo seed, history seed, write-back probe
├── datahub-skill-contribution/   the trust-score skill contributed upstream
├── examples/          sample outputs (leaderboard, Slack payload, domain scores)
└── run_week.py        weekly orchestrator
```

## How it maps to the judging criteria

- **Use of DataHub:** reads the context graph (tests, ownership, lineage, docs) and writes back six
  kinds of metadata: structured properties, tier tags, descriptions, incidents, and an MCP tool.
- **Technical Execution:** idempotent writes, retry with backoff on transient GMS errors,
  renormalized scoring with no silent zeros, unit tests, runs end to end.
- **Originality:** the score becomes shared context that a second agent consumes, and governance is
  framed as a competitive league. Not another read-only quality dashboard.
- **Real-World Usefulness:** a data team sees exactly what drags their score, gets an actionable
  quest, and downstream agents refuse to build on untrusted data.
- **Submission Quality:** reproducible quickstart, sample outputs, and a focused demo.

## Open source contributions

- A reusable `trust-score` DataHub Skill contributed to
  [datahub-project/datahub-skills](https://github.com/datahub-project/datahub-skills)
  (see `datahub-skill-contribution/`).
- A one-line fix to the DataHub CLI for a real Windows bug: drive-letter paths (`C:\...`) were parsed
  as URI schemes in `get_path_schema`, breaking `datapack load` on Windows. The workaround ships in
  `scripts/load_datapack.py` and is proposed upstream with a regression test.

## Pre-existing code

None. All code was written during the submission period (July 6 to August 10, 2026), per the
"New Projects Only" rule. Third-party libraries are listed in `requirements.txt` and
`frontend/package.json`.

## License

Apache License 2.0. See [LICENSE](LICENSE).
