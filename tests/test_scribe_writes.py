"""Tests for what the Scribe actually writes into the graph.

This is the half of the project that makes it an agent rather than a dashboard,
and until now it had no automated evidence behind it at all. "Every write is
idempotent" was prose, and the flagship correctness claim, that an unrated asset
has its score REMOVED rather than written as 0.0, could only be demonstrated by
running the live demo and looking.

The fake graph records every mutation, so these assert on the mutations issued
rather than on a return value. That is the only thing that matters here: a write
path is correct when it sends the right calls and, on a second identical run,
sends none it does not need to.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.metadata.schema_classes import GlobalTagsClass, TagAssociationClass

from agents import scribe
from agents.auditor import AuditedDomain, DomainInfo
from scoring.trust_score import ComponentBreakdown, DatasetScore, DomainScore

_DOMAIN = "urn:li:domain:team"
_DATASET = "urn:li:dataset:(urn:li:dataPlatform:dbt,orders,PROD)"


class FakeGraph:
    """Records mutations; answers aspect reads from a dict the test controls."""

    def __init__(self, tags: list[str] | None = None, description: str = ""):
        self.mutations: list[tuple[str, dict]] = []
        self.emitted: list = []
        self._tags = tags or []
        self._description = description

    # -- reads ---------------------------------------------------------------
    def get_aspect(self, urn, aspect_type):
        if aspect_type is GlobalTagsClass:
            if not self._tags:
                return None
            return GlobalTagsClass(tags=[TagAssociationClass(tag=t) for t in self._tags])
        return None

    def emit_mcp(self, wrapper):
        self.emitted.append(wrapper)

    # -- mutations -----------------------------------------------------------
    def execute_graphql(self, query: str, variables=None):
        name = (
            "upsert" if "upsertStructuredProperties" in query
            else "remove_props" if "removeStructuredProperties" in query
            else "add_tag" if "addTag" in query
            else "remove_tag" if "removeTag" in query
            else "other"
        )
        self.mutations.append((name, variables or {}))
        if "domain(" in query or "dataset(" in query:
            return {"domain": {"properties": {"description": self._description}}}
        return {}

    def kinds(self) -> list[str]:
        return [name for name, _ in self.mutations]


def _dataset(score: float, *, rated: bool) -> DatasetScore:
    return DatasetScore(
        urn=_DATASET, score=score, coverage=0.65 if not rated else 1.0, rated=rated,
        components=ComponentBreakdown(quality=None if not rated else 80.0,
                                      documentation=50.0, ownership=100.0, freshness=90.0),
    )


def _audited(*, rated: bool, score: float = 84.0) -> AuditedDomain:
    return AuditedDomain(
        info=DomainInfo(urn=_DOMAIN, name="Data Platform Team"),
        score=DomainScore(domain="Data Platform Team", score=score, dataset_count=1,
                          rated_dataset_count=1 if rated else 0, coverage=1.0, rated=rated),
        dataset_scores=[_dataset(score, rated=rated)],
    )


def test_a_rated_asset_gets_its_numeric_score_written():
    graph = FakeGraph()

    scribe.write_domain_score(graph, _audited(rated=True))

    upserts = [v for name, v in graph.mutations if name == "upsert"]
    assert upserts, "nothing was written"
    assert all("score" in v for v in upserts)
    assert "remove_props" not in graph.kinds()


def test_an_unrated_asset_has_its_score_removed_not_written_as_zero():
    """The claim the whole unrated design rests on.

    trustScore is a filterable number in DataHub. Writing the 0.0 that stands for
    "could not measure" makes every facet and range query read it as worst in the
    company, and merely omitting it leaves last week's number sitting under an
    "unrated" tier, which is the same lie with an extra step.
    """
    graph = FakeGraph()

    scribe.write_domain_score(graph, _audited(rated=False, score=0.0))

    upserts = [v for name, v in graph.mutations if name == "upsert"]
    assert upserts, "nothing was written"
    assert all("score" not in v for v in upserts), "an unrated asset was given a number"
    assert "remove_props" in graph.kinds(), "the previous score was left in place"


def test_the_tier_tag_replaces_the_old_one_and_leaves_exactly_one():
    graph = FakeGraph(tags=["urn:li:tag:trust.at-risk"])

    scribe._write_tier_tag(graph, _DATASET, "gold")

    removed = [v["tag"] for name, v in graph.mutations if name == "remove_tag"]
    added = [v["tag"] for name, v in graph.mutations if name == "add_tag"]
    assert removed == ["urn:li:tag:trust.at-risk"]
    assert added == ["urn:li:tag:trust.gold"]


def test_writing_the_tag_that_is_already_there_issues_no_mutation():
    # Mutations are the one call this codebase deliberately does not retry, so a
    # no-op has to actually be a no-op rather than a remove-then-add.
    graph = FakeGraph(tags=["urn:li:tag:trust.gold"])

    scribe._write_tier_tag(graph, _DATASET, "gold")

    assert graph.mutations == []


def test_the_tag_write_leaves_unrelated_tags_alone():
    graph = FakeGraph(tags=["urn:li:tag:pii", "urn:li:tag:trust.bronze"])

    scribe._write_tier_tag(graph, _DATASET, "silver")

    removed = [v["tag"] for name, v in graph.mutations if name == "remove_tag"]
    assert removed == ["urn:li:tag:trust.bronze"]


def test_a_second_identical_run_issues_no_tag_mutations():
    """Idempotency, as a check rather than a sentence in the README."""
    first = FakeGraph(tags=["urn:li:tag:trust.at-risk"])
    scribe._write_tier_tag(first, _DATASET, "gold")

    second = FakeGraph(tags=["urn:li:tag:trust.gold"])
    scribe._write_tier_tag(second, _DATASET, "gold")

    assert first.mutations != []
    assert second.mutations == []


def test_the_scorecard_of_an_unrated_domain_does_not_state_a_score():
    card = scribe._render_scorecard(
        DomainScore(domain="T", score=0.0, dataset_count=5, coverage=0.4, rated=False), "unrated"
    )

    assert "UNRATED" in card
    assert "0.0" not in card
    assert card.startswith(scribe._DESC_START)
    assert card.endswith(scribe._DESC_END)


def test_the_scorecard_lives_in_a_delimited_block_that_can_be_replaced():
    # The block markers are what make a second run replace the card instead of
    # appending another copy to the domain description.
    card = scribe._render_scorecard(
        DomainScore(domain="T", score=84.0, dataset_count=27, coverage=1.0, rated=True,
                    component_averages={"quality": 88.0, "documentation": 79.0,
                                        "ownership": 92.0, "freshness": 77.0}), "gold")

    assert card.count(scribe._DESC_START) == 1
    assert card.count(scribe._DESC_END) == 1
    assert "84" in card
