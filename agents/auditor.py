"""Agent 1: The Auditor.

Walks the DataHub datasets, extracts quality, documentation, ownership and
freshness signals by reading aspects through the SDK, groups them by domain
(team) and computes the composite Trust Score using scoring.trust_score.

Returns one DomainScore per team, ready for the Scribe to write back to the
graph and for the Herald to publish.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    DomainsClass,
    EditableDatasetPropertiesClass,
    EditableSchemaMetadataClass,
    GlossaryTermsClass,
    OwnershipClass,
    SchemaMetadataClass,
    TestResultsClass,
)

from mcp_client.datahub_connection import execute_graphql_retry, get_graph
from scoring.trust_score import (
    DatasetScore,
    DatasetSignals,
    DomainScore,
    score_dataset,
    score_domain,
)

_MS_PER_DAY = 86_400_000


@dataclass(frozen=True)
class DomainInfo:
    urn: str
    name: str


@dataclass(frozen=True)
class AuditedDomain:
    """Result of auditing a domain: info, aggregate score and per-dataset scores."""

    info: DomainInfo
    score: DomainScore
    dataset_scores: list[DatasetScore]


def _safe_aspect(graph, urn: str, aspect_type):
    try:
        return graph.get_aspect(urn, aspect_type)
    except Exception:  # noqa: BLE001 - missing aspect or one-off error => no signal
        return None


def list_domains(graph) -> dict[str, str]:
    """Returns {domain_urn: name} for the domains that have a name."""
    query = (
        '{ search(input: {type: DOMAIN, query: "*", start: 0, count: 100}) '
        "{ searchResults { entity { urn ... on Domain { properties { name } } } } } }"
    )
    results = execute_graphql_retry(graph, query)["search"]["searchResults"]
    out: dict[str, str] = {}
    for r in results:
        e = r["entity"]
        name = (e.get("properties") or {}).get("name")
        if name:
            out[e["urn"]] = name
    return out


def list_dataset_urns(graph) -> list[str]:
    query = (
        '{ search(input: {type: DATASET, query: "*", start: 0, count: 200}) '
        "{ searchResults { entity { urn } } } }"
    )
    return [r["entity"]["urn"] for r in execute_graphql_retry(graph, query)["search"]["searchResults"]]


def extract_signals(graph, dataset_urn: str, now_ms: int | None = None) -> DatasetSignals:
    """Reads a dataset's aspects and translates them into DatasetSignals."""
    now_ms = now_ms or int(time.time() * 1000)

    # Quality: testResults.
    test_results = _safe_aspect(graph, dataset_urn, TestResultsClass)
    passing = len(test_results.passing or []) if test_results else 0
    failing = len(test_results.failing or []) if test_results else 0
    has_tests = test_results is not None and (passing + failing) > 0

    # Documentation: dataset-level description (editable or from the source).
    editable = _safe_aspect(graph, dataset_urn, EditableDatasetPropertiesClass)
    props = _safe_aspect(graph, dataset_urn, DatasetPropertiesClass)
    has_description = bool(
        (editable and editable.description) or (props and props.description)
    )

    # Documentation: field-level docs.
    has_field_docs = False
    editable_schema = _safe_aspect(graph, dataset_urn, EditableSchemaMetadataClass)
    if editable_schema and editable_schema.editableSchemaFieldInfo:
        has_field_docs = any(f.description for f in editable_schema.editableSchemaFieldInfo)
    if not has_field_docs:
        schema = _safe_aspect(graph, dataset_urn, SchemaMetadataClass)
        if schema and schema.fields:
            has_field_docs = any(f.description for f in schema.fields)

    # Documentation: glossary.
    terms = _safe_aspect(graph, dataset_urn, GlossaryTermsClass)
    has_glossary_terms = bool(terms and terms.terms)

    # Ownership.
    ownership = _safe_aspect(graph, dataset_urn, OwnershipClass)
    has_owner = bool(ownership and ownership.owners)

    # Freshness: days since the last recorded modification.
    freshness_days: float | None = None
    if props and props.lastModified and props.lastModified.time:
        freshness_days = max(0.0, (now_ms - props.lastModified.time) / _MS_PER_DAY)

    return DatasetSignals(
        urn=dataset_urn,
        tests_passing=passing,
        tests_failing=failing,
        has_tests=has_tests,
        has_description=has_description,
        has_field_docs=has_field_docs,
        has_glossary_terms=has_glossary_terms,
        has_owner=has_owner,
        freshness_days=freshness_days,
    )


def _domain_of(graph, dataset_urn: str) -> str | None:
    domains = _safe_aspect(graph, dataset_urn, DomainsClass)
    if domains and domains.domains:
        return domains.domains[0]
    return None


def audit_all_domains(graph=None) -> list[AuditedDomain]:
    """Walks DataHub and returns the Trust Score of each domain (team)."""
    graph = graph or get_graph()
    domain_names = list_domains(graph)
    now_ms = int(time.time() * 1000)

    grouped: dict[str, list[DatasetSignals]] = {}
    for urn in list_dataset_urns(graph):
        domain_urn = _domain_of(graph, urn)
        if domain_urn is None or domain_urn not in domain_names:
            continue
        signals = extract_signals(graph, urn, now_ms=now_ms)
        grouped.setdefault(domain_urn, []).append(signals)

    results: list[AuditedDomain] = []
    for domain_urn, signals in grouped.items():
        info = DomainInfo(urn=domain_urn, name=domain_names[domain_urn])
        dataset_scores = [score_dataset(s) for s in signals]
        results.append(
            AuditedDomain(
                info=info,
                score=score_domain(info.name, signals),
                dataset_scores=dataset_scores,
            )
        )

    results.sort(key=lambda a: a.score.score, reverse=True)
    return results


def _print_leaderboard(results: list[AuditedDomain]) -> None:
    from scoring.trust_score import trust_tier

    print(f"\n{'#':>2}  {'Team':<24} {'Score':>6}  {'Tier':<8} {'Datasets':>8}  Weakest")
    print("-" * 74)
    for i, a in enumerate(results, 1):
        ds = a.score
        print(
            f"{i:>2}  {a.info.name:<24} {ds.score:>6.1f}  {trust_tier(ds.score):<8} "
            f"{ds.dataset_count:>8}  {ds.weakest_component or '-'}"
        )


if __name__ == "__main__":
    _print_leaderboard(audit_all_domains())
