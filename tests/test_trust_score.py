"""Tests de la logica pura del Trust Score (patron Arrange-Act-Assert)."""
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
    # Arrange: todas las senales al maximo.
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
    # Arrange: sin ninguna senal positiva; tests y freshness ausentes.
    signals = DatasetSignals(urn="urn:li:dataset:test.empty")

    # Act
    result = score_dataset(signals)

    # Assert: documentation=0 y ownership=0 estan disponibles; quality y
    # freshness ausentes. El score es 0 pero la cobertura lo refleja.
    assert result.score == 0.0
    assert result.components.quality is None
    assert result.components.freshness is None
    assert result.coverage == 0.45  # solo doc(0.25)+ownership(0.20)


def test_missing_signals_are_not_silent_zeros():
    # Arrange: dataset con calidad perfecta pero SIN tests ni freshness.
    # No debe hundirse por los componentes ausentes: se renormaliza.
    with_signal = DatasetSignals(
        urn="urn:li:dataset:test.docs",
        has_description=True,
        has_field_docs=True,
        has_glossary_terms=True,
        has_owner=True,
    )

    # Act
    result = score_dataset(with_signal)

    # Assert: doc=100 y ownership=100 disponibles => score 100 pese a huecos.
    assert result.score == 100.0
    assert result.coverage == 0.45


def test_quality_is_pass_ratio():
    # Arrange: 3 de 4 tests pasan => quality 75.
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
    # Arrange: dos datasets, uno perfecto y uno vacio.
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
