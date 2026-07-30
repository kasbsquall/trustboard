"""Tests for how the Auditor reads the graph, using a fake in-memory graph.

The behaviour under test is the difference between an aspect that is absent and
an aspect that could not be read. The first is evidence and lowers coverage. The
second is nothing, and treating it as evidence is how a GMS hiccup rewrites a
team's score with no trace in the output.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    OwnershipClass,
)
from datahub.metadata.schema_classes import (
    TestResultsClass as _TestResults,
)

from agents import auditor


class FakeGraph:
    """Answers aspect reads from a dict. `explode` names aspects that error."""

    def __init__(self, aspects: dict | None = None, explode: set[str] | None = None):
        self.aspects = aspects or {}
        self.explode = explode or set()
        self.calls: list[str] = []

    def get_aspect(self, urn, aspect_type):
        name = aspect_type.ASPECT_NAME
        self.calls.append(name)
        if name in self.explode:
            raise RuntimeError("500 connection lease timeout")
        return self.aspects.get(name)

    def get_timeseries_values(self, entity_urn, aspect_type, filter, limit=10):
        return []


def test_an_absent_aspect_is_a_signal(monkeypatch):
    # Arrange: nothing in the graph for this dataset. Absent ownership is a real
    # fact about it, so it scores zero on ownership rather than being dropped.
    graph = FakeGraph()

    # Act
    signals = auditor.extract_signals(graph, "urn:li:dataset:t.absent", now_ms=0)

    # Assert
    assert signals.has_owner is False
    assert signals.has_tests is False
    assert signals.freshness_days is None


def test_an_unreadable_aspect_raises_instead_of_reading_as_absent(monkeypatch):
    # Arrange: the GMS errors on ownership.
    graph = FakeGraph(explode={"ownership"})

    # Act / Assert
    with pytest.raises(auditor.SignalReadError, match="ownership"):
        auditor.extract_signals(graph, "urn:li:dataset:t.broken", now_ms=0)


def test_a_read_is_retried_before_it_is_given_up_on(monkeypatch):
    # Arrange: fails twice, then succeeds. A transient 500 must not cost the
    # dataset its place in the audit.
    monkeypatch.setattr(auditor.time, "sleep", lambda _s: None)
    attempts = {"n": 0}

    class Flaky(FakeGraph):
        def get_aspect(self, urn, aspect_type):
            if aspect_type.ASPECT_NAME == "ownership":
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise RuntimeError("500")
                return OwnershipClass(owners=[])
            return None

    # Act
    signals = auditor.extract_signals(Flaky(), "urn:li:dataset:t.flaky", now_ms=0)

    # Assert
    assert attempts["n"] == 3
    assert signals.has_owner is False


def test_freshness_falls_back_to_the_metadata_stamp_and_says_so():
    # Arrange: no operations, no profile, only the aspect's own audit stamp.
    from datahub.metadata.schema_classes import AuditStampClass

    day = 86_400_000
    graph = FakeGraph(
        {
            "datasetProperties": DatasetPropertiesClass(
                customProperties={},
                lastModified=AuditStampClass(time=10 * day, actor="urn:li:corpuser:x"),
            )
        }
    )

    # Act
    signals = auditor.extract_signals(graph, "urn:li:dataset:t.stamp", now_ms=15 * day)

    # Assert: five days old, and labelled as the weak source it is.
    assert signals.freshness_days == 5.0
    assert signals.freshness_source.value == "metadata-timestamp"


def test_operations_beats_the_metadata_stamp():
    # Arrange: both present, disagreeing. Operations is about the data.
    from datahub.metadata.schema_classes import AuditStampClass, OperationClass

    day = 86_400_000

    class WithOps(FakeGraph):
        def get_timeseries_values(self, entity_urn, aspect_type, filter, limit=10):
            if aspect_type.ASPECT_NAME == "operation":
                return [
                    OperationClass(
                        timestampMillis=14 * day,
                        operationType="UPDATE",
                        lastUpdatedTimestamp=14 * day,
                    )
                ]
            return []

    graph = WithOps(
        {
            "datasetProperties": DatasetPropertiesClass(
                customProperties={},
                lastModified=AuditStampClass(time=1 * day, actor="urn:li:corpuser:x"),
            )
        }
    )

    # Act
    signals = auditor.extract_signals(graph, "urn:li:dataset:t.ops", now_ms=15 * day)

    # Assert
    assert signals.freshness_days == 1.0
    assert signals.freshness_source.value == "operations"


def test_assertion_results_are_passed_through_to_the_signals():
    # Arrange
    graph = FakeGraph({"testResults": _TestResults(passing=[], failing=[])})

    # Act
    signals = auditor.extract_signals(
        graph, "urn:li:dataset:t.assert", now_ms=0, assertion_results=(7, 3)
    )

    # Assert
    assert signals.has_assertions is True
    assert signals.assertions_passing == 7
    assert signals.assertions_failing == 3


def test_downstream_counts_are_inverted_from_upstream_lineage():
    # Arrange: b and c both read from a.
    from datahub.metadata.schema_classes import (
        DatasetLineageTypeClass,
        UpstreamClass,
        UpstreamLineageClass,
    )

    a, b, c = "urn:li:dataset:a", "urn:li:dataset:b", "urn:li:dataset:c"

    class WithLineage(FakeGraph):
        def get_aspect(self, urn, aspect_type):
            if aspect_type.ASPECT_NAME != "upstreamLineage":
                return None
            if urn in (b, c):
                return UpstreamLineageClass(
                    upstreams=[UpstreamClass(dataset=a, type=DatasetLineageTypeClass.TRANSFORMED)]
                )
            return None

    # Act
    counts = auditor.build_downstream_counts(WithLineage(), [a, b, c])

    # Assert
    assert counts == {a: 2, b: 0, c: 0}


def test_lineage_pointing_outside_the_audited_set_is_ignored():
    # Arrange: an upstream the audit never saw must not create a phantom entry.
    from datahub.metadata.schema_classes import (
        DatasetLineageTypeClass,
        UpstreamClass,
        UpstreamLineageClass,
    )

    known, unknown = "urn:li:dataset:known", "urn:li:dataset:elsewhere"

    class WithLineage(FakeGraph):
        def get_aspect(self, urn, aspect_type):
            if aspect_type.ASPECT_NAME == "upstreamLineage":
                return UpstreamLineageClass(
                    upstreams=[
                        UpstreamClass(dataset=unknown, type=DatasetLineageTypeClass.TRANSFORMED)
                    ]
                )
            return None

    # Act
    counts = auditor.build_downstream_counts(WithLineage(), [known])

    # Assert
    assert counts == {known: 0}
