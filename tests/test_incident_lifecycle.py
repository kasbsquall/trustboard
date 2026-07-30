"""Tests for what happens to an open incident when an asset stops being judgeable.

Written because the shipped demo graph contained the contradiction: six datasets
tagged `unrated`, with the trustScore property deliberately absent, each carrying
an ACTIVE incident titled "is at-risk (26/100)". Skipping the raise for an
unrated asset was correct; skipping the resolve was not, so a ticket outlived the
score that justified it and the graph asserted two incompatible things about the
same table.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import incidents
from scoring.trust_score import ComponentBreakdown, DatasetScore

_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,orders,PROD)"


def _score(*, rated: bool, score: float) -> DatasetScore:
    return DatasetScore(
        urn=_URN, score=score, coverage=0.65, rated=rated,
        components=ComponentBreakdown(quality=None, documentation=50.0, ownership=100.0, freshness=90.0),
    )


class _Graph:
    """Records the mutations it is asked to run, and reports one open incident."""

    def __init__(self, open_incidents=("urn:li:incident:abc",)):
        self.open_incidents = list(open_incidents)
        self.raised: list[dict] = []
        self.resolved: list[dict] = []

    def execute_graphql(self, query: str, variables=None):
        if "incidents(" in query:
            return {"entity": {"incidents": {"incidents": [
                {"urn": u, "title": f"{incidents.TITLE_PREFIX} orders is at-risk (26/100)",
                 "status": {"state": "ACTIVE"}}
                for u in self.open_incidents
            ]}}}
        if "raiseIncident" in query:
            self.raised.append(variables or {})
            return {"raiseIncident": True}
        if "updateIncidentStatus" in query:
            self.resolved.append(variables or {})
            return {"updateIncidentStatus": True}
        raise AssertionError(f"unexpected query: {query[:60]}")


def test_an_asset_that_becomes_unrated_has_its_incident_closed():
    graph = _Graph()

    report = incidents.remediate(graph, [_score(rated=False, score=26.0)])

    assert report.skipped_unrated == 1
    assert report.raised == 0
    assert report.resolved == 1
    assert "no longer judge" in graph.resolved[0]["msg"]


def test_an_unrated_asset_with_no_open_incident_stays_quiet():
    graph = _Graph(open_incidents=())

    report = incidents.remediate(graph, [_score(rated=False, score=26.0)])

    assert report.skipped_unrated == 1
    assert report.raised == 0
    assert report.resolved == 0


def test_an_unrated_asset_never_gets_a_new_incident():
    # Its score is below the threshold, so only the rated flag keeps a ticket off
    # a table nobody has measured.
    graph = _Graph(open_incidents=())

    incidents.remediate(graph, [_score(rated=False, score=5.0)])

    assert graph.raised == []


def test_a_rated_asset_below_the_threshold_still_gets_one():
    graph = _Graph(open_incidents=())

    report = incidents.remediate(graph, [_score(rated=True, score=26.0)])

    assert report.raised == 1
    assert "26" in graph.raised[0]["title"]
