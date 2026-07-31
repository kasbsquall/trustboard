"""Agent 1: The Auditor.

Walks the DataHub datasets, extracts quality, documentation, ownership and
freshness signals by reading aspects through the SDK, groups them by domain
(team) and computes the composite Trust Score using scoring.trust_score.

Returns one DomainScore per team, ready for the Scribe to write back to the
graph and for the Herald to publish.

Two things here are deliberate and worth reading before changing them.

Signals have a preference order, and which one was used travels with the score.
Quality prefers real data assertions and falls back to DataHub Tests; freshness
prefers the Operation aspect (when the data changed) and falls back through the
dataset profile to the metadata audit stamp. The fallbacks mean far less than
the primary source, so the score reports which one answered rather than
presenting them as equivalent.

A signal that cannot be read is not a signal worth zero. get_aspect answers 404
for an aspect that is genuinely absent, and raises for anything else. Absent is
a fact and feeds the coverage figure. A 500 from an overloaded GMS is not a
fact, so the dataset is dropped from the audit and counted, and a run that loses
too many datasets refuses to publish instead of shipping a leaderboard built on
whatever happened to answer.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from datahub.metadata.schema_classes import (
    DatasetProfileClass,
    DatasetPropertiesClass,
    DomainsClass,
    EditableDatasetPropertiesClass,
    EditableSchemaMetadataClass,
    GlossaryTermsClass,
    OperationClass,
    OwnershipClass,
    SchemaMetadataClass,
    TestResultsClass,
    UpstreamLineageClass,
)

from mcp_client.datahub_connection import execute_graphql_retry, get_graph
from scoring.trust_score import (
    DatasetScore,
    DatasetSignals,
    DomainScore,
    FreshnessSource,
    score_dataset,
    score_domain,
)

_MS_PER_DAY = 86_400_000


def _today_ms() -> int:
    """Now, floored to midnight UTC, so a score does not drift with the clock."""
    return int(time.time() * 1000) // _MS_PER_DAY * _MS_PER_DAY

# Search returns one page at a time. The old code asked for a single page of 200
# and treated it as the whole graph, so dataset 201 onwards simply did not
# exist as far as the score was concerned.
_PAGE = 100

# Datasets per batched assertions query. Large enough to make the round trips
# negligible, small enough that one bad URN does not cost the whole run.
_ASSERTION_BATCH = 25

# Above this share of unreadable datasets the audit refuses to publish. A run
# that lost a fifth of the graph to transport errors does not produce a
# leaderboard, it produces a ranking of whichever teams happened to answer.
MAX_UNREADABLE_RATIO = 0.20


class SignalReadError(Exception):
    """A dataset's aspects could not be read, so it has no honest score."""


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


def _aspect(graph, urn: str, aspect_type, retries: int = 3):
    """Reads a versioned aspect. None means absent; a read failure raises.

    Absent and unreadable are different facts and the score depends on the
    difference: absent lowers coverage, unreadable invalidates the dataset.
    Collapsing both into None is what lets a GMS hiccup quietly rewrite a team's
    score downward with no trace in the output.
    """
    for attempt in range(retries):
        try:
            return graph.get_aspect(urn, aspect_type)
        except Exception as err:  # noqa: BLE001
            if attempt == retries - 1:
                raise SignalReadError(
                    f"{aspect_type.ASPECT_NAME} of {urn}: {type(err).__name__}"
                ) from None
            time.sleep(2 ** attempt)
    return None


def _latest_timeseries(graph, urn: str, aspect_type):
    """Latest value of a timeseries aspect, or None when there is none.

    Timeseries aspects go through a different endpoint that answers with an
    empty list rather than a 404, and the SDK refuses them through get_aspect
    outright.

    Retried like any other read, and a failure that survives the retries is
    raised rather than swallowed. Returning None on an error looked harmless and
    was not: `Operation` is where freshness learns when the DATA changed, so one
    transient 500 silently demoted a dataset to the crawler's own audit stamp,
    the source this module calls misleading, at 20% of the score weight, with
    nothing in the coverage figure or the run summary to show it happened.
    """
    for attempt in range(3):
        try:
            values = graph.get_timeseries_values(
                entity_urn=urn, aspect_type=aspect_type, filter={}, limit=1
            )
            return values[0] if values else None
        except Exception as err:
            if attempt == 2:
                raise SignalReadError(
                    f"could not read {aspect_type.__name__} for {urn}: {err}"
                ) from err
            time.sleep(2 ** attempt)
    return None


def _paged_search(graph, entity_type: str, extra_fields: str = "") -> list[dict]:
    """Every entity of a type, walking the pages instead of taking the first."""
    out: list[dict] = []
    start = 0
    while True:
        query = (
            f'{{ search(input: {{type: {entity_type}, query: "*", '
            f"start: {start}, count: {_PAGE}}}) "
            f"{{ total searchResults {{ entity {{ urn {extra_fields} }} }} }} }}"
        )
        page = execute_graphql_retry(graph, query)["search"]
        results = page.get("searchResults") or []
        out.extend(r["entity"] for r in results)
        # Advance by what came back, not by what was asked for. A GMS that caps
        # the page size below _PAGE would have left this skipping the entities in
        # between, silently, which is the same first-page-is-everything family of
        # bug the loop exists to avoid. incidents.py already did it this way.
        start += len(results)
        if not results or start >= (page.get("total") or 0):
            break
    return out


def list_domains(graph) -> dict[str, str]:
    """Returns {domain_urn: name} for the domains that have a name."""
    entities = _paged_search(graph, "DOMAIN", "... on Domain { properties { name } }")
    out: dict[str, str] = {}
    for e in entities:
        name = (e.get("properties") or {}).get("name")
        if name:
            out[e["urn"]] = name
    return out


def list_dataset_urns(graph) -> list[str]:
    # Sorted so that two runs over the same graph walk it in the same order.
    # Search ranks by relevance, and that ranking moves once the Scribe writes
    # tags back.
    return sorted(e["urn"] for e in _paged_search(graph, "DATASET"))


_ASSERTIONS_QUERY = """
query a($urns: [String!]!) {
  entities(urns: $urns) {
    urn
    ... on Dataset {
      assertions(start: 0, count: 100) {
        total
        assertions {
          urn
          runEvents(limit: 1) { total failed succeeded }
        }
      }
    }
  }
}
"""


def fetch_assertion_results(graph, dataset_urns: list[str]) -> dict[str, tuple[int, int]]:
    """Returns {dataset_urn: (passing, failing)} from real data assertions.

    Batched, because the alternative is one round trip per dataset for a signal
    most demo graphs do not have at all. A GMS that does not expose the
    assertions field answers with an error; that degrades quality to DataHub
    Tests and says so on stderr, rather than pretending the datasets all passed.
    """
    out: dict[str, tuple[int, int]] = {}
    for i in range(0, len(dataset_urns), _ASSERTION_BATCH):
        batch = dataset_urns[i : i + _ASSERTION_BATCH]
        try:
            res = execute_graphql_retry(graph, _ASSERTIONS_QUERY, variables={"urns": batch})
        except Exception as err:
            # All or nothing, and this used to return whatever it had collected
            # so far. That looked harmless and was the worst kind of failure this
            # codebase has: a batch erroring on URN 40 of 67 left the first
            # thirty-nine scored from assertions and the rest silently demoted to
            # catalog tests capped at 60%, a swing of roughly fourteen points
            # decided by where a URN happened to sort. Nothing was added to the
            # unreadable count, so MAX_UNREADABLE_RATIO never got to rule on the
            # run, and the leaderboard published a confident number built partly
            # on a timeout. A whole-graph fallback is a fact about the GMS that
            # the run reports and every dataset shares; a partial one is noise
            # wearing the shape of data.
            if i > 0:
                raise SignalReadError(
                    f"assertions failed on batch {i // _ASSERTION_BATCH + 1} after "
                    f"{len(out)} datasets had already been read; refusing to score "
                    f"half the graph from assertions and half from catalog tests ({err})"
                ) from err
            print(
                f"  note: assertions unavailable on this GMS "
                f"({type(err).__name__}), quality falls back to DataHub Tests",
                file=sys.stderr,
            )
            return {}
        for entity in res.get("entities") or []:
            if not entity:
                continue
            block = entity.get("assertions") or {}
            passing = failing = 0
            for a in block.get("assertions") or []:
                runs = a.get("runEvents") or {}
                passing += runs.get("succeeded") or 0
                failing += runs.get("failed") or 0
            if passing + failing > 0:
                out[entity["urn"]] = (passing, failing)
    return out


def build_downstream_counts(graph, dataset_urns: list[str]) -> dict[str, int]:
    """Returns {dataset_urn: how many datasets read from it}.

    Built by inverting each dataset's UpstreamLineage rather than querying
    lineage per dataset, which keeps it to reads this audit already performs.
    It counts dataset consumers only: a table feeding thirty dashboards and no
    tables registers as zero here, so the weighting understates BI blast radius
    and never overstates it.
    """
    counts: dict[str, int] = {urn: 0 for urn in dataset_urns}
    for urn in dataset_urns:
        lineage = _aspect(graph, urn, UpstreamLineageClass)
        for up in (lineage.upstreams if lineage else None) or []:
            if up.dataset in counts:
                counts[up.dataset] += 1
    return counts


def _read_freshness(
    graph, dataset_urn: str, props, now_ms: int
) -> tuple[float | None, FreshnessSource]:
    """Days since the data changed, and which source that claim rests on.

    Operation carries lastUpdatedTimestamp, which is the only one of the three
    that is about the data. The profile timestamp says when someone last looked
    at it. DatasetProperties.lastModified is the metadata's own audit stamp and
    on most ingestion setups it moves every time the crawler runs, whether or
    not a single row changed, which is why it is last and labelled.
    """
    op = _latest_timeseries(graph, dataset_urn, OperationClass)
    if op is not None:
        stamp = op.lastUpdatedTimestamp or op.timestampMillis
        if stamp:
            return max(0.0, (now_ms - stamp) / _MS_PER_DAY), FreshnessSource.OPERATIONS

    profile = _latest_timeseries(graph, dataset_urn, DatasetProfileClass)
    if profile is not None and profile.timestampMillis:
        return (
            max(0.0, (now_ms - profile.timestampMillis) / _MS_PER_DAY),
            FreshnessSource.PROFILE,
        )

    if props and props.lastModified and props.lastModified.time:
        return (
            max(0.0, (now_ms - props.lastModified.time) / _MS_PER_DAY),
            FreshnessSource.METADATA,
        )

    return None, FreshnessSource.NONE


def extract_signals(
    graph,
    dataset_urn: str,
    now_ms: int | None = None,
    assertion_results: tuple[int, int] | None = None,
    downstream_count: int = 0,
) -> DatasetSignals:
    """Reads a dataset's aspects and translates them into DatasetSignals.

    Raises SignalReadError when an aspect cannot be read, so the caller can drop
    the dataset instead of scoring it on partial evidence.
    """
    # Floored to the day. Freshness is days-since-change over a 30-day window, so
    # an unfloored clock moved every score by about 0.14 points an hour with
    # nothing in the graph changing, and the README's claim that two runs give
    # identical scores held only within the same minute.
    now_ms = now_ms or _today_ms()

    # Quality, fallback source: DataHub Tests. These check catalog compliance,
    # not the data, which is why assertions win when both are present.
    test_results = _aspect(graph, dataset_urn, TestResultsClass)
    passing = len(test_results.passing or []) if test_results else 0
    failing = len(test_results.failing or []) if test_results else 0
    has_tests = test_results is not None and (passing + failing) > 0

    a_pass, a_fail = assertion_results or (0, 0)

    # Documentation: dataset-level description (editable or from the source).
    editable = _aspect(graph, dataset_urn, EditableDatasetPropertiesClass)
    props = _aspect(graph, dataset_urn, DatasetPropertiesClass)
    has_description = bool(
        (editable and editable.description) or (props and props.description)
    )

    # Documentation: field-level docs.
    has_field_docs = False
    editable_schema = _aspect(graph, dataset_urn, EditableSchemaMetadataClass)
    if editable_schema and editable_schema.editableSchemaFieldInfo:
        has_field_docs = any(f.description for f in editable_schema.editableSchemaFieldInfo)
    if not has_field_docs:
        schema = _aspect(graph, dataset_urn, SchemaMetadataClass)
        if schema and schema.fields:
            has_field_docs = any(f.description for f in schema.fields)

    # Documentation: glossary.
    terms = _aspect(graph, dataset_urn, GlossaryTermsClass)
    has_glossary_terms = bool(terms and terms.terms)

    # Ownership.
    ownership = _aspect(graph, dataset_urn, OwnershipClass)
    has_owner = bool(ownership and ownership.owners)

    freshness_days, freshness_source = _read_freshness(graph, dataset_urn, props, now_ms)

    return DatasetSignals(
        urn=dataset_urn,
        assertions_passing=a_pass,
        assertions_failing=a_fail,
        has_assertions=(a_pass + a_fail) > 0,
        tests_passing=passing,
        tests_failing=failing,
        has_tests=has_tests,
        has_description=has_description,
        has_field_docs=has_field_docs,
        has_glossary_terms=has_glossary_terms,
        has_owner=has_owner,
        freshness_days=freshness_days,
        freshness_source=freshness_source,
        downstream_count=downstream_count,
    )


def _domain_of(graph, dataset_urn: str) -> str | None:
    domains = _aspect(graph, dataset_urn, DomainsClass)
    if domains and domains.domains:
        return domains.domains[0]
    return None


def audit_all_domains(graph=None) -> list[AuditedDomain]:
    """Walks DataHub and returns the Trust Score of each domain (team)."""
    graph = graph or get_graph()
    domain_names = list_domains(graph)
    now_ms = _today_ms()

    urns = list_dataset_urns(graph)
    assertions = fetch_assertion_results(graph, urns)
    # Guarded, because build_downstream_counts calls _aspect and therefore
    # raises SignalReadError. Unprotected, a single transient 500 on one lineage
    # read among hundreds aborted the whole weekly run three lines before
    # MAX_UNREADABLE_RATIO, the mechanism that exists to decide whether a partial
    # read is publishable, got a chance to look at it. Blast radius is a
    # refinement of the aggregate, so losing it costs precision, not correctness:
    # every dataset falls back to weight 1.0, which is the flat mean.
    try:
        downstream = build_downstream_counts(graph, urns)
    except SignalReadError as err:
        print(f"  lineage unavailable, weighting every dataset equally ({err})")
        downstream = {}

    grouped: dict[str, list[DatasetSignals]] = {}
    unreadable: list[str] = []

    for urn in urns:
        try:
            domain_urn = _domain_of(graph, urn)
            if domain_urn is None or domain_urn not in domain_names:
                continue
            signals = extract_signals(
                graph,
                urn,
                now_ms=now_ms,
                assertion_results=assertions.get(urn),
                downstream_count=downstream.get(urn, 0),
            )
        except SignalReadError as err:
            unreadable.append(str(err))
            continue
        grouped.setdefault(domain_urn, []).append(signals)

    if unreadable:
        scored = sum(len(v) for v in grouped.values())
        total = scored + len(unreadable)
        print(
            f"  warning: {len(unreadable)} of {total} datasets could not be read "
            f"and were excluded from the score",
            file=sys.stderr,
        )
        for line in unreadable[:5]:
            print(f"    - {line}", file=sys.stderr)
        if total and len(unreadable) / total > MAX_UNREADABLE_RATIO:
            raise SignalReadError(
                f"{len(unreadable)} of {total} datasets unreadable, above the "
                f"{MAX_UNREADABLE_RATIO:.0%} limit. Refusing to publish a "
                "leaderboard built on a partial read of the graph."
            )

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


def print_quality_sources(results: list[AuditedDomain]) -> None:
    """Prints which source backed the quality signal, in three groups.

    Three and not two, because "no signal at all" is not a weaker measurement,
    it is the absence of one, and this is the distinction the whole scoring model
    is built on. Printed from here rather than under __main__ so the command the
    Quickstart actually gives you shows it.
    """
    counts: dict[str, int] = {}
    for a in results:
        for source, n in a.score.quality_sources.items():
            counts[source] = counts.get(source, 0) + n
    print(
        f"      quality read from: assertions={counts.get('assertions', 0)}, "
        f"catalog tests={counts.get('metadata-tests', 0)}, "
        f"no quality signal={counts.get('none', 0)}"
    )


def _print_leaderboard(results: list[AuditedDomain]) -> None:
    from scoring.trust_score import trust_tier

    header = (
        f"\n{'#':>2}  {'Team':<24} {'Score':>6}  {'Tier':<8} {'Datasets':>8} "
        f"{'Cov':>5}  Weakest"
    )
    print(header)
    print("-" * len(header))
    for i, a in enumerate(results, 1):
        ds = a.score
        print(
            f"{i:>2}  {a.info.name:<24} {ds.score:>6.1f}  "
            f"{trust_tier(ds.score, ds.rated):<8} {ds.dataset_count:>8} "
            f"{ds.coverage:>5.2f}  {ds.weakest_component or '-'}"
        )
    sources: dict[str, int] = {}
    for a in results:
        for src, n in a.score.quality_sources.items():
            sources[src] = sources.get(src, 0) + n
    if sources:
        print("\nQuality signal source: " + ", ".join(f"{k}={v}" for k, v in sorted(sources.items())))


if __name__ == "__main__":
    from mcp_client.datahub_connection import cli

    cli(lambda: _print_leaderboard(audit_all_domains()))
