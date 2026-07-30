"""Prepares the TrustBoard demo scenario by seeding signals into the graph.

The showcase-ecommerce datapack concentrates almost every dataset in a single
domain and ships with sparse quality signals. So that the leaderboard has 5
comparable teams and a story (a champion, a laggard, three in the middle), this
script:

  1. Maps each data platform to a team (a named domain).
  2. Reassigns each dataset to its team (domains aspect).
  3. Seeds contrasting signals according to the team's health profile:
     ownership, documentation (editableDatasetProperties), glossaryTerms,
     an update timestamp (datasetProperties.lastModified) and testResults
     (pass/fail). These are exactly the four signals the Auditor reads
     afterwards to compute the Trust Score.

It is idempotent: emitting an aspect replaces the previous one, so it can be
re-run without duplicating. It is declared as demo environment preparation,
separate from the logic the Auditor audits.

Usage:
    python scripts/seed_demo.py
"""
from __future__ import annotations

import hashlib
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import EmitMode
from datahub.metadata.schema_classes import (
    AssertionInfoClass,
    AssertionResultClass,
    AssertionResultTypeClass,
    AssertionRunEventClass,
    AssertionRunStatusClass,
    AssertionStdOperatorClass,
    AssertionTypeClass,
    AuditStampClass,
    DatasetAssertionInfoClass,
    DatasetAssertionScopeClass,
    DatasetPropertiesClass,
    DomainsClass,
    EditableDatasetPropertiesClass,
    GlossaryTermAssociationClass,
    GlossaryTermsClass,
    OperationClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    TestResultClass,
    TestResultsClass,
    TestResultTypeClass,
)

from agents.auditor import _aspect, list_dataset_urns, list_domains
from mcp_client.datahub_connection import cli, get_graph

ACTOR = "urn:li:corpuser:datahub"

# The five teams the demo needs. Their URNs carry a UUID the datapack mints on
# load, so they are resolved by name at runtime rather than pinned here: a URN
# copied from one machine points at nothing on the next, and the failure would
# be silent, with every dataset assigned to a domain that does not exist.
TEAM_NAMES = [
    "Data Platform Team",
    "Ecommerce Operations",
    "E-Commerce",
    "Engineering Division",
    "Marketing",
]

# Each team owns its own platform stack (realistic assignment).
PLATFORM_TO_TEAM = {
    "snowflake": "Data Platform Team",
    "dbt": "Data Platform Team",
    "postgres": "Ecommerce Operations",
    "s3": "E-Commerce",
    "tableau": "Engineering Division",
    "powerbi": "Marketing",
    "looker": "Marketing",
}

# Health profile per team. Every fraction is the share of that team's datasets
# receiving the signal, and `checks` is how many data assertions a documented
# dataset carries.
#
# These used to be one dial per team, every fraction sliding together, and it
# made the demo argue against the product. When documentation, ownership,
# freshness and quality all correlate perfectly, the leaderboard collapses to a
# single axis of team virtue, "fix this first" says quality for everyone because
# quality carries the top weight, and the assertions-versus-catalog-tests
# distinction can never diverge because one number drives both. A real catalog
# does not look like that: teams are uneven, and which signal a team is worst at
# is the interesting part of the number.
#
# So each team now has a shape rather than a level. The strongest team is thin on
# glossary terms; the second tests well but ships stale; the third documents
# nothing and runs fresh; the fourth has nobody's name on anything; the last is
# behind everywhere, which is what "at risk" should look like.
PROFILES = {
    # Strong engineering discipline, weak on business vocabulary.
    "Data Platform Team": dict(doc=0.95, own=0.95, terms=0.60, checks=5, pass_ratio=0.92,
                               fresh=0.90, assertions=0.85, quality=1.00),
    # Tests thoroughly, but the pipelines lag.
    "Ecommerce Operations": dict(doc=0.70, own=0.75, terms=0.65, checks=4, pass_ratio=0.85,
                                 fresh=0.30, assertions=0.70, quality=0.92),
    # Fresh data nobody has written a word about.
    "E-Commerce": dict(doc=0.20, own=0.60, terms=0.15, checks=3, pass_ratio=0.70,
                       fresh=0.95, assertions=0.55, quality=0.85),
    # Documented and current, but orphaned: no owner to ask.
    "Engineering Division": dict(doc=0.75, own=0.10, terms=0.55, checks=2, pass_ratio=0.60,
                                 fresh=0.70, assertions=0.40, quality=0.75),
    # Behind on everything, which is what at-risk should actually look like.
    "Marketing": dict(doc=0.20, own=0.20, terms=0.10, checks=1, pass_ratio=0.35,
                      fresh=0.20, assertions=0.15, quality=0.60),
}

# Freshness prefers the Operation aspect, which records when the DATA changed.
# The seeder emits both that and DatasetProperties.lastModified so the audit
# exercises its primary source and its fallback on the same graph. A dataset
# inside the team's fresh fraction changed a few days ago, one outside it months
# ago, which puts it well past the scoring window.
_MS_PER_DAY = 86_400_000
FRESH_AGE_DAYS = 3
STALE_AGE_DAYS = 75

OWNERS = [
    "urn:li:corpuser:b2fd91.alex@example.com",
    "urn:li:corpuser:b2fd91.bryan@example.com",
    "urn:li:corpuser:b2fd91.kirk@example.com",
    "urn:li:corpuser:b2fd91.marty@example.com",
    "urn:li:corpuser:b2fd91.sam@example.com",
    "urn:li:corpuser:b2fd91.michael@example.com",
]
TERMS = [
    "urn:li:glossaryTerm:b2fd91.Email_Address",
    "urn:li:glossaryTerm:b2fd91.Phone_Number",
]
# Four standard quality checks per dataset (synthetic metadata tests).
TEST_CHECKS = [
    "urn:li:test:trustboard.completeness",
    "urn:li:test:trustboard.freshness",
    "urn:li:test:trustboard.validity",
    "urn:li:test:trustboard.uniqueness",
]

# Data assertions, the quality source the Auditor prefers. Each one is a claim
# about the data rather than about the catalog entry.
# There are six because the score rewards breadth: a team that asserts one thing
# about a table has not established much, and with only three defined here no
# dataset could ever reach BREADTH_TARGET, which would have quietly capped every
# team in the demo below full quality marks. How many of these a given team
# actually uses comes from its profile.
ASSERTION_CHECKS = [
    ("row-count-not-zero", DatasetAssertionScopeClass.DATASET_ROWS, AssertionStdOperatorClass.GREATER_THAN),
    ("no-null-primary-key", DatasetAssertionScopeClass.DATASET_COLUMN, AssertionStdOperatorClass.NOT_NULL),
    ("schema-unchanged", DatasetAssertionScopeClass.DATASET_SCHEMA, AssertionStdOperatorClass.EQUAL_TO),
    ("primary-key-unique", DatasetAssertionScopeClass.DATASET_COLUMN, AssertionStdOperatorClass.EQUAL_TO),
    ("row-count-within-range", DatasetAssertionScopeClass.DATASET_ROWS, AssertionStdOperatorClass.BETWEEN),
    ("no-future-timestamps", DatasetAssertionScopeClass.DATASET_COLUMN, AssertionStdOperatorClass.LESS_THAN),
]

_PLATFORM_RE = re.compile(r"dataPlatform:([^,]+),")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _audit() -> AuditStampClass:
    return AuditStampClass(time=_now_ms(), actor=ACTOR)


def _platform_of(dataset_urn: str) -> str | None:
    m = _PLATFORM_RE.search(dataset_urn)
    return m.group(1) if m else None


def _assertion_urn(dataset_urn: str, check: str) -> str:
    """A stable URN for a seeded assertion.

    Derived from the dataset and the check name, so re-running the seeder
    updates the same assertion instead of minting a new one every time. A random
    id here would leave the graph accumulating dead assertions, and each run
    would change the score.
    """
    digest = hashlib.sha1(f"{dataset_urn}|{check}".encode()).hexdigest()[:20]
    return f"urn:li:assertion:trustboard-{digest}"


def resolve_domains(graph) -> dict[str, str]:
    """Maps each team name to the domain URN this DataHub instance minted.

    Fails loudly and by name when a domain is missing, because the alternative
    is assigning every dataset to a dangling URN and watching the Auditor find
    nothing to score with no explanation.
    """
    by_name = {name: urn for urn, name in list_domains(graph).items()}
    resolved = {name: by_name[name] for name in TEAM_NAMES if name in by_name}
    missing = [name for name in TEAM_NAMES if name not in resolved]
    if missing:
        raise SystemExit(
            "These domains are not in DataHub: "
            + ", ".join(missing)
            + ".\nLoad the datapack first: "
            "datahub datapack load showcase-ecommerce --force"
        )
    return resolved


def seed_dataset(graph, domains: dict[str, str], dataset_urn: str, team: str, idx: int) -> None:
    """Emits a dataset's aspects according to its team's profile.

    idx walks the team's datasets and decides deterministically (no randomness)
    which fraction receives each signal, respecting the profile.
    """
    profile = PROFILES[team]
    def emit(aspect, mode: EmitMode = EmitMode.SYNC_PRIMARY) -> None:
        graph.emit_mcp(
            MetadataChangeProposalWrapper(entityUrn=dataset_urn, aspect=aspect),
            emit_mode=mode,
        )

    # 1. Domain (team). Emitted with SYNC_WAIT rather than the default, because
    # this is the one aspect that decides which team a dataset counts toward. A
    # write that has not landed yet does not merely delay a number, it files the
    # dataset under whichever domain the datapack gave it.
    emit(DomainsClass(domains=[domains[team]]), mode=EmitMode.SYNC_WAIT)

    # Deterministic threshold: the i-th dataset "falls inside" fraction f if
    # (i mod 100)/100 < f. Spreads the signals in a stable way.
    def within(fraction: float) -> bool:
        return ((idx * 37) % 100) / 100.0 < fraction

    # 2, 3, 4. Ownership, documentation and glossary terms. The absent case is
    # emitted as an empty aspect rather than skipped: emitting replaces, but
    # skipping leaves whatever a previous run wrote in place, so signals would
    # only ever accumulate and every re-run would raise the scores.

    # 2. Ownership.
    owners = (
        [OwnerClass(owner=OWNERS[idx % len(OWNERS)], type=OwnershipTypeClass.DATAOWNER)]
        if within(profile["own"])
        else []
    )
    emit(OwnershipClass(owners=owners))

    # 3. Documentation.
    emit(
        EditableDatasetPropertiesClass(
            created=_audit(),
            lastModified=_audit(),
            description=(
                f"Owned by {team}. Curated dataset with documented schema, "
                "lineage and business context maintained by the team."
            )
            if within(profile["doc"])
            else "",
        )
    )

    # 4. Glossary terms.
    terms = (
        [GlossaryTermAssociationClass(urn=TERMS[idx % len(TERMS)])]
        if within(profile["terms"])
        else []
    )
    emit(GlossaryTermsClass(terms=terms, auditStamp=_audit()))

    # 5. Freshness, in both sources the Auditor knows about. The existing
    # datasetProperties aspect is read back and re-emitted with only lastModified
    # changed, so the name, description and custom properties that came with the
    # datapack survive.
    age_days = FRESH_AGE_DAYS if within(profile["fresh"]) else STALE_AGE_DAYS
    changed_at = _now_ms() - age_days * _MS_PER_DAY

    props = graph.get_aspect(dataset_urn, DatasetPropertiesClass) or DatasetPropertiesClass(
        customProperties={}
    )
    props.lastModified = AuditStampClass(time=changed_at, actor=ACTOR)
    emit(props)

    # The Operation aspect is the one that says when the DATA changed, and it is
    # what the Auditor reads first. It is a timeseries aspect, so the timestamp
    # and messageId are derived from the dataset rather than from the clock: an
    # ordinary now() here would append a new point on every run and the graph
    # would fill up with duplicate operations.
    emit(
        OperationClass(
            timestampMillis=changed_at,
            operationType="UPDATE",
            lastUpdatedTimestamp=changed_at,
            actor=ACTOR,
            messageId=f"trustboard-op-{hashlib.sha1(dataset_urn.encode()).hexdigest()[:16]}",
        )
    )

    # 6. Quality. A dataset outside the team's `quality` fraction gets NO quality
    # signal from either source: an empty testResults and no assertions. That is
    # an uninstrumented table, and the scorer returns it unrated rather than
    # inventing a grade for data nobody checks.
    if not within(profile["quality"]):
        emit(TestResultsClass(passing=[], failing=[]))
        return

    # testResults: 4 checks, how many pass depends on pass_ratio.
    n_pass = round(profile["pass_ratio"] * len(TEST_CHECKS))
    # Deterministic +-1 jitter so that not every dataset is identical.
    if idx % 3 == 0 and n_pass < len(TEST_CHECKS):
        n_pass += 1
    elif idx % 3 == 1 and n_pass > 0:
        n_pass -= 1
    n_pass = max(0, min(len(TEST_CHECKS), n_pass))

    passing = [
        TestResultClass(test=TEST_CHECKS[i], type=TestResultTypeClass.SUCCESS)
        for i in range(n_pass)
    ]
    failing = [
        TestResultClass(test=TEST_CHECKS[i], type=TestResultTypeClass.FAILURE)
        for i in range(n_pass, len(TEST_CHECKS))
    ]
    emit(TestResultsClass(passing=passing, failing=failing))

    # 7. Data assertions with recorded runs, the quality source the Auditor
    # prefers over metadata tests. Only the team's `assertions` fraction gets
    # them, so both code paths run against this graph.
    if within(profile["assertions"]):
        _seed_assertions(graph, dataset_urn, profile["pass_ratio"], idx, changed_at, profile["checks"])


def _seed_assertions(
    graph, dataset_urn: str, pass_ratio: float, idx: int, run_at: int, checks: int
) -> None:
    """Emits three data assertions on a dataset, each with one recorded run.

    Deterministic throughout: the assertion URNs come from the dataset name, the
    run timestamp comes from the same clock the freshness signal uses, and the
    messageId is derived from the assertion. Re-running replaces these points
    rather than stacking new ones, which is what keeps the score stable across
    runs.
    """
    used = ASSERTION_CHECKS[: max(1, min(checks, len(ASSERTION_CHECKS)))]
    n_pass = round(pass_ratio * len(used))
    # Same deterministic jitter as the metadata tests, so a team's assertion
    # results and test results move together instead of contradicting.
    if idx % 3 == 0 and n_pass < len(used):
        n_pass += 1
    elif idx % 3 == 1 and n_pass > 0:
        n_pass -= 1
    n_pass = max(0, min(len(used), n_pass))

    for i, (check, scope, operator) in enumerate(used):
        urn = _assertion_urn(dataset_urn, check)
        graph.emit_mcp(
            MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=AssertionInfoClass(
                    type=AssertionTypeClass.DATASET,
                    description=f"TrustBoard demo assertion: {check}",
                    datasetAssertion=DatasetAssertionInfoClass(
                        dataset=dataset_urn, scope=scope, operator=operator
                    ),
                ),
            )
        )
        result = (
            AssertionResultTypeClass.SUCCESS if i < n_pass else AssertionResultTypeClass.FAILURE
        )
        graph.emit_mcp(
            MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=AssertionRunEventClass(
                    timestampMillis=run_at,
                    runId=f"trustboard-{run_at}",
                    asserteeUrn=dataset_urn,
                    status=AssertionRunStatusClass.COMPLETE,
                    assertionUrn=urn,
                    result=AssertionResultClass(type=result),
                    messageId=f"trustboard-run-{hashlib.sha1(urn.encode()).hexdigest()[:16]}",
                ),
            )
        )


def verify_domains(graph, domains: dict[str, str], intended: dict[str, str]) -> int:
    """Reads back every domain assignment and repairs the ones that did not land.

    Writes are checked rather than assumed. Two datasets out of sixty-seven came
    back filed under the domain the datapack gave them despite a successful-looking
    emit, and because nothing read them back, the effect showed up much later as a
    team gaining a dataset and another losing one between two runs of an audit that
    is supposed to be deterministic. A seeder that does not verify its own writes
    makes every reproducibility claim downstream of it unprovable.
    """
    by_urn = {urn: name for name, urn in domains.items()}
    repaired = 0
    for dataset_urn, team in intended.items():
        current = _aspect(graph, dataset_urn, DomainsClass)
        got = by_urn.get(current.domains[0]) if current and current.domains else None
        if got == team:
            continue
        graph.emit_mcp(
            MetadataChangeProposalWrapper(
                entityUrn=dataset_urn, aspect=DomainsClass(domains=[domains[team]])
            ),
            emit_mode=EmitMode.SYNC_WAIT,
        )
        repaired += 1
        print(f"  repaired domain: {dataset_urn.split(',')[1]} -> {team} (was {got})")
    return repaired


def main() -> None:
    graph = get_graph()
    domains = resolve_domains(graph)
    urns = list_dataset_urns(graph)
    print(f"Datasets found: {len(urns)}")

    per_team_idx: dict[str, int] = {t: 0 for t in TEAM_NAMES}
    assigned = {t: 0 for t in TEAM_NAMES}
    intended: dict[str, str] = {}
    skipped = 0

    for urn in urns:
        platform = _platform_of(urn)
        team = PLATFORM_TO_TEAM.get(platform)
        if team is None:
            skipped += 1
            continue
        seed_dataset(graph, domains, urn, team, per_team_idx[team])
        per_team_idx[team] += 1
        assigned[team] += 1
        intended[urn] = team

    repaired = verify_domains(graph, domains, intended)
    if repaired:
        print(f"  ({repaired} domain assignments did not land on the first write and were repaired)")

    print("\nDatasets assigned per team:")
    for team, n in assigned.items():
        p = PROFILES[team]
        print(
            f"  {team}: {n} datasets  (profile doc={p['doc']:.0%} own={p['own']:.0%} "
            f"tests_pass={p['pass_ratio']:.0%} fresh={p['fresh']:.0%})"
        )
    if skipped:
        print(f"  (no recognized platform: {skipped})")
    print("\nOK: demo scenario seeded into DataHub.")


if __name__ == "__main__":
    cli(main)
