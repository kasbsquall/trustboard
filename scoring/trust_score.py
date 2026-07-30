"""Pure Trust Score computation logic.

No DataHub or I/O dependencies: it takes already-extracted signals and returns
scores. That makes it packageable as a reusable DataHub Skill
(datahub-skill-contribution/) and testable in isolation.

A dataset's Trust Score combines four components (0-100), each with a weight. A
component can be ABSENT (for example a dataset with no assertions and no
tests). It is not counted as a silent zero: the weights are renormalized over
the available components and the coverage is reported alongside the score, so a
gap reads as reduced confidence in the number rather than as a hidden penalty.

Two things follow from that, and both are enforced here rather than left to the
caller:

  - Coverage travels with every score, at dataset AND domain level, and a
    domain whose mean coverage falls below MIN_COVERAGE is returned UNRATED
    instead of scored. Renormalizing over one surviving signal produces a
    confident-looking number from almost no evidence, which is worse than
    admitting there is not enough to judge.
  - A domain's score weights each dataset by its downstream blast radius. An
    unweighted mean lets an abandoned scratch table drag a team down as hard as
    the table forty dashboards read from, which is not how anyone actually
    experiences data trust.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

# Weights of the composite score. They add up to 1.0.
WEIGHTS = {
    "quality": 0.35,        # assertions passing, else metadata tests passing
    "documentation": 0.25,  # description + field docs + glossary
    "ownership": 0.20,      # the dataset has an owner assigned
    "freshness": 0.20,      # how recently the data itself changed
}

# Freshness window: at FRESHNESS_WINDOW_DAYS days, the freshness score reaches
# 0. A dataset updated today scores 100.
FRESHNESS_WINDOW_DAYS = 30.0

# Below this share of the weight, a domain is not scored at all. 0.45 is the
# floor where documentation plus ownership alone would carry a score: those two
# are always present, so anything at or under it means quality and freshness
# were both missing and the "score" would be a metadata-completeness figure
# wearing a trust label.
MIN_COVERAGE = 0.50

# Quality is required, not merely weighted. A coverage floor alone does not
# protect the score, and reasoning about documentation plus ownership missed it:
# freshness is nearly free, because its last fallback is an audit stamp that
# moves whenever the crawler runs. So a team that has never written a single
# check reaches 0.65 coverage, clears the floor, and scores 100 out of three
# maxed components, while a team that runs real assertions and fails half of
# them scores 82.5. That is a metric telling people to stop testing their data.
# With no quality signal from either source, the asset is unrated. There is no
# honest trust score for data nobody checks.
QUALITY_REQUIRED = True

# How many PASSING checks a dataset needs to earn full quality marks. Four is the
# number of distinct things worth asserting about most tables (row count, nulls
# in the key, uniqueness, freshness), so it is a floor for "somebody thought
# about this table", not a target to grind.
BREADTH_TARGET = 4

# The most a dataset can score on quality when the only evidence is DataHub
# Tests. They check the catalog entry, not the data, and the rest of this module
# is built on refusing to present those as the same claim.
TESTS_FALLBACK_CAP = 0.6

SCORE_VERSION = "2.1"

# The tier cut-offs, in descending order, defined once. Six places used to spell
# them out: this table, the API, the Slack footer, two property descriptions and
# the scorecard, and one of them (the Slack footer) imported nothing from here,
# so a weight change would have had the weekly message state a model that was no
# longer in use. Everything that mentions a threshold now derives it from here.
TIERS: tuple[tuple[str, float], ...] = (
    ("gold", 80.0),
    ("silver", 60.0),
    ("bronze", 40.0),
    ("at-risk", 0.0),
)

# The tier at which TrustBoard opens an incident: anything below bronze.
AT_RISK_THRESHOLD = dict(TIERS)["bronze"]


def tier_scale_text() -> str:
    """The cut-offs as one sentence, for anywhere a human reads them."""
    parts = [
        f"{name} {int(floor)}+" if floor else f"{name.replace('-', ' ')} below {int(TIERS[i - 1][1])}"
        for i, (name, floor) in enumerate(TIERS)
    ]
    return "Tiers: " + ", ".join(parts) + "."


def weights_text() -> str:
    """The weights as one sentence, derived from WEIGHTS."""
    return " + ".join(f"{w:.0%} {name}" for name, w in WEIGHTS.items())


class QualitySource(StrEnum):
    """Where the quality component came from, in order of what it means.

    ASSERTIONS is a statement about the data. TESTS is a statement about the
    metadata (DataHub Tests check catalog compliance). They are not
    interchangeable, so the score reports which one it used instead of quietly
    presenting them as the same thing.
    """

    ASSERTIONS = "assertions"
    TESTS = "metadata-tests"
    NONE = "none"


class FreshnessSource(StrEnum):
    """Where the freshness component came from, in order of what it means.

    OPERATIONS is when the data last changed. PROFILE is when the data was last
    profiled, a decent proxy. METADATA is the aspect's own audit stamp, which
    often reflects the last ingestion run rather than anything about the data,
    and is reported as such so nobody mistakes it for data recency.
    """

    OPERATIONS = "operations"
    PROFILE = "profile"
    METADATA = "metadata-timestamp"
    NONE = "none"


@dataclass(frozen=True)
class DatasetSignals:
    """Raw signals extracted from DataHub for a dataset."""

    urn: str

    # Quality, preferred source: real data assertions.
    assertions_passing: int = 0
    assertions_failing: int = 0
    has_assertions: bool = False

    # Quality, fallback source: DataHub Tests (metadata compliance).
    tests_passing: int = 0
    tests_failing: int = 0
    has_tests: bool = False

    has_description: bool = False
    has_field_docs: bool = False
    has_glossary_terms: bool = False
    has_owner: bool = False

    freshness_days: float | None = None  # None => signal absent
    freshness_source: FreshnessSource = FreshnessSource.NONE

    # How many downstream entities read this dataset, for blast-radius weighting.
    downstream_count: int = 0


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
    quality_source: QualitySource = QualitySource.NONE
    freshness_source: FreshnessSource = FreshnessSource.NONE
    impact_weight: float = 1.0  # blast radius, used when aggregating
    # Checks failing and passing right now. The score does not price failures,
    # because any formula that did would pay a team to delete them, so they are
    # surfaced through the incident path instead.
    failing_checks: int = 0
    passing_checks: int = 0

    @property
    def mostly_failing(self) -> bool:
        """More checks failing than passing.

        The line for an incident, and it is drawn here rather than at "any
        failure" because that version paged 30 of 67 datasets on the first run,
        eight of them gold. DataHub already surfaces individual assertion
        failures; a second system shouting about the same single failure is how
        people learn to ignore both. A table where most of what is asserted is
        false is a different claim, and it is one about trust.
        """
        return self.failing_checks > self.passing_checks
    # False when there is no quality signal at all, or coverage is below the
    # floor. An unrated dataset has a score of 0.0 that means nothing; read this
    # before the number.
    rated: bool = True


@dataclass(frozen=True)
class DomainScore:
    domain: str
    score: float
    dataset_count: int
    # How many of those datasets were judgeable. The gap between the two is the
    # size of the catalog gap, and it belongs next to the score.
    rated_dataset_count: int = 0
    coverage: float = 0.0  # mean share of weight the signals actually covered
    # False when coverage fell below MIN_COVERAGE, or when fewer than half the
    # datasets had a quality signal. An unrated domain's score is 0.0 and means
    # nothing; never write that number anywhere a filter can read it.
    rated: bool = True
    # average of each component over the datasets where it was available
    component_averages: dict[str, float] = field(default_factory=dict)
    weakest_component: str | None = None
    # how many datasets contributed each quality/freshness source, so a reader
    # can tell a score built on assertions from one built on metadata tests
    quality_sources: dict[str, int] = field(default_factory=dict)
    freshness_sources: dict[str, int] = field(default_factory=dict)
    score_version: str = SCORE_VERSION


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _quality_from(passing: int, cap: float) -> float:
    """Quality earned by `passing` checks that currently pass.

    Counted, not averaged, and this is the whole point. Quality used to be
    `passing / (passing + failing)`, and any formula containing a pass RATE pays
    a team to delete the checks that fail: ten checks with one passing scored 10,
    and deleting the nine failures scored 100. Adding a breadth multiplier only
    softened it, 68.5 to 73.75, because shrinking the denominator still won.
    There is no way to price a rate that does not reward deletion, so the rate is
    gone.

    What replaces it: a failing assertion is worth exactly what a missing one is
    worth, which is nothing. That is not leniency, it is what the word means. A
    check that fails gives you no assurance about the data, so it buys no trust,
    and deleting it therefore changes the score by zero. Adding one can only
    help, whether it passes today or not, because passing it later is the only
    way to move the number.

    The failure itself is not ignored, it is just not priced here. It opens an
    incident on the dataset, which is a thing a person has to close, and no
    arithmetic makes that go away.
    """
    return _clamp(min(1.0, passing / BREADTH_TARGET) * 100.0 * cap)


def _quality(s: DatasetSignals) -> tuple[float | None, QualitySource]:
    """Assertions first, metadata tests only as a discounted fallback."""
    if s.has_assertions and (s.assertions_passing + s.assertions_failing) > 0:
        return _quality_from(s.assertions_passing, 1.0), QualitySource.ASSERTIONS

    if s.has_tests and (s.tests_passing + s.tests_failing) > 0:
        # Capped, because a DataHub Test checks the catalog entry and an
        # assertion checks the data. This module has always said those are
        # different claims and then paid them the same, so a team could reach
        # full quality marks without anything ever looking at a row. The cap is
        # what makes the distinction cost something.
        return _quality_from(s.tests_passing, TESTS_FALLBACK_CAP), QualitySource.TESTS

    return None, QualitySource.NONE


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


def impact_weight(downstream_count: int) -> float:
    """How much a dataset's score counts toward its team's, by blast radius.

    Logarithmic on purpose. Linear weighting would let one heavily consumed
    table swamp everything else, and equal weighting is what makes an orphaned
    scratch table as damaging as a table forty dashboards depend on. log1p
    gives a table with twenty consumers roughly four times the pull of an
    unused one, not twenty times.
    """
    return 1.0 + math.log1p(max(0, downstream_count))


def score_dataset(s: DatasetSignals) -> DatasetScore:
    """Computes a dataset's Trust Score, renormalizing over what is available."""
    quality, quality_source = _quality(s)
    if quality_source is QualitySource.ASSERTIONS:
        failing, passing = s.assertions_failing, s.assertions_passing
    elif quality_source is QualitySource.TESTS:
        failing, passing = s.tests_failing, s.tests_passing
    else:
        failing = passing = 0
    components = {
        "quality": quality,
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
    coverage = round(available_weight, 2)
    has_quality = quality is not None
    rated = coverage >= MIN_COVERAGE and (has_quality or not QUALITY_REQUIRED)

    return DatasetScore(
        urn=s.urn,
        score=round(_clamp(weighted), 2),
        components=breakdown,
        coverage=coverage,
        quality_source=quality_source,
        freshness_source=s.freshness_source if components["freshness"] is not None else FreshnessSource.NONE,
        impact_weight=round(impact_weight(s.downstream_count), 3),
        rated=rated,
        failing_checks=failing,
        passing_checks=passing,
    )


def _weakest_by_leverage(component_averages: dict[str, float]) -> str | None:
    """The component where fixing things moves the score most.

    Not the lowest absolute value. A component at 40 carrying 20% of the weight
    has less leverage than one at 55 carrying 35%, so pointing a team at the
    former is advice that costs them effort and barely moves their rank.
    Leverage is weight times headroom.
    """
    if not component_averages:
        return None
    return max(
        component_averages,
        key=lambda c: WEIGHTS[c] * (100.0 - component_averages[c]),
    )


def score_domain(domain: str, signals: list[DatasetSignals]) -> DomainScore:
    """Aggregates a domain's dataset scores into the team's Trust Score."""
    if not signals:
        return DomainScore(domain=domain, score=0.0, dataset_count=0, rated=False)

    dataset_scores = [score_dataset(s) for s in signals]

    # Aggregate over the datasets we could actually judge. Averaging in the ones
    # declared unrated would put a number we called meaningless back into the
    # team's score through the side door.
    rated_scores = [ds for ds in dataset_scores if ds.rated]

    # Weighted by blast radius rather than a flat mean.
    total_weight = sum(ds.impact_weight for ds in rated_scores)
    avg_score = (
        sum(ds.score * ds.impact_weight for ds in rated_scores) / total_weight
        if total_weight
        else 0.0
    )
    mean_coverage = sum(ds.coverage for ds in dataset_scores) / len(dataset_scores)

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

    quality_sources: dict[str, int] = {}
    freshness_sources: dict[str, int] = {}
    for ds in dataset_scores:
        quality_sources[ds.quality_source.value] = quality_sources.get(ds.quality_source.value, 0) + 1
        freshness_sources[ds.freshness_source.value] = freshness_sources.get(ds.freshness_source.value, 0) + 1

    # Half the datasets have to be judgeable before the team's number means
    # anything. One instrumented table out of twenty does not describe a team.
    rated = mean_coverage >= MIN_COVERAGE and len(rated_scores) * 2 >= len(dataset_scores)

    return DomainScore(
        domain=domain,
        score=round(_clamp(avg_score), 2) if rated else 0.0,
        rated_dataset_count=len(rated_scores),
        dataset_count=len(signals),
        coverage=round(mean_coverage, 2),
        rated=rated,
        component_averages=component_averages,
        weakest_component=_weakest_by_leverage(component_averages),
        quality_sources=quality_sources,
        freshness_sources=freshness_sources,
    )


def trust_tier(score: float, rated: bool = True) -> str:
    """Translates a Trust Score into a tier (for tags and badges).

    An unrated domain is not at-risk. Conflating "we could not measure this"
    with "this is bad" is how a governance tool loses the room: the team gets
    punished for a gap in the catalog rather than told what to fix.
    """
    if not rated:
        return "unrated"
    for name, floor in TIERS:
        if score >= floor:
            return name
    return TIERS[-1][0]
