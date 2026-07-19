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

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.emitter.mcp import MetadataChangeProposalWrapper  # noqa: E402
from datahub.metadata.schema_classes import (  # noqa: E402
    AuditStampClass,
    DatasetPropertiesClass,
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

# Health profile per team: target fraction for each signal. This creates the
# contrast that makes the leaderboard interesting.
PROFILES = {
    "Data Platform Team": dict(doc=0.90, own=0.90, terms=0.80, pass_ratio=0.90, fresh=0.85),
    "Ecommerce Operations": dict(doc=0.75, own=0.70, terms=0.60, pass_ratio=0.78, fresh=0.70),
    "E-Commerce": dict(doc=0.55, own=0.50, terms=0.40, pass_ratio=0.55, fresh=0.50),
    "Engineering Division": dict(doc=0.35, own=0.30, terms=0.25, pass_ratio=0.38, fresh=0.30),
    "Marketing": dict(doc=0.15, own=0.15, terms=0.10, pass_ratio=0.22, fresh=0.15),
}

# Freshness reads DatasetProperties.lastModified. A dataset inside the team's
# fresh fraction was updated a few days ago, one outside it months ago, which
# puts it well past the scoring window.
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
    # Sorted, because search returns results by relevance and that ranking
    # shifts once the Scribe writes tags. An unstable order would hand each
    # dataset a different index on the next run, and with it a different set
    # of signals, so the scores would drift every time this is re-run.
    return sorted(r["entity"]["urn"] for r in results)


def resolve_domains(graph) -> dict[str, str]:
    """Maps each team name to the domain URN this DataHub instance minted.

    Fails loudly and by name when a domain is missing, because the alternative
    is assigning every dataset to a dangling URN and watching the Auditor find
    nothing to score with no explanation.
    """
    query = (
        '{ search(input: {type: DOMAIN, query: "*", start: 0, count: 100}) '
        "{ searchResults { entity { urn ... on Domain { properties { name } } } } } }"
    )
    results = graph.execute_graphql(query)["search"]["searchResults"]
    by_name = {
        (r["entity"].get("properties") or {}).get("name"): r["entity"]["urn"]
        for r in results
    }
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
    def emit(aspect) -> None:
        graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=dataset_urn, aspect=aspect))

    # 1. Domain (team).
    emit(DomainsClass(domains=[domains[team]]))

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

    # 5. Freshness. The existing aspect is read back and re-emitted with only
    # lastModified changed, so the name, description and custom properties that
    # came with the datapack survive.
    props = graph.get_aspect(dataset_urn, DatasetPropertiesClass) or DatasetPropertiesClass(
        customProperties={}
    )
    age_days = FRESH_AGE_DAYS if within(profile["fresh"]) else STALE_AGE_DAYS
    props.lastModified = AuditStampClass(
        time=_now_ms() - age_days * _MS_PER_DAY, actor=ACTOR
    )
    emit(props)

    # 6. testResults: 4 checks, how many pass depends on pass_ratio.
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
    domains = resolve_domains(graph)
    urns = list_dataset_urns(graph)
    print(f"Datasets found: {len(urns)}")

    per_team_idx: dict[str, int] = {t: 0 for t in TEAM_NAMES}
    assigned = {t: 0 for t in TEAM_NAMES}
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
    main()
