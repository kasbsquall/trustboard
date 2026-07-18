"""Remediacion via incidents (parte del Escriba).

Convierte al Auditor de medidor en remediador: abre un Incident en DataHub
sobre cada dataset "toxico" (Trust Score bajo umbral) explicando que senal
fallo, y RESUELVE el incident cuando el dataset se recupera. Esto es accion
real y visible en la UI de DataHub, no una anotacion pasiva.

Idempotente: antes de abrir consulta los incidents ACTIVE de TrustBoard del
dataset; no duplica. El prefijo del titulo identifica los incidents propios.
"""
from __future__ import annotations

from dataclasses import dataclass

from mcp_client.datahub_connection import execute_graphql_retry
from scoring.trust_score import DatasetScore

TITLE_PREFIX = "TrustBoard:"
AT_RISK_THRESHOLD = 40.0

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


def _short_name(dataset_urn: str) -> str:
    # urn:li:dataset:(urn:li:dataPlatform:dbt,name,PROD) -> name
    if "," in dataset_urn:
        return dataset_urn.split(",")[1]
    return dataset_urn


def _weakest(ds: DatasetScore) -> str:
    comps = {k: v for k, v in ds.components.as_dict().items() if v is not None}
    return min(comps, key=comps.get) if comps else "quality"


def _active_incidents(graph, dataset_urn: str) -> list[str]:
    try:
        res = execute_graphql_retry(graph, _QUERY_INCIDENTS, variables={"urn": dataset_urn})
    except Exception:  # noqa: BLE001
        return []
    entity = res.get("entity") or {}
    incidents = ((entity.get("incidents") or {}).get("incidents")) or []
    return [
        inc["urn"]
        for inc in incidents
        if (inc.get("title") or "").startswith(TITLE_PREFIX)
        and ((inc.get("status") or {}).get("state") == "ACTIVE")
    ]


def remediate(graph, dataset_scores: list[DatasetScore], threshold: float = AT_RISK_THRESHOLD) -> IncidentReport:
    """Abre/resuelve incidents segun el Trust Score de cada dataset."""
    raised = resolved = unchanged = 0

    for ds in dataset_scores:
        active = _active_incidents(graph, ds.urn)
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
                unchanged += 1
        elif not is_toxic and active:
            for inc_urn in active:
                try:
                    execute_graphql_retry(
                        graph, _RESOLVE,
                        variables={"urn": inc_urn, "msg": f"Trust Score recovered to {ds.score:.0f}/100."},
                    )
                    resolved += 1
                except Exception:  # noqa: BLE001
                    unchanged += 1
        else:
            unchanged += 1

    return IncidentReport(raised=raised, resolved=resolved, unchanged=unchanged)
