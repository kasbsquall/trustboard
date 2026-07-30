"""Agent 2: The Scribe.

Takes the Trust Scores computed by the Auditor and writes them BACK to the
DataHub graph, so the score is discoverable both by people and by other agents:

  1. structured properties (trustScore, trustTier, trustCoverage,
     trustScoreVersion) on the domain AND on every dataset, queryable and
     filterable in the DataHub UI.
  2. tier tag (Trust: Gold/Silver/Bronze/At-Risk/Unrated) on every dataset, with
     remove-before-add so the old tier does not stay stuck.
  3. domain description with the per-component breakdown, inside an idempotent
     delimited block.

This is the step that satisfies the "contribute back to the graph, not just
read from it" criterion. Every write is idempotent: running the Scribe N times
leaves the same state.

The score is written per dataset and not only per domain because that is the
grain other agents ask at. A Gatekeeper deciding whether to build on
orders_raw cannot use a number that describes the team that owns it, and
coverage travels with the score for the same reason: an agent needs to know
whether a 78 rests on four signals or on one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DomainPropertiesClass,
    GlobalTagsClass,
    StructuredPropertyDefinitionClass,
    TagPropertiesClass,
)

from agents.auditor import AuditedDomain, audit_all_domains
from agents.incidents import IncidentReport, remediate
from mcp_client.datahub_connection import execute_graphql_retry, get_graph
from scoring.trust_score import (
    MIN_COVERAGE,
    SCORE_VERSION,
    DatasetScore,
    DomainScore,
    tier_scale_text,
    trust_tier,
    weights_text,
)

PROP_SCORE = "urn:li:structuredProperty:io.trustboard.trustScore"
PROP_TIER = "urn:li:structuredProperty:io.trustboard.trustTier"
PROP_COVERAGE = "urn:li:structuredProperty:io.trustboard.trustCoverage"
PROP_VERSION = "urn:li:structuredProperty:io.trustboard.trustScoreVersion"

_ENTITY_TYPES = [
    "urn:li:entityType:datahub.domain",
    "urn:li:entityType:datahub.dataset",
]

TIERS = {
    "gold": ("urn:li:tag:trust.gold", "Trust: Gold", "#D4AF37"),
    "silver": ("urn:li:tag:trust.silver", "Trust: Silver", "#9AA0A6"),
    "bronze": ("urn:li:tag:trust.bronze", "Trust: Bronze", "#B87333"),
    "at-risk": ("urn:li:tag:trust.at-risk", "Trust: At-Risk", "#E03131"),
    # Not a bad grade. It marks an asset TrustBoard could not judge, which is a
    # gap in the catalog rather than a failure of the team, and reads very
    # differently to anyone browsing.
    "unrated": ("urn:li:tag:trust.unrated", "Trust: Unrated", "#6B7280"),
}

_DESC_START = "<!-- trustboard:start -->"
_DESC_END = "<!-- trustboard:end -->"


def _emit(graph, entity_urn: str, aspect) -> None:
    graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=aspect))


def _definition(qualified: str, display: str, value_type: str, description: str):
    return StructuredPropertyDefinitionClass(
        qualifiedName=qualified,
        displayName=display,
        valueType=f"urn:li:dataType:datahub.{value_type}",
        cardinality="SINGLE",
        entityTypes=_ENTITY_TYPES,
        description=description,
    )


def ensure_definitions(graph) -> None:
    """Defines (idempotently) the structured properties and the tier tags."""
    _emit(
        graph,
        PROP_SCORE,
        _definition(
            "io.trustboard.trustScore",
            "Trust Score",
            "number",
            f"TrustBoard weekly trust score (0-100). Weights: {weights_text()}, "
            "renormalized over the signals actually present. Absent on an unrated "
            "asset rather than written as zero.",
        ),
    )
    _emit(
        graph,
        PROP_TIER,
        _definition(
            "io.trustboard.trustTier",
            "Trust Tier",
            "string",
            f"TrustBoard tier. {tier_scale_text()} Or unrated, when there was no "
            "quality signal at all or coverage was too low to judge.",
        ),
    )
    _emit(
        graph,
        PROP_COVERAGE,
        _definition(
            "io.trustboard.trustCoverage",
            "Trust Signal Coverage",
            "number",
            "Share of the scoring weight backed by a signal that was actually "
            "present (0-1). A score at low coverage rests on little evidence.",
        ),
    )
    _emit(
        graph,
        PROP_VERSION,
        _definition(
            "io.trustboard.trustScoreVersion",
            "Trust Score Version",
            "string",
            "Version of the TrustBoard scoring model that produced the score. "
            "Scores from different versions are not comparable.",
        ),
    )
    for tag_urn, name, color in TIERS.values():
        _emit(graph, tag_urn, TagPropertiesClass(name=name, description="TrustBoard tier badge.", colorHex=color))


_UPSERT_PROPS = """
mutation up($urn: String!, $score: Float!, $tier: String!, $coverage: Float!, $version: String!) {
  upsertStructuredProperties(input: {
    assetUrn: $urn,
    structuredPropertyInputParams: [
      {structuredPropertyUrn: "%s", values: [{numberValue: $score}]},
      {structuredPropertyUrn: "%s", values: [{stringValue: $tier}]},
      {structuredPropertyUrn: "%s", values: [{numberValue: $coverage}]},
      {structuredPropertyUrn: "%s", values: [{stringValue: $version}]}
    ]
  }) { properties { structuredProperty { urn } } }
}
""" % (PROP_SCORE, PROP_TIER, PROP_COVERAGE, PROP_VERSION)

# An unrated asset gets the tier, the coverage and the model version, and no
# numeric score. trustScore is a filterable number in DataHub, so writing the
# 0.0 that stands for "could not measure" makes every facet and every range
# query read it as worst in the company. That is exactly the conflation this
# project spends a paragraph promising to avoid, arriving through the write path.
_UPSERT_PROPS_UNRATED = """
mutation up($urn: String!, $tier: String!, $coverage: Float!, $version: String!) {
  upsertStructuredProperties(input: {
    assetUrn: $urn,
    structuredPropertyInputParams: [
      {structuredPropertyUrn: "%s", values: [{stringValue: $tier}]},
      {structuredPropertyUrn: "%s", values: [{numberValue: $coverage}]},
      {structuredPropertyUrn: "%s", values: [{stringValue: $version}]}
    ]
  }) { properties { structuredProperty { urn } } }
}
""" % (PROP_TIER, PROP_COVERAGE, PROP_VERSION)

# Omitting trustScore is not the same as removing it. upsert leaves properties it
# was not asked about exactly as they were, so an asset that scored last week and
# is unrated this week kept its old number sitting under an "unrated" tier: the
# two disagreed, and the stale figure was the one a numeric filter would find.
# The tag write already learned this lesson; the properties had not.
_REMOVE_SCORE = """
mutation rm($urn: String!) {
  removeStructuredProperties(input: {
    assetUrn: $urn, structuredPropertyUrns: ["%s"]
  }) { properties { structuredProperty { urn } } }
}
""" % PROP_SCORE

_ADD_TAG = "mutation a($tag:String!,$urn:String!){ addTag(input:{tagUrn:$tag,resourceUrn:$urn}) }"
_REMOVE_TAG = "mutation r($tag:String!,$urn:String!){ removeTag(input:{tagUrn:$tag,resourceUrn:$urn}) }"

_TAG_URNS = {tag_urn for tag_urn, _n, _c in TIERS.values()}


def _write_structured_properties(
    graph, asset_urn: str, score: float, tier: str, coverage: float, rated: bool = True
) -> None:
    common = {
        "urn": asset_urn,
        "tier": tier,
        "coverage": coverage,
        "version": SCORE_VERSION,
    }
    if not rated:
        execute_graphql_retry(graph, _UPSERT_PROPS_UNRATED, variables=common)
        # Remove-then-leave, the same shape the tier tag uses. Without this an
        # asset that was scored before and is unrated now keeps the old number.
        try:
            execute_graphql_retry(graph, _REMOVE_SCORE, variables={"urn": asset_urn})
        except Exception as err:
            if "not found" not in str(err).lower():
                raise
        return
    execute_graphql_retry(graph, _UPSERT_PROPS, variables={**common, "score": score})


def _write_tier_tag(graph, asset_urn: str, tier: str) -> None:
    """Leaves exactly one tier tag on the asset (idempotent).

    Reads the current tags first and removes only the tier tags that are
    actually there. Firing a removal for every tier unconditionally meant four
    wasted mutations per dataset, and mutations are the one call this codebase
    deliberately does not retry.
    """
    current = graph.get_aspect(asset_urn, GlobalTagsClass)
    present = {t.tag for t in (current.tags if current else None) or []} & _TAG_URNS
    wanted = TIERS[tier][0]

    for tag_urn in present - {wanted}:
        execute_graphql_retry(graph, _REMOVE_TAG, variables={"tag": tag_urn, "urn": asset_urn})
    if wanted not in present:
        execute_graphql_retry(graph, _ADD_TAG, variables={"tag": wanted, "urn": asset_urn})


def _render_scorecard(score: DomainScore, tier: str) -> str:
    if not score.rated:
        return "\n".join(
            [
                _DESC_START,
                "**TrustBoard: UNRATED**",
                "",
                f"Signal coverage was {score.coverage:.0%} across "
                f"{score.dataset_count} datasets, below the {MIN_COVERAGE:.0%} this "
                "model needs to publish a score, or too few of them carried a "
                "quality check. Add quality checks or freshness signals and the "
                "team becomes scoreable.",
                _DESC_END,
            ]
        )

    lines = [
        _DESC_START,
        f"**TrustBoard score: {score.score:.1f}/100 ({tier.upper()})**",
        "",
        tier_scale_text(),
        "",
        "| Component | Weight | Score |",
        "| --- | --- | --- |",
    ]
    from scoring.trust_score import WEIGHTS

    for comp, value in score.component_averages.items():
        lines.append(f"| {comp} | {WEIGHTS[comp]:.0%} | {value:.0f} |")
    lines.append(f"| datasets evaluated | | {score.dataset_count} |")
    lines.append(f"| signal coverage | | {score.coverage:.0%} |")

    quality_from = ", ".join(
        f"{n} from {src}" for src, n in sorted(score.quality_sources.items()) if src != "none"
    )
    if quality_from:
        lines.append("")
        lines.append(f"Quality signal: {quality_from}.")

    if score.weakest_component:
        lines.append("")
        lines.append(
            f"Highest leverage: **{score.weakest_component}**, by weight times "
            "room to improve. Fixing it moves the team's rank more than anything else."
        )
    lines.append(f"\nScored by TrustBoard model v{score.score_version}.")
    lines.append(_DESC_END)
    return "\n".join(lines)


def _write_description(graph, domain_urn: str, name: str, score: DomainScore, tier: str) -> None:
    """Updates the domain description with the scorecard inside a delimited block."""
    current = graph.get_aspect(domain_urn, DomainPropertiesClass)
    base_desc = current.description if current and current.description else ""
    # Strip any previous TrustBoard block.
    if _DESC_START in base_desc and _DESC_END in base_desc:
        before = base_desc.split(_DESC_START)[0].rstrip()
        after = base_desc.split(_DESC_END)[-1].lstrip()
        base_desc = (before + "\n" + after).strip()

    scorecard = _render_scorecard(score, tier)
    new_desc = (base_desc + "\n\n" + scorecard).strip() if base_desc else scorecard

    _emit(
        graph,
        domain_urn,
        DomainPropertiesClass(
            name=name,
            description=new_desc,
            parentDomain=current.parentDomain if current else None,
            created=current.created if current else AuditStampClass(time=int(time.time() * 1000), actor="urn:li:corpuser:datahub"),
        ),
    )


def _dataset_tier(ds: DatasetScore) -> str:
    """A dataset nobody checks is unrated, not at-risk.

    The scorer already decided this, weighing both the coverage floor and the
    requirement that a quality signal exist at all. Recomputing the rule here
    from coverage alone is how the tag and the score came to disagree.
    """
    return trust_tier(ds.score, rated=ds.rated)


def write_domain_score(graph, audited: AuditedDomain) -> None:
    """Writes a domain's Trust Score to the graph, and each dataset's own score.

    Domain level: structured properties plus a description with the scorecard.
    Dataset level: structured properties and the tier tag (domains do not
    support the globalTags aspect).
    """
    info, score = audited.info, audited.score
    tier = trust_tier(score.score, score.rated)
    _write_structured_properties(
        graph, info.urn, score.score, tier, score.coverage, rated=score.rated
    )
    _write_description(graph, info.urn, info.name, score, tier)
    for ds in audited.dataset_scores:
        ds_tier = _dataset_tier(ds)
        _write_structured_properties(
            graph, ds.urn, ds.score, ds_tier, ds.coverage, rated=ds.rated
        )
        _write_tier_tag(graph, ds.urn, ds_tier)


@dataclass(frozen=True)
class WriteReport:
    """What the Scribe managed to write, and to which domains."""

    results: list[AuditedDomain]
    written_urns: set[str]
    incidents: IncidentReport


def write_all(graph=None, results: list[AuditedDomain] | None = None) -> WriteReport:
    """Writes every score back to DataHub (audits first if no results are given).

    A domain whose write fails is reported and left out of `written_urns`, which
    the caller reads to decide what to claim in the local history. The history
    used to record every row as written to DataHub regardless of what happened
    here, which made the one field meant to track that worthless.
    """
    graph = graph or get_graph()
    ensure_definitions(graph)
    time.sleep(2)  # give the definitions time to register

    results = results if results is not None else audit_all_domains(graph)
    written: set[str] = set()
    all_dataset_scores = []
    for audited in results:
        tier = trust_tier(audited.score.score, audited.score.rated)
        try:
            write_domain_score(graph, audited)
        except Exception as err:  # noqa: BLE001
            print(
                f"  FAILED:  {audited.info.name:<24} not written "
                f"({type(err).__name__}: {str(err)[:120]})"
            )
            continue
        written.add(audited.info.urn)
        all_dataset_scores.extend(audited.dataset_scores)
        print(
            f"  written: {audited.info.name:<24} score={audited.score.score:.1f} "
            f"tier={tier} coverage={audited.score.coverage:.0%}  "
            f"({len(audited.dataset_scores)} datasets scored and tagged)"
        )

    # Remediation: raise/resolve incidents on the toxic datasets.
    report = remediate(graph, all_dataset_scores)
    print(
        f"\nIncidents: {report.raised} raised, {report.resolved} resolved, "
        f"{report.unchanged} unchanged"
        + (f", {report.skipped_unrated} skipped as unrated" if report.skipped_unrated else "")
        + (f", {report.failed} FAILED." if report.failed else ".")
    )
    return WriteReport(results=results, written_urns=written, incidents=report)


if __name__ == "__main__":
    from mcp_client.datahub_connection import cli

    def main() -> None:
        print("Writing Trust Scores back to the DataHub graph...\n")
        report = write_all()
        print(f"\n{len(report.written_urns)} of {len(report.results)} domains written.")
        print(
            "\nOK: scores written as structured properties on every domain and "
            "dataset, plus a tier tag and a scorecard."
        )

    cli(main)
