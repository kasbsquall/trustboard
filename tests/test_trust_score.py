"""Tests for the pure Trust Score logic (Arrange-Act-Assert pattern)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoring.trust_score import (  # noqa: E402
    DatasetSignals,
    score_dataset,
    score_domain,
    trust_tier,
)


def test_perfect_dataset_scores_100():
    # Arrange: every signal at its maximum.
    signals = DatasetSignals(
        urn="urn:li:dataset:test.perfect",
        tests_passing=4,
        tests_failing=0,
        has_tests=True,
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=True,
        freshness_days=0.0,
    )

    # Act
    result = score_dataset(signals)

    # Assert
    assert result.score == 100.0
    assert result.coverage == 1.0


def test_empty_dataset_scores_low_not_crash():
    # Arrange: no positive signal at all; tests and freshness absent.
    signals = DatasetSignals(urn="urn:li:dataset:test.empty")

    # Act
    result = score_dataset(signals)

    # Assert: documentation=0 and ownership=0 are available; quality and
    # freshness are absent. The score is 0 but coverage reflects the gap.
    assert result.score == 0.0
    assert result.components.quality is None
    assert result.components.freshness is None
    assert result.coverage == 0.45  # only doc(0.25)+ownership(0.20)


def test_missing_signals_are_not_silent_zeros():
    # Arrange: documentation and ownership are perfect, quality and freshness
    # are absent. The score must not sink because of the missing components:
    # the weights renormalize over what is available.
    with_signal = DatasetSignals(
        urn="urn:li:dataset:test.docs",
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=True,
    )

    # Act
    result = score_dataset(with_signal)

    # Assert: doc=100 and ownership=100 available => score 100 despite the gaps.
    assert result.score == 100.0
    assert result.coverage == 0.45


def test_quality_is_pass_ratio():
    # Arrange: 3 of 4 tests pass => quality 75.
    signals = DatasetSignals(
        urn="urn:li:dataset:test.quality",
        tests_passing=3,
        tests_failing=1,
        has_tests=True,
    )

    # Act
    result = score_dataset(signals)

    # Assert
    assert result.components.quality == 75.0


def test_domain_score_averages_datasets():
    # Arrange: two datasets, one perfect and one empty.
    perfect = DatasetSignals(
        urn="urn:li:dataset:d.1",
        tests_passing=4,
        tests_failing=0,
        has_tests=True,
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=True,
        freshness_days=0.0,
    )
    empty = DatasetSignals(urn="urn:li:dataset:d.2")

    # Act
    result = score_domain("Marketing", [perfect, empty])

    # Assert
    assert result.dataset_count == 2
    assert result.score == 50.0  # (100 + 0) / 2
    assert result.weakest_component in {"documentation", "ownership"}


def test_empty_domain_does_not_crash():
    # Arrange / Act
    result = score_domain("Empty", [])

    # Assert
    assert result.score == 0.0
    assert result.dataset_count == 0


def test_trust_tiers():
    # Arrange / Act / Assert
    assert trust_tier(95) == "gold"
    assert trust_tier(70) == "silver"
    assert trust_tier(45) == "bronze"
    assert trust_tier(20) == "at-risk"


def test_quality_weight_matches_the_documented_formula():
    # Arrange: quality perfect, every other component present but zero.
    # freshness_days beyond the window scores 0, so only quality contributes.
    signals = DatasetSignals(
        urn="urn:li:dataset:test.quality-only",
        tests_passing=4,
        tests_failing=0,
        has_tests=True,
        has_description=False,
        has_field_docs=False,
        has_glossary_terms=False,
        has_owner=False,
        freshness_days=999.0,
    )

    # Act
    result = score_dataset(signals)

    # Assert: 0.35*100 + 0 + 0 + 0 = 35.0. Fails if the quality weight moves.
    assert result.score == 35.0


def test_freshness_weight_matches_the_documented_formula():
    # Arrange: freshness perfect (updated today), everything else zero.
    signals = DatasetSignals(
        urn="urn:li:dataset:test.fresh-only",
        tests_passing=0,
        tests_failing=4,
        has_tests=True,
        has_description=False,
        has_field_docs=False,
        has_glossary_terms=False,
        has_owner=False,
        freshness_days=0.0,
    )

    # Act
    result = score_dataset(signals)

    # Assert: 0.20*100 = 20.0. Fails if the freshness weight moves.
    assert result.score == 20.0


def test_documentation_weight_is_isolated():
    # Arrange: only documentation is perfect, and quality/freshness are absent
    # so the weights renormalize over documentation (0.25) and ownership (0.20).
    signals = DatasetSignals(
        urn="urn:li:dataset:test.docs-only",
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=False,
    )

    # Act
    result = score_dataset(signals)

    # Assert: 0.25*100 / (0.25 + 0.20) = 55.56
    assert round(result.score, 2) == 55.56


def test_tier_boundaries_are_inclusive():
    # Arrange / Act / Assert: exact cut-off values, where a > vs >= regression hides.
    assert trust_tier(80.0) == "gold"
    assert trust_tier(79.99) == "silver"
    assert trust_tier(60.0) == "silver"
    assert trust_tier(59.99) == "bronze"
    assert trust_tier(40.0) == "bronze"
    assert trust_tier(39.99) == "at-risk"
