# TrustBoard

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)

**Demo video (1:49): https://youtu.be/6aZ8X2LyaNQ**
**Live demo: https://trustboard.duckdns.org** (a saved snapshot of a real run, see below)

**TrustBoard turns data governance into a weekly sport.** Four cooperating components read quality
signals from DataHub, compute a Trust Score for every data team, write it back to the graph as
first-class metadata, open incidents on the datasets that drag a team down, and post a gamified
leaderboard to Slack. The score does not live in a private database: it lives inside DataHub, where
the next person, pipeline or agent inherits it.

One thing to be straight about before you read further, because the word is doing a lot of work in
this competition: **there is no model call anywhere in this codebase.** These are deterministic
components with role names, not LLM agents, and the pipeline is four sequential steps rather than a
planner. What is genuinely agentic is the boundary between them. The Gatekeeper is a separate process
that reaches the score over MCP and changes its behaviour based on what a different component wrote
into DataHub in an earlier run, which is the part of "agents that do real work" this project actually
demonstrates. Calling the rest of it multi-agent would be padding.

Built for **Build with DataHub: The Agent Hackathon** (2026), track **Agents That Do Real Work**.

## Why it matters

DataHub aims to be a universal data registry for centralized compliance and policy enforcement. But
keeping metadata healthy is the chore nobody wants to do, and quality reports are dashboards nobody
opens. TrustBoard flips that: it makes the health of your metadata a weekly competition teams *want*
to win, and turns the resulting score into a trust signal that other agents consult before they act.

## What it does

Three components that run the weekly cycle, plus a fourth that proves the point by consuming their
output from outside the process:

1. **The Auditor** connects to DataHub through the acryl-datahub SDK, walks every dataset by domain,
   and computes a composite Trust Score from four signals: quality, documentation, ownership and
   freshness. Each signal has a preference order and reports which source answered. Quality prefers
   real data assertions and falls back to DataHub Tests; freshness prefers the `Operation` aspect,
   which records when the data changed, and falls back through the dataset profile to the metadata
   audit stamp. Missing signals are renormalized, never counted as silent zeros, and a signal that
   could not be *read* drops the dataset from the audit rather than scoring it as absent.
2. **The Scribe** writes the score *back to the graph*: structured properties on each domain **and
   on every dataset** (score, tier, signal coverage, model version), a scorecard in the domain
   description, a Gold/Silver/Bronze/At-Risk/Unrated tier tag on every dataset, and an
   **operational incident** opened (and later resolved) on datasets that fall below the trust
   threshold. Every write is idempotent.
3. **The Herald** builds the weekly ranking against last week and posts it to Slack as a sports
   scoreboard: podium, tiers, "team of the week", and the "most improved" comeback story.
4. **The Gatekeeper** is a *separate* agent that consults the Trust Score before using a dataset. A
   gold dataset gets a GO; an at-risk one gets a NO-GO and is escalated to the team that owns it.
   It reaches the score **over MCP**, spawning the TrustBoard MCP server as its own process and
   calling `is_trustworthy`. The only TrustBoard module it imports is the MCP transport, and it
   shares no database and no run with the pipeline, so what it inherits, it inherits from the graph.
   Its verdict has three outcomes rather than two: below the bar, unrated, or not in the graph at
   all. This closes the loop: agent to graph to agent.

A web dashboard (FastAPI + Next.js) shows the current league and each team's trend over time.

## How TrustBoard contributes back to the graph

This is the heart of the project. TrustBoard does not just read metadata, it enriches it. After a
run you can open DataHub and see, on each domain and dataset:

| What is written | Where it lands in DataHub | Who inherits it |
| --- | --- | --- |
| `io.trustboard.trustScore` (0-100) | Structured property on the domain **and each dataset** | Anyone filtering or querying the catalog |
| `io.trustboard.trustTier` (gold/silver/bronze/at-risk/unrated) | Structured property on the domain and each dataset | Governance dashboards, search facets |
| `io.trustboard.trustCoverage` (0-1) | Structured property on the domain and each dataset | Anyone who needs to know how much evidence a score rests on |
| `io.trustboard.trustScoreVersion` | Structured property on the domain and each dataset | Anyone comparing scores across time |
| Scorecard with weights, coverage and cut-offs | Domain description (idempotent block) | Any human opening the asset |
| `Trust: Gold/Silver/Bronze/At-Risk/Unrated` tag | Global tag on each dataset | "Show me every at-risk dataset" in search |
| Operational incident | Incident on low-trust datasets | On-call, data owners, the DataHub UI |
| `get_trust_score`, `is_trustworthy`, `get_team_leaderboard` | Custom MCP tools | Any other AI agent in the ecosystem |

The score is written per dataset and not only per domain because that is the grain other agents ask
at. An agent deciding whether to build on `orders_raw` cannot act on a number that describes the team
that owns it.

## How the Trust Score is computed

Model version 2.1. A weighted average of four components, each 0-100:

```
Trust Score = 0.35 * quality        (checks passing, out of 4; catalog tests capped at 60%)
            + 0.25 * documentation  (description + field docs + glossary terms)
            + 0.20 * ownership      (has an assigned owner)
            + 0.20 * freshness      (days since the data changed, over a 30-day window)
```

Tiers: gold >= 80, silver >= 60, bronze >= 40, at-risk below 40, plus **unrated**. Those cut-offs are
served by the API at `/api/model` and printed into every scorecard, so the rules that govern a badge
are visible to the people being ranked by them rather than buried in the source.

Four things about the model are worth stating plainly, because each one is a decision that could
have gone the other way.

**Signals declare their source.** Quality from assertions is a claim about the data. Quality from
DataHub Tests is a claim about the catalog. They are not the same, so the score records which one
answered (`quality_sources` on a domain, `quality_source` on a dataset) instead of presenting them
as interchangeable. Freshness works the same way, and its weakest source, the metadata audit stamp,
is labelled as such because on most ingestion setups that stamp moves whenever the crawler runs
whether or not a row changed.

**Quality counts checks that pass; it is never a pass rate.** `passing / (passing + failing)` pays a
team to delete the checks that fail: ten checks with one passing scored 10, and deleting the nine
failures scored 100. A breadth multiplier on top of the rate only softens that, because shrinking
the denominator still wins, so the rate is gone. Quality counts the checks that currently pass,
against a target of four.

The consequence is deliberate: a failing check is worth exactly what a missing one is worth, which is
nothing. A check that fails gives you no assurance about the data, so it buys no trust, and deleting
it moves the score by zero rather than upward. The failure is priced where arithmetic cannot reach
it, as an incident, and only when most of a dataset's checks are failing, because raising one per
failure paged 30 of 67 datasets on the first run and DataHub already surfaces individual assertion
failures. Catalog tests are capped at 60% of full marks, since a DataHub Test checks the catalog
entry and an assertion checks the data.

**Quality is required, and coverage has a floor.** If a signal is absent, its weight is removed and
the rest renormalize, so a gap reads as reduced confidence rather than a hidden zero. That creates an
obvious hole: a team with no tests would be scored on the three components it does have and could
outrank a team that runs tests and fails them.

A coverage floor alone does not close it, and v2.0 of this model shipped believing it did. The
reasoning stopped at documentation plus ownership, which supply 45%, and missed that freshness is
nearly free because its last fallback is an audit stamp that moves whenever the crawler runs. So a
team that had never written a single check reached 65% coverage, cleared the 50% floor, and scored
**100 out of three maxed components** while a team running real assertions and failing half of them
scored 82.5. The metric was telling people to stop testing their data.

Both guards are now in place. Coverage below 50% is unrated, and **no quality signal from either
source is unrated regardless of coverage**, because there is no honest trust score for data nobody
checks. A domain also needs half its datasets judgeable before its own number is published. The aggregate
takes its scores from the rated datasets and its denominator from all of them, which matters more
than it sounds: excluding unrated datasets outright let a team raise its own score by fifty points
and jump from bronze to gold purely by deleting the assertions on its worst tables, since those
tables then vanished from the arithmetic instead of counting against it. Keeping their weight in the
denominator makes hiding a table cost what leaving it broken costs, so instrumenting it is always the
better move. The trade-off, stated rather than buried: a team is diluted by its own uninstrumented
backlog. That is fair at team level, and individual assets keep the protection that matters, since
they are still not scored, not tagged at-risk and not paged.
`tests/test_quality_required.py` and `tests/test_quality_incentives.py` pin all of it, the latter
exhaustively rather than by example, because a spot check passed against the broken version too.

**Unrated is not a bad grade.** It gets its own tier, its own tag, and no incident, and the
`trustScore` property is left **absent** rather than written as 0.0. That number is filterable in
DataHub, so writing the zero that stands for "could not measure" would make every facet and range
query read it as worst in the company, which is the same conflation arriving through the write path.
A dataset TrustBoard cannot judge is a gap in the catalog, and opening a ticket on it would teach
teams that registering an asset is what gets them paged. The demo leaves part of each team's
datasets uninstrumented on purpose, so this path is visible in the graph, the tags and the dashboard
rather than being an argument in a README.

**A domain's score weights each dataset by its downstream blast radius**, `1 + ln(1 + consumers)`,
derived by inverting every dataset's `UpstreamLineage`. A flat mean lets an abandoned scratch table
drag a team down as hard as the table forty dashboards read from. The weighting is logarithmic so one
heavily consumed table cannot swamp everything else: twenty consumers buys about four times the pull
of none, not twenty times. With no lineage anywhere it collapses back to a flat mean.

The "improve this first" advice points at **weight times headroom**, not the lowest raw number. A
component at 40 carrying 20% of the weight has less leverage than one at 55 carrying 35%, and sending
a team after the former costs them effort that barely moves their rank.

The scoring logic is pure and unit-tested, which is why it can be packaged as a reusable DataHub
Skill. Most of the suite covers `scoring/trust_score.py` directly; the rest cover the policy gate,
the MCP boundary and the aspect-reading rules.

## Architecture

```
                        DataHub (GMS :8080)
                    reads  |                  ^  writes properties, tags, incidents
    assertions, tests,     |                  |
    docs, owners, lineage, v                  |
    Operation           Auditor ---scores---> Scribe
                           |                     |
                           |                     | publishes
                           v                     v
                    local history          MCP tools: get_trust_score,
                      (SQLite)             is_trustworthy, get_team_leaderboard
                           |                     |
                  +--------+--------+            | separate process, stdio
                  v                 v            v
            FastAPI backend      Herald      Gatekeeper agent
                  |                 |        reads the score back OUT of
                  v                 v        DataHub before deciding
           Next.js dashboard     Slack       (GO / NO-GO on a dataset)

The Scribe receives the Auditor's results in memory; the SQLite snapshot is
written afterwards and only feeds the dashboard's trend. The Gatekeeper shares
neither: what it knows, it reads from the graph.
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

More precisely, the seeder writes both of the sources the Auditor knows about for its two ranked
signals, so neither code path is decoration:

- **Quality:** real `Assertion` entities with recorded `AssertionRunEvent` results on a fraction of
  each team's datasets, plus `testResults` on most of them. Running the Auditor prints the split
  it actually read, in three groups rather than two: scored from assertions, fallen back to catalog
  tests, and no quality signal at all. That last group is not a weaker measurement, it is the
  absence of one, and folding it into the fallback would commit in prose the exact conflation the
  code spends two hundred lines refusing to make.
- **Freshness:** the `Operation` aspect, which is when the data changed, alongside
  `datasetProperties.lastModified`, which is the metadata's own audit stamp. The Auditor prefers the
  first and labels the score with whichever it used.

So the *inputs* are fabricated. What runs on top of them is not: the Auditor reads those aspects
back through the SDK with no knowledge of the seeder, the scoring is the real model, and the Scribe
writes the results into DataHub as metadata you can open in the UI.

The whole thing is reproducible, and that is checked rather than asserted. Seed, audit, seed again,
audit again gives byte-identical scores. Getting there turned up two real bugs worth naming: the
domain aspect was emitted asynchronously, so two datasets out of sixty-seven were still filed under
the datapack's domain when the audit read them, and nothing verified the write. The seeder now emits
that aspect with `SYNC_WAIT` and reads every assignment back, repairing and reporting any that did
not land.

The hosted demo at trustboard.duckdns.org serves a saved snapshot of one of these runs. It is not
connected to a live DataHub instance.

### 3. Dashboard

```bash
uvicorn backend.main:app --port 8000 --reload      # API
cd frontend && npm install && npm run dev          # dashboard at http://localhost:3000
```

The dashboard reads the scoring model itself from `GET /api/model`, so the weights, tier cut-offs
and coverage floor on screen come from the same place the scores do. There is no second copy of them
in the TypeScript to drift out of sync.

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
├── tests/             98 tests: scoring model, quality incentives, policy gate,
│                   MCP boundary, gatekeeper degradation, aspect-reading rules
├── mcp_client/        authenticated DataHub connection (SDK, retry with backoff)
├── mcp_server/        FastMCP server exposing get_trust_score to other agents
├── backend/           FastAPI + SQLite history
├── frontend/          Next.js dashboard
├── scripts/           datapack loader, demo seed, history seed, write-back probe
├── datahub-skill-contribution/   the datahub-trust-score skill, as submitted upstream
├── examples/          sample outputs (leaderboard, Slack payload, domain scores)
├── .github/workflows/ CI: tests, lint, import check with no GMS, frontend build
└── run_week.py        weekly orchestrator
```

## How it maps to the judging criteria

- **Use of DataHub:** reads assertions, assertion run events, catalog tests, ownership, schema and
  field docs, glossary terms, upstream lineage, operations and dataset profiles. Writes back four
  structured properties on domains and datasets, tier tags, domain descriptions, operational
  incidents, and three MCP tools.
- **Technical Execution:** mutations deliberately not retried, reads retried with backoff, paged
  searches instead of a first-page-is-the-graph assumption, an unreadable aspect excluded rather
  than scored as absent, a run that refuses to publish when it loses more than 20% of the graph, a
  tool error over MCP that becomes a readable refusal instead of a `KeyError` inside the caller's
  decision logic, every threshold derived from one table, 98 tests and CI. Idempotency is checked by
  running the pipeline twice and diffing, not by a test; see Limitations.
- **Originality:** the score becomes shared context a second process consumes over MCP, with a
  three-outcome verdict that distinguishes bad data from unmeasured data, and governance is framed
  as a competitive league. Not another read-only quality dashboard.
- **Real-World Usefulness:** the quality signal is real data assertions, freshness is when the data
  changed, teams are weighted by blast radius, the advice points at the highest-leverage fix, and an
  asset nobody has instrumented comes back unrated rather than accused.
- **Submission Quality:** reproducible quickstart, sample outputs from one real run, a [demo
  video](https://youtu.be/6aZ8X2LyaNQ), and a live board at trustboard.duckdns.org.

## Limitations

Worth knowing before you point this at anything that matters.

- Blast radius counts **dataset** consumers only, by inverting `UpstreamLineage`. A table feeding
  thirty dashboards and no tables registers as an orphan, so the weighting understates BI reach and
  never overstates it.
- The assertions query needs the `assertions` field on `Dataset`. A GMS that does not expose it
  degrades quality to catalog tests and says so on stderr, rather than reporting that everything
  passed.
- Scores from different model versions are not comparable. The version travels with every score for
  that reason, but nothing stops a trend chart from spanning a model change.
- The weights are a judgement, not a measurement. They are visible at `/api/model` and in every
  scorecard precisely so a team can argue with them.
- The hosted demo serves a saved snapshot. It is not attached to a live DataHub instance, and
  `load_seed_if_empty` only loads when the database is empty, so a deploy on a persistent volume
  keeps serving whichever run landed first until the volume is cleared.
- **The write path is thinly tested.** The scoring model, the policy gate, the MCP boundary and the
  aspect-reading rules have tests, and so does the write path: `tests/test_scribe_writes.py` runs the
  Scribe against a fake graph and asserts on the mutations it issues, `tests/test_mcp_surface.py`
  spawns the real MCP server over stdio and calls every tool. `agents/herald.py` and the backend
  still do not, so
  "every write is idempotent" rests on running the pipeline twice and diffing the output rather than
  on an assertion in CI. That is a real gap and it is the next thing worth building.
- **The trend history is authored, not measured.** `scripts/seed_history.py` holds a per-team
  trajectory table and writes finished scores straight into the history for the three prior weeks.
  Only the current week comes from a real audit. The "most improved" headline is a value in that
  table, not a measurement, and the earlier rows carry no coverage, model version or dataset count.
- The score depends on wall-clock time through freshness, so two runs days apart differ slightly
  even if nothing in the data changed. "Reproducible" above means seed, audit, seed, audit within a
  session, which is what the idempotency claim is actually about.

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
