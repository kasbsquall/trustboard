"""DataHub connection.

The acryl-datahub SDK through DataHubGraph, pointing at the GMS on
DATAHUB_GMS_URL: reading aspects (assertions, testResults, ownership,
schemaMetadata, lineage, operations) and executing GraphQL (searches,
upsertStructuredProperties, incidents). This is the path the Auditor, the
Scribe and the Gatekeeper all use.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache

from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph

from config import get_settings


class DataHubUnreachable(Exception):
    """The GMS did not answer.

    A plain Exception rather than SystemExit on purpose. This module sits under
    a long-lived MCP server, and FastMCP catches Exception to turn a failure
    into a tool error for the calling agent. SystemExit derives from
    BaseException, so it would sail past that handler and take the whole server
    down, leaving the agent with a broken pipe instead of an answer it can act
    on. CLI entry points convert this into a clean exit themselves, via
    `exit_on_unreachable`.
    """


def cli(main: Callable[[], None]) -> None:
    """Runs a console entry point, turning an unreachable GMS into a clean exit.

    This is where SystemExit belongs: at the boundary a human is looking at, so
    someone running a script sees the URL it tried and what to start instead of
    a traceback from inside the SDK. Library and server code never calls it.
    """
    try:
        main()
    except DataHubUnreachable as err:
        raise SystemExit(str(err)) from None


@lru_cache
def get_graph() -> DataHubGraph:
    """Returns a DataHubGraph authenticated against the GMS (cached).

    Raises DataHubUnreachable if the GMS does not answer, so a caller can
    decide what to do: a script exits, the MCP server reports a tool error.
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
        raise DataHubUnreachable(
            f"Cannot reach DataHub GMS at {settings.datahub_gms_url}. "
            "Start it with `datahub docker quickstart`, then check the URL and "
            f"token in your .env. ({type(err).__name__}: {str(err)[:160]})"
        ) from None
    return graph


# Mutations must not be retried blindly: a write the server actually applied
# can time out on the way back, and reissuing it duplicates the effect. The
# incident guard exists precisely to avoid duplicates, so a retry here would
# defeat it.
def _is_mutation(query: str) -> bool:
    return query.lstrip().lower().startswith("mutation")


def execute_graphql_retry(graph, query: str, variables: dict | None = None, retries: int = 4):
    """Executes GraphQL, retrying reads on transient server errors.

    The quickstart GMS returns 500 (connection lease timeout) when OpenSearch is
    under pressure after a burst of writes. Retrying reads with exponential
    backoff handles that without failing the pipeline. Mutations are attempted
    once, because retrying a write that may already have landed is how you get
    two incidents for one problem.
    """
    attempts = 1 if _is_mutation(query) else retries
    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            return graph.execute_graphql(query, variables=variables)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
    raise last_err  # type: ignore[misc]


__all__ = [
    "DataHubUnreachable",
    "cli",
    "execute_graphql_retry",
    "get_graph",
    "get_settings",
]
