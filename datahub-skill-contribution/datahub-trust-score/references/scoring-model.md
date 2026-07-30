# Scoring model

## Components and weights

| Component     | Weight | Range | Meaning |
| ------------- | ------ | ----- | ------- |
| Quality       | 35     | 0-100 | Share of data tests or assertions passing |
| Documentation | 25     | 0-100 | Description, field-level docs and glossary coverage |
| Ownership     | 20     | 0-100 | Datasets with at least one assigned owner |
| Freshness     | 20     | 0-100 | Recency of lineage and last update |

Weights are a starting point, not a standard. Adjust them to the organization and state
the chosen weights wherever the score is shown. Persist a `score_version` alongside the
value so a change in methodology is distinguishable from a change in the data.

## Signal sources

| Component     | Primary aspect | Fallback |
| ------------- | -------------- | -------- |
| Quality       | `assertionRunEvent` results | `testResults` (`passing` / `failing`) |
| Documentation | `editableDatasetProperties.description` | `datasetProperties.description`, `editableSchemaMetadata`, `glossaryTerms` |
| Ownership     | `ownership.owners` | none |
| Freshness     | Most recent operation or update timestamp | `datasetProperties.lastModified`, presence of `upstreamLineage` |

Some deployments have no assertion entities at all. In that case `testResults` at dataset
level carries the pass and fail counts and is the correct source for the quality
component.

## Component formulas

```
quality       = passing / (passing + failing) * 100        # absent when no tests exist
documentation = 50 * has_description
              + 25 * has_field_docs
              + 25 * has_glossary_terms
ownership     = 100 if the dataset has an owner else 0
freshness     = max(0, 100 - days_since_update / WINDOW * 100)   # absent without a timestamp
```

`WINDOW` defaults to 30 days. Documentation and ownership are always available: their
absence is a real signal, not a gap. Quality and freshness can be genuinely absent.

## Quality: count what passes, never a pass rate

Use the number of checks currently passing, against a target of about four, rather than
`passing / (passing + failing)`.

This is the single most important rule here, and it is not obvious. Any formula containing
a pass rate pays a team to delete the checks that fail. Ten checks with one passing scores
10; delete the nine failures and it scores 100. A breadth multiplier on top of the rate
softens it and does not fix it, because shrinking the denominator still wins. There is no
way to price a rate that does not reward deletion.

Counting instead means a failing check is worth exactly what a missing one is worth, which
is nothing. That is not leniency: a check that fails gives you no assurance about the data,
so it buys no trust, and deleting it therefore moves the score by zero. The failure is not
ignored, it is priced somewhere arithmetic cannot reach it: raise an incident on any failing
check regardless of score, so clearing it requires a person to fix the check or deliberately
retire an assertion that was asserting the wrong thing.

Cap the fallback source. Data assertions are a claim about the data; catalog-compliance
tests are a claim about the metadata entry. If both earn full marks, a team maxes out
quality without anything reading a row.

## Renormalization, coverage and the floor

Never score an absent signal as zero. Drop it and rescale:

```
score = sum(weight_i * value_i for available i) / sum(weight_i for available i)
```

Report `coverage = sum(weight_i for available i) / 100` next to the score. A domain at 90
with 45% coverage is a different claim from a domain at 90 with full coverage, and the
reader deserves to see the difference.

Coverage alone is not enough, and it is worth saying why, because the obvious design fails
here. Below a floor of about 50%, return **unrated** rather than a number: renormalizing over
one surviving signal produces a confident-looking score from almost no evidence. But a floor
by itself still lets a team with no quality checks reach 65% coverage from documentation,
ownership and a freshness value whose weakest source is an audit stamp that moves whenever
the crawler runs, then score 100 out of three maxed components while a team running real
assertions and failing half of them scores 82.5. So require the quality signal outright: with
no assertions and no tests, the asset is unrated whatever its coverage.

**Unrated is not a bad grade.** Give it its own tier and its own tag, raise no incident on it,
and leave the numeric score ABSENT rather than writing zero. A trust score is usually a
filterable number in the catalog, so a 0.0 meaning "could not measure" makes every facet and
range query read it as worst in the company. Omitting it is not enough either: an asset that
scored last week and is unrated this week keeps its old number under an "unrated" label, so
remove the property rather than merely not rewriting it.

## Aggregation

Weight each dataset by its downstream blast radius, `1 + ln(1 + consumers)`, read from
lineage. An unweighted mean lets an abandoned scratch table drag a team down as hard as the
table forty dashboards read from, which is not how anyone experiences data trust. The
logarithm matters: linear weighting lets one heavily consumed table swamp everything else.
With no lineage available this collapses back to a flat mean, which is the correct fallback.

Aggregate over the datasets you could actually judge, and publish how many that was
alongside the count of datasets in the domain. Averaging in a score you declared meaningless
puts it back into the team's number through the side door.

## Tiers

| Tier    | Range     |
| ------- | --------- |
| gold    | 80 to 100 |
| silver  | 60 to 79  |
| bronze  | 40 to 59  |
| at-risk | below 40  |
| unrated | no score: not enough signal to judge |

Publish these thresholds in any interface that shows a tier. A reader who sees "bronze"
cannot tell whether that means 41 or 59 unless the scale is visible.

## Determinism

Given the same graph state, the score must be identical. Avoid sampling, avoid ordering
dependencies, and round only at presentation time.
