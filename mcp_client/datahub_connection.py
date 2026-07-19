"""DataHub connection (Step 3).

The acryl-datahub SDK through DataHubGraph, pointing at the GMS on
DATAHUB_GMS_URL: reading aspects (ownership, schemaMetadata,
structuredProperties, testResults) and executing GraphQL (searches,
upsertStructuredProperties, incidents). This is the path the Auditor, the
Scribe and the Gatekeeper all use.
"""
from __future__ import annotations

import time
from functools import lru_cache

from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig

from config import get_settings


@lru_cache
def get_graph() -> DataHubGraph:
    """Returns a DataHubGraph authenticated against the GMS (cached).

    An unreachable GMS is the most likely first failure for anyone running
    this, so it exits with the URL it tried and what to start, rather than
    with a connection traceback from deep inside the SDK.
    """
    settings = get_settings()
    graph = DataHubGraph(
        DatahubClientConfig(
            server=settings.datahub_gms_url,
            token=settings.datahub_gms_token or None,
        )
    )
    try:
        graph.test_connection()
    except Exception as err:  # noqa: BLE001
        raise SystemExit(
            f"Cannot reach DataHub GMS at {settings.datahub_gms_url}. "
            "Start it with `datahub docker quickstart`, then check the URL and "
            f"token in your .env. ({type(err).__name__}: {str(err)[:160]})"
        ) from None
    return graph


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
