"""DataHub connection (Step 3).

Two paths, both pointing at the GMS on DATAHUB_GMS_URL:

1. acryl-datahub SDK through DataHubGraph: reading aspects (ownership,
   schemaMetadata, structuredProperties, testResults) and executing GraphQL
   (searches, upsertStructuredProperties). This is the path the Auditor and the
   Scribe use.

2. Agent Context Kit: exposes the DataHub tools as LangChain tools for a
   conversational agent (build_langchain_tools).
"""
from __future__ import annotations

import time
from functools import lru_cache

from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig

from config import get_settings


@lru_cache
def get_graph() -> DataHubGraph:
    """Returns a DataHubGraph authenticated against the local GMS (cached)."""
    settings = get_settings()
    return DataHubGraph(
        DatahubClientConfig(
            server=settings.datahub_gms_url,
            token=settings.datahub_gms_token or None,
        )
    )


def execute_graphql_retry(graph, query: str, variables: dict | None = None, retries: int = 4):
    """Executes GraphQL, retrying on transient server errors.

    The quickstart GMS returns 500 (connection lease timeout) when OpenSearch is
    under pressure after a burst of writes. Retrying with exponential backoff
    handles these cases without failing the pipeline.
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


__all__ = ["get_graph", "execute_graphql_retry", "get_settings"]
