"""Segundo agente: el Gatekeeper (demo del angulo killer).

Representa a "el proximo agente" del ecosistema: antes de usar un dataset para
una tarea (construir un dashboard, entrenar un modelo, correr una query),
consulta el Trust Score que TrustBoard escribio al grafo y decide GO/NO-GO. Si
el dataset no es confiable, se niega a usarlo y propone una alternativa de un
equipo mejor rankeado.

Esto cierra el loop: el Auditor calcula, el Escriba escribe al grafo, y un
agente COMPLETAMENTE DISTINTO hereda ese conocimiento sin integrarse con
TrustBoard, solo consultando DataHub (via el MCP tool o esta libreria).

Demo:
    .venv/Scripts/python -m agents.gatekeeper
"""
from __future__ import annotations

from dataclasses import dataclass

from agents import trust_lookup
from mcp_client.datahub_connection import execute_graphql_retry, get_graph


@dataclass(frozen=True)
class Decision:
    task: str
    dataset_urn: str
    allowed: bool
    reason: str
    alternative: str | None = None


def evaluate(dataset_urn: str, task: str, min_tier: str = "silver", graph=None) -> Decision:
    """Decide si un agente puede usar un dataset segun su Trust Score."""
    graph = graph or get_graph()
    verdict = trust_lookup.is_trustworthy(dataset_urn, min_tier=min_tier, graph=graph)

    if verdict["trustworthy"]:
        return Decision(
            task=task,
            dataset_urn=dataset_urn,
            allowed=True,
            reason=(
                f"Dataset is '{verdict.get('trust_tier')}' (team "
                f"{verdict.get('owning_team')} scored {verdict.get('team_trust_score')}). "
                f"{verdict['reason']}. Proceeding."
            ),
        )

    # NO-GO: busca una alternativa del equipo mejor rankeado.
    best_team = None
    board = trust_lookup.leaderboard(graph=graph)
    if board:
        best_team = board[0]["name"]

    return Decision(
        task=task,
        dataset_urn=dataset_urn,
        allowed=False,
        reason=(
            f"Refusing to use this dataset: {verdict['reason']} "
            f"(tier '{verdict.get('trust_tier')}'). Using untrusted data would "
            "propagate quality issues downstream."
        ),
        alternative=(
            f"Prefer a dataset owned by '{best_team}', the highest-trust team this week."
            if best_team
            else None
        ),
    )


def _find_dataset_by_tier(graph, tier: str) -> str | None:
    """Busca un dataset etiquetado con un tier dado (para el demo)."""
    q = (
        'query s($tag: String!) { search(input: {type: DATASET, query: "*", '
        'orFilters: [{and: [{field: "tags", values: [$tag]}]}], start: 0, count: 1}) '
        "{ searchResults { entity { urn } } } }"
    )
    try:
        res = execute_graphql_retry(graph, q, variables={"tag": f"urn:li:tag:trust.{tier}"})
        results = res["search"]["searchResults"]
        return results[0]["entity"]["urn"] if results else None
    except Exception:  # noqa: BLE001
        return None


def _print_decision(d: Decision) -> None:
    mark = "GO " if d.allowed else "NO-GO"
    print(f"\n[{mark}] task: {d.task}")
    print(f"        dataset: {d.dataset_urn.split(',')[1] if ',' in d.dataset_urn else d.dataset_urn}")
    print(f"        reason: {d.reason}")
    if d.alternative:
        print(f"        suggestion: {d.alternative}")


def _demo() -> None:
    graph = get_graph()
    print("Gatekeeper agent: consulta el Trust Score en DataHub antes de usar datos.")

    gold = _find_dataset_by_tier(graph, "gold")
    risky = _find_dataset_by_tier(graph, "at-risk") or _find_dataset_by_tier(graph, "bronze")

    if gold:
        _print_decision(evaluate(gold, "Build the executive revenue dashboard", graph=graph))
    if risky:
        _print_decision(evaluate(risky, "Train the churn prediction model", graph=graph))


if __name__ == "__main__":
    _demo()
