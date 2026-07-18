"""Pure Trust Score computation logic.

No DataHub or I/O dependencies: it takes already-extracted signals and returns
scores. That makes it packageable as a reusable DataHub Skill
(datahub-skill-contribution/) and testable in isolation.

A dataset's Trust Score combines four components (0-100), each with a weight. A
component can be ABSENT (for example a dataset with no tests or no lineage). In
that case it is not counted as a silent zero: the weights are renormalized over
the available components and the coverage is reported, so that the score does
not hide a penalty for a missing signal.

A domain's (team's) Trust Score is the average of its datasets' scores.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Weights of the composite score. They add up to 1.0.
WEIGHTS = {
    "quality": 0.35,        # % of quality tests that pass
    "documentation": 0.25,  # description + field docs + glossary
    "ownership": 0.20,      # the dataset has an owner assigned
    "freshness": 0.20,      # how recent the lineage/update is
}

# Freshness window: at FRESHNESS_WINDOW_DAYS days, the freshness score reaches
# 0. A dataset updated today scores 100.
FRESHNESS_WINDOW_DAYS = 30.0

SCORE_VERSION = "1.0"


@dataclass(frozen=True)
class DatasetSignals:
    """Raw signals extracted from DataHub for a dataset."""

    urn: str
    tests_passing: int = 0
    tests_failing: int = 0
    has_tests: bool = False
    has_description: bool = False
    has_field_docs: bool = False
    has_glossary_terms: bool = False
    has_owner: bool = False
    freshness_days: float | None = None  # None => signal absent


@dataclass(frozen=True)
class ComponentBreakdown:
    """Per-component score of a dataset, flagging availability."""

    quality: float | None
    documentation: float
    ownership: float
    freshness: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "quality": self.quality,
            "documentation": self.documentation,
            "ownership": self.ownership,
            "freshness": self.freshness,
        }


@dataclass(frozen=True)
class DatasetScore:
    urn: str
    score: float
    components: ComponentBreakdown
    coverage: float  # fraction of weight covered by the available signals


@dataclass(frozen=True)
class DomainScore:
    domain: str
    score: float
    dataset_count: int
    # average of each component over the datasets where it was available
    component_averages: dict[str, float] = field(default_factory=dict)
    weakest_component: str | None = None


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _quality(s: DatasetSignals) -> float | None:
    total = s.tests_passing + s.tests_failing
    if not s.has_tests or total == 0:
        return None
    return _clamp(s.tests_passing / total * 100.0)


def _documentation(s: DatasetSignals) -> float:
    # Always available: the absence of docs is a real signal, not a gap.
    return _clamp(
        (50.0 if s.has_description else 0.0)
        + (25.0 if s.has_field_docs else 0.0)
        + (25.0 if s.has_glossary_terms else 0.0)
    )


def _ownership(s: DatasetSignals) -> float:
    return 100.0 if s.has_owner else 0.0


def _freshness(s: DatasetSignals) -> float | None:
    if s.freshness_days is None:
        return None
    decay = s.freshness_days / FRESHNESS_WINDOW_DAYS * 100.0
    return _clamp(100.0 - decay)


def score_dataset(s: DatasetSignals) -> DatasetScore:
    """Computes a dataset's Trust Score, renormalizing over what is available."""
    components = {
        "quality": _quality(s),
        "documentation": _documentation(s),
        "ownership": _ownership(s),
        "freshness": _freshness(s),
    }

    available_weight = sum(WEIGHTS[k] for k, v in components.items() if v is not None)
    if available_weight == 0:
        weighted = 0.0
    else:
        weighted = sum(
            WEIGHTS[k] * v for k, v in components.items() if v is not None
        ) / available_weight

    breakdown = ComponentBreakdown(
        quality=components["quality"],
        documentation=components["documentation"],
        ownership=components["ownership"],
        freshness=components["freshness"],
    )
    return DatasetScore(
        urn=s.urn,
        score=round(_clamp(weighted), 2),
        components=breakdown,
        coverage=round(available_weight, 2),
    )


def score_domain(domain: str, signals: list[DatasetSignals]) -> DomainScore:
    """Aggregates a domain's dataset scores into the team's Trust Score."""
    if not signals:
        return DomainScore(domain=domain, score=0.0, dataset_count=0)

    dataset_scores = [score_dataset(s) for s in signals]
    avg_score = sum(ds.score for ds in dataset_scores) / len(dataset_scores)

    # Per-component average over the datasets where it was available.
    component_averages: dict[str, float] = {}
    for comp in WEIGHTS:
        values = [
            getattr(ds.components, comp)
            for ds in dataset_scores
            if getattr(ds.components, comp) is not None
        ]
        if values:
            component_averages[comp] = round(sum(values) / len(values), 2)

    weakest = min(component_averages, key=component_averages.get) if component_averages else None

    return DomainScore(
        domain=domain,
        score=round(_clamp(avg_score), 2),
        dataset_count=len(signals),
        component_averages=component_averages,
        weakest_component=weakest,
    )


def trust_tier(score: float) -> str:
    """Translates a Trust Score into a tier (for Gold/Silver/Bronze tags and badges)."""
    if score >= 80:
        return "gold"
    if score >= 60:
        return "silver"
    if score >= 40:
        return "bronze"
    return "at-risk"
