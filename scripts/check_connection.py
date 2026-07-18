"""Smoke test del Paso 3: verifica la conexion autenticada a DataHub.

Comprueba de punta a punta que el SDK puede:
  - autenticarse con el token del .env,
  - listar los dominios (los "equipos" del leaderboard),
  - contar datasets,
  - leer el aspecto testResults de un dataset (la senal de calidad del score).

Uso:
    .venv/Scripts/python scripts/check_connection.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permite ejecutar el script directamente (agrega la raiz del proyecto al path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.metadata.schema_classes import TestResultsClass  # noqa: E402

from mcp_client.datahub_connection import get_graph  # noqa: E402

DOMAINS_QUERY = """
{ listDomains(input: {start: 0, count: 50}) {
    total
    domains { urn properties { name } }
} }
"""

DATASET_COUNT_QUERY = """
{ search(input: {type: DATASET, query: "*", start: 0, count: 0}) { total } }
"""


def main() -> None:
    graph = get_graph()
    print("Conectado. Actor:", graph.execute_graphql("{ me { corpUser { username } } }")["me"]["corpUser"]["username"])

    domains = graph.execute_graphql(DOMAINS_QUERY)["listDomains"]
    print(f"\nDominios ({domains['total']}):")
    for d in domains["domains"]:
        name = (d.get("properties") or {}).get("name") or d["urn"]
        print(f"  - {name}")

    total_datasets = graph.execute_graphql(DATASET_COUNT_QUERY)["search"]["total"]
    print(f"\nDatasets totales: {total_datasets}")

    # Lee testResults de un dataset de muestra para confirmar la senal de calidad.
    sample = graph.execute_graphql(
        '{ search(input: {type: DATASET, query: "*", start: 0, count: 5}) '
        "{ searchResults { entity { urn } } } }"
    )["search"]["searchResults"]

    print("\ntestResults por dataset (muestra):")
    found = 0
    for r in sample:
        urn = r["entity"]["urn"]
        tr = graph.get_aspect(urn, TestResultsClass)
        if tr is not None:
            passing = len(tr.passing or [])
            failing = len(tr.failing or [])
            print(f"  - {urn.split(',')[1] if ',' in urn else urn}: {passing} pass / {failing} fail")
            found += 1
    if found == 0:
        print("  (ningun dataset de la muestra tiene testResults; se veran otros al recorrer todos)")

    print("\nOK: conexion autenticada y lectura de senales verificada.")


if __name__ == "__main__":
    main()
