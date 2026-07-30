"""Tests for the rule that data nobody checks has no trust score.

These exist because a coverage floor alone did not protect the score. A team with
no quality signal reached 0.65 coverage from documentation, ownership and a
freshness value whose weakest source is an audit stamp that moves on every
crawler run, cleared the 0.50 floor, and scored 100 out of three maxed
components, beating a team that ran real assertions and failed half of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoring.trust_score import (
    TIERS,
    DatasetSignals,
    FreshnessSource,
    score_dataset,
    score_domain,
    tier_scale_text,
    trust_tier,
)


def _no_checks(urn: str, **over) -> DatasetSignals:
    """Perfect on everything except that nobody ever checked the data."""
    base = dict(
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=True,
        freshness_days=0.0,
        freshness_source=FreshnessSource.METADATA,
    )
    base.update(over)
    return DatasetSignals(urn=urn, **base)


def _checks_and_fails(urn: str) -> DatasetSignals:
    """Runs real assertions, fails half of them, everything else perfect."""
    return DatasetSignals(
        urn=urn,
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=True,
        freshness_days=0.0,
        freshness_source=FreshnessSource.OPERATIONS,
        assertions_passing=2,
        assertions_failing=2,
        has_assertions=True,
    )


def test_a_dataset_nobody_checks_is_unrated():
    result = score_dataset(_no_checks("urn:li:dataset:t.unchecked"))

    assert result.rated is False
    assert trust_tier(result.score, result.rated) == "unrated"


def test_not_testing_your_data_cannot_beat_testing_it_badly():
    # This is the whole point. Before the quality requirement, the first of these
    # scored 100.0 and took gold while the second scored 82.5.
    lazy = score_domain("Never tests", [_no_checks(f"urn:li:dataset:a{i}") for i in range(4)])
    diligent = score_domain("Tests and fails", [_checks_and_fails(f"urn:li:dataset:b{i}") for i in range(4)])

    assert lazy.rated is False
    assert diligent.rated is True
    assert trust_tier(lazy.score, lazy.rated) == "unrated"
    assert diligent.score > 0


def test_either_quality_source_satisfies_the_requirement():
    from_tests = _no_checks("urn:li:dataset:t.t", tests_passing=1, tests_failing=1, has_tests=True)
    from_assertions = _no_checks(
        "urn:li:dataset:t.a", assertions_passing=1, assertions_failing=1, has_assertions=True
    )

    assert score_dataset(from_tests).rated is True
    assert score_dataset(from_assertions).rated is True


def test_a_domain_needs_half_its_datasets_judgeable():
    checked = [_checks_and_fails(f"urn:li:dataset:c{i}") for i in range(2)]
    unchecked = [_no_checks(f"urn:li:dataset:u{i}") for i in range(3)]

    result = score_domain("Mostly uninstrumented", checked + unchecked)

    assert result.rated_dataset_count == 2
    assert result.dataset_count == 5
    assert result.rated is False


def test_an_unrated_dataset_contributes_no_score_and_still_takes_up_room():
    """It dilutes the team rather than disappearing from the arithmetic.

    Excluding unrated datasets outright meant a team could raise its own score by
    deleting the assertions on its worst tables: they became unrated, dropped out
    of the average, and the team went from bronze to gold. Keeping their weight in
    the denominator makes hiding a table cost exactly what leaving it broken costs,
    so instrumenting it is always the better move.
    """
    good = [_checks_and_fails(f"urn:li:dataset:g{i}") for i in range(3)]
    unchecked = [_no_checks("urn:li:dataset:u")]

    with_gap = score_domain("With a gap", good + unchecked)
    without_gap = score_domain("Without", good)

    assert with_gap.rated is True
    assert with_gap.rated_dataset_count == 3
    assert with_gap.dataset_count == 4
    assert with_gap.score < without_gap.score


def test_turning_the_checks_off_cannot_raise_the_team_score():
    """The exploit, pinned directly.

    A team with healthy tables and broken ones deletes the assertions on the
    broken ones. Before, that was worth fifty points and a jump from bronze to
    gold, with no failing check left behind to explain it.
    """
    healthy = [_checks_and_fails(f"urn:li:dataset:h{i}") for i in range(4)]
    broken = [
        DatasetSignals(urn=f"urn:li:dataset:b{i}", assertions_passing=0,
                       assertions_failing=6, has_assertions=True)
        for i in range(4)
    ]
    gone_dark = [DatasetSignals(urn=f"urn:li:dataset:b{i}") for i in range(4)]

    honest = score_domain("Honest", healthy + broken)
    hiding = score_domain("Hiding", healthy + gone_dark)

    assert hiding.score <= honest.score


def test_remediation_skips_unrated_assets_on_the_flag_not_on_coverage():
    # An uninstrumented table still reaches 0.65 coverage from documentation,
    # ownership and a crawler timestamp, so a coverage test would have let it
    # through to be paged about. Only the rated flag catches it.
    from agents.incidents import remediate
    from scoring.trust_score import MIN_COVERAGE

    result = score_dataset(_no_checks("urn:li:dataset:t.new"))
    assert result.rated is False
    assert result.coverage > MIN_COVERAGE  # a coverage check would have missed this

    class ExplodingGraph:
        def execute_graphql(self, *a, **k):
            raise AssertionError("remediate must not touch the graph for an unrated asset")

    report = remediate(ExplodingGraph(), [result])
    assert report.skipped_unrated == 1
    assert report.raised == 0


def test_the_tier_scale_text_is_derived_from_the_table():
    # Six places used to spell the cut-offs out by hand, and one of them imported
    # nothing from the scorer.
    text = tier_scale_text()

    for name, floor in TIERS:
        assert name.replace("-", " ") in text or name in text
        if floor:
            assert str(int(floor)) in text
