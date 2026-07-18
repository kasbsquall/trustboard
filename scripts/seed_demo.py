"""Prepara el escenario de demo de TrustBoard sembrando señales en el grafo.

El datapack showcase-ecommerce concentra casi todos los datasets en un solo
dominio y trae señales de calidad escasas. Para que el leaderboard tenga 5
equipos comparables y una historia (un campeon, un rezagado, tres en medio),
este script:

  1. Mapea cada plataforma de datos a un equipo (dominio con nombre).
  2. Reasigna cada dataset a su equipo (aspecto domains).
  3. Siembra señales con contraste segun el perfil de salud del equipo:
     ownership, documentacion (editableDatasetProperties), glossaryTerms y
     testResults (pass/fail). Estas son justo las señales que el Auditor
     leera despues para calcular el Trust Score.

Es idempotente: emitir un aspecto reemplaza el anterior, asi que se puede
re-ejecutar sin duplicar. Se declara como preparacion del entorno de demo,
separado de la logica que audita el Auditor.

Uso:
    .venv/Scripts/python scripts/seed_demo.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.emitter.mcp import MetadataChangeProposalWrapper  # noqa: E402
from datahub.metadata.schema_classes import (  # noqa: E402
    AuditStampClass,
    DomainsClass,
    EditableDatasetPropertiesClass,
    GlossaryTermAssociationClass,
    GlossaryTermsClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    TestResultClass,
    TestResultsClass,
    TestResultTypeClass,
)

from mcp_client.datahub_connection import get_graph  # noqa: E402

ACTOR = "urn:li:corpuser:datahub"

# Dominios reales del datapack (urn -> nombre) confirmados en el entorno.
DOMAINS = {
    "Data Platform Team": "urn:li:domain:b2fd91.1caf2b7c-ca73-4708-bdec-6687d78cab0e",
    "Ecommerce Operations": "urn:li:domain:b2fd91.91994180-93ee-43f7-9c97-5e74a4a43fbd",
    "E-Commerce": "urn:li:domain:b2fd91.d4f24004-fb54-4e3c-8dea-2b7e209230b0",
    "Engineering Division": "urn:li:domain:b2fd91.ce125416-344c-4db4-9f07-f7086a851606",
    "Marketing": "urn:li:domain:b2fd91.e0f246dc-e7a5-40ed-9441-1e397ed6e2ad",
}

# Cada equipo es dueño de su stack de plataformas (asignacion realista).
PLATFORM_TO_TEAM = {
    "snowflake": "Data Platform Team",
    "dbt": "Data Platform Team",
    "postgres": "Ecommerce Operations",
    "s3": "E-Commerce",
    "tableau": "Engineering Division",
    "powerbi": "Marketing",
    "looker": "Marketing",
}

# Perfil de salud por equipo: fracciones objetivo de cada señal. Crea el
# contraste que hace interesante el leaderboard.
PROFILES = {
    "Data Platform Team": dict(doc=0.90, own=0.90, terms=0.80, pass_ratio=0.90),
    "Ecommerce Operations": dict(doc=0.75, own=0.70, terms=0.60, pass_ratio=0.78),
    "E-Commerce": dict(doc=0.55, own=0.50, terms=0.40, pass_ratio=0.55),
    "Engineering Division": dict(doc=0.35, own=0.30, terms=0.25, pass_ratio=0.38),
    "Marketing": dict(doc=0.15, own=0.15, terms=0.10, pass_ratio=0.22),
}

OWNERS = [
    "urn:li:corpuser:b2fd91.alex@example.com",
    "urn:li:corpuser:b2fd91.bryan@example.com",
    "urn:li:corpuser:b2fd91.kirk@example.com",
    "urn:li:corpuser:b2fd91.marty@example.com",
    "urn:li:corpuser:b2fd91.sam@example.com",
    "urn:li:corpuser:b2fd91.michael@example.com",
]
TERMS = [
    "urn:li:glossaryTerm:b2fd91.Email_Address",
    "urn:li:glossaryTerm:b2fd91.Phone_Number",
]
# Cuatro chequeos de calidad estandar por dataset (metadata tests sinteticos).
TEST_CHECKS = [
    "urn:li:test:trustboard.completeness",
    "urn:li:test:trustboard.freshness",
    "urn:li:test:trustboard.validity",
    "urn:li:test:trustboard.uniqueness",
]

_PLATFORM_RE = re.compile(r"dataPlatform:([^,]+),")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _audit() -> AuditStampClass:
    return AuditStampClass(time=_now_ms(), actor=ACTOR)


def _platform_of(dataset_urn: str) -> str | None:
    m = _PLATFORM_RE.search(dataset_urn)
    return m.group(1) if m else None


def list_dataset_urns(graph) -> list[str]:
    query = (
        '{ search(input: {type: DATASET, query: "*", start: 0, count: 200}) '
        "{ searchResults { entity { urn } } } }"
    )
    results = graph.execute_graphql(query)["search"]["searchResults"]
    return [r["entity"]["urn"] for r in results]


def seed_dataset(graph, dataset_urn: str, team: str, idx: int) -> None:
    """Emite los aspectos de un dataset segun el perfil de su equipo.

    idx recorre los datasets del equipo y decide de forma determinista (sin
    azar) que fraccion recibe cada señal, respetando el perfil.
    """
    profile = PROFILES[team]
    emit = lambda aspect: graph.emit_mcp(  # noqa: E731
        MetadataChangeProposalWrapper(entityUrn=dataset_urn, aspect=aspect)
    )

    # 1. Dominio (equipo).
    emit(DomainsClass(domains=[DOMAINS[team]]))

    # Umbral determinista: el dataset i-esimo "cae dentro" de la fraccion f
    # si (i mod 100)/100 < f. Reparte las señales de forma estable.
    def within(fraction: float) -> bool:
        return ((idx * 37) % 100) / 100.0 < fraction

    # 2. Ownership.
    if within(profile["own"]):
        owner = OWNERS[idx % len(OWNERS)]
        emit(OwnershipClass(owners=[OwnerClass(owner=owner, type=OwnershipTypeClass.DATAOWNER)]))

    # 3. Documentacion.
    if within(profile["doc"]):
        emit(
            EditableDatasetPropertiesClass(
                created=_audit(),
                lastModified=_audit(),
                description=(
                    f"Owned by {team}. Curated dataset with documented schema, "
                    "lineage and business context maintained by the team."
                ),
            )
        )

    # 4. Glossary terms.
    if within(profile["terms"]):
        emit(
            GlossaryTermsClass(
                terms=[GlossaryTermAssociationClass(urn=TERMS[idx % len(TERMS)])],
                auditStamp=_audit(),
            )
        )

    # 5. testResults: 4 chequeos, cuantos pasan depende del pass_ratio.
    n_pass = round(profile["pass_ratio"] * len(TEST_CHECKS))
    # Jitter determinista de +-1 para que no todos los datasets sean identicos.
    if idx % 3 == 0 and n_pass < len(TEST_CHECKS):
        n_pass += 1
    elif idx % 3 == 1 and n_pass > 0:
        n_pass -= 1
    n_pass = max(0, min(len(TEST_CHECKS), n_pass))

    passing = [
        TestResultClass(test=TEST_CHECKS[i], type=TestResultTypeClass.SUCCESS)
        for i in range(n_pass)
    ]
    failing = [
        TestResultClass(test=TEST_CHECKS[i], type=TestResultTypeClass.FAILURE)
        for i in range(n_pass, len(TEST_CHECKS))
    ]
    emit(TestResultsClass(passing=passing, failing=failing))


def main() -> None:
    graph = get_graph()
    urns = list_dataset_urns(graph)
    print(f"Datasets encontrados: {len(urns)}")

    per_team_idx: dict[str, int] = {t: 0 for t in DOMAINS}
    assigned = {t: 0 for t in DOMAINS}
    skipped = 0

    for urn in urns:
        platform = _platform_of(urn)
        team = PLATFORM_TO_TEAM.get(platform)
        if team is None:
            skipped += 1
            continue
        seed_dataset(graph, urn, team, per_team_idx[team])
        per_team_idx[team] += 1
        assigned[team] += 1

    print("\nDatasets asignados por equipo:")
    for team, n in assigned.items():
        p = PROFILES[team]
        print(f"  {team}: {n} datasets  (perfil doc={p['doc']:.0%} own={p['own']:.0%} tests_pass={p['pass_ratio']:.0%})")
    if skipped:
        print(f"  (sin plataforma reconocida: {skipped})")
    print("\nOK: escenario de demo sembrado en DataHub.")


if __name__ == "__main__":
    main()
