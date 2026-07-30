"""Tests for the GO/NO-GO policy gate other agents call over MCP.

The point of these is that a refusal has to be readable. An agent told
"trustworthy: false" needs to know whether it just hit bad data or an empty
catalog entry, because only one of those is the data owner's problem.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import trust_lookup

_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,orders,PROD)"


def _stub(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(trust_lookup, "read_trust", lambda urn, graph=None: payload)


def test_gold_passes_a_silver_bar(monkeypatch):
    # Arrange
    _stub(monkeypatch, {"urn": _URN, "kind": "dataset", "trust_tier": "gold", "trust_score": 88.0})

    # Act
    verdict = trust_lookup.is_trustworthy(_URN, min_tier="silver")

    # Assert
    assert verdict["trustworthy"] is True
    assert verdict["status"] == "rated"


def test_silver_fails_a_gold_bar(monkeypatch):
    # Arrange
    _stub(monkeypatch, {"urn": _URN, "kind": "dataset", "trust_tier": "silver", "trust_score": 65.0})

    # Act
    verdict = trust_lookup.is_trustworthy(_URN, min_tier="gold")

    # Assert
    assert verdict["trustworthy"] is False
    assert verdict["status"] == "rated"


def test_unrated_is_reported_apart_from_untrusted(monkeypatch):
    # Arrange: the asset exists, TrustBoard could not judge it.
    _stub(
        monkeypatch,
        {"urn": _URN, "kind": "dataset", "trust_tier": "unrated", "coverage": 0.45},
    )

    # Act
    verdict = trust_lookup.is_trustworthy(_URN)

    # Assert: blocked by default, but the status says why so a caller does not
    # report this as a data quality problem.
    assert verdict["trustworthy"] is False
    assert verdict["status"] == "unrated"
    assert "45%" in verdict["reason"]


def test_unscored_asset_is_unrated_not_at_risk(monkeypatch):
    # Arrange: no tier at all, which is what a freshly ingested dataset looks like.
    _stub(monkeypatch, {"urn": _URN, "kind": "dataset", "trust_tier": None})

    # Act
    verdict = trust_lookup.is_trustworthy(_URN)

    # Assert
    assert verdict["status"] == "unrated"
    assert "not scored" in verdict["reason"]


def test_unrated_can_be_allowed_by_policy(monkeypatch):
    # Arrange
    _stub(monkeypatch, {"urn": _URN, "kind": "dataset", "trust_tier": "unrated", "coverage": 0.3})

    # Act
    verdict = trust_lookup.is_trustworthy(_URN, on_unrated="allow")

    # Assert: allowed, and the reason does not claim the data is fine.
    assert verdict["trustworthy"] is True
    assert verdict["status"] == "unrated"


def test_missing_asset_is_its_own_status(monkeypatch):
    # Arrange
    _stub(monkeypatch, {"urn": _URN, "found": False})

    # Act
    verdict = trust_lookup.is_trustworthy(_URN)

    # Assert
    assert verdict["trustworthy"] is False
    assert verdict["status"] == "not_found"


def test_a_misspelled_min_tier_raises_instead_of_relaxing_the_gate(monkeypatch):
    # Arrange: this used to fall back to silver, so a caller asking for "Gold"
    # got a laxer gate than requested and no warning about it.
    _stub(monkeypatch, {"urn": _URN, "kind": "dataset", "trust_tier": "silver"})

    # Act / Assert
    with pytest.raises(ValueError, match="unknown min_tier"):
        trust_lookup.is_trustworthy(_URN, min_tier="Gold")


def test_an_unknown_unrated_policy_raises(monkeypatch):
    _stub(monkeypatch, {"urn": _URN, "kind": "dataset", "trust_tier": "silver"})

    with pytest.raises(ValueError, match="unknown on_unrated"):
        trust_lookup.is_trustworthy(_URN, on_unrated="maybe")


def test_an_unrecognised_tier_does_not_silently_become_at_risk(monkeypatch):
    # Arrange: a tier written by a future model version.
    _stub(monkeypatch, {"urn": _URN, "kind": "dataset", "trust_tier": "platinum"})

    # Act
    verdict = trust_lookup.is_trustworthy(_URN)

    # Assert: refused, and the reason names the real problem.
    assert verdict["trustworthy"] is False
    assert verdict["status"] == "unrated"
    assert "platinum" in verdict["reason"]


def test_every_input_to_the_decision_comes_back(monkeypatch):
    # Arrange
    _stub(
        monkeypatch,
        {
            "urn": _URN,
            "kind": "dataset",
            "trust_tier": "bronze",
            "trust_score": 52.0,
            "coverage": 0.8,
            "score_version": "2.0",
        },
    )

    # Act
    verdict = trust_lookup.is_trustworthy(_URN, min_tier="silver", on_unrated="warn")

    # Assert: enough to reconstruct the decision from a log line months later.
    assert verdict["policy"] == {"min_tier": "silver", "on_unrated": "warn"}
    assert verdict["coverage"] == 0.8
    assert verdict["score_version"] == "2.0"
    assert verdict["trust_score"] == 52.0
