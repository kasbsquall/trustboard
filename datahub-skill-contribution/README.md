# Upstream contribution

`datahub-trust-score/` is the exact content submitted to the DataHub Skills
repository in [datahub-skills#39](https://github.com/datahub-project/datahub-skills/pull/39).

It generalizes the pattern this project implements: compose DataHub signals into
one score per domain, write it back as structured properties and tier tags, and
raise incidents on the assets dragging a domain down. It is kept here so the
submission is self-contained; the canonical copy lives in the pull request.

The second contribution, a Windows path-handling fix for the DataHub CLI, is
[datahub#18479](https://github.com/datahub-project/datahub/pull/18479). Its
workaround ships in `scripts/load_datapack.py`.
