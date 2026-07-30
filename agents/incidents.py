"""Remediation through incidents (part of the Scribe).

Turns the Auditor from a meter into a remediator: it raises an Incident in
DataHub on every "toxic" dataset (Trust Score below the threshold) explaining
which signal failed, and RESOLVES the incident once the dataset recovers. This
is real action, visible in the DataHub UI, not a passive annotation.

Idempotent: before raising, it queries the dataset's ACTIVE TrustBoard
incidents, so it does not duplicate. The title prefix identifies our own
incidents.
"""
from __future__ import annotations

from dataclasses import dataclass

from mcp_client.datahub_connection import execute_graphql_retry
from scoring.trust_score import AT_RISK_THRESHOLD, WEIGHTS, DatasetScore

TITLE_PREFIX = "TrustBoard:"

_QUERY_INCIDENTS = """
query i($urn: String!) {
  entity(urn: $urn) { ... on Dataset {
    incidents(start: 0, count: 50) { incidents { urn title status { state } } }
  } }
}
"""
_RAISE = """
mutation r($urn: String!, $title: String!, $desc: String!) {
  raiseIncident(input: {resourceUrn: $urn, type: OPERATIONAL, title: $title, description: $desc})
}
"""
_RESOLVE = """
mutation res($urn: String!, $msg: String!) {
  updateIncidentStatus(urn: $urn, input: {state: RESOLVED, message: $msg})
}
"""


@dataclass(frozen=True)
class IncidentReport:
    raised: int = 0
    resolved: int = 0
    unchanged: int = 0
    failed: int = 0
    # Datasets whose signal coverage was too low to judge. Reported apart from
    # unchanged so a run over a thinly catalogued graph does not look like a run
    # where everything was already fine.
    skipped_unrated: int = 0


def _short_name(dataset_urn: str) -> str:
    # urn:li:dataset:(urn:li:dataPlatform:dbt,name,PROD) -> name
    if "," in dataset_urn:
        return dataset_urn.split(",")[1]
    return dataset_urn


def _weakest(ds: DatasetScore) -> str:
    """Highest-leverage component: weight times room to improve.

    Same rule the domain scorecard uses. Picking the lowest raw value instead
    would have the incident and the scorecard point a team at two different
    signals for the same problem.
    """
    comps = {k: v for k, v in ds.components.as_dict().items() if v is not None}
    if not comps:
        return "quality"
    return max(comps, key=lambda c: WEIGHTS[c] * (100.0 - comps[c]))


def _active_incidents(graph, dataset_urn: str) -> list[str]:
    """Returns the URNs of this dataset's open TrustBoard incidents.

    The failure is deliberately not swallowed. Returning an empty list on a
    failed query reads as "nothing is open", so the next step raises a
    duplicate incident on a dataset that already has one, and it does that
    again every week. Idempotency here depends on knowing what is open.
    """
    res = execute_graphql_retry(graph, _QUERY_INCIDENTS, variables={"urn": dataset_urn})
    entity = res.get("entity") or {}
    incidents = ((entity.get("incidents") or {}).get("incidents")) or []
    return [
        inc["urn"]
        for inc in incidents
        if (inc.get("title") or "").startswith(TITLE_PREFIX)
        and ((inc.get("status") or {}).get("state") == "ACTIVE")
    ]


def remediate(graph, dataset_scores: list[DatasetScore], threshold: float = AT_RISK_THRESHOLD) -> IncidentReport:
    """Raises/resolves incidents according to each dataset's Trust Score.

    Failures are counted apart from no-ops. Folding them into 'unchanged'
    turns a run where every call errored into a summary that reads exactly
    like a run where there was nothing to do.

    An unrated dataset never gets an incident, and the test is the scorer's own
    `rated` flag rather than a coverage comparison repeated here. Re-deriving the
    rule locally missed the case it exists for: a table nobody checks can still
    have 0.65 coverage from documentation, ownership and a crawler timestamp, so a
    coverage test would have waved it through and paged somebody about data that
    was never measured.
    """
    raised = resolved = unchanged = failed = skipped = 0

    for ds in dataset_scores:
        if not ds.rated:
            skipped += 1
            continue
        try:
            active = _active_incidents(graph, ds.urn)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        is_toxic = ds.score < threshold

        if is_toxic and not active:
            weak = _weakest(ds)
            title = f"{TITLE_PREFIX} {_short_name(ds.urn)} is at-risk ({ds.score:.0f}/100)"
            desc = (
                f"Trust Score {ds.score:.0f}/100, below the {threshold:.0f} threshold. "
                f"Weakest signal: **{weak}**. Improving {weak} will clear this incident."
            )
            try:
                execute_graphql_retry(graph, _RAISE, variables={"urn": ds.urn, "title": title, "desc": desc})
                raised += 1
            except Exception:  # noqa: BLE001
                failed += 1
        elif not is_toxic and active:
            for inc_urn in active:
                try:
                    execute_graphql_retry(
                        graph, _RESOLVE,
                        variables={"urn": inc_urn, "msg": f"Trust Score recovered to {ds.score:.0f}/100."},
                    )
                    resolved += 1
                except Exception:  # noqa: BLE001
                    failed += 1
        else:
            unchanged += 1

    return IncidentReport(
        raised=raised,
        resolved=resolved,
        unchanged=unchanged,
        failed=failed,
        skipped_unrated=skipped,
    )
