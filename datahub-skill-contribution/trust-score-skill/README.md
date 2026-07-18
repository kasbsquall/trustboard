# trust-score skill (contribucion a datahub-skills)

Placeholder del DataHub Skill que empaqueta la logica de calculo del Trust
Score como skill reutilizable, para el PR abierto hacia
`datahub-project/datahub-skills` (Paso 9 del plan).

El contenido real (`SKILL.md` con su frontmatter, `references/`, `templates/`)
se arma en el Paso 9, copiando el formato de un skill existente del repo, por
ejemplo `skills/datahub-quality/SKILL.md`. El PR debe seguir Conventional
Commits en el titulo (`feat: add trust-score skill`) y pasar los pre-commit
hooks del repo.

La logica que se empaqueta vive en `scoring/trust_score.py`, escrita sin
dependencias de I/O justamente para poder portarla aqui.
