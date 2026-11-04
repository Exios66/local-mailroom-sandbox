# Vendored llm-dojo-scoring

Authoritative source: https://github.com/Exios66/llm-dojo-scoring

- Source ref: `v0.27.1` (tag)
- Exact source commit: `a82843e808336e0078c7d5b27dcdb3ff8b698170`
- Source package version: `0.27.1`
- Snapshot layout: llm_dojo_scoring/ relocated under src/ with the same shared exclusions.
- Snapshot of the reviewed commit tree (`git archive`), 2026-11-04 UTC.
  File contents, paths and executable modes come from the reviewed commit.

Changes originate in the authoritative standalone repository, are committed and
reviewed there, then consumed here. Never patch this snapshot or export hub
changes back into the owning repository. After importing the same revisions,
the Digital-Mailroom workspace and these generated snapshots must match.

Dojo owns scoring; llm-mailroom owns the pipeline. Production corporate v6
and sandbox evaluation v7 remain separate intentional prompt catalogs.

This adopts llm-dojo-scoring 0.27.1, the commit `a82843e8` of Dojo PR #118 (tag `v0.27.1`).
0.27.0 added tiered per-document-type scoring (`score_document`, new `score_archive_block`
keys for the llm-mailroom unified audit row); 0.27.1 makes `score_document` and
`score_archive_block` never raise on bad field values, derives the CMS `cms_source_table`
from `doc_subclass`, and guards the new block keys. Field-map scores are unchanged except
CMS insurance rows scored with `doc_subclass` and no `expected_subclass`.
It supersedes the v0.26.0 snapshot (`2fea5ea7`).

Previously: llm-dojo-scoring 0.26.0, the release merge commit `2fea5ea7` of Dojo PR #112
(stack PR #104: reviewer-lane scoring and `dojo-rescore`, the CMS #93 mapping where
`claim_type` and `cms_source_table` are separate fields, the five-class extraction schema
registry frozen from mailroom-dataset v9.2.1, and the bug sweep). Modules now live in
subpackages (`analysis/`, `scoring/`, `metrics/`, `pipeline/`, `integrations/`, `schemas/`);
the old flat import paths keep working through `_layout.install_legacy_aliases()`.
It supersedes the v0.25.0 snapshot (`e35504db`). The pin names the `v0.26.0` tag and verifies
its SHA; this refresh fetched the commit directly because the tag was not yet on GitHub.

Previously: llm-dojo-scoring 0.25.0, the release merge commit `e35504db` of Dojo PR #91
(`llm_dojo_scoring.sorter_guide`, the sorter-facing subclass catalog that sorter prompt V15
and the sorter-condensed lineage are built on; the unannotated merger subclass `other` is no
longer scored; the classification arbiter node). It supersedes the interim commit `db15b7c5`
and the historical v0.22.0 snapshot. The `v0.25.0` tag is published and points at this
commit; the pin now names the tag and verifies its SHA.
