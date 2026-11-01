# Vendored llm-dojo-scoring

Authoritative source: https://github.com/Exios66/llm-dojo-scoring

- Source ref: `db15b7c593a533bb07c388a5af74f70750769055`
- Exact source commit: `db15b7c593a533bb07c388a5af74f70750769055`
- Source package version: `0.24.2`
- Snapshot layout: llm_dojo_scoring/ relocated under src/ with the same shared exclusions.
- Snapshot of the reviewed commit tree (`git archive`), 2026-11-01 UTC.
  File contents, paths and executable modes come from the reviewed commit.

Changes originate in the authoritative standalone repository, are committed and
reviewed there, then consumed here. Never patch this snapshot or export hub
changes back into the owning repository. After importing the same revisions,
the Digital-Mailroom workspace and these generated snapshots must match.

Dojo owns scoring; llm-mailroom owns the pipeline. Production corporate v6
and sandbox evaluation v7 remain separate intentional prompt catalogs.

This adopts the interim post-v0.24.2 commit `db15b7c5` (branch
`fix/sorter-subclass-guide`, on top of the `total_tokens: 0` zero-usage fix
`718e326c`). It adds `llm_dojo_scoring.sorter_guide`, the sorter-facing subclass
catalog that sorter prompt V15 is built on, and stops scoring the unannotated merger
subclass `other`. It supersedes the historical v0.22.0 snapshot. The pin returns to the
next released Dojo commit once published.
