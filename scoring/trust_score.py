"""Logica pura de calculo del Trust Score.

Sin dependencias de DataHub ni de I/O: recibe senales ya extraidas y devuelve
scores. Esto permite empaquetarlo como DataHub Skill reutilizable
(datahub-skill-contribution/) y testearlo de forma aislada.

El Trust Score de un dataset combina cuatro componentes (0-100), cada uno con
un peso. Un componente puede estar AUSENTE (p.ej. un dataset sin tests o sin
linaje). En ese caso no se cuenta como cero silencioso: se renormalizan los
pesos sobre los componentes disponibles y se reporta la cobertura, para que el
score no castigue de forma oculta la falta de una senal.

El Trust Score de un dominio (equipo) es el promedio de los scores de sus
datasets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Pesos del score compuesto. Suman 1.0.
WEIGHTS = {
    "quality": 0.35,        # % de tests de calidad que pasan
    "documentation": 0.25,  # descripcion + docs de campos + glosario
    "ownership": 0.20,      # el dataset tiene owner asignado
    "freshness": 0.20,      # que tan reciente es el linaje/actualizacion
}

# Ventana de freshness: a los FRESHNESS_WINDOW_DAYS dias, el score de freshness
# llega a 0. Un dataset actualizado hoy puntua 100.
FRESHNESS_WINDOW_DAYS = 30.0

SCORE_VERSION = "1.0"


@dataclass(frozen=True)
class DatasetSignals:
    """Senales crudas extraidas de DataHub para un dataset."""

    urn: str
    tests_passing: int = 0
    tests_failing: int = 0
    has_tests: bool = False
    has_description: bool = False
    has_field_docs: bool = False
    has_glossary_terms: bool = False
    has_owner: bool = False
    freshness_days: float | None = None  # None => senal ausente


@dataclass(frozen=True)
class ComponentBreakdown:
    """Score por componente de un dataset, con marca de disponibilidad."""

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
    coverage: float  # fraccion de peso cubierto por senales disponibles


@dataclass(frozen=True)
class DomainScore:
    domain: str
    score: float
    dataset_count: int
    # promedio de cada componente sobre los datasets donde estaba disponible
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
    # Siempre disponible: la ausencia de docs es una senal real, no un hueco.
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
    """Calcula el Trust Score de un dataset renormalizando sobre lo disponible."""
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
    """Agrega los scores de los datasets de un dominio en el Trust Score del equipo."""
    if not signals:
        return DomainScore(domain=domain, score=0.0, dataset_count=0)

    dataset_scores = [score_dataset(s) for s in signals]
    avg_score = sum(ds.score for ds in dataset_scores) / len(dataset_scores)

    # Promedio por componente sobre los datasets donde estaba disponible.
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
    """Traduce un Trust Score a un tier (para tags/badges Gold/Silver/Bronze)."""
    if score >= 80:
        return "gold"
    if score >= 60:
        return "silver"
    if score >= 40:
        return "bronze"
    return "at-risk"
