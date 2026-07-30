"""Tests for the v2 scoring behaviour: source preference, coverage floor,
blast-radius weighting and leverage-based advice.

These cover the claims the README makes about the model, so a change that
quietly breaks one of them fails here rather than in a demo.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoring.trust_score import (
    MIN_COVERAGE,
    DatasetSignals,
    FreshnessSource,
    QualitySource,
    impact_weight,
    score_dataset,
    score_domain,
    trust_tier,
)


def _rich(urn: str, **over) -> DatasetSignals:
    """A dataset with every component present, so coverage is never the variable."""
    base = dict(
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=True,
        freshness_days=0.0,
        freshness_source=FreshnessSource.OPERATIONS,
        assertions_passing=4,
        assertions_failing=0,
        has_assertions=True,
    )
    base.update(over)
    return DatasetSignals(urn=urn, **base)


# --- quality source preference -------------------------------------------------


def test_assertions_win_over_metadata_tests():
    # Arrange: tests all pass, assertions mostly fail. Assertions describe the
    # data, tests describe the catalog, so the data must decide the score.
    signals = _rich(
        "urn:li:dataset:t.both",
        tests_passing=4,
        tests_failing=0,
        has_tests=True,
        assertions_passing=1,
        assertions_failing=3,
        has_assertions=True,
    )

    # Act
    result = score_dataset(signals)

    # Assert
    assert result.quality_source is QualitySource.ASSERTIONS
    assert result.components.quality == 25.0


def test_tests_are_used_when_there_are_no_assertions():
    # Arrange
    signals = _rich("urn:li:dataset:t.tests", assertions_passing=0, assertions_failing=0,
                   has_assertions=False, tests_passing=3, tests_failing=1, has_tests=True)

    # Act
    result = score_dataset(signals)

    # Assert
    assert result.quality_source is QualitySource.TESTS
    # 3 passing of the 4 a dataset needs, discounted by TESTS_FALLBACK_CAP,
    # because a catalog test is not a statement about the data.
    assert result.components.quality == 45.0


def test_no_quality_signal_is_absent_not_zero():
    # Arrange: neither source present.
    signals = _rich("urn:li:dataset:t.none", assertions_passing=0, assertions_failing=0, has_assertions=False, tests_passing=0, tests_failing=0, has_tests=False)

    # Act
    result = score_dataset(signals)

    # Assert
    assert result.quality_source is QualitySource.NONE
    assert result.components.quality is None
    assert result.coverage == 0.65  # 1.0 minus quality's 0.35


def test_freshness_source_travels_with_the_score():
    # Arrange: a freshness value read from the metadata audit stamp is worth
    # less than one read from operations, and the score has to say which it was.
    signals = _rich(
        "urn:li:dataset:t.stamp", freshness_days=1.0, freshness_source=FreshnessSource.METADATA
    )

    # Act
    result = score_dataset(signals)

    # Assert
    assert result.freshness_source is FreshnessSource.METADATA


def test_absent_freshness_reports_no_source():
    # Arrange: a source label with no value behind it would be a lie.
    signals = _rich(
        "urn:li:dataset:t.nofresh",
        freshness_days=None,
        freshness_source=FreshnessSource.OPERATIONS,
    )

    # Act
    result = score_dataset(signals)

    # Assert
    assert result.freshness_source is FreshnessSource.NONE


# --- coverage floor ------------------------------------------------------------


def test_thin_domain_is_unrated_not_at_risk():
    # Arrange: documentation and ownership only, so coverage is 0.45, under the
    # floor. Both datasets happen to score 100 on what is there.
    thin = [
        DatasetSignals(
            urn=f"urn:li:dataset:t.thin{i}",
            has_description=True,
            has_field_docs=True,
            has_glossary_terms=True,
            has_owner=True,
        )
        for i in range(3)
    ]

    # Act
    result = score_domain("Thin", thin)

    # Assert: no score is published, and the tier says unmeasured rather than bad.
    assert result.coverage == 0.45
    assert result.rated is False
    assert result.score == 0.0
    assert trust_tier(result.score, result.rated) == "unrated"


def test_domain_above_the_floor_is_rated():
    # Arrange: full signals, so coverage is 1.0.
    result = score_domain("Full", [_rich("urn:li:dataset:t.full")])

    # Assert
    assert result.coverage == 1.0
    assert result.rated is True
    assert result.score == 100.0


def test_the_floor_is_where_it_is_documented_to_be():
    # Arrange / Act / Assert: doc+ownership alone must not clear the bar, or the
    # floor stops protecting against metadata-completeness scores in disguise.
    assert MIN_COVERAGE > 0.45


def test_unrated_only_applies_when_rated_is_false():
    # Arrange / Act / Assert: the tier function must not invent unrated on its own.
    assert trust_tier(85.0) == "gold"
    assert trust_tier(85.0, rated=False) == "unrated"
    assert trust_tier(10.0, rated=True) == "at-risk"


# --- blast-radius weighting ---------------------------------------------------


def test_impact_weight_grows_with_consumers_but_sublinearly():
    # Arrange / Act / Assert
    assert impact_weight(0) == 1.0
    assert impact_weight(20) < 1.0 + 20  # not linear
    assert impact_weight(20) > impact_weight(4) > impact_weight(0)


def test_negative_consumer_count_is_treated_as_none():
    assert impact_weight(-5) == 1.0


def test_a_widely_read_dataset_pulls_the_domain_score():
    # Arrange: one good dataset read by twenty others, one bad orphan.
    good = _rich("urn:li:dataset:t.hub", downstream_count=20)
    bad = _rich(
        "urn:li:dataset:t.orphan",
        tests_passing=0,
        tests_failing=4,
        has_description=False,
        has_field_docs=False,
        has_glossary_terms=False,
        has_owner=False,
        freshness_days=999.0,
        downstream_count=0,
    )

    # Act
    weighted = score_domain("Weighted", [good, bad])

    # Assert: a flat mean would be 50. The hub's blast radius pulls it up.
    assert weighted.score > 50.0
    assert weighted.score < 100.0


def test_equal_blast_radius_reduces_to_a_flat_mean():
    # Arrange: same reasoning as above with no lineage anywhere, which is the
    # common case and must not shift the numbers.
    good = _rich("urn:li:dataset:t.a")
    bad = _rich(
        "urn:li:dataset:t.b",
        assertions_passing=0,
        assertions_failing=4,
        has_description=False,
        has_field_docs=False,
        has_glossary_terms=False,
        has_owner=False,
        freshness_days=999.0,
    )

    # Act
    result = score_domain("Flat", [good, bad])

    # Assert
    assert result.score == 50.0


# --- leverage-based advice ----------------------------------------------------


def test_advice_points_at_weight_times_headroom_not_the_lowest_value():
    # Arrange: ownership at 0 carries 20% of the weight; quality at 30 carries
    # 35%. Quality has 0.35*70 = 24.5 of leverage, ownership 0.20*100 = 20, so
    # quality is the better thing to fix even though ownership looks worse.
    signals = DatasetSignals(
        urn="urn:li:dataset:t.leverage",
        tests_passing=2,
        tests_failing=3,
        has_tests=True,
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=False,
        freshness_days=0.0,
        freshness_source=FreshnessSource.OPERATIONS,
    )

    # Act
    result = score_domain("Leverage", [signals])

    # Assert
    assert result.component_averages["ownership"] == 0.0
    assert result.component_averages["quality"] == 30.0
    assert result.weakest_component == "quality"


def test_a_perfect_domain_still_names_a_component():
    # Arrange: nothing to fix. The field must not be a crash or a stale value.
    result = score_domain("Perfect", [_rich("urn:li:dataset:t.p")])

    # Assert
    assert result.weakest_component in result.component_averages


# --- reporting ---------------------------------------------------------------


def test_domain_reports_which_sources_backed_the_quality_signal():
    # Arrange: one dataset scored from assertions, one from tests, one unscored.
    signals = [
        _rich("urn:li:dataset:t.1", assertions_passing=2, assertions_failing=0, has_assertions=True),
        _rich("urn:li:dataset:t.2", assertions_passing=0, assertions_failing=0, has_assertions=False,
              tests_passing=4, tests_failing=0, has_tests=True),
        _rich("urn:li:dataset:t.3", assertions_passing=0, assertions_failing=0, has_assertions=False),
    ]

    # Act
    result = score_domain("Mixed", signals)

    # Assert
    assert result.quality_sources == {"assertions": 1, "metadata-tests": 1, "none": 1}


def test_score_version_is_reported_and_not_dead():
    # Arrange / Act
    result = score_domain("Versioned", [_rich("urn:li:dataset:t.v")])

    # Assert: scores from different models are not comparable, so the number has
    # to carry the model that produced it.
    assert result.score_version
    assert result.score_version[0].isdigit()


@pytest.mark.parametrize("count", [0, 1, 5, 100])
def test_impact_weight_is_finite_and_positive(count):
    w = impact_weight(count)
    assert w >= 1.0
    assert w < 10.0
