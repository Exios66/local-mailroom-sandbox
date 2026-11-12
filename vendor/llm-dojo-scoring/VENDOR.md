# Vendored llm-dojo-scoring

Authoritative source: https://github.com/Exios66/llm-dojo-scoring

- Source ref: `46811485ce516392b3f72d3269ed9e43b7ca9ed8` (pre-merge commit, branch `claude/vibrant-sagan-fltg8i-cuad-category-counts`)
- Exact source commit: `46811485ce516392b3f72d3269ed9e43b7ca9ed8`
- Source package version: `0.28.1`
- Snapshot layout: llm_dojo_scoring/ relocated under src/ with the same shared exclusions.
- Snapshot of the reviewed commit tree (`git archive`), 2026-11-12 UTC.
  File contents, paths and executable modes come from the reviewed commit.

Pin note: this snapshot is the pre-merge commit `4681148` at the top of the trimmed Dojo stack
(production slim-down, `doc_classes` registry, CUAD category counts, score fixes). The package version is
still `0.28.1`. It is staged ahead of the Dojo PRs on purpose; re-pin to the merge commit or the next
release tag once they land. Previous pin: release `v0.28.1` (`00a2a7f7b058`).

Dojo release `v0.28.1`. v0.28.0 aligns with mailroom-dataset v10: corporate schema v2
(new registered fields such as party roles, signatories, agreement and expiration dates,
termination notice and dispute forum) and the v10 row schemas (`schemas/v10_rows.py`).
v0.28.1 changes the sorter guide: a bylaw amendment is `bylaws`, never `board_resolution`
(corpus rule C); v9.3 labels 8 such amendments `board_resolution`, so scoring against v9.3
counts those 8 as wrong until v10 relabels them.

Changes originate in the authoritative standalone repository, are committed and
reviewed there, then consumed here. Never patch this snapshot or export hub
changes back into the owning repository. After importing the same revisions,
the Digital-Mailroom workspace and these generated snapshots must match.

Dojo owns scoring; llm-mailroom owns the pipeline. Production corporate v6
and sandbox evaluation v7 remain separate intentional prompt catalogs.

Previous pin: llm-dojo-scoring `main` at `b3ec0fba` (Dojo PR #123), on top of the 0.27.2 release.
#123 fixes review findings on the 0.27.2 vendor bump (llm-mailroom#164): prose-wrapped JSON
with many failing candidate objects parses in linear time (each candidate is decoded from
its own balanced slice), and `rescore_record` picks an already-current record's headline by
the same task routing a fresh rescore uses. #122 changes Dojo's release scripts only. The
package version is still `0.27.2`; return the pin to a release tag once v0.27.3 is cut.

Previously: llm-dojo-scoring 0.27.2, the squash merge `1cd4aba7` of Dojo PR #121. 0.27.2 fixes
the review findings on the 0.27.1 snapshot (local-mailroom-sandbox#245): `score_document`
never raises on deeply nested prediction text and parses brace-heavy text in linear time;
any `Mapping` prediction is a dict payload for adherence; a prose-wrapped Python repr sets
`prose_wrapper`; `rescore` reports `headline_score` for CUAD/MAUD rows. No field-map, tier 0
or headline score changes. The pin names the `v0.27.2` tag and verifies its SHA.

It builds on 0.27.1, the commit `a82843e8` of Dojo PR #118 (tag `v0.27.1`).
0.27.0 added tiered per-document-type scoring (`score_document`, new `score_archive_block`
keys for the llm-mailroom unified audit row); 0.27.1 makes `score_document` and
`score_archive_block` never raise on bad field values, derives the CMS `cms_source_table`
from `doc_subclass`, and guards the new block keys. Field-map scores are unchanged except
CMS insurance rows scored with `doc_subclass` and no `expected_subclass`.
It supersedes the v0.26.0 snapshot (`2fea5ea7`) and, here, the v0.27.1 snapshot (`a82843e8`).

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
