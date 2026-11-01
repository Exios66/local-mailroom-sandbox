# Vendored llm-dojo-scoring

Authoritative source: https://github.com/Exios66/llm-dojo-scoring

- Source ref: `e35504db12f09aeda07ae116663c177acd8c0d6e`
- Exact source commit: `e35504db12f09aeda07ae116663c177acd8c0d6e`
- Source package version: `0.25.0`
- Snapshot layout: llm_dojo_scoring/ relocated under src/ with the same shared exclusions.
- Snapshot of the reviewed commit tree (`git archive`), 2026-11-01 UTC.
  File contents, paths and executable modes come from the reviewed commit.

Changes originate in the authoritative standalone repository, are committed and
reviewed there, then consumed here. Never patch this snapshot or export hub
changes back into the owning repository. After importing the same revisions,
the Digital-Mailroom workspace and these generated snapshots must match.

Dojo owns scoring; llm-mailroom owns the pipeline. Production corporate v6
and sandbox evaluation v7 remain separate intentional prompt catalogs.

This adopts llm-dojo-scoring 0.25.0, the release merge commit `e35504db` of Dojo PR #91
(`llm_dojo_scoring.sorter_guide`, the sorter-facing subclass catalog that sorter prompt V15
and the sorter-condensed lineage are built on; the unannotated merger subclass `other` is no
longer scored; the classification arbiter node). It supersedes the interim commit `db15b7c5`
and the historical v0.22.0 snapshot. The pin is by commit until the `v0.25.0` tag is
published; the snapshot does not change when it is.
