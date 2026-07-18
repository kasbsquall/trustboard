"""Conexion a DataHub (Paso 3).

Dos vias, ambas apuntando al GMS en DATAHUB_GMS_URL:

1. SDK acryl-datahub via DataHubGraph: lectura de aspectos (ownership,
   schemaMetadata, structuredProperties, testResults), ejecucion de GraphQL
   (busquedas, upsertStructuredProperties). Es la via que usan el Auditor y
   el Escriba.

2. Agent Context Kit: expone las tools de DataHub como herramientas LangChain
   para un agente conversacional (build_langchain_tools).
"""
from __future__ import annotations

import time
from functools import lru_cache

from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig

from config import get_settings


@lru_cache
def get_graph() -> DataHubGraph:
    """Devuelve un DataHubGraph autenticado contra el GMS local (cacheado)."""
    settings = get_settings()
    return DataHubGraph(
        DatahubClientConfig(
            server=settings.datahub_gms_url,
            token=settings.datahub_gms_token or None,
        )
    )


def execute_graphql_retry(graph, query: str, variables: dict | None = None, retries: int = 4):
    """Ejecuta GraphQL reintentando ante errores transitorios de servidor.

    El GMS del quickstart devuelve 500 (connection lease timeout) cuando
    OpenSearch esta bajo presion tras una rafaga de escrituras. Reintentar con
    backoff exponencial resuelve estos casos sin fallar el pipeline.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return graph.execute_graphql(query, variables=variables)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
    raise last_err  # type: ignore[misc]


def build_agent_tools(include_mutations: bool = False):
    """Herramientas LangChain del Agent Context Kit.

    Se importa de forma perezosa para que el resto del proyecto no dependa de
    datahub-agent-context si solo se usa el SDK.
    """
    from datahub.sdk.main_client import DataHubClient
    from datahub_agent_context.langchain_tools import build_langchain_tools

    settings = get_settings()
    client = DataHubClient(
        server=settings.datahub_gms_url,
        token=settings.datahub_gms_token or None,
    )
    return build_langchain_tools(client, include_mutations=include_mutations)


__all__ = ["get_graph", "build_agent_tools", "execute_graphql_retry", "get_settings"]
