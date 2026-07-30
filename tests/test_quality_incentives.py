"""Tests that the metric cannot be improved by deleting evidence.

A trust score is a target, so the question is never only "is it accurate" but
"what does a team do once they know how it works". v2.1 answered that badly.
Quality was `passing / (passing + failing)`, so a dataset with ten checks and one
passing scored 10, and deleting the nine that failed scored 100. Ten minutes of
deletion beat a quarter of pipeline work, and the same arithmetic let a dataset
with one trivial check outrank one with twenty thorough ones.

These tests pin the property that fixes it rather than any particular number:
no action that removes a check may raise the score, and no action that adds one
may lower it. That is checked exhaustively, because a spot check would have
passed against the broken version too.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoring.trust_score import (
    BREADTH_TARGET,
    TESTS_FALLBACK_CAP,
    DatasetSignals,
    QualitySource,
    score_dataset,
)

_RANGE = range(0, 13)


def _quality(passing: int, failing: int, *, catalog_tests: bool = False) -> float | None:
    kw: dict = {"urn": "urn:li:dataset:t"}
    if catalog_tests:
        kw |= {"tests_passing": passing, "tests_failing": failing, "has_tests": True}
    else:
        kw |= {"assertions_passing": passing, "assertions_failing": failing, "has_assertions": True}
    return score_dataset(DatasetSignals(**kw)).components.quality


def test_deleting_a_failing_check_can_never_raise_quality():
    # Deleting the last remaining check is excluded because it does not leave a
    # comparable score: the dataset becomes unrated, which blocks the gate
    # outright. That is covered in tests/test_quality_required.py, and it is a
    # worse outcome for the team, not a better one.
    offenders = [
        (p, f)
        for p in _RANGE
        for f in _RANGE
        if f >= 1
        and _quality(p, f) is not None
        and _quality(p, f - 1) is not None
        and _quality(p, f - 1) > _quality(p, f)
    ]

    assert offenders == [], f"deleting a failing check paid off at {offenders[:5]}"


def test_deleting_the_last_check_makes_the_asset_unrated_not_perfect():
    stripped = score_dataset(
        DatasetSignals(urn="u", assertions_passing=0, assertions_failing=0, has_assertions=False)
    )

    assert stripped.rated is False
    assert stripped.components.quality is None


def test_adding_a_check_can_never_lower_quality():
    # Including a check that fails. A team weighing whether to assert something
    # new must never find that asserting it is what costs them the rank.
    offenders = [
        (p, f)
        for p in _RANGE
        for f in _RANGE
        if _quality(p, f) is not None
        and (_quality(p + 1, f) < _quality(p, f) or _quality(p, f + 1) < _quality(p, f))
    ]

    assert offenders == [], f"adding a check cost points at {offenders[:5]}"


def test_the_only_way_up_is_to_make_a_check_pass():
    below = _quality(BREADTH_TARGET - 1, 5)
    at = _quality(BREADTH_TARGET, 5)

    assert at > below
    assert at == 100.0


def test_a_thorough_suite_with_failures_beats_one_trivial_passing_check():
    # The comparison that came out backwards under the pass-rate model.
    thorough = _quality(10, 10)
    trivial = _quality(1, 0)

    assert thorough > trivial


def test_catalog_tests_cannot_reach_full_marks():
    # A DataHub Test checks the catalog entry, not the data. Paying it the same
    # as an assertion let a team max out quality without anything reading a row.
    assert _quality(BREADTH_TARGET, 0, catalog_tests=True) == 100.0 * TESTS_FALLBACK_CAP
    assert _quality(BREADTH_TARGET, 0, catalog_tests=True) < _quality(BREADTH_TARGET, 0)


def test_failing_checks_are_reported_so_something_else_can_act_on_them():
    # The score deliberately does not price failures. It would be dishonest to
    # then drop them, so they travel with the score for the incident path.
    scored = score_dataset(
        DatasetSignals(urn="u", assertions_passing=4, assertions_failing=3, has_assertions=True)
    )

    assert scored.components.quality == 100.0
    assert scored.failing_checks == 3
    assert scored.quality_source is QualitySource.ASSERTIONS
