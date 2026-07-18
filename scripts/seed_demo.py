"""Prepares the TrustBoard demo scenario by seeding signals into the graph.

The showcase-ecommerce datapack concentrates almost every dataset in a single
domain and ships with sparse quality signals. So that the leaderboard has 5
comparable teams and a story (a champion, a laggard, three in the middle), this
script:

  1. Maps each data platform to a team (a named domain).
  2. Reassigns each dataset to its team (domains aspect).
  3. Seeds contrasting signals according to the team's health profile:
     ownership, documentation (editableDatasetProperties), glossaryTerms and
     testResults (pass/fail). These are exactly the signals the Auditor will
     read afterwards to compute the Trust Score.

It is idempotent: emitting an aspect replaces the previous one, so it can be
re-run without duplicating. It is declared as demo environment preparation,
separate from the logic the Auditor audits.

Usage:
    .venv/Scripts/python scripts/seed_demo.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.emitter.mcp import MetadataChangeProposalWrapper  # noqa: E402
from datahub.metadata.schema_classes import (  # noqa: E402
    AuditStampClass,
    DomainsClass,
    EditableDatasetPropertiesClass,
    GlossaryTermAssociationClass,
    GlossaryTermsClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    TestResultClass,
    TestResultsClass,
    TestResultTypeClass,
)

from mcp_client.datahub_connection import get_graph  # noqa: E402

ACTOR = "urn:li:corpuser:datahub"

# Real datapack domains (urn -> name) confirmed in the environment.
DOMAINS = {
    "Data Platform Team": "urn:li:domain:b2fd91.1caf2b7c-ca73-4708-bdec-6687d78cab0e",
    "Ecommerce Operations": "urn:li:domain:b2fd91.91994180-93ee-43f7-9c97-5e74a4a43fbd",
    "E-Commerce": "urn:li:domain:b2fd91.d4f24004-fb54-4e3c-8dea-2b7e209230b0",
    "Engineering Division": "urn:li:domain:b2fd91.ce125416-344c-4db4-9f07-f7086a851606",
    "Marketing": "urn:li:domain:b2fd91.e0f246dc-e7a5-40ed-9441-1e397ed6e2ad",
}

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

# Health profile per team: target fraction for each signal. This creates the
# contrast that makes the leaderboard interesting.
PROFILES = {
    "Data Platform Team": dict(doc=0.90, own=0.90, terms=0.80, pass_ratio=0.90),
    "Ecommerce Operations": dict(doc=0.75, own=0.70, terms=0.60, pass_ratio=0.78),
    "E-Commerce": dict(doc=0.55, own=0.50, terms=0.40, pass_ratio=0.55),
    "Engineering Division": dict(doc=0.35, own=0.30, terms=0.25, pass_ratio=0.38),
    "Marketing": dict(doc=0.15, own=0.15, terms=0.10, pass_ratio=0.22),
}

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

_PLATFORM_RE = re.compile(r"dataPlatform:([^,]+),")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _audit() -> AuditStampClass:
    return AuditStampClass(time=_now_ms(), actor=ACTOR)


def _platform_of(dataset_urn: str) -> str | None:
    m = _PLATFORM_RE.search(dataset_urn)
    return m.group(1) if m else None


def list_dataset_urns(graph) -> list[str]:
    query = (
        '{ search(input: {type: DATASET, query: "*", start: 0, count: 200}) '
        "{ searchResults { entity { urn } } } }"
    )
    results = graph.execute_graphql(query)["search"]["searchResults"]
    return [r["entity"]["urn"] for r in results]


def seed_dataset(graph, dataset_urn: str, team: str, idx: int) -> None:
    """Emits a dataset's aspects according to its team's profile.

    idx walks the team's datasets and decides deterministically (no randomness)
    which fraction receives each signal, respecting the profile.
    """
    profile = PROFILES[team]
    emit = lambda aspect: graph.emit_mcp(  # noqa: E731
        MetadataChangeProposalWrapper(entityUrn=dataset_urn, aspect=aspect)
    )

    # 1. Domain (team).
    emit(DomainsClass(domains=[DOMAINS[team]]))

    # Deterministic threshold: the i-th dataset "falls inside" fraction f if
    # (i mod 100)/100 < f. Spreads the signals in a stable way.
    def within(fraction: float) -> bool:
        return ((idx * 37) % 100) / 100.0 < fraction

    # 2. Ownership.
    if within(profile["own"]):
        owner = OWNERS[idx % len(OWNERS)]
        emit(OwnershipClass(owners=[OwnerClass(owner=owner, type=OwnershipTypeClass.DATAOWNER)]))

    # 3. Documentation.
    if within(profile["doc"]):
        emit(
            EditableDatasetPropertiesClass(
                created=_audit(),
                lastModified=_audit(),
                description=(
                    f"Owned by {team}. Curated dataset with documented schema, "
                    "lineage and business context maintained by the team."
                ),
            )
        )

    # 4. Glossary terms.
    if within(profile["terms"]):
        emit(
            GlossaryTermsClass(
                terms=[GlossaryTermAssociationClass(urn=TERMS[idx % len(TERMS)])],
                auditStamp=_audit(),
            )
        )

    # 5. testResults: 4 checks, how many pass depends on pass_ratio.
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


def main() -> None:
    graph = get_graph()
    urns = list_dataset_urns(graph)
    print(f"Datasets found: {len(urns)}")

    per_team_idx: dict[str, int] = {t: 0 for t in DOMAINS}
    assigned = {t: 0 for t in DOMAINS}
    skipped = 0

    for urn in urns:
        platform = _platform_of(urn)
        team = PLATFORM_TO_TEAM.get(platform)
        if team is None:
            skipped += 1
            continue
        seed_dataset(graph, urn, team, per_team_idx[team])
        per_team_idx[team] += 1
        assigned[team] += 1

    print("\nDatasets assigned per team:")
    for team, n in assigned.items():
        p = PROFILES[team]
        print(f"  {team}: {n} datasets  (profile doc={p['doc']:.0%} own={p['own']:.0%} tests_pass={p['pass_ratio']:.0%})")
    if skipped:
        print(f"  (no recognized platform: {skipped})")
    print("\nOK: demo scenario seeded into DataHub.")


if __name__ == "__main__":
    main()
