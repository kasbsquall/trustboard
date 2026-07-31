"""Tests for the audit run itself: pagination, the publish refusal, degradation.

The three features the README lists loudest under Technical Execution had no test
between them. `audit_all_domains` was never invoked by the suite, `_paged_search`
was never made to walk past page one, and the 20% refusal that is supposed to stop
a leaderboard being built on a partial read had never fired in anger. A test count
of 98 with two thirds of it on the pure scorer measures the component least likely
to break in production.

The fake graph counts calls, so these assert on what the run actually did rather
than on what it returned.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import auditor
from agents.auditor import MAX_UNREADABLE_RATIO, SignalReadError

_DOMAIN = "urn:li:domain:team"


def _dataset(i: int) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:dbt,t{i:03d},PROD)"


class FakeGraph:
    """Answers searches with a controllable page size and total."""

    def __init__(self, n_datasets: int = 5, page: int = 100, fail_urns: set[str] | None = None):
        self.n = n_datasets
        self.page = page
        self.fail_urns = fail_urns or set()
        self.search_calls: list[tuple[int, int]] = []

    def execute_graphql(self, query: str, variables=None):
        variables = variables or {}
        if "type: DOMAIN" in query or "DOMAIN" in query:
            return {"search": {"total": 1, "searchResults": [
                {"entity": {"urn": _DOMAIN, "properties": {"name": "Team"}}}
            ]}}
        if "type: DATASET" in query or "DATASET" in query:
            # _paged_search interpolates start/count into the query text rather
            # than passing them as variables, so they are read from there.
            m = re.search(r"start:\s*(\d+),\s*count:\s*(\d+)", query)
            start = int(m.group(1)) if m else 0
            count = int(m.group(2)) if m else self.page
            self.search_calls.append((start, count))
            window = [_dataset(i) for i in range(start, min(start + count, self.n))]
            return {"search": {"total": self.n,
                               "searchResults": [{"entity": {"urn": u}} for u in window]}}
        if "assertions" in query:
            return {"entities": []}
        return {}

    def get_aspect(self, urn, aspect_type):
        if urn in self.fail_urns:
            raise RuntimeError("GMS returned 500")
        name = aspect_type.__name__
        if name == "DomainsClass":
            return SimpleNamespace(domains=[_DOMAIN])
        return None

    def get_timeseries_values(self, **kwargs):
        return []


def test_the_dataset_search_walks_every_page():
    # A fixed first page was the "the first 200 results are the graph" assumption
    # this project was built to refuse, and nothing exercised the fix.
    graph = FakeGraph(n_datasets=250, page=100)

    auditor.audit_all_domains(graph)

    starts = [s for s, _ in graph.search_calls]
    assert len(starts) >= 3, f"stopped after {len(starts)} page(s)"
    assert starts[0] == 0
    assert max(starts) >= 200


def test_a_run_that_loses_too_much_of_the_graph_refuses_to_publish():
    # The circuit breaker, fired for the first time. Half the datasets unreadable
    # is well past the limit, and the run must raise rather than return a
    # confident leaderboard built on the other half.
    n = 20
    failing = {_dataset(i) for i in range(n // 2)}
    graph = FakeGraph(n_datasets=n, fail_urns=failing)

    with pytest.raises(SignalReadError, match="Refusing to publish"):
        auditor.audit_all_domains(graph)


def test_a_run_that_loses_a_little_still_publishes():
    # Below the limit the run continues, because refusing on one bad read would
    # make the pipeline hostage to a single flaky aspect.
    n = 40
    failing = {_dataset(0)}  # 2.5%, well under the limit
    assert len(failing) / n < MAX_UNREADABLE_RATIO
    graph = FakeGraph(n_datasets=n, fail_urns=failing)

    results = auditor.audit_all_domains(graph)

    assert results
    assert results[0].score.dataset_count == n - len(failing)


def test_a_failing_assertion_batch_after_the_first_aborts_the_run():
    """Half the graph scored from assertions and half from catalog tests is not
    a degraded answer, it is two different measurements averaged together."""
    calls = {"n": 0}

    def flaky(graph, query, variables=None, **kw):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("GMS returned 500")
        return {"entities": []}

    urns = [_dataset(i) for i in range(60)]
    with pytest.raises(SignalReadError, match="half the graph"):
        auditor.fetch_assertion_results.__wrapped__(object(), urns) if hasattr(
            auditor.fetch_assertion_results, "__wrapped__"
        ) else _run_with(flaky, urns)


def _run_with(fake_execute, urns):
    original = auditor.execute_graphql_retry
    auditor.execute_graphql_retry = fake_execute
    try:
        return auditor.fetch_assertion_results(object(), urns)
    finally:
        auditor.execute_graphql_retry = original


def test_assertions_missing_on_the_very_first_batch_is_a_clean_fallback():
    # A GMS with no assertions support at all is a fact about the instance that
    # every dataset shares, so it degrades the whole run consistently instead of
    # aborting it.
    def always_fails(graph, query, variables=None, **kw):
        raise RuntimeError("field 'assertions' not found")

    original = auditor.execute_graphql_retry
    auditor.execute_graphql_retry = always_fails
    try:
        assert auditor.fetch_assertion_results(object(), [_dataset(0)]) == {}
    finally:
        auditor.execute_graphql_retry = original
