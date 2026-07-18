"""Verifica en runtime que capacidades de write-back funcionan en el quickstart.

El panel de jueces marco 3 caveats a confirmar el dia 1 antes de construir el
agente remediador (Escriba). Este probe los prueba de forma aislada contra el
DataHub local y reporta OK/FALLA por cada uno, para decidir la arquitectura:

  1. structured property a nivel DOMAIN (no documentado; plan B: dataset).
  2. custom EXTERNAL assertion + report result (OSS vs Cloud).
  3. incident raise (raiseIncident).
  4. tag programatico.

No deja basura relevante: usa una property/tag de prueba idempotentes.

Uso:
    .venv/Scripts/python scripts/probe_writeback.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.emitter.mcp import MetadataChangeProposalWrapper  # noqa: E402
from datahub.metadata.schema_classes import StructuredPropertyDefinitionClass  # noqa: E402

from mcp_client.datahub_connection import get_graph  # noqa: E402

PROP_URN = "urn:li:structuredProperty:io.trustboard.trustScore"
PROP_QUALIFIED = "io.trustboard.trustScore"
DOMAIN_URN = "urn:li:domain:b2fd91.e0f246dc-e7a5-40ed-9441-1e397ed6e2ad"  # Marketing


def _first_dataset(graph) -> str:
    q = '{ search(input:{type:DATASET, query:"*", start:0, count:1}) { searchResults { entity { urn } } } }'
    return graph.execute_graphql(q)["search"]["searchResults"][0]["entity"]["urn"]


def _ok(label: str) -> None:
    print(f"  [OK]    {label}")


def _fail(label: str, err: Exception) -> None:
    print(f"  [FALLA] {label}: {type(err).__name__}: {str(err)[:200]}")


def define_property(graph) -> bool:
    try:
        definition = StructuredPropertyDefinitionClass(
            qualifiedName=PROP_QUALIFIED,
            displayName="Trust Score",
            valueType="urn:li:dataType:datahub.number",
            cardinality="SINGLE",
            entityTypes=[
                "urn:li:entityType:datahub.dataset",
                "urn:li:entityType:datahub.domain",
            ],
            description="TrustBoard weekly trust score (0-100).",
        )
        graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=PROP_URN, aspect=definition))
        _ok("definir structured property con entityTypes [dataset, domain]")
        return True
    except Exception as e:  # noqa: BLE001
        _fail("definir structured property", e)
        return False


def assign_property(graph, asset_urn: str, label: str) -> None:
    """Asigna la property via mutation GraphQL upsertStructuredProperties."""
    mutation = """
    mutation up($urn: String!, $prop: String!, $val: Float!) {
      upsertStructuredProperties(input: {
        assetUrn: $urn,
        structuredPropertyInputParams: [{structuredPropertyUrn: $prop, values: [{numberValue: $val}]}]
      }) { properties { structuredProperty { urn } values { ... on NumberValue { numberValue } } } }
    }
    """
    try:
        res = graph.execute_graphql(mutation, variables={"urn": asset_urn, "prop": PROP_URN, "val": 82.0})
        props = res["upsertStructuredProperties"]["properties"]
        _ok(f"asignar structured property a {label} (valor leido: {props[0]['values'][0]['numberValue']})")
    except Exception as e:  # noqa: BLE001
        _fail(f"asignar structured property a {label}", e)


def probe_assertion(graph, dataset_urn: str) -> None:
    try:
        res = graph.upsert_custom_assertion(
            urn=None,
            entity_urn=dataset_urn,
            type="Trust Score",
            description="TrustBoard trust score threshold assertion.",
            platform_name="TrustBoard",
        )
        assertion_urn = res.get("urn") if isinstance(res, dict) else None
        if not assertion_urn:
            raise RuntimeError(f"sin urn en respuesta: {res}")
        graph.report_assertion_result(
            urn=assertion_urn,
            timestamp_millis=int(time.time() * 1000),
            type="SUCCESS",
            properties=[{"key": "trust_score", "value": "82"}],
        )
        _ok(f"custom assertion + report result (urn: {assertion_urn[:48]}...)")
    except Exception as e:  # noqa: BLE001
        _fail("custom assertion", e)


def probe_incident(graph, dataset_urn: str) -> None:
    mutation = """
    mutation raise($urn: String!) {
      raiseIncident(input: {
        resourceUrn: $urn, type: OPERATIONAL,
        title: "TrustBoard: low trust score",
        description: "Probe incident from TrustBoard write-back check."
      })
    }
    """
    try:
        res = graph.execute_graphql(mutation, variables={"urn": dataset_urn})
        _ok(f"raiseIncident (id: {str(res.get('raiseIncident'))[:40]})")
    except Exception as e:  # noqa: BLE001
        _fail("raiseIncident", e)


def probe_tag(graph, dataset_urn: str) -> None:
    mutation = """
    mutation add($tag: String!, $urn: String!) {
      addTag(input: {tagUrn: $tag, resourceUrn: $urn})
    }
    """
    try:
        graph.execute_graphql(mutation, variables={"tag": "urn:li:tag:trust.gold", "urn": dataset_urn})
        _ok("addTag (trust.gold)")
    except Exception as e:  # noqa: BLE001
        _fail("addTag", e)


def main() -> None:
    graph = get_graph()
    dataset_urn = _first_dataset(graph)
    print(f"Dataset de prueba: {dataset_urn[:70]}...\n")

    print("1. Structured property:")
    if define_property(graph):
        time.sleep(2)  # dar tiempo a que la definicion se registre
        assign_property(graph, dataset_urn, "DATASET")
        assign_property(graph, DOMAIN_URN, "DOMAIN")

    print("\n2. Custom assertion (historia nativa):")
    probe_assertion(graph, dataset_urn)

    print("\n3. Incident:")
    probe_incident(graph, dataset_urn)

    print("\n4. Tag:")
    probe_tag(graph, dataset_urn)

    print("\nProbe terminado. Lo marcado [OK] es seguro para el Escriba.")


if __name__ == "__main__":
    main()
