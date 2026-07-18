"""Agent 2: The Scribe.

Takes the Trust Scores computed by the Auditor and writes them BACK to the
DataHub graph in three complementary ways, so the score is discoverable both
by people and by other agents:

  1. domain-level structured property (trustScore + trustTier), queryable and
     filterable in the DataHub UI.
  2. tier tag (Trust: Gold/Silver/Bronze/At-Risk) on the domain, with
     remove-before-add so the old tier does not stay stuck.
  3. domain description with the per-component breakdown, inside an idempotent
     delimited block.

This is the step that satisfies the "contribute back to the graph, not just
read from it" criterion. Every write is idempotent: running the Scribe N times
leaves the same state.
"""
from __future__ import annotations

import time

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DomainPropertiesClass,
    StructuredPropertyDefinitionClass,
    TagPropertiesClass,
)

from agents.auditor import AuditedDomain, DomainInfo, audit_all_domains
from agents.incidents import remediate
from mcp_client.datahub_connection import execute_graphql_retry, get_graph
from scoring.trust_score import DomainScore, trust_tier

PROP_SCORE = "urn:li:structuredProperty:io.trustboard.trustScore"
PROP_TIER = "urn:li:structuredProperty:io.trustboard.trustTier"

TIERS = {
    "gold": ("urn:li:tag:trust.gold", "Trust: Gold", "#D4AF37"),
    "silver": ("urn:li:tag:trust.silver", "Trust: Silver", "#9AA0A6"),
    "bronze": ("urn:li:tag:trust.bronze", "Trust: Bronze", "#B87333"),
    "at-risk": ("urn:li:tag:trust.at-risk", "Trust: At-Risk", "#E03131"),
}

_DESC_START = "<!-- trustboard:start -->"
_DESC_END = "<!-- trustboard:end -->"


def _emit(graph, entity_urn: str, aspect) -> None:
    graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=aspect))


def ensure_definitions(graph) -> None:
    """Defines (idempotently) the structured properties and the tier tags."""
    _emit(
        graph,
        PROP_SCORE,
        StructuredPropertyDefinitionClass(
            qualifiedName="io.trustboard.trustScore",
            displayName="Trust Score",
            valueType="urn:li:dataType:datahub.number",
            cardinality="SINGLE",
            entityTypes=["urn:li:entityType:datahub.domain", "urn:li:entityType:datahub.dataset"],
            description="TrustBoard weekly trust score (0-100).",
        ),
    )
    _emit(
        graph,
        PROP_TIER,
        StructuredPropertyDefinitionClass(
            qualifiedName="io.trustboard.trustTier",
            displayName="Trust Tier",
            valueType="urn:li:dataType:datahub.string",
            cardinality="SINGLE",
            entityTypes=["urn:li:entityType:datahub.domain", "urn:li:entityType:datahub.dataset"],
            description="TrustBoard tier: gold, silver, bronze or at-risk.",
        ),
    )
    for _tier, (tag_urn, name, color) in TIERS.items():
        _emit(graph, tag_urn, TagPropertiesClass(name=name, description="TrustBoard tier badge.", colorHex=color))


_UPSERT_PROPS = """
mutation up($urn: String!, $score: Float!, $tier: String!) {
  upsertStructuredProperties(input: {
    assetUrn: $urn,
    structuredPropertyInputParams: [
      {structuredPropertyUrn: "%s", values: [{numberValue: $score}]},
      {structuredPropertyUrn: "%s", values: [{stringValue: $tier}]}
    ]
  }) { properties { structuredProperty { urn } } }
}
""" % (PROP_SCORE, PROP_TIER)

_ADD_TAG = "mutation a($tag:String!,$urn:String!){ addTag(input:{tagUrn:$tag,resourceUrn:$urn}) }"
_REMOVE_TAG = "mutation r($tag:String!,$urn:String!){ removeTag(input:{tagUrn:$tag,resourceUrn:$urn}) }"


def _write_structured_properties(graph, domain_urn: str, score: float, tier: str) -> None:
    execute_graphql_retry(graph, _UPSERT_PROPS, variables={"urn": domain_urn, "score": score, "tier": tier})


def _write_tier_tag(graph, asset_urn: str, tier: str) -> None:
    """Removes the tier tags that do not apply and adds the current one (idempotent).

    Applies to datasets (domains do not support the globalTags aspect). This
    leaves the catalog filterable by trust: "show me every Bronze dataset".
    """
    for name, (tag_urn, _n, _c) in TIERS.items():
        if name == tier:
            continue
        try:
            execute_graphql_retry(graph, _REMOVE_TAG, variables={"tag": tag_urn, "urn": asset_urn})
        except Exception:  # noqa: BLE001 - it was not set, no problem
            pass
    execute_graphql_retry(graph, _ADD_TAG, variables={"tag": TIERS[tier][0], "urn": asset_urn})


def _render_scorecard(score: DomainScore, tier: str) -> str:
    lines = [
        _DESC_START,
        f"**TrustBoard score: {score.score:.1f}/100 ({tier.upper()})**",
        "",
        "| Component | Score |",
        "| --- | --- |",
    ]
    for comp, value in score.component_averages.items():
        lines.append(f"| {comp} | {value:.0f} |")
    lines.append(f"| datasets evaluated | {score.dataset_count} |")
    if score.weakest_component:
        lines.append("")
        lines.append(f"Weakest signal: **{score.weakest_component}**. Improving it lifts the team's rank.")
    lines.append(_DESC_END)
    return "\n".join(lines)


def _write_description(graph, domain_urn: str, name: str, score: DomainScore, tier: str) -> None:
    """Updates the domain description with the scorecard inside a delimited block."""
    from datahub.metadata.schema_classes import DomainPropertiesClass as _DP

    current = graph.get_aspect(domain_urn, _DP)
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


def write_domain_score(graph, audited: AuditedDomain) -> None:
    """Writes a domain's Trust Score to the graph.

    At the domain level: structured property (score + tier) plus a description
    with the scorecard. At the dataset level: the individual tier tag of each
    dataset (domains do not support tags).
    """
    info, score = audited.info, audited.score
    tier = trust_tier(score.score)
    _write_structured_properties(graph, info.urn, score.score, tier)
    _write_description(graph, info.urn, info.name, score, tier)
    for ds in audited.dataset_scores:
        _write_tier_tag(graph, ds.urn, trust_tier(ds.score))


def write_all(graph=None, results: list[AuditedDomain] | None = None) -> list[AuditedDomain]:
    """Writes every score back to DataHub (audits first if no results are given)."""
    graph = graph or get_graph()
    ensure_definitions(graph)
    time.sleep(2)  # give the definitions time to register

    results = results if results is not None else audit_all_domains(graph)
    all_dataset_scores = []
    for audited in results:
        write_domain_score(graph, audited)
        all_dataset_scores.extend(audited.dataset_scores)
        tier = trust_tier(audited.score.score)
        print(
            f"  written: {audited.info.name:<24} score={audited.score.score:.1f} "
            f"tier={tier}  ({len(audited.dataset_scores)} datasets tagged)"
        )

    # Remediation: raise/resolve incidents on the toxic datasets.
    report = remediate(graph, all_dataset_scores)
    print(
        f"\nIncidents: {report.raised} raised, {report.resolved} resolved, "
        f"{report.unchanged} unchanged."
    )
    return results


if __name__ == "__main__":
    print("Writing Trust Scores back to the DataHub graph...\n")
    write_all()
    print("\nOK: scores written as structured property + tag + description on each domain.")
