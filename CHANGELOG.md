# Changelog

<!-- markdownlint-disable MD024 -- Keep a Changelog sections (Added/Changed/Fixed) repeat within a release by design -->

## [Unreleased]

- **Production slices score against staged overlay `9.3.1-rc.6` (rc.5 review fixes).**
  - `config/staged_overlays.yaml` pins rc.6 (mailroom-issues `c19b48d1`, manifest `28ec2d67…`).
    The seven `config/runs/production/slice-*` configs move from rc.5 to rc.6.
  - rc.6 trims describing lead-ins from party, advisor and counsel names ("the retention of X",
    "Subsidiary of Y, and X" become X). Only 3 overlay cells differ from rc.5, all on merger
    `financial_advisors`, `merger_sub` and `parties`.
  - The master summary's `outputs_sha256` now hashes the `master/` files. The builder's digests
    are kept as `builder_outputs_sha256`.
  - Scores differ from rc.5 only on those merger fields. Re-baseline before a paired re-run.
- **Production slices score against staged overlay `9.3.1-rc.5` (review fixes).**
  - `config/staged_overlays.yaml` pins rc.5 (mailroom-issues `d4e92a68`, manifest `27d0bb37…`).
    The seven `config/runs/production/slice-*` configs move from rc.4 to rc.5.
  - rc.5 holds back the following as `disputed_unresolved`: 23 interim merger effective dates
    whose audit awaits the owner, and conflicting labels on two pairs of identical-text
    documents. It also removes suffix-only and defined-term name captures.
  - Scores are not comparable to rc.4 on those fields. Establish a new baseline before a
    paired re-run.
- **Production slices now score against the validated staged overlay `9.3.1-rc.4`.**
  - `config/staged_overlays.yaml` pins rc.4 (mailroom-issues `3dd4e402`, manifest
    `3a6efaed…`). The seven `config/runs/production/slice-*` configs move from rc.3 to rc.4.
  - `scripts/stage_label_overlay.py` validates the merged labels before staging:
    - whole ISO dates only; canonical `cuad_family` keys;
    - governing-law jurisdictions taken from whole clauses;
    - `parties` without aliases or clause fragments, and de-duplicated entity lists;
    - Hub correspondence `keywords` stripped of maildir metadata (queued as overrides).
  - The stager also applies the reviewed, quote-checked corrections in
    `data/labels/review/validation_corrections.jsonl`.
  - It writes `queues/header_restoration.csv`, which lists the correspondence whose
    header-sourced labels need the Enron header text restored in the next release. Those labels
    stay as truth.
  - Docs: `docs/staged-label-overlay.md` and `scripts/export_mailroom_cache.py` (the cache
    README).
- **Production slice configs score against staged overlay `9.3.1-rc.3`.** The seven
  `config/runs/production/slice-*` configs (local and Modal-host twins) set
  `dataset.staged_overlay: 9.3.1-rc.3` in place of `interim_labels` / `near_gold_labels`.
  Pull the cut before preflight. `judge-audit-0026` keeps its earlier labels on purpose.
- **Production scoring reads the staged label overlay, pinned and hash-checked.**
  - New `dataset.staged_overlay: <version>` (`mailroom_sandbox.staged_overlay`). A run applies
    a mailroom-issues `production-overlay` cut over the Hub labels, instead of the interim and
    near-gold overlays. Setting it together with either of them fails at parse.
  - Only versions pinned in `config/staged_overlays.yaml` are accepted: the mailroom-issues
    commit plus the `MANIFEST.json` sha256, which pins every overlay file. A cache that differs
    from the pin, a Hub source on another revision, or an unpinned version is refused when
    the labels are applied, right after the draw and before any document is scored. A record applies only to the document with its `content_sha256`.
  - The spec hash records the version and manifest sha256. The run lock records the overlay
    provenance. Each row names the fields it took and keeps each replaced Hub value under
    `staged_overlay.overrides`.
  - `sandbox rescore` re-applies the locked cut. The gold audit and subclass schema tallies
    attribute those fields to `staged`.
  - `scripts/pull_staged_overlay.py` fetches only the pinned cut, sparse and shallow, for
    deploy images and job workers. Guide: [`docs/staged-label-overlay.md`](docs/staged-label-overlay.md).
  - Pinned: `9.3.1-rc.3` (mailroom-issues `838ca211`, manifest `2c2b9f12`). Pulled from GitHub
    and applied to the v9.3 corpus: 3,297 of 3,302 documents take 18,439 staged fields (99 Hub
    overrides), none stale.
  - Tests: `tests/test_staged_overlay.py`.
- **Staged overlay cut `v9.3.1-rc.3`: self-contained, cut-off magnitudes repaired.**
  - `stage_label_overlay.py` now verifies that the builder outputs and `build_label_repaired.py`
    are byte-identical to the named builder commit (PR #384 head `f0951873`). It caches the
    outputs under `builder/` in the cut, so restaging no longer needs that unmerged branch. The
    script's sha256 and commit are recorded; mailroom-issues holds no code.
  - The builder's period grammar keeps one number word, cutting "one hundred eighty (180)
    days" to "eighty (180) days". Staged values are now rewritten with the document's own
    spelling: 12 `termination_notice_period` cells. One that cannot be grounded is queued.
    Hub values are never rewritten.
  - rc.3 otherwise equals rc.2: 43,154 of 48,688 cells, 101 Hub overrides, 84 queued cells.
    rc.1 and rc.2 are unchanged.

- **Staged production-scoring overlay for the planned v10 labels.** `scripts/stage_label_overlay.py` merges the repaired-label builder output (`build_label_repaired.py`, PR #384 head `f0951873`) with an earlier repaired CSV that kept different `termination_notice_period` labels, and stages the result as `mailroom_cache/v9.3.0/pre-release/v9.3.1-rc.2/` in mailroom-issues. It adds an assist term only when it reads as a notice period, is not a cure or breach period, has a magnitude the builder lacks, and occurs verbatim in the Hub v9.3 text (13 terms in 13 cells, 4 of them new fills; 43,154 of 48,688 cells labeled). `overlay/<class>.jsonl` holds the 18,441 labels that differ from Hub v9.3 (101 Hub overrides, `override: true`), and `queues/` lists 84 cells for a person and the 101 overrides for sign-off (`decided_by` blank). `export_mailroom_cache.py` finds the labels commit by content, refuses a too-shallow clone, and indexes both pre-release kinds. Tests: `tests/test_stage_label_overlay.py`.

- **SemVer label cache export for mailroom-issues.** `scripts/export_mailroom_cache.py` writes `mailroom_cache/` in LLM-Mailroom-Services/mailroom-issues: one folder per dataset release (`vX.Y.0`, from `FAMILY_HF_TAG` and `LEGACY_FAMILY_HF_REVISIONS`) with an `hf-revision/` pin manifest, and unpublished label work as an immutable pre-release under it (`v9.3.0/pre-release/v9.3.1-rc.1/`): the full repaired label set CSV plus `data/labels/review` under `repairs/`, and `gold`, `gold-overlay`, `gold-supplementary` and `interim` under `enhancements/`. The CSV must hold the full corpus and its subclass repairs must equal the accepted `subclass_corrections.jsonl` lines exactly; a cut pre-release is never rewritten; `--check` exits 1 when the cache is stale. Tests: `tests/test_export_mailroom_cache.py`.

- **`sandbox rescore`: re-score a finished run against other ground truth, with no model call.** It scores a run's stored answers against the run's own revision, another revision (`--revision v9.3`; the run's documents are read from that revision's full corpus, not re-drawn) or a local truth file. Label overlays are applied as the run used them, dropped or all applied (`--overlays`). It writes a derived run directory in the runtime layout and never modifies the source run: the new truth, the re-scored items with each item's first score in `score_original`, a lock marked `rescore.lock` that names the source run, `scores.json` with run-level means overall and by class, and `rescore.json` with the before/after digest. A rescore to another revision leaves the source's split file out of the derived lock, so the gold audit and `compare_sorter_arms` resolve the new revision's split and apply its held-out checks (a runbook-v1 dev document can be runbook-v2 held-out). It reads committed report bundles too. An `--out` that is, contains or lies inside the source run is refused even with `--force`; a derived run records the overlays its truth was built with; agent tasks keep truth keys outside the corpus row shape (`expected_snippet`); a local truth file takes the one revision its rows carry. A document the new truth lacks stops the rescore unless `--allow-missing`. Pipeline per-document scoring moves to `eval.runners.pipeline_item_score`, and label overlays to `corpus.apply_label_overlays`, shared with `prepare_subset`; neither change alters a run's scores (`docs/rescore.md`).

- **H5 decision-sorter question set 4.1.0.** The unrun decision-model-as-sorter configs (`rb1-r13b-decision-sorter-luna-dev-look1`, `rb1-r13b-decision-sorter-jev-1.14-dev-look1`, sealed `rb1-r70b-decision-sorter-luna-heldout`) pinned `reviewer_decisions_v4.0.0`. That set, and 4.0.1 / 4.0.2, still filed a board-adopted bylaw amendment as `board_resolution`. The primary classification node (`classify_node`, production prompt `sorter_condensed_v5`, catalog `sorter_guide`) files it as `bylaws`. `reviewer_decisions_v4.1.0` keeps 4.0.2's form, abstain and subclass gate, and aligns the class and subclass criteria the node states: bylaw amendments, asset-purchase supply, unit purchase options, officer certificates, appended charter amendments, employment-letter termination, and arbitration demands. Completed smokes and the form-calibration runs stay on the sets they ran. No paid run. The reviewer frontrunner stays 3.1.0.

- **PR domain reviewer subagent and review-lane map.** New roster agent
  `pr-domain-reviewer` (canonical `.opencode/agents/pr-domain-reviewer.md`, Claude
  wrapper, Cursor stub) owns silent-failure / Dojo / spend / SHF-HF PR review and
  meshes with CodeRabbit, CodeAnt and CodeFactor via companion notes. Lane map:
  [`docs/pr-review-lanes.md`](docs/pr-review-lanes.md). CodeRabbit tone and
  `src/**/*.py` path instructions defer that domain deep-dive. Complementary to
  `adversarial-reviewer`. No paid run or deployment.

- **Decisions calls are charged once against the live API cap.** A returned Decisions response was priced by the transport and again by HF-004's `record_usage` wrapper, so a decision-model run reached `job.api_cost_cap_usd` at about half the real spend and could be cut off mid-document. The accumulator now records tokens without a second live charge. Isolated `sorter_reviewer` and `extraction_gate` rows enter the per-document call scope at the default ceiling of 16 (a pipeline document stays at 40); chunked specialists stay unscoped. No paid run.

- **Experiment figures in one house style, and H5 comparison figures (#373).** New `figure_style` (colour roles, type scale, deterministic SVG, text linter), `decision_figures` (per-run: routing, confidence, risk-coverage, form-mass, park-reasons, subclass, latency) and `comparison_figures` (H5: runtime, latency, quality against the margins, routing, cost-quality, list pricing by prompt size). Human guide: [`docs/experiment-figures.md`](docs/experiment-figures.md).
  - `sandbox report build --run <id>` now writes the full per-run figure set with alt text. Trees built earlier carry only `latency.svg`; rebuild them, then run `--campaign rb1` (which refreshes indexes only).
  - `scripts/compare_sorter_arms.py --figures DIR` is new, and `--write` also writes the figures. `--allow-mock` labels every figure simulated. Without `--split-dir` the arms pair on the split their locks drew from.
  - The pricing figure places one tick per model call at that call's prompt size (`call_usage`, else the item total split over `llm_calls`), the size a price tier applies to.
  - Cost: `per_1k_docs_usd` is list price × tokens for every arm. Figures plot billed totals only when every arm is billed, and neither figures nor the digest call an arm cheaper or dearer until every arm is billed and at least 1,000 paired documents are compared (`sorter_arms.COST_CLAIM_MIN_DOCS`); the digest prints `not a cost comparison yet (...)` until then.
  - Follow-up: H5's verdict reads `undecided` instead of `SUPPORTED` while the lower-cost leg rests on list-price cost that is not yet a cost comparison, every pair of arms is checked for a list-price/billed reversal, and a speed-up needs complete timing (`timing_complete`, `interleaved_docs` known).
  - `python -m mailroom_sandbox.figure_style lint PATH...` checks figure text and type; exit 0 clean, 1 problems, 2 on a usage error, a missing path or no SVG found.
  - New skill `.claude/skills/experiment-figures/`. No paid run, deployment or model call.

- **Incorrect-archive metric, offline stress harness, and `hf_tool` (#370).** Pipeline runs report `incorrect_archives` beside `routed_to_human_review` (`eval/archive_correctness.py`): per-class archives that are wrong (gate `is_wrong_class` semantics, lowercased) or flagged with reasons — should-have-reviewed, incomplete extraction under the gate's quality bar (`Bars.quality`, pinned by test), or a parse error — plus `failure_report()`, a deterministic aggregation over per-document gate statuses (outcomes, causes, cause-by-class) for failure debugging at scale. The production gate stays authoritative; the metric is the per-run debugging surface and documents its deliberate divergences (`stage_should_review`, `parse_error_archive`, per-document quality without the gate's `min_labelled` threshold). `mailroom_sandbox.stress` runs deterministic mock scenarios against the real load seams — admission through `backpressure.saturated`, per-document call ceilings through `call_guard`, a real `ApiBudget` under refusals — with seven built-in scenarios and invariants computed against spec-derived bounds (nothing dropped, spend within one call of the cap, ceiling respected, injected failures are error rows); reports are labeled instrument readings, never model evidence. `scripts/hf_tool.py` is a read-only NDJSON Hub CLI (`pins`, `verify-pin`, `status`, `whoami`, `search`, `card`, `files`) with `HF_TOKEN` auth, offline refusal under `HF_HUB_OFFLINE`, and the `job/spec.py` pin ledger as a first-class provenance check. No paid run, deployment or model call.

- **Dependency contract alignment (#345).** FastAPI 0.163.1 and Modal 1.6.4 move together with the guarded CLI pin, installed-version checks, SDK contract fixtures and operator docs. Historical serving measurements retain their recorded versions. No deployment is performed.

- **v9.3 split exposure repair.** All 50 calibration documents used to develop question set 4.0.2 are excluded from the new held-out set; one previously entered it. Rebuilt runbook-v2 and its field registry. The spent draw-1 config retains its v9.1 revision and split.

- **Family dataset pin moves to Hub tag v9.3.** `FAMILY_HF_TAG` is `v9.3`, `FAMILY_HF_REVISION` `ff4ca546d4346991628c2616ae014afc15e9fe04` and `FAMILY_HF_DATA_REVISION` `7fd99b406ab1b627f43602dd6a3af5fb5b7a3ac5`. v9.3 changes labels only (the corporate repair, per-subclass corporate `gt_presence` keys, merger agreements routed to `merger_agreement_specialist`, six-regime `annotation_method`); rows, document IDs and text are unchanged since v9.1. Measured on all 3,302 rows, every corporate record changes labels (`gt_presence`, `record_type`; `entity_name`, `keywords`, `subject_matter` on 412; `intent` and `expected_subclass` on 12), 23 correspondence documents change `related_document_ids` (14 also `relationships`), and `annotation_method` changes on 1,541 rows. The v9.1 pair moves to the new `LEGACY_FAMILY_HF_REVISIONS`, and `KNOWN_FAMILY_HF_REVISIONS` / the benchmark gate's `accepted_revisions` keep accepting it. The production slices (0100/0250/0500, their modal-host twins and slice-full), the tiers pipeline configs, `config/datasets.yaml` and the GT labeler follow the new pin. Configs, locks, reports and studies measured on v9.1 keep it, since scores only compare on one label revision: the SAND-032/037/040/042 grids, the autoresearch mailroom-v1/v2 bases, `judge-audit-0026` (paired with the v9.1 slice-0100 r2 run) and the five rb1 R13b smoke runs that already ran. The full-corpus cache directory is keyed on the tag revision, so the first `sandbox datasets pull` after this change downloads the v9.3 corpus into `…__ff4ca546d434/`. `config/extraction/subclass_schemas.json` is rebuilt on v9.3 (`sandbox schemas build`): only `corporate_record` fields change (for example `entity_name` and `record_type` are now labeled on all 450 rows), with 0 mismatches. Its per-set counts use the new runbook-v2 sets (below), so `articles_of_incorporation` now has the 20 dev rows an `iterate` verdict needs and `rights_instrument` drops to `thin`. The v9.1 registry is kept as `config/extraction/subclass_schemas-runbook-v1.json` (graded on bc9eab28 and runbook-v1) for re-checking v9.1 runs, and `build_gold_audit_sheet.py` refuses a registry graded on a revision other than the run's.
- **Campaign rb1 moves to split runbook-v2 on v9.3 (plan Deviations log D1).** `config/splits/runbook-v2` is drawn on v9.3 with runbook-v1's seed, families and set sizes. 820 of 900 dev and 969 of 1,000 held-out documents are the same, and `bylaws` becomes its own unit. Its exposure list, `config/splits/runbook-v2-exposure.txt` (new `scripts/build_split_exposure.py`, `--check` in tests), adds runbook-v1's spent dev-look1 and the R02 and smoke documents to the production tuning list, so held-out holds none of them. Every rb1 config that has not run pins `ff4ca546` and reads runbook-v2, and the R03 class configs take the new per-class dev counts (corporate 164, correspondence 201, insurance 229). The draw now balances `annotation_method` inside each unit (`_band_interleaved`), and the `annotation_method` / `source_corpus` mix gate compares each set with the mix its units imply in the corpus. v9.3's method follows the subclass, so the old plain within-class gap, now informational, fails by design at 15 pts. runbook-v1 still rebuilds byte for byte, because its method is constant within class. `sandbox splits audit` / `show` read the split manifest's own families and exposure list, where they used to read the production default. `experiment_splits.CURRENT_SPLIT` (runbook-v2) is the default for `splits`, `schemas build` (whose `--split` now defaults to the one split on `--revision`) and the sorter-arm comparison. That comparison takes the split from the runs' locks and refuses runs from two splits or a `--split-dir` other than theirs, and `build_gold_audit_sheet.py` picks the run's split and the one registry graded on its revision and split. `job.spec.family_tag_commit` maps a tag name or parquet parent to the tag commit for those comparisons.
- **Campaign patch contract and readiness.** HF-006 preserves explicit zero specialist confidence; required unavailable hotfixes fail preflight, and G0 checks both patch layers. The input-cost envelope includes confidence retries and reports the rejudge scenario separately. The current campaign contract documents v9.3 truth, split exposure, interim/near-gold precedence, patch behavior and unresolved live/policy gates. The README provider graphic now keeps labels inside its panel.

- **Backpressure on the pipeline's filesystem bins.** The bins act as queues, and nothing bounded them: the watcher queued every inbox file it saw, and `sandbox api eval` uploaded every row before waiting for any. Each stage now has a maximum depth (`MAILROOM_MAX_QUEUE_DEPTH_<INBOX|DISPATCH|PROCESSING|REVIEW>`, defaults 256 / 32 / 32 / off, in the new `mailroom_sandbox.backpressure`). At a limit, intake slows and nothing is dropped.
  - HF-005 wraps the vendored `pipeline.watcher._DispatchPool.submit`. Over a limit the file stays in `inbox/` and the 1-second rescan offers it again. It is `unavailable` (not stale) where langfuse is not installed, since the watcher imports it. Upstream draft J-4.
  - In-process pipeline runs wait before writing into a full shared inbox, for at most `MAILROOM_BACKPRESSURE_TIMEOUT_SECONDS` (default 600; `0` = no limit). Past it the document raises `BackpressureTimeout`: a job run records an error row and goes on (rerun on resume), and a direct eval stops as it does on any document error.
  - `run_api_eval` keeps at most `max_in_flight` uploads unfinished (default: the inbox limit). It retries a 503 from the API's pause gate as it does a 429, and no longer marks that refusal as an unconfirmed upload. If the window does not drain within `doc_timeout`, it stops sending and reports the rows it did not send.
  - Adding a hotfix changes `vendor_hotfixes.describe()`, so a run locked before this change refuses to resume until it is re-locked, and a Modal job worker needs a redeploy from this checkout.

- **The offline notebooks run again and leave the checkout clean.** Notebook 03 failed with `NameError` (`sorter` and `run_pipeline_eval` were never defined or imported), and notebook 02 failed its last assertion whenever Jupyter started the kernel in `notebooks/`. A relative `MAILROOM_BASE_DIR=./data` from `.env` also put pipeline run stores in `notebooks/data/`.
  - New `mailroom_sandbox.notebook`: `bootstrap()` (finds the checkout from any working directory, pins an absolute `MAILROOM_BASE_DIR`, uses the offline `ollama` profile unless `SANDBOX_PROFILE` is set, turns tracing off and pipeline logs down to `WARNING`), `experiment_log_redirect()` (notebook evals append to `data/runtime/notebooks/experiment_log.jsonl`; `SANDBOX_NOTEBOOK_LOG=reports` keeps the old target), and `check_prepared_artifacts()`.
  - Notebooks 01–03 are rewritten (step tables, cost notes, validation of prepared artifacts, a determinism check, dry-run plans, per-document pipeline results, an opt-in provider probe). The new `04_experiment_log_explorer` gives a read-only view of the records. `notebooks/README.md` is now real Markdown, not `#` comments.
  - `environment_checklist()` no longer raises `ValueError` when `MAILROOM_BASE_DIR` is outside the checkout.
  - `ruff check` now covers `notebooks/` (CI, `CLAUDE.md`). `tests/test_notebooks.py` checks structure and that outputs are cleared, and, when `nbclient` is installed, runs every notebook from `notebooks/`.
  - The bootstrap module also carries `gold_field_grounding()` / `ungrounded()` from the fixture gold fix (`contract_msa` / `contract_nda` parties); notebook 02's grounding cell is a gate again.

- **Gold grounding check: fixtures, agent fixtures and the scoring overlays (#344, #355).** `mailroom_sandbox.notebook.gold_field_grounding` checks that every extractive gold value in `data/fixtures/manifest.csv` is written in its fixture text, literally or in a canonical form (ISO date, amount by value, spelled-out numeral, a short explicit `ALIASES` table), never inside a longer word or number. `agent_fixture_grounding` applies it to `data/fixtures/agents/*.jsonl` rows that have text (a catalog document or inline `text`), including their expected snippets. `label_overlay_grounding` checks every populated label of the near-gold and interim overlays (the truth SHF-010 and `dataset.interim_labels` score against) against its evidence with the gate's value rules (`gold_labels.evidence_support`). `tests/test_notebook.py` fails on any new ungrounded value, and notebook 02 prints all three. The check found copied gold: `contract_msa`, `contract_nda` and the judge's `judge_msa` named the 10-K's parties (Northwind Logistics Corporation, HarborPoint Holdings, Inc.), now the MSA's and NDA's own. **Score changes:** extraction on the two contract fixtures and the judge's MSA row; their `dataset_fingerprint` changed, so earlier experiment-log records on them are not comparable. Each overlay label is checked by the rule that admitted it: reviewed labels by the review file's rule (so the `original_header` fill whose Exchange header fuses the surname with the org passes), derived labels recomputed from the subclass, closed labels against their vocabulary, and, with a pulled Hub corpus (`cached_doc_rows()`), unquoted gap fills and CUAD corrections against their documents. At the current pin every truth label passes; without the cache (CI) 803 interim labels stay `no_evidence`. `merged_truth` runs the scoring merge (Hub, then interim, then near-gold) over Hub rows: where each scored field comes from (the overlays fill 10,710 fields beyond the Hub's 68,702), where the overlays overlap (2,450 document fields, all settled by precedence), any result the precedence forbids (none), and the Hub labels an overlay disagrees with that no review or CUAD check has settled (30 `disputed`, kept as Hub truth and listed for review).
- **rb1 R01 smoke defects closed (#350).** Pipeline runs route blind by default, and API routes read whole documents. Two new pipeline hotfixes: HF-003 lets an intake `cleaned_text` replace the document only when it keeps the document's length and words, in order. HF-004 prices every API call against `job.api_cost_cap_usd` as it returns. `job/call_guard.py` refuses any OpenRouter call once the cap or the per-document call ceiling (40 for `pipeline`, 16 otherwise) is reached. A document cut short by the guard is an error row, never a score. Scoring hotfixes SHF-001..012 are dual reported beside the Dojo pin's raw values (`docs/scoring-hotfixes.md`). The process that executes a run, locally or on the Modal job worker, refuses a hotfix set other than the lock's, or a hotfix not in effect there (`runner.verify_locked_hotfixes`). `scripts/check_r01_smoke.py` also reads each run's item records. Every drawn document needs an ok item. On a pipeline run, the sorter and the routed specialist must each have called on it, and no agent may make more than 6 calls on one document. The i01 records fail on every defect they showed.
- **Campaign report tree and the `rb1` naming grammar (SAND-108).** `sandbox report build --run <run_id> [--iteration N] [--check]` files a run's records under `reports/campaigns/<campaign>/<key>-<slug>/<run_id>/<iNN>/` (`logs/`, `traces/`, `outputs/`, `report/`, `analysis/`, `figures/`, `docs/`), read only from the run store, the experiment log, the served-provider ledger and gate outputs; `--campaign rb1` rebuilds the campaign and experiment READMEs and `index.jsonl` (one row per run iteration), and `--check` fails on stale output (now a `checks` CI step). Every generated file is named `<run_id>-<iNN>.<name>.<ext>`; the grammar, the parse/format helpers and the `campaign_paths()` / `experiment_paths()` API for analysis scripts live in `mailroom_sandbox.report_campaigns` and `reports/campaigns/README.md`. An iteration is one locked generation (archived re-locks first, then the live store); resumes are listed as launches. Headline scores come only from the run's matching experiment-log record (never recomputed; missing means "not recorded"), cost from the serving renderer with its basis, mock runs carry a banner, and files over 256 KiB plus datasets, span mirrors and trace packs are referenced by path and sha256. The runner builds the tree at the end of every non-mock run in the grammar, best-effort (`SANDBOX_CAMPAIGN_REPORTS=0` disables it). Campaign `rb1` (runbook-v1) maps all 39 runbook rows in `config/campaigns/rb1.yaml`. The runbook configs are renamed to `config/runs/rb1-r01-smoke-*.yaml` and `rb1-r03-*-v0-dev.yaml` (run_id equals the stem), their ledgers to `data/runtime/rb1-r01/served-<model>.jsonl`, and the R02 sheet moves to `reports/campaigns/rb1/rb1-r02-scorer-handcheck/rb1-r02.*`. `scripts/check_g0.py --write-digest` and `scripts/check_r01_smoke.py --write-docs` write their gate results into the tree. A store prepared under an old `runbook-*` run_id is not picked up: preflight the renamed config.
- **H5: the LLM sorter against a decision model acting as the sorter (SAND-108, experiment keys `rb1-r13b` / `rb1-r70b`).** `mailroom_sandbox.sorter_arms` and `scripts/compare_sorter_arms.py` pair two or more finished sorter runs by document. They score class, subclass and subclass unit against the same locked truth, and price every item's tokens from the catalogs. The report covers accuracy, macro-F1, per-class F1, calibration, latency, cost per 1k documents and per correct document, and monthly cost. Paired tests: macro-F1 permutation, McNemar, bootstrap CIs, one-sided non-inferiority (2 pts macro-F1, 4 pts unit), and a Holm-adjusted H5 family. More than two runs adds a cost-quality frontier. The tool refuses unpaired runs, revision or truth mismatches, mock runs, handoff question sets, and held-out documents outside `--confirmatory`. `--write` saves the outputs under `reports/campaigns/rb1/<key>-sorter-vs-decision/`. Arm B reuses `task: sorter_reviewer` with handoff-free `reviewer_decisions_v4.0.0`, so no new task. Configs: `rb1-r13b-decision-sorter-{luna,jev-1.14}-dev-look1` (≈ $0.71 list) and the SEALED `rb1-r70b-decision-sorter-luna-heldout` template. New `mailroom_sandbox.heldout_seal`: preflight refuses a `heldout.exclude.ids` draw unless the run id is `rb1-r70*`..`rb1-r72*` and `SANDBOX_UNSEAL_HELDOUT` names it, and refuses any other split draw that prepares held-out rows. Plan: H5, findings 18-19, R13b/R70b rows, power. Nothing paid was launched.
- **Runbook Phase 0 setup finished offline (SAND-108): R01 pins and smoke configs, R02 hand-check, R03 audit tooling, G0 check.** Provider pins now cover the LangChain agents, including the production sorter, and the Decisions calls, all in the served-provider ledger. `config/provider_pins.yaml` pins one endpoint per chat model, the owner's first-party / full-precision choice, and a served display name matches a pin's tag. Six `config/runs/rb1-r01-smoke-*.yaml` configs (≈ $0.74 total) feed `scripts/check_r01_smoke.py`. `scripts/build_scorer_handcheck.py` and `check_scorer_handcheck.py` build and check the 20-doc R02 sheet (agent drafts until a person confirms them). Five specialist v0 configs and `scripts/build_gold_audit_sheet.py` cover R03. `scripts/check_g0.py` runs every Phase 0 gate. Nothing paid was launched.
- **Vendor hotfix layer and the subclass in isolated specialist runs.** `mailroom_sandbox.vendor_hotfixes` wraps vendored pipeline functions the experiments need fixed before llm-mailroom ships the fix, without editing `vendor/`: each hotfix is bound to the sha256 of the source it wraps (a vendor refresh that changes it fails `sandbox run preflight` until re-validated or retired), and every run lock records the hotfix set (`vendor_hotfixes`), which a resume must match. HF-001 fills a null corporate `record_type` from every corporate subclass through Dojo's map (indenture, board resolutions, officer certificates and subsidiary lists are `other`; charter amendments and certificates of formation `articles_of_incorporation`); upstream filled it only for the five Hub tokens (llm-mailroom#313). `job.specialist_subclass` (`none` / `gold` / `sorter` with `job.specialist_subclass_file`, needs `job.pipeline_handoff`, hashed only when set) names the subclass an isolated specialist's handoff carries, so `cms_source_table` and `record_type` are derived as in the pipeline; `gold` is refused for the merger specialist, whose subclass is its scored answer. Guide: `docs/vendor-hotfixes.md`.
- **Specialist candidates from the deployed frontrunners, aligned to the repaired schema (SAND-108, decision 3).** `contracts_specialist_condensed_v1` (from `contracts_specialist_v33_simplified`, half its length) names the 8 repaired contract fields the frontrunner never lists (`party_roles` with its role vocabulary, `signatories`, `agreement_date`, `expiration_date`, `termination_notice_period`, `dispute_forum`, `payment_terms`, `territory`) and writes `contract_value` as the plain dollar figure Dojo parses; it opens a contracts agent in `specialist_condensed_lineage.yaml` whose frontrunner stays `v33_simplified` until a candidate validates. `insurance_claims_specialist_condensed_v6` (from v3, asking for `cms_source_table`) is withdrawn before any run: the output schema cannot carry the field, which the pipeline derives from the subclass. `job.schema_guide`'s `contract_value` description follows the plain-dollar convention. Correspondence v4 and corporate v2 remain the aligned candidates; merger stays on `maud_v2`.

- **Class-specific calibration gates for the runbook (SAND-108, decision 6).** `config/splits/families.yaml` gains a `calibration` block (2% at 95%); a class whose documents left after dev and held-out cannot fund the 149 error-free accepts its own gate needs keeps all of them in calibration, none in the pool (audit gate). `runbook-v1` is rebuilt: calibration holds contract 105, corporate_record 137, correspondence 348, insurance_claim 376, merger_agreement 34, and `sandbox splits show` prints each class's best certifiable bound. `experiment_stats.zero_failure_n` and `class_gate_plan` size the gates. The reallocation is opt-in: a families file without the block keeps the old mix.
- **Price and decision catalogs refreshed, and time-of-day windows no longer read as tiers.** `refresh_api_prices.py` wrote OpenRouter's `utc_days` / `utc_start` discount windows as extra `min_prompt_tokens: 0` tiers; windows now fold into the base tier at their highest price (cap-safe) and the row records `time_windows`. 2026-11-18 list prices: `deepseek/deepseek-v4.1-flash-1017` $0.30/$1.20 per 1M at peak (was $0.036/$0.50), `deepseek/deepseek-v4-flash` $0.09/$0.18, `qwen/qwen3.5-9b` max completion 40,960. `microsoft/microsoft-decision-1.1` joins the decision catalog.
- **Decision question set 4.0.0 is in the lineage.** `reviewer_decisions_v4.0.0.yaml` landed without a `LINEAGE.yaml` entry; it is registered as a candidate (parent 3.1.0) with `typesafe/jev-1.14` as a `candidate_models` entry, and a test requires every question-set file to be listed.
- **R03 v0 sorter dev pass config.** `config/runs/rb1-r03-sorter-v0-dev.yaml` (900 dev docs, Qwen 3.7 Flash, production prompt, about $0.92 list with the long-prompt tiers, caps $1.50); preflight passes on dataset and prompt and waits for the owner's key and initials.

- **Markdown lint covers every rule and the CI lint tools are pinned.** `.markdownlint-cli2.yaml` turns on all markdownlint rules except line length and first-line heading (each disabled rule states why), sets list, code-block, emphasis and table-pipe styles, and stops ignoring `CHANGELOG.md`; the tree goes from about 4,800 findings to 0. The fixes include repairs to real rendering bugs: wrapped lines starting `#NN` that GitHub showed as headings, unescaped `|` that split table rows, bare `<placeholder>` text dropped as HTML, and invalid escaped backticks in code spans. The runbook generator demotes a nested card's headings and backticks placeholders, so regenerated `docs/runbooks/` stays clean. CircleCI gains a `checks` job (reports hub, requirements mirrors, CLI reference, `sandbox runbook check`) that starts with lint and test instead of waiting for coverage; lint installs pinned tools from `.circleci/lint-requirements.txt` (cache keyed on its checksum); JUnit results are stored even when a shard fails, so the timing split keeps its data. Branch protection should add `ci/circleci: checks`.

- **Extraction schemas graded against the truth runs score.** `sandbox schemas build|show` writes `config/extraction/subclass_schemas.json`: every (class, subclass) field with its Dojo status, its effective status under Hub + interim + near-gold truth, labeled counts by source and by runbook set, the dominant value, the corporate entity schema and the labeling-guide convention, plus a verdict (`iterate`, `thin`, `constant`, `fixed`, `no_truth`, `not_applicable`). It repairs 23 class-level fields the Dojo still marks `pending_annotation`, lists 6 labeled fields it marks `not_applicable` and the output fields with no truth, and fails (`--check`) on a stale file, truth the model cannot emit, a label outside its closed vocabulary or a `record_type` contradicting the subclass (0 today). `job.schema_guide: true` sets the guide's conventions as the specialist output-schema descriptions of the repaired fields (off by default, hashed only when set). Candidate prompts `corporate_records_specialist_condensed_v2` and `correspondence_specialist_condensed_v4` align with the guide. `sandbox splits show` prints the split's revision and the overlay flags.
- **Phase 0 review fixes.** The split ranks a leak component by its most-exposed member, so held-out holds no tuning-list document or anything linked to one (305 never-tuned + 695 untuned train docs; split rebuilt before any run used it), links identical `content_sha256`, places linked components before singletons in calibration/pool, refuses a missing exposure list and a `--name` outside `config/splits`, and its audit compares `assignments.jsonl` and every look complement with the rebuild. Provider-pin ledger rows carry `status: verified / unverified / mismatch`, a missing provider or model is `unverified`, and an explicit fallback chain is checked against its own models. `refresh_provider_pins.py --write-order` pins endpoint `tag` slugs, keeps the header and exits 1 without writing on a failed lookup. Exact McNemar no longer overflows past 1,024 discordant pairs, `paired_permutation` rejects NaN scores, and `paired_macro_f1` tests H1's macro-F1 directly. Offline, an uncached `ground_truth` shard is refused rather than read as blind rows.
- **Evaluation runbook Phase 0 pathways (R00-R02).** `sandbox splits build|audit|show` freezes a dev 900 / calibration 1,000 / held-out 1,000 / pool 402 split offline from the HF cache: per-unit quotas (subclasses, families from `config/splits/families.yaml`), length-band and source stratification, leak components (matter, group, normalized email subject, identical text; message ids and related ids when present), nested dev looks (300/600), and held-out seated least-exposed first (see the review fixes above). `sandbox splits audit` re-derives the split from its seed and checks the families and tuning-list hashes. Runs select a set with `exclude_ids_file` + `draw: ranked`. `mailroom_sandbox.experiment_stats` adds exact McNemar, a sign-flip permutation test, Holm, the sequential-look keep rule, cost-weighted error and Brier/ECE null floors. `mailroom_sandbox.provider_pins` pins OpenRouter providers per model (`config/provider_pins.yaml`) and records each call's served model and provider (`SANDBOX_SERVED_LOG`), flagging a provider outside the pin or a model other than the requested id or its dated slug; `scripts/refresh_provider_pins.py` lists endpoints. `corpus.load_hf_rows` reads cached shards when the Hub tree cannot be listed for a pinned sha. Plan and runbook audit: `docs/superpowers/plans/2026-11-18-evaluation-runbook-plan.md`.
- **Critical-regressions checklist.** `docs/critical-regressions.md` lists the failure classes every PR checks against; the PR template, AGENTS.md and CLAUDE.md link it.
- **The interim overlay applies to Hub parquet rows directly.** `apply_overlay` matched rows only on the prepared shape (`id`, `doc_text`, `expected_fields`), so a raw `ground_truth` shard row (`document_id`, `gt_fields`, no text) silently took no labels. It now also reads `document_id` and `gt_fields`, matches a row without text on its `content_sha256` (the overlay's `doc_sha256` is the first 16 hex of the same hash), and writes the labels back into `gt_fields` as a JSON string. `interim_labels.apply_overlay_parquet` and `scripts/interim_labels.py apply --parquet SHARD --out FILE` write a shard with the same columns plus `interim_labels`. `check --rows` accepts a parquet shard, and `check --prune` keeps a reviewed gap fill the Hub supersedes and reports it instead. A reviewed correction that differs from the Hub value is kept without a report, because a correction replaces the Hub value it names. On the ccd040f6 shards the overlay applies 3,690 labels to 1,552 of 2,979 train rows and 150 labels to 65 of 323 test rows, including every one of the 1,847 reviewed labels.
- **Interim labels take reviewed corrections and the original email headers.** `scripts/interim_labels.py review [--apply FILE]` writes reviewed labels from `data/labels/review/interim_reviews.jsonl` into the interim overlay, without a gate run. The 52 correspondence `intent` values the review found wrong in the Hub become `correction` labels (basis `review_read_message`). They replace 52 of the 72 `disputed` labels and now replace the Hub value in production. 1,795 correspondence `sender`, `recipient`, `additional_recipients` and `communication_date` fields take the original message's header from the CMU Enron maildir as `gap_fill` labels (basis `original_header`). Each label quotes its header lines and file, and the builder checks every name token and the `Date` against them. They replace 329 gate gap fills (315 with a different value) and win over the text-only near-gold labels. Every reviewed label keeps `review`, `evidence` and the label it `replaced`. The manifest lists each review file with its sha256: `check` fails when the file changes or one of its labels is missing, and `build` applies the files again after a rebuild. The header values are not in the corpus text, so extraction scores on those fields drop until mailroom-dataset restores the headers.
- **Contract amounts Dojo can parse.** Seven near-gold `contract_value` labels were phrases Dojo's `parse_money` cannot read ("$5 million", "$10 million", "US$400,000.00", "$55,000USD", "$40 per month", "$0.05 per Unit"). A correct numeric prediction scored as low as 0.11 against the scale-word and currency-code forms. The rate forms scored 1.0 only through the scorer's text fallback. They are now plain dollar figures ("$5,000,000", "$400,000.00", "$55,000", "$40", "$0.05"), with their quotes unchanged, from `data/labels/review/contract_value_review.jsonl`. The new `scripts/gold_labels.py review --corpus DIR --review FILE` applies `accept` and `correct` lines to the committed catalog in place, using the same gate on the corpus text. The gate accepts a plain dollar figure that exactly restates a scaled figure in the quote ("$5,000,000" for "$5 million"). `gold_labels.py check` now rejects a near-gold currency phrase Dojo cannot parse, and the labeling guide gives the plain-dollar form. The near-gold overlay is re-exported: contract `opus_reviewed_correct` 7, `two_pass_agree` 893.
- **CI is CircleCI only, and it rejects leaked links.** The GitHub Actions workflows (Dependabot auto-merge and the link guard) are removed because Actions cannot start jobs on this account; Dependabot PRs are now merged by hand. The new CircleCI job `no-session-links` fails when a commit carries a claude.ai session, project, chat, artifact or share link, a `Claude-Session` trailer or a "Generated with Claude Code" footer. It also checks the PR title and description, warning and skipping that part if the GitHub API is unreachable. Commits follow the new `.gitmessage` template.
- **Autoresearch charges what a resume billed again.** `api_spend` now reads `api_usage_of_rerun_document` events as well as `api_usage_of_failed_document`, matching the run's own API budget, so a resumed round no longer under-counts against the study budget.
- **An interrupted mock round can be retried.** A mock run reserves no `pending` row, so it now claims its run id first (as the holdout does); a stop after its run directory existed was refused as stale.
- **The autoresearch `key_spend` baseline survives a different key.** `key_start.json` is committed under `reports/autoresearch/`, so a fresh checkout with another key judged the new key against the old key's starting balance. The file now carries `key_identity`, a 16-hex digest of the label `GET /api/v1/key` returns (never the key or a hash of it). A different identity, or more balance than the recorded start, takes a new first reading with a `key_baseline` warning in the ledger; an older file without an identity adopts the current key. The committed `reports/autoresearch/` files are untouched.
- **An interrupted autoresearch holdout can be retried.** `prepare()` creates the holdout's run directory before the pending ledger row exists, so a stop in between made the retry refuse its own directory as stale (mock holdouts too). The study now claims the run id in `claimed-runs.txt` of its state directory before `prepare()`; a directory nobody claimed is still refused.
- **`sandbox autoresearch` works inside `sandbox tui`.** The shell prepended its session defaults (`--profile`, and `--model`/`--prompt`/`--agent-model` when set) to every command, and the autoresearch override refusal read them as typed, so every command was refused. `cli.main(argv, injected=...)` parses the defaults first but keeps them out of `args.raw_argv`; a flag typed at the prompt is still refused.
- **The autoresearch context check sizes an omitted `max_input_chars` like execution does.** A question set without one was checked as 0 characters, so a small-window Decisions model passed the catalog check; the check now uses `DECISIONS_MAX_INPUT_CHARS` (explicit smaller caps stand; the extraction gate also counts its largest `max_input_chars_by_class` value).
- **A Decisions `:variant` id is unpriced through `call_price` and `token_price_ceiling` too.** `price_sheet` already refused it, but both then reached `token_price`'s dojo and prefix fallbacks and priced it at a chat model's rate. An explicit price-sheet row of its base id, or an exact row for the variant, still prices it.
- **`--profile` has help text.** The shared flag documents itself in `sandbox --help` and `docs/cli-reference.md` (provider profile name; default from `SANDBOX_PROFILE`, then `.env`, then the providers default).
- **A resumed whole-run job counts the documents it billed again against `job.api_cost_cap_usd`.** A resume re-runs every locked row; a document the earlier attempt had persisted was billed a second time but never recorded again, so the next resume's budget seed missed that bill. It is now kept as an `api_usage_of_rerun_document` event (the item row stays the evidence) and `usage_records` counts it.
- **`sandbox autoresearch`: a config-only greedy search over run-spec levers, with a held-out confirmation run.** `plan|step|run|status|holdout --study PATH` (`docs/autoresearch.md`). It changes no pipeline code and drives the existing locked-run lifecycle (spec, preflight, start, gate).
  - Each round diagnoses the champion into a weakness table (lost utility charged to node x class), applies the first untried lever attached to the worst node (champion plus ONE patch, validated as a `RunSpec`), runs it on the same frozen draw, scores per-document utility, and keeps or reverts on a paired stratified bootstrap. An append-only `ledger.jsonl` under `reports/autoresearch/<study>/` makes it resumable. It stops on budget, exhausted levers, or 3 consecutive reverts.
  - Utility per document: correct archive = its extraction score, unscorable 0, review -0.25, wrong archive -1.0, crash or `judge_error` -1.0 (configurable). Keep needs the CI low above `max(0, effective noise floor)`, no gated class down more than the larger of 0.05 and its replicate swing, no more wrong archives, and cost per document within 1.25x unless the gain is at least 0.05. Placement levers use `goal: cost` (not worse, at most 0.9x the cost) and still face the class-drop and wrong-archive guards.
  - Levers (`config/autoresearch/levers.yaml`): Decisions-API reviewers only (the champion's reviewer is the chat reviewer), cheaper worker models, specialist prompts and windows, judge routing, an extraction-gate diagnostic, three tiers of supervisor models in the judge, arbiter and boss roles with `requires` ordering and derived per-role placements, and `repair-283`, a pipeline-source lever run with `MAILROOM_SRC` (never proposed without `AUTORESEARCH_PR283_SRC`; `vendor/` is untouched).
  - Replicate baseline: the baseline's identical spec runs a second time on the same draw, and the study's effective noise floor is `max(configured noise_floor, |mean paired delta|, CI half-width)` of the pair; no lever runs or is kept before the replicate exists. A round the run's own API cap aborts is `aborted_cap`: no verdict, not a revert, charged at least its full cap.
  - Spend: initials are required for any non-mock study and never defaulted. Before each paid round the loop checks `ledger spend + round cap <= study_usd` (a NaN fails closed; a ledger row with a non-finite cost stops the study), the key's remaining limit, and the bill itself (`key_spend`: the key's drop since the study's first reading, kept in `key_start.json`, plus the cap must fit the study budget); the two key checks need a key with a spend limit and are skipped, with a warning, for an unlimited key. A run is charged `max(scored cost, its own ApiBudget spend)`, which counts retried attempts and documents that raised after a paid call. A `pending` ledger row reserves each paid round's cap before its child runs, so a crash cannot spend the same budget twice; `step`, `run` and `holdout` hold an exclusive `flock` on the state directory, and specs, `champion.yaml` and scores are written atomically. A lever whose runtime-bound estimate (the champion's tokens priced at the candidate's dearest API model, like the run's own budget) exceeds its round cap (the study's, or a supervisor lever's derived cap up to `max_round_cap_usd`) is written as `skipped: over_round_cap`. Child-process output is scrubbed (the key, `sk-or-` tokens, bearer tokens) before it is truncated. The OpenRouter key is never printed or stored.
  - Production parity: the `mailroom-v1` base is `config/runs/production/slice-0100.yaml` with a 5-per-class draw and the chat reviewer, at the production sampling temperatures (no temperature override anywhere); the run-to-run noise that follows is measured by the replicate baseline. `report.md` lists the vendored pipeline and Dojo commits and every difference. The holdout draws the next ranked block (at most twice the dev draw), excluding `config/production/excluded-ids.txt` plus every dev document, and refuses any overlap.
  - Also: `config/decision_models.yaml` and `scripts/refresh_decision_models.py [--check]` pin the Decisions-API catalog; `decision_backends.is_decisions_model` accepts an id only when it is listed (never `~` aliases, `-latest`, or chat models such as `typesafe/jev-router`); `config/api_prices.yaml` and the `openrouter` profile gain the supervisor models; items record `usage_by_agent` so cost splits by worker, oversight and reviewer (older runs are totals only).
  - Review hardening: a candidate that recorded an unpriced model is reverted where a cost rule applies (its cost is understated); a run directory with no ledger row is refused, not resumed as a new measurement; the lever catalog's `requires` argument shapes, `requires` group matching without a tier, and every `placements` expansion are checked at load; the paid-study reviewer guard reads the validated `job.mock` and a `:variant` reviewer takes its base model's context window; a `:variant` of a Decisions model is never priced by a chat model's prefix; `usage_by_agent_from_pipeline` is soft for a malformed slot and logs; the report compares the champion with the frozen baseline spec; `--model`, `--prompt` and `--agent-model` are refused by `autoresearch` instead of ignored.
- **Run specs carry llm-mailroom's decision slots (`decision_slots:`), with a Decisions-API closed-field resolver and per-slot scoring.** A `task: pipeline` spec may set the mailroom's `decision_slots` block (sorter-reviewer park cap, archive gate, judge replacement, arbiter veto, judge and boss approval checks, closed-field resolver, field-level review), and its `confidence` block may set the mailroom's archive-check flags `judge_complete_archives`, `arbiter_accept_archives` and `judge_clears_low_confidence` (strict booleans; `true` restores the old route for a baseline arm; they take effect only after the vendor refresh that brings llm-mailroom #309; until then preflight refuses a spec that names them, since the current vendor would ignore them); it is written verbatim to the runtime taxonomy, checked at preflight by the vendored mailroom's own `parse_slots`, and refused when a gate slot has no `extraction_gate` block, the resolver slot has no `resolver`, or the vendored mailroom predates the slots (re-vendor). `decision_slots.resolver` registers a Decisions-API resolver (`config/decisions/closed_field_resolver_v1.0.0.yaml`, uncalibrated: one pick-one question over the field's allowed labels plus `none_of_these`), frozen by content in the lock and counted in the OpenRouter spend, budget and deploy checks; mock runs get an offline resolver that never picks. The pipeline gate now reports `fields_asked` (evidence; the mailroom judges coverage from its own `gate_key_fields`). A live lock that registers Decisions-API models refuses a `mock` override at run time (activation would still call them while skipping the API budget). Caps start from a fresh ledger every run. Mock runs never exercise the gate slots: the mock gate answers no `field_support`. Items export `decision_slot_outcomes`, `decision_slot_marks`, `closed_field_resolutions` and `judge_source`, and the slice gate report adds a `decision_slots` section from the Dojo's `analysis.risk_coverage` (gated classes only, like the pooled rates: per-slot park, release, capped and unavailable rates; the gate `key_field_score` risk-coverage curve over scorable archives, with the observed-rate and Wilson operating points at the slice's wrong-archive bar). Running a non-baseline block needs the llm-mailroom and Dojo vendor refresh that brings both modules; nothing was run against a paid model.

- **`sandbox api eval --dataset-config <yaml>` scores a running or deployed mailroom API on corpus documents with production ground truth.** The YAML's `dataset:` block (any `config/runs/production/` slice works as is) is prepared exactly as a run prepares it: the pinned revision, the seeded draw and strata guards, the `content_sha256` check (a mismatch is a usage error), and the interim and near-gold overlays (Hub > interim > near_gold, except that an enabled interim `correction` label replaces the Hub value it names). The plan and the report carry that provenance under `dataset` (with `selected`: the ids of the rows actually sent after `--class`/`--sample`, where `--sample` is a prefix, not a stratified draw), and a `--floor-run` copy records it in `spec.lock.json`, where `dataset.sha256` is the hash of the saved `dataset.jsonl` and `dataset.prepared_sha256` that of the prepared draw. An empty or malformed YAML, an empty `--dataset-config` value, a Hub revision that lacks the shard, and a row with no document text are usage errors (exit 2) rather than silently drawing the whole Hub corpus or a traceback, and the prepared JSONL is split on `\n` only, so document text holding U+2028/U+2029 stays one row. Fix found on the way: inline-text corpus rows whose source name is not `.txt`/`.md` (`*.htm`, `*.html`, `*.eml`, …) were refused by `/upload` (HTTP 400) and stopped the eval at the first such document; they now upload as `.txt`, with a position prefix when two rows would otherwise share an upload name. Checked with `sandbox api eval --mock --dataset-config` on 10 corpus documents (2 per class, revision bc9eab28): 10 of 10 archived, interim labels on 4 rows and near-gold on 2.
- **Review decisions for the gold build, and a validation of production truth.** `data/labels/review/decisions.jsonl` turns the label review into `scripts/gold_labels.py build --review` lines for the correspondence and corporate-record catalogs: 3,069 `accept` (each naming the current value) and 173 `correct` (each passing the gate on the Hub text; the four owner `signatories` decisions already landed in #336). Built in, they raise near-gold truth from 4,256 to 6,253 correspondence fields and from 75 to 799 corporate-record fields, and leave 1 near-gold label that disagrees with the review instead of 40. Labels corrected from the header of a reply typed above quoted mail follow the labeling guide's reply rule. `decisions_held.jsonl` lists the 10 labels left out, and `tests/test_label_review_decisions.py` checks the file against the committed catalogs. `VALIDATION.md` reports the checks (pipeline schema, Dojo field types and self-scores, text grounding, agreement with the review) and the open owner decisions: interim gap fills that override reviewed gold, 52 wrong Hub `intent` labels, and six contract `contract_value` phrases that Dojo's money parser scores below 1.
- **The owner's review-desk decisions are locked in.** `data/labels/review/human_reviews.jsonl` records the 8 labels the owner decided on the review desk (4 kept, 4 changed), and `verdicts.jsonl` carries them as `human_verified` or `human_corrected`; 77 labels still need a human. These decisions are final: any rebuild of the verdicts applies them last, the integration (still pending, see `data/labels/review/INTERIM_AUDIT.md`) must write their values as is when it is implemented, and `tests/test_label_review_human.py` fails if one is lost or changed.
- **Audit of the interim truth labels, with an integration handoff.** `data/labels/review/interim_audit.jsonl` gives one verdict per interim label used as truth (2,682 labels): 2,079 verified, 411 grounded in the text where no reviewed gold exists, 69 format-only differences, 97 wrong (3.6%) and 26 waiting on a policy decision. Errors concentrate in correspondence `recipient` (23%) and `sender` (9%) gap fills, which reviewed gold already covers, and all 23 merger `effective_date` labels hold the signing date although the gate rule leaves the field empty when only an Effective Time is defined. Six corporate `record_type` labels were derived from an outdated subclass. `INTERIM_AUDIT.md` gives the results by stratum, assesses contracts, merger agreements and insurance claims (only contracts and merger agreements need a gold catalog), and lists the integration steps, including letting reviewed gold supersede interim gap fills under `dataset.near_gold_labels`.
- **Label review verdicts for every gold and disputed interim label.** `data/labels/review/verdicts.jsonl` records one verdict per label for 8,286 labels: 6,339 verified, 196 corrected, 1,666 correspondence fields filled from the original email headers (CMU Enron maildir) where the document text omits them, 8 decided by the owner, and 77 left for a human. The 77 are grouped into policy questions in `policy_questions.json`. The rebuilt `cuad_clauses` for four disputed contracts follow the Hub's CUAD expert spans. Nothing reads the folder by default; see its `README.md`.
- **Owner review-desk decisions applied to the near-gold catalog.** Four corporate-record `signatories` labels now take the owner's values from the review desk (#327), recorded as `correct` reviews by reviewer `{"model": "human", "role": "owner_review_desk"}` and validated by the same gate. Three of them were single-pass candidates and are now `near_gold`, so the overlay fills 78 corporate-record fields on 41 documents (was 75 on 38).
- **Production runs score against Claude near-gold labels where the Hub has none.** `dataset.near_gold_labels: true` (on in every `config/runs/production/` slice) merges `data/labels/gold-overlay/` into the drawn rows after the interim overlay. A Hub label or an interim truth label always wins (an interim correction may itself replace a Hub value). The labels stay marked `near_gold`: each row lists the fields it took, and the lock records the overlay's sha256. The labels were made on corpus revision ccd040f6; on it and on the production pin bc9eab28 (same text for every labelled document) this fills 4,256 correspondence fields on 780 documents, 900 contract fields on 110 documents and 78 corporate-record fields on 41 documents. See `docs/EXTRACTION_GATE_VETTING.md`.
- **Floor viewer: repaired, and built for analysis.**
  - Repairs: the graph now fits its drawn boxes instead of a fixed 2200×1400 canvas, so node figures are readable at load; a run whose checkpoint says `running` but whose artifacts have been idle for 15 minutes (`FLOOR_STALL_SECONDS`) is shown as `stalled`, is not chosen as the default run and gets no RUNNING pills. The resident app rebuilds at least every 60 seconds while a checkpoint says running, so a run that dies while the viewer is open turns stalled, and one that resumes comes back.
  - New analysis panel under the graph: SCORES vs GT (classification accuracy, per-class recall/precision, Dojo extraction mean, a confusion matrix, label tiers), DOCUMENTS (one row per document with its node path; click one to trace it on the graph) and NODES (where the documents through each node ended up).
  - Ground truth is split by label tier with Hub > interim > near_gold precedence: a document whose GT used any near-gold field is reported as `near_gold`, never as Hub GT, and the headline extraction mean shows the Hub-only mean beside the all-tier one. Fixture-manifest labels show as `fixture`. A finished document with no predicted class counts as a classification miss.
  - `sandbox api eval --floor-run [ID] [--base DIR]` records the eval as a floor run (node paths from each document's stage audit), so `sandbox api eval --mock` gives a no-spend run to inspect.
  - The digest gains `docs`, `scores`, `node_outcomes`, `checkpoint_state`, `stalled_s` and `last_activity_utc` per run; the viewer still opens older digests.

- **Vendor refresh: llm-mailroom `f83e398` → `8cebcd8` (`main`); Dojo stays at `025400f`.** `8cebcd8` is llm-mailroom `main` after #287 squashed the v0.30.0 release line into it; its tree is byte-identical to `v0.30.0` at `815c169`. It still declares Dojo `025400f`, so the Dojo snapshot is unchanged.
  - #283: insurance `cms_source_table` comes from the Hub subclass, and CMS claims carry `supporting_documents` references, Part D NDC included.
  - #284: an opt-in, pinned interim ground-truth overlay. It is off unless a run enables it.
  - #286 and #289/#291: routing as data and pluggable decision points. Decision points are empty by default, so routing is unchanged.
  - **Score changes:** insurance extraction on CMS rows (`claim_type`, `supporting_documents`). Rescore stored runs before comparing them with runs on `f83e398`.
  - Not scored yet: `cms_source_table`. The pipeline now emits it, but the Dojo insurance suite (`025400f`) has no class-level field type for it, and the sandbox's extraction scope stays equal to the Dojo engine. `tests/test_extraction_scope.py` records this and checks the scope against the vendored schemas, so the next field a refresh adds cannot go unscored silently.
  - The floor digest (`reports/dashboard/build_floor_digest.py`) reads the edge topology from `graph/route_spec.py`, where #286 moved it; the derived graph is identical to `f83e398`'s (40 edges).

- **`sandbox api`: one client for the mailroom API and the selected Dojo.**
  - `sandbox api status` shows the pinned and selected mailroom and Dojo (source, version, commit) and the API's `/health`. `--offline` skips the API probe.
  - `sandbox api eval` uploads fixture documents (`--class`, `--sample`) to a running API, waits until each reaches `archived`, `review` or `failed`, and scores them with the same Dojo scorers as `sandbox eval pipeline`: classification and stage over every finished document (a `failed` one counts as wrong), extraction over archived documents only. It works on the local `sandbox pipeline api` or on a deployment named by `MAILROOM_API_URL` (token from `MAILROOM_API_TOKEN`, never printed). It only plans unless `--submit` is given, because the API process runs its own models and this client cannot cap that spend. Each upload is renamed with a run tag, so an earlier run's same-named document is never read back. Documents that do not finish are listed as `incomplete` and not scored. Incomplete or `failed` documents, or an API error mid-run, make the command exit 1; the report still lists every accepted upload. An upload refused by the API's rate limit (HTTP 429) is retried after a back-off.
  - `sandbox api eval --mock` runs the same upload, poll and score loop against the vendored API app in process: the real FastAPI routes, bins, catalog and LangGraph pipeline, with the mock LLM and a temporary data directory. It needs no server, no network and no spend; tracing and Langfuse prompt or score calls are switched off even when keys are set, and the whole environment is restored afterwards. It checks the API wiring end to end: all 11 fixtures reach a final stage and are classified correctly, but under the blind mock 9 of 11 stop in `review`, so extraction is scored on the 2 archived documents only. It says nothing about model quality. It needs the `observability` extra, which the API imports.
  - `mailroom_sandbox.family_api` exposes the same pieces (`MailroomAPI`, `family_status`, `run_api_eval`) to scripts and notebooks. `tests/test_family_api.py` also checks that the vendored API still serves every endpoint and document field the client reads, so a vendor refresh that breaks the contract fails there.

- **Insurance v4 is adopted and folded into a v5 candidate; the judge audit leaves routing alone.**
  - The v4 A/B (40 documents): mean 0.874 → 0.880 and Part D NDC 0/5 → 5/5. `claim_type` did not move: the pipeline's structured-output schema still asks for CMS table tokens, which only llm-mailroom #280 changes.
  - `insurance_claims_specialist_condensed_v5` is v4 plus #280's line-of-business vocabulary. Its A/B arms, `specialist-condensed-v5-insurance-claim-qwen-{v4arm,v5arm}`, run on the v4 A/B's documents after #280 is vendored. The slices stay on v3 until v5 passes.
  - `config/production/excluded-ids.txt` adds the v4 A/B's 40 documents. Its header now names the correspondence reference arm that was actually drawn (`v2arm-r2`); the ids are unchanged. The slices' `ranked` draw keeps every slice as it was.
  - Judge audit (26 documents paired with slice 100 r2): judging every corporate, correspondence and insurance extraction caught 1 of 6 wrong archives, sent 5 other archives to review and cost up to 3× the tokens. `judge_band_high` stays as it is.
- **Vendor refresh: llm-mailroom `63f6841` → `f83e398`, Dojo `116da0b` → `025400f` (0.30.1, untagged).** These are the release-branch heads after llm-mailroom #281 and llm-dojo-scoring #174. llm-mailroom `f83e398` declares Dojo `025400f`.
  - Insurance `claim_type` is the product line (llm-mailroom #280, #174 §2). The structured-output description asks for `auto`, `property`, `liability`, `health`, `life`, `workers_comp` or `other`, the extract node normalizes a CMS table token to `health`, and extraction ground truth does the same. `tests/test_pipeline_handoff.py` now expects `health` for a Part D claim.
  - CUAD `agreement_date` and `expiration_date` count toward clause recall only (Dojo #173, #167). A filled date is never a false positive where CUAD left it unannotated.
  - `requirements/dojo-release.txt`, `snapshots.PINS` and `tests/test_eval.py` move to Dojo 0.30.1 at `025400f`. The specialist prompt mirrors are unchanged.
  - **Score changes:** insurance `claim_type` on CMS rows and CUAD clause precision/F1. Rescore stored runs before comparing them with runs on the old pins.
  - Unblocks the insurance v5 A/B (#320) and slice 100 r3.
- **Vendor refresh: llm-mailroom `abb1ccf` → `63f6841`, Dojo `13adc8e` → `116da0b` (tag `v0.30.1`).** These are the release-branch heads after llm-mailroom #271 and llm-dojo-scoring #169. llm-mailroom `63f6841` declares Dojo `116da0b`.
  - Fixes the production slices hit:
    - A 200 response with `choices: null` is a transient error, not a `judge_error` (llm-mailroom #261, #260).
    - A decision-reviewer backend error is recorded as an error (#268).
    - Correspondence `communication_type` is typed by content, not carrier (#269, Dojo #166).
    - A typed decision with no gold for its class counts as `no_gold` (Dojo #168).
  - Routing ignores `ground_truth` unless oracle routing is on (#207). The sandbox already sets `blind_routing`. Retry keep-best (#254) and the chunk-merge evidence policy (#255) are opt-in and stay off.
  - `tests/test_judge_second_pass.py` drops its strict #260 xfail, which would now fail CI.
  - `config/prompts/correspondence_specialist_production.txt` is re-synced to the content-typed vendor text (`e3bc920d`). The frozen eval-environment stem `correspondence_specialist_v7` (`correspondence_specialist_simplified`, `2b0b81ff`) keeps its bytes; `tests/test_eval_environment_lineage.py` now pins that Dojo's `production_prompts` text moved past it. Production slices use `correspondence_specialist_condensed_v3` and are unaffected.
  - **Score changes:** Dojo `decision.*` lane scores can move on unchanged records. Extraction field scores do not change. Pipeline behaviour changes for correspondence typing, retries and judge errors, so runs locked on the old pins are not directly comparable.
  - Not included: insurance `claim_type` (llm-mailroom #280, #174 §2) and CUAD dates (Dojo #173, #167). Both are open upstream.
- **A run without `job.blind_routing` still routes on its labels.** llm-mailroom #264 ignores `ground_truth` unless oracle routing is on. Without a fix, every non-blind sandbox config would have quietly become blind. `eval.runners` now runs each pipeline document under `oracle_routing_override(not blind)`, so locked configs reproduce. A blind run forces oracle routing off whatever `MAILROOM_ORACLE_ROUTING` says. `tests/test_pipeline_routing_matrix.py` walks the ground-truth arms with oracle routing on, and pins that they are skipped with it off.
- **The gate counts only fields the Dojo scores** (#306).
  - `labelled_count` now keeps only keys in the Dojo extraction schema (`field_names(doc_class)`), falling back to the old count for an unregistered class. Corpus annotations (`content_topic`, `sentiment_label`, `sentiment_score`) are no longer counted as labels.
  - Effect: 23 correspondence rows that are scored on `intent` alone are now unscorable. Re-gated, slice 100 r2 is 40/55 = 0.727 wrong archives, not 48/78 = 0.615.
  - `config/runs/production/judge-audit-0026.yaml` is a diagnostic arm that judges every corporate, correspondence and insurance extraction on 26 documents that pair with r2 (llm-mailroom #278). A human launches it.
- **A run lock names the code that ran** (#312).
  - Every run-spec section (`dataset`, `job`, `engine`, `trace`, the prompt refs and the top level)
    now rejects unknown keys. An older checkout silently ignored `dataset.exclude_ids_file` and drew
    a different 40 documents for the correspondence v2 reference arm.
  - Preflight's new `checkout` check fails when the imported `mailroom_sandbox` lives in another
    git checkout than the cwd's, the case of a worktree sharing the main checkout's venv
    (override: `SANDBOX_ALLOW_FOREIGN_CHECKOUT=1`). It runs on every preflight, including the one
    `run start` makes, and the lock records the code's checkout as `package: {path, commit}`.
- **Specialist A/Bs can see the pipeline's handoff** (#306).
  - `job.pipeline_handoff: true` (specialist tasks only; hashed only when set) sends each document the
    vendored extract node's handoff, built by `graph.build_graph._build_handoff_context` with the
    class alone (no subclass, confidence or document id), and applies the node's inventory
    normalization (`_enrich_contract_result`). Earlier specialist A/Bs ran without that note.
    In production slice 100 r2 the note overrode the prompt: all 18 CMS rows got a CMS table
    token for `claim_type`, and it tells correspondence that "Enron-style inbox text is email"
    (llm-mailroom #174).
  - `insurance_claims_specialist_condensed_v4` (candidate): `claim_type` is the printed line of
    business, never a CMS table token, and a Part D statement lists its NDC in `supporting_documents`.
    Three arms share one 40-document draw (v3 without the handoff, v3 with it, v4 with it):
    `config/runs/specialist-condensed-v4-insurance-claim-qwen-{v3arm-plain,v3arm,v4arm}.yaml`.
  - `config/production/excluded-ids-insurance-v4-ab.txt` is the tuning list plus the slice-500 draw,
    so the arms never draw a production-slice document.
- **Modal job host runs OpenRouter slices** (#308).
  - `deploy/modal_job.py` ships `OPENROUTER_API_KEY` in the deploy Secret, never the image, when
    the deploying shell has it. `run_job` drops it for a locked run that never calls OpenRouter
    (`deploy_env.lock_uses_openrouter`) and restores it for a later OpenRouter input in the same
    warm container. A run that does call OpenRouter fails before its first document if the worker
    has no key.
  - Preflight no longer refuses the `decisions` reviewer in modal mode; the `api` and `jev` guards
    stay. A locked run's profile already sets `DEFAULT_PROVIDER` on the worker, so the image's
    `vllm` default applies only before activation.
  - The slice twins preflight offline with only the missing key as an error. Tests cover the
    twins, the key scoping and a worker round trip.

- **Frozen confidence includes the component routing overlay** (follow-up to #303). Preflight
  froze `effective_confidence` from the vendored taxonomy and the taxonomy overlay only, while a
  locked activation replaces the runtime block with it. The `config/components.yaml` routing
  layer (global `high` 0.95, `low` 0.7, `retry_max` 1, `conflict_threshold` 0.3) was therefore
  dropped from locked runs. `effective_thresholds` now merges it in the same order as
  `build_merged_taxonomy`. A test asserts that a locked run routes exactly like an unlocked one.
  No run had been locked with the incomplete block.

- **Production slice gate** (#305). Production runs are nested slices of the HF mailroom dataset,
  and each slice must pass a gate before the next one runs. The slices exclude the recorded
  pipeline tuning runs; sorter accuracy and the earlier specialist A/B documents remain in-sample
  (see the runbook's known limits). The runbook is `docs/runbooks/production-slices.md`.
  - `dataset.exclude_ids_file` drops listed documents before the draw and is hashed into the run spec.
    `config/production/excluded-ids.txt` holds 147 tuning documents: the 107 of the 11 ladder runs and
    the 40 of the correspondence v3 A/B. `excluded-ids-ladder.txt` is the frozen ladder-only list, which
    the A/B arms exclude. Both lists are regenerated by `scripts/build_excluded_ids.py`.
  - `dataset.draw: ranked`, opt-in and hashed only when set, orders each strata bucket by a
    per-document hash rather than shuffling it. Adding ids to the exclusion list then keeps the rest of
    every slice, and the slices stay nested. The default `shuffle` draw is unchanged for every other
    config.
  - `sandbox run gate` is offline and writes `gate.json` and `gate.md`. The bars are
    `config/production/bars.yaml`: ≥ 0.90 per document, ≤ 2% wrong archives, ≤ 5% review, and no
    crashes or `judge_error`. Mergers are outside the quality and rate bars, but a merger crash or
    `judge_error` still fails the slice. Duplicate keys in a bars file are refused.
  - Each review or wrong archive gets one primary cause. The new `input:near_empty` applies to
    reviews only; a wrong archive keeps its classification or extraction cause.
  - Each document row carries its `archive`, `trace_id` and `job.item` `span_id`. A missing
    `job.item` span, or an archive without the archived class's subdirectory, fails the gate.
  - With `--prev-run-id`, a run over the same documents gets a paired re-run check, which fails if
    wrong archives, reviews, crashes or `judge_error` rose, or if the two runs' labels differ on a
    shared document. Any other pairing is a step-up: the whole new run is gated first, then the
    step-up check on the new documents adds its reasons, so either can fail the verdict.
    `--thresholds` adds the judge-threshold replay, which is an upper bound. Non-finite paired
    confidence bounds are written as `null`, so `gate.json` is strict JSON.
  - A run that never started, a bad bars file or a scorer failure exits 1 with a JSON `failed`
    status, never a FAIL verdict. An archive with enough labels that the scorer could not score
    fails the gate instead of leaving the wrong-archive denominator.
  - `gate.md` has a per-document table whose archive links are relative to `gate.md`. `--thresholds` also projects the wrong-archive and review
    rates for each candidate threshold, plus a worst-case review rate.
  - New bar `min_scorable_per_class: 20`: from the 500-document slice onward, a gated class with fewer
    scorable archives fails the slice (corporate records, llm-dojo-scoring #164). A gated class absent
    from the run counts as 0 scorable archives and fails too.
  - `config/runs/production/slice-{0100,0250,0500,full}.yaml` use r3's settings with seed 3302 and
    nested draws. Slices 0100, 0250 and 0500 have Modal job-host twins (the full slice has none);
    the twins are blocked by #308.
  - `correspondence_specialist_condensed_v3` is adopted (#306) after its paired A/B, and the slice
    configs use it. A strict xfail tracks the null-`choices` judge `TypeError` (llm-mailroom #260).
  - The Decisions backend masks card-shaped 4-4-4-4 digit groups (`mask_card_numbers`) in the
    document text and the extraction-gate handoff, which the endpoint's content filter otherwise
    refuses with a 403. Unbroken digit runs are kept.
  - `prepare_subset` reads the exclusion file once and records its sha256. The run lock hashes
    those bytes, so an edit during preflight cannot make the lock disagree with the draw.
- **Paired report, routing audit and label tooling hardening** (#303 review).
  - `job/pair_report.py` refuses a run directory without `dataset.jsonl` or `items.jsonl`, so a
    misspelled run id fails instead of printing an empty report. Documents whose locked labels
    differ between the arms are listed under `label_mismatch` and are not paired.
  - Preflight freezes the resolved confidence block as `effective_confidence` in the run lock. The
    routing audit reads it (`thresholds_source: locked`). For older runs it reports
    `judge_rejudge_retry` as unknown unless the run set it, instead of today's default.
  - `scripts/interim_labels.py rederive` restores every file if a write fails, so the overlay
    still passes its integrity check and the command can be retried.
  - The ladder audit states the E3 overlap it checked (0 documents shared with E1 or E2, 1 with
    r2 and 1 with r3). It no longer reads the unpaired E3 correspondence score as evidence about
    the prompt. The E3 treatment config is marked as an obsolete plan.

- **Blind routing, interim-label fix and paired report for E2/E3** (#300).
  - `job.blind_routing: true` (pipeline runs only) keeps the dataset labels out of the graph's
    `ground_truth` state, so the class-miss gate and the coverage-floor retry cannot use them
    (llm-mailroom #207). Scoring still uses the full locked row. The value is hashed only when set.
  - Interim-label fix: the derived corporate `record_type` is now the Dojo's 5-token enum, not
    the raw subclass. 109 committed labels such as `indenture` or `charter_amendment` would have
    scored a correct `other` or `articles_of_incorporation` as wrong.
    `scripts/interim_labels.py rederive` rewrote them; the other label files are byte-identical.
  - `scripts/ladder_pair_report.py` (`job/pair_report.py`) re-scores a finished pair offline, on
    all fields and without the templated corporate/correspondence `keywords` / `subject_matter`
    (llm-dojo-scoring #164, #94).
  - Every E2/E3 arm now sets blind routing, `dataset.interim_labels: true` and the adopted
    condensed specialist prompts (corporate v1, correspondence v2, insurance v3). The sorter's
    vendored default is already the adopted `sorter_condensed_v5`.
- **E2 rejudge arm re-paired** (#300): `pipeline-qwen-flash-25-e2-corporate-rejudge` is now the
  E2 control plus `corporate_record.judge_rejudge_retry: true`, paired with the control. On the
  judge arm (`judge_band_high: 1.01`) every archivable extraction is already judged, so the
  switch cannot change that arm's routing. The E2 control and judge arms state `false`, and
  `sandbox run routing` reports the value.

- **Faster CI** (2026-11-16): the `test` job now runs on 4 parallel containers, with test files
  split by recorded timings and two `--dist loadfile` xdist workers each. A new `coverage` job
  combines every container's data and enforces the unchanged 84% floor on the total. The dev
  virtualenv is cached on `pyproject.toml`, and lint installs ShellCheck from `shellcheck-py`
  instead of apt. `overlay.load_yaml` caches parsed YAML by content digest (callers get a deep
  copy), and `agent_routes.describe()` resolves the known agents once; together they cut the
  local suite from about 340 s to about 100 s. Branch protection should add
  `ci/circleci: coverage` as a required check.

- **`judge_rejudge_retry` run knob** (2026-11-16): a run spec's `confidence` block (global or
  `by_class`) now accepts llm-mailroom #241's `judge_rejudge_retry`, so E2 can run its on and
  off arms without editing the overlay. Only `true`/`false` are accepted: upstream reads the
  key by truthiness, so a quoted `"false"` would have switched it on. The vendored default
  stays `false`; the knob is part of the run's locked, hashed identity.
- **Vendor refresh** (2026-11-16): llm-mailroom `98c89b8` → `abb1ccf` (`v0.30.0` branch after
  llm-mailroom #252, package 0.9.3) and llm-dojo-scoring `542a1c3` → `13adc8e` (`v0.30.0` branch
  after llm-dojo-scoring #163, package 0.30.0), the upstream fixes for tracking issue #300.
  Pipeline: an opt-in re-judge of retried extractions (`judge_rejudge_retry`, default `false`,
  so default routing is unchanged), judge field lists without metadata keys, budget-safe
  `sliding_windows`, `chunk_failed` parking on a total chunk failure and safer sweep resume.
  Dojo: month-first dates, retired-class archive scoring (`KeyError`), outward Wilson
  rounding, decision-lane gold, MAUD `calibration_error` and off-vocabulary considerations.
  Date fields, MAUD question micro-accuracy, `decision.*` and Wilson display bounds can move,
  so runs scored on `542a1c3` (including r2 and E1) are not directly comparable. The sandbox
  scoring goldens are unchanged. `snapshots.PINS` and `requirements/dojo-release.txt` move
  with `_VENDOR_PINS`.
- **Vendor refresh** (2026-11-16): llm-mailroom `5bcfe44` → `98c89b8` (`v0.30.0` branch,
  package 0.9.3) and llm-dojo-scoring v0.29.0 → `542a1c3` (`v0.30.0` branch, package
  0.30.0). Dojo 0.30.0 drops the unused analysis, CLI, Langfuse/Phoenix sync, sandbox
  composite and rescore modules (no sandbox importer used them) and moves some scores, so
  the scoring goldens were regenerated. `snapshots.PINS` moves with `_VENDOR_PINS`.
- **Vendor refresh** (2026-11-16): llm-mailroom `19203ea` → `5bcfe44` (`main` after #223,
  package 0.9.3) and llm-dojo-scoring v0.28.1 → v0.29.0 (`f95c318`). Routing changes that
  move experiments: chunked extractions merge confidence as the MIN across windows and a
  lost window blocks archiving; parks after a spent confidence budget also name
  `retries_exhausted`; reviewer-applied fields resume straight to `compile_report`
  (two new graph edges, now walked by the routing matrix). Dojo v0.29.0 hardens date
  scoring, so date-field scores can move against earlier runs. The sandbox's runtime
  overrides (context fit, judge/arbiter source windows, run-scoped thresholds) still
  bind: the vendored symbols they patch are unchanged.

- **Routing calibration** (2026-11-16). Escalations now have measurable value
  and run-scoped, locked thresholds:
  - Pipeline runs record each extraction pass's self-reported
    `extraction_confidence`, which is what the judge gate routes on.
  - `sandbox run routing --run-id <id>` audits a finished run offline: fire
    rates, retry yield, judged vs unjudged quality, escalation input cost, and
    threshold suggestions.
  - Runs accept a `confidence` block (global and per-class thresholds and
    retry budgets). It is validated, locked, hashed only when set, and applied
    over the vendored and overlay values.
  - Preflight's `context_plan` prices each class's clean, judged and worst-case
    loop from API tiers. Token-billed routes only; Modal GPU-hour serving is
    not priced per call.

- **Context-fit budgets for long-context API routes** (2026-11-15). Specialists,
  `judge` and `arbiter` routed through OpenRouter now get an input budget sized
  to their model's `context_length` (`config/api_prices.yaml`) instead of the
  16k-token L4 posture. The chunk cap and the vendored judge/arbiter source
  windows follow that budget. With `qwen/qwen3.7-flash`, a 418k-character merger
  agreement is extracted in one call per pass, and the judge and arbiter read
  all of it. The classification arbiter no longer sends documents over 16k
  characters to a person unread. Modal, vLLM, Ollama and LM Studio routes are
  unchanged. Source windows are restored on every other activation. Configure
  under `context_fit` in `config/taxonomy.overlay.yaml`; run `agent_knobs` still
  win.

- **Preflight context plan** (2026-11-15). `pipeline` and specialist preflights
  now attach an advisory `context_plan`. It covers chunk windows per extraction
  pass under the run's effective budgets, judge/arbiter source coverage per
  class, a note when `agents.judge.max_input_chars` has no effect, and
  near-empty rows. It never fails preflight. It comes from the
  `pipeline-qwen-flash-25` audit: there, 16k-window budgets split ~400k-character
  merger agreements into 14 windows per pass, and the judge saw 4% of them. See
  [the audit](docs/audits/2026-11-15-pipeline-qwen-flash-25-failure-modes.md).

- **Per-document spans for whole-run jobs; floor graph in narrow windows**
  (2026-11-16, #297). `pipeline`, `specialist` and single-agent job tasks now
  mirror a `job.item` span per finished document, timed by the document's own
  execution window. `pipeline` documents also get a `job.node` child per
  finished or failed graph node. Documents that raise are recorded as failed
  items. Before this, their span mirror held only `job.run`. Whole-run jobs read
  `items.jsonl` once per run, not once per document, and a failed whole-run
  checkpoint keeps its saved item count and total instead of resetting to 0/0.
  The floor viewer stacks its side rails under the graph below 900 px. It now
  refits on resize until the user zooms or pans, and it no longer fixes zoom at 0
  when the graph area starts at zero size. See [tracing](docs/tracing.md).

- **Verified stable dependency snapshots** (2026-11-10, SAND-104 / #285).
  `sandbox deps fetch` verifies released Dojo artifacts and immutable pipeline
  commit archives into an atomic offline cache. Explicit source locks preserve
  reviewed defaults; new run locks/status record both sources and refuse drift.
  Selected caches and matching installed distributions (including their metadata)
  are bundled into Modal worker images without changing the selected source layer. Vendor trees and
  dependency pins remain unchanged. Mutable installed/vendor/source trees are
  fingerprinted by runtime file bytes, relative paths and executable modes so
  unchanged version/commit metadata cannot hide edited code. See [the guide](docs/dependency-snapshots.md).

- **Floor viewer isolation and offline assets** (2026-11-09). Resident viewers
  now build and serve private temporary digests, so separate bases/ports in
  one checkout cannot show each other's runs. Static snapshot generation stays
  explicit. The offline image includes the floor builder and HTML template;
  missing-builder startup errors are reported cleanly. Focused regressions
  cover two concurrent HTTP viewers, cleanup and relocated image assets.

- **Floor, dataset and CI operator references** (2026-11-09). Add complete
  floor options/live-refresh/replay guidance, named-dataset schema and lock
  migration, and CI scheduling/cache/artifact/runtime verification guidance.
  Link the guides from the README, docs index and configuration docs; correct
  stale environment-template and API-run ownership instructions. Expensive
  verification stays on hosted CI. This follow-up changes documentation only.

- **Task-GT filter participates in dataset identity** (2026-11-09). A true
  `dataset.require_task_gt` now changes the spec hash for both local and Hub
  datasets. Toggling it refuses resume instead of silently reusing the old
  subset; an explicit relock archives the prior generation. The false default
  preserves unfiltered hashes. Regression checks cover both filter directions.

- **PR #274 follow-up: agent dataset and floor guidance** (2026-11-09). The tool
  router and Hugging Face skill distinguish raw Hub downloads, normalized corpus
  JSONL, fixture preparation and locked run subsets. Document canonical selection,
  conditional provenance, filename-based hash migration, replay ownership and
  simulated results; clarify package-specific subagent commands and import-guard
  verification. This documentation layer changes no executable behavior.

- **Live floor: `sandbox floor` app + RUNNING pills** (`src/mailroom_sandbox/tui/floor_app.py`,
  `reports/dashboard/build_floor_digest.py`, `reports/dashboard/floor.template.html`,
  `tests/test_floor_app.py`). The digest now carries per-run `inflight` (open `running` records
  from `nodes.jsonl`), `avg_doc_ms`, and a ground-truth-keyed `routing` block; the v10 viewer
  gained a live mode — green RUNNING pill with ticking elapsed seconds on any node holding docs,
  a ribbon progress bar (cursor/total · AVG), 3s digest poll with selection preserved, and
  `?run=`/`?class=` deep links — pills, elapsed clocks and polling run only over http(s) while a
  run's state is `running` (`file://` stays a frozen snapshot with no timers; the progress bar
  and routing suffix are static digest facts). Every panel figure is computed from the displayed
  run's digest and repainted when that digest changes; the graph auto-fits at load so all node
  figures are in frame from the first paint. `sandbox floor` rebuilds the digest
  on a timer (mtime-sweep skip) and serves the viewer loopback-only on `:8769`; run-store base
  via `--base`/`MAILROOM_BASE_DIR` so the WSL lane's `/home/gemooslin/sandbox-data` works from
  any shell. Validated against a live 50-doc LM Studio pipeline run
  (`config/runs/pipeline-lmstudio-even50-demo.yaml`). Node numbers keep the v10 contract:
  docs that have *entered* a node (arrival fires it; the pill shows who is still inside).
  Digest selftest 22→29 checks; floor app + replay tests.

- **Floor replay: pinned sample + `sandbox floor --replay`** (`data/fixtures/floor/replay/`,
  `src/mailroom_sandbox/tui/floor_app.py`, `tests/test_floor_app.py`). 120 public
  `mailroom-dataset` docs (24 per live class at the pinned revision; IDs/metadata only, no
  document text) drive a scripted wall-clock timeline (~66 s) replayed one record at a time
  INTO the base as its own labeled run: staggered arrivals, many docs in flight for their
  recorded latencies (nodes run ~0.1–1.8 s while later docs proceed), three failed extracts,
  four parked open at human review (judge- and extract-triggered) and one classification
  review resolved by the reviewer that re-enters extraction — so one viewer
  lists the base's historical runs AND the sample (selectable in the RUNS rail) and its
  progress, class rail, routing, node counts, RUNNING pills with growing elapsed timers,
  outcome buckets and the Routed-to-human-review strip move like a live run without a local
  run store, network, key or GPU. `--replay` forces the sample (resetting only that run
  dir) and a base with no runs falls back to it; every panel figure is computed from the
  displayed run's digest and the run is labeled as simulated.

- **Floor review-accounting + post-hoc prompt identification** (`reports/dashboard/
  build_floor_digest.py`, `floor.template.html`, `selftest_floor_digest.py`,
  `data/fixtures/floor/replay/`). The digest keeps every run's `review_routed`
  metric — documents routed to human review in total, split by the trigger stage
  (classification / extraction / judgment / reporting) from item review causes or,
  for replay/demo node traces, the node visited before `human_review` — and the
  outcomes contract is explicit: a parked review document stays HELD ("Human-in-the-
  loop"), FAILED remains technical runtime failures only. The viewer mirrors the
  pipeline's stage-audit side channel (audit A-1) as dashed arrows from every
  `_emit_stage_audit` call site parsed out of `build_graph.py` to an audit-log box —
  a behavioral distinction carried by data, never hard-coded — with the
  `human_review → audit log` arrow showing this run's routed count.
  `prompt.lock.json` (written
  for every served/run job since DMR-056; `checkpoint.py`) is surfaced per run as
  resolved `prompts` (agent → stem) and shown in the viewer's prompt card for the
  highlighted node only (each firing agent's stem, full list as the hover title), so
  prompt versions are identifiable post hoc in any run or replay; the sample locks
  its simulated stems on disk next to `spec.lock.json`. Digest selftest 29→33 checks.

- **Named datasets: `config/datasets.yaml` + `${VAR}` dataset paths.** A run spec can name a
  dataset (`dataset: {name: pipeline-even100-shuffled2}`) instead of embedding a machine path;
  the registry supplies the provider fields or a local path, expands `${VAR}`/`${VAR:-default}`
  from the environment (the CLI loads `.env` first), and may pin `sha256`. Preflight verifies the
  pin; locks record the prepared subset sha and local source sha, with `name` / `pull` metadata
  only when supplied. `$SANDBOX_DATASETS_REGISTRY` selects another registry file. Local-file
  `spec_hash` now keys on the file name + source bytes instead of the checkout path, so an
  identical same-named dataset hashes the same in any clone. Older local-file spec hashes change under
  this scheme (inspect drift before relocking); Hub hashes are unaffected.
  `config/runs/pipeline-lmstudio-even50-demo.yaml` uses the
  registry (no user path), and a guard test refuses machine paths in committed run specs.

- **Vendor refresh: llm-mailroom `main` at #179 (`19203ea`) and Dojo `v0.28.1` (`00a2a7f`)**
  (`_VENDOR_PINS`, `requirements/dojo-release.txt`, both `VENDOR.md` files, README badges and pin
  table). The vendored sorter catalog now states rule C (a bylaw amendment is `bylaws`), so the
  condensed sorter v5 is no longer shown the old board_resolution rule. llm-mailroom also brings the
  condensed sorter v5 as its production sorter and a guard that refuses a managed sorter prompt
  missing the condensed rules. The Dojo pin is a release tag again; the llm-mailroom pin is a
  reviewed `main` commit until its next release.
- **`contracts_specialist_v33` is frozen** (`scripts/sync_specialist_prompts.py` `FROZEN`). Dojo 0.28
  (schema v2) re-renders v33's "Registered schema fields" line under the same version id, so the
  vendor text is no longer the v33 that was scored. The file keeps its bytes (sha256 `6a5047ed…`),
  sync never writes it, and `--check` fails if it changes or goes missing. New contracts work goes
  to a new compact contracts lineage (planned; contracts stay outside specialist_condensed_lineage.yaml until it is built and validated).

- **Sorter answer key: rule C, a bylaw amendment is bylaws** (mailroom-dataset v10 corpus rule C,
  user decision 2026-11-07). `scripts/patch_sorter_handoff.py` gains rule 7: a corporate record whose
  title names an amendment to the bylaws targets `bylaws`, decided by the title alone. Rule 3 needs
  the Decisions reviewer to agree with the title, and the reviewer (question sets up to 3.1.0) still
  files bylaw amendments under board_resolution, so these rows could never move. On the train split
  8 bylaw amendments move from board_resolution to bylaws (`corrected`) and 2 bylaws labels are
  confirmed; the test split has none and is byte-identical. The rule matches exactly those 10 rows in
  the 3,302-document corpus ("amendment to" or "amendment of" the bylaws; a combined amendment of the
  charter and the bylaws is not rule C). `--rule-c-only --corpus-cache` applies the rule to the saved targets
  from document text alone (the sorter and reviewer run outputs the full build reads are not needed).
  `compare_sorter_prompt.py --prime` keeps a rule-C target: the published v9.3 label and a reviewer
  on the old convention are checked for class only. 3 of the 8 are in the saved prime draw.
- **Sorter answer key: user decisions** (rule 8, `USER_DECISIONS`): two full bylaws the user
  corrected on 2026-11-07, `DOC-cce54a03af3b1c4a` (SunGard Public Sector, labelled board_resolution)
  and `DOC-8b2aaa4b6ea655be` (Arrestage International, labelled articles_of_incorporation), target
  bylaws. `--rule-c-only` is now idempotent: a second pass changes nothing.

- **Production sorter is `sorter_condensed_v5`: a bylaw amendment is bylaws, never
  board_resolution** (mailroom-dataset v10 corpus rule C, user directive 2026-11-07). v5 is v1
  with that one clause changed (config/prompts/sorter_condensed_v5.txt, 3,681 chars rendered);
  v1 is marked superseded and keeps its bytes. v5 was adopted by directive, not by a compare, so
  v1's prime-sample numbers below do not carry over. The v9.3 truth files 8 board-adopted bylaw
  amendments under board_resolution, so scoring against v9.3 counts those as wrong until v10
  relabels them. `FAMILY_B_KEYS["sorter"]` pins v5; llm-mailroom pin -> PR #179 head `af957b6`,
  which ships the same bytes as `sorter_condensed_v5` (vendored from a `git archive` of that
  commit with the sync_vendor exclusions; the vendor diff equals the upstream diff, 8 files).
  The Dojo sorter guide now agrees (v0.28.1, vendored below); the reviewer decision catalog
  follows in reviewer decisions 3.2.0.

- **Sorter default flip: the condensed lineage becomes the production sorter.** (Superseded in
  part by the v5 entry above: production and `FAMILY_B_KEYS["sorter"]` are now
  `sorter_condensed_v5`, and the llm-mailroom pin is the merged main `19203ea`, which replaces the
  PR #179 heads `d573919` and `af957b6` named here.) `sorter_condensed_v1`
  (config/prompts/sorter_condensed_v1.txt, 3,681 chars rendered) beat long-form sorter V15 on the
  vetted prime-sample promotion compare (275 documents, labels Hub ccd040f6, qwen/qwen3.7-flash,
  runs `sorter-condensed-v1-qwen-train-prime-sample` + `sorter-v15-qwen-train-prime-sample`): class
  fixed-broken 108 vs 100 (right-after 263 vs 255), subclass 135 vs 126 (228 vs 219), at about 0.83x the listed cost
  (rounded figures of $0.30 vs $0.36 list; compare reports under `reports/sorter-handoff/`).
  - Evidence correction (2026-11-11, issue #259): the former 96 vs 80 figures
    incorrectly subtracted still-wrong answers. Neither run broke a class answer;
    the committed compare reports record 108 vs 100 fixed and zero broken.
  - The mutation research that got there: `sorter_condensed_v2` (literal marker phrases, rejected
    35/61 vs 36/61 on the held-out marker set) and `sorter_condensed_v3` (notice-is-a-decision rule,
    32/58 vs 31/58 on held-out set 2, within noise) and `sorter_condensed_v4` (restated notice rule
    with wrapper exclusions, rejected 34/61 vs 36/61 on held-out set 1; the notice-rule family is
    plateaued within noise on both sets and stops here).
  - `sorter_condensed_v1` is now produced by both mailroom trees: llm-mailroom
    `SORTER_PROMPT_CONDENSED`, the `sorter` alias, `SorterAgent` default and the bound pin
    (llm-mailroom PR #179); the sandbox vendored snapshot consumes those bytes in the same
    commit, refreshed to the new pinned snapshot and guarded by the vendor drift test.
  - The sandbox registry pins it too: `FAMILY_B_KEYS["sorter"]` is `sorter_condensed_v1`
    (was `sorter_v15`; freeze tests updated; V15 stays frozen as the reference).
  - llm-mailroom pin `v0.9.2` (`9e8f30b2`) -> PR #179 head `d573919` (branch
    `claude/sorter-condensed-production`: the prompt flip + its test-pin
    follow-up); vendored snapshot refreshed with the same exclusions as
    sync_vendor from the pin. The refresh carries the standalone schema-v2
    work consumed since `9e8f30b2`: the merger agent now emits
    schema-v2 fields (acquirer, merger_sub, target, legal_counsel,
    financial_advisors, exchange_ratio, per_share_cash_amount, signatories,
    outside_date, parent_termination_fee, target_termination_fee), so
    `LIVE_SCHEMA_FIELDS["merger_agreement"]` and the merger extraction gate
    cell score them. `config/prompts/contracts_specialist_v33.txt` keeps its
    published bytes (frozen; see the vendor refresh entry above).
- Prime sorter-prompt validation sample (`scripts/compare_sorter_prompt.py --prime --current-labels DIR --sample`):
  - **Prime filter.** It keeps only documents whose labels are the highest quality, checked against the published ground truth in `DIR` (v9.3, Hub `ccd040f6`). Each document must pass all of these:
    - the target agrees with the published class and subclass;
    - its status is a label (as published, normalized, or corrected by two independent sources);
    - class and subclass are both scored;
    - a contract's subclass comes from CUAD rather than the EX-10 exhibit-title heuristic;
    - a class error has its label confirmed by a corpus rule or the reviewer;
    - a confident reviewer (p >= 0.9) does not dispute the label;
    - a corporate record's subclass (an EDGAR exhibit heuristic) is confirmed by its title line or the reviewer, and neither names another subclass.
  - **Result.** 2,642 of 2,979 train targets qualify. Excluded: 102 unverified and 8 title-disputed corporate subclasses, 84 EX-10 contracts, 67 reviewer disputes, 49 merger agreements with no MAUD consideration type, 22 targets that disagree with v9.3's corporate labels (the targets were built on v9.1), and 5 ambiguous.
  - **Draw.** From those: every class error the saved V14 pass made (120), then per class/subclass stratum a seeded draw of 3 subclass errors and 2 right answers. That is 275 documents across 51 of 53 strata. `corporate_record/other` (2 documents) and `correspondence/attorney_demand` (3) have no verified label left and need a person's check.
  - **Selection file.** `inputs` writes the draw to `<file>.selection.json`, and `score` grades exactly that draw (it refuses a run that answered documents outside it). `--corpus-cache` reads the text from the pinned corpus cache.
  - **Run configs.** `sorter-condensed-v1-qwen-train-prime-sample` and `sorter-v15-qwen-train-prime-sample`, about $0.34 + $0.41 list (caps $0.55 / $0.65). They replace the full 1,003-document comparison (about $0.78 + $0.99) for deciding whether `sorter_condensed_v1` becomes the production sorter.
  - **Score check.** `score` checks that the sample file still matches the selection's sha256 and that every row the run locked is a row of the sample (compared parsed, since the lock re-serializes rows and so has its own sha256). A subset scores; documents outside it count as `no_answer`, and a document the run locked but did not answer also scores as a wrong answer, so a failed call cannot avoid `broken`. This replaces the autofix check that compared the lock's sha256 with the sample file's, which refused every real run. It also refuses a selection drawn from another `--name`. Labels must come from Hub `ccd040f6` (`PRIME_LABELS_REVISION`).
  - **Paid smoke.** `sorter-condensed-v1-qwen-train-prime-smoke` and `sorter-v15-qwen-train-prime-smoke` run the same specs on 10 rows of the sample (`train-sorter-prime-smoke.jsonl`): one per class, the securities and mailbox boundary cases, the CMS carrier case, the 6-character mailbox stub and the three largest documents (>32k price tier). About $0.03 each, capped at $0.10.
- `sandbox run start` and `run resume` refuse `--max-items` for a whole-run task (everything but `sorter`, including `isolated`), the same way they refuse it for Modal. The runner ran every locked row and ignored the cap, so a 6-item smoke of an `isolated` run ran all 275 documents and a paid one would have billed them all. `job.runner` raises on the same case for any other caller.
- Modal SDK pin `1.6.2` -> `1.6.3` (`[deploy]` extra, supersedes dependabot #236, which bumped only `pyproject.toml` and `requirements/` and left the pin tests red). The 1.6.3 wheel was source-diffed against 1.6.2: `exception.py`, `_functions.py`, `_utils/function_utils.py`, `cli/app.py` and `cli/run.py` are byte-identical, so the `FunctionCall.get(timeout=0)` reset guard in `job/remote.py` keeps its semantics, and `modal --version` prints the same format. New in 1.6.3 and unused here: OAuth JWT auth, the opt-in `2026.10` image builder (the workspace setting still selects the builder) and sandbox internals. `uv.lock` also moves `synchronicity` 0.12.6 -> 0.12.7 (modal's own requirement). `services/modal_cli.PINNED_SDK`, the deploy and setup docs, the Modal skill, `AGENTS.md` and the pin tests updated to match. The real-CLI contract smoke (`SANDBOX_SERVICE_SMOKE=1`) has not been run against 1.6.3.
- Floor analytics under `reports/dashboard/`, moved here from the Digital-Mailroom hub (hub #224, DMR-116), where it was added directly under `packages/local-mailroom-sandbox/`. The sandbox owns these files, and the next hub import brings them back unchanged:
  - `build_floor_digest.py`: stdlib-only digest of every run dir, with graph topology parsed from `build_graph.py`. Missing artifacts degrade to `?`.
  - `floor.template.html`: class-isolation and node-selection viewer. A run without `dataset.jsonl`, or a class with unlabeled items, shows `?` and cannot be isolated.
  - `selftest_floor_digest.py`: deterministic fixture gate (22/22), now run by `tests/test_floor_digest.py`.
  - `FLOOR_RUN_REPORT.md`, `floor_digest.json` and `floor_digest.js`: the two local-GPU full-pipeline runs, as committed in the hub.
  - Review fixes after the move: runs, classes, graph nodes and zoom controls are keyboard-operable (focusable, Enter/Space, focus kept across re-render); the cross-consistency selftest skips when the vendored graph is absent; `FLOOR_RUN_REPORT.md` corrects the mergers-only total (10 / 100) and the corpus share (500 docs, about 15.6%) and drops a reference to a spec file that does not exist.
- Vendor snapshots refreshed to the newest reviewed code of both owning repos with `sandbox fetch-deps` (SHA-verified): llm-mailroom `a7d7bf0` (v0.9.0) -> `main` `65523a2` (v0.9.1 + #164 Dojo v0.27.2 pin, #165 display-contract export, #166 Railway retired, #167 doc links; adds `scripts/export_contract.py`, `scripts/release.py`, `scripts/roadmap_status.py`), and llm-dojo-scoring `v0.27.2` (`1cd4aba7`) -> `main` `b3ec0fb` (#123: linear-time parsing of prose-wrapped JSON with many failing candidates, `rescore_record` routes an already-current record's headline by task; #122 release scripts only). Neither is a release tag yet; return both pins to tags once llm-mailroom and Dojo v0.27.3 are cut. `_VENDOR_PINS`, `requirements/dojo-release.txt`, `vendor/README.md`, both `VENDOR.md` files and `tests/test_eval.py` updated to match.
- GT labeler (`sandbox-vllm-gt-labeler`, SAND-045) moves from `Qwen/Qwen3-14B-AWQ` on two L4s to `Qwen/Qwen3-32B-FP8` on one H100, the strongest model in `config/models.yaml` that keeps the 32k window on a single GPU. The 14B journal for SEC EDGAR EX-10 CUAD labels failed downstream re-verification on 126 spans (Mailroom-Corpus-EDA v9.4), and small Qwen3 CUAD presence F1 here measures 0.57–0.64 (SAND-032/SAND-042). `assert_posture` now refuses the 14B. Cost model: $3.95/h (a higher `MODAL_GPU_USD_PER_HOUR` / `MODAL_GPU_USD_PER_SEC` override raises projections and the EX-10 spend meter; a lower one is ignored), 1 replica, 8 in flight, 420 s boot, 70 s per document; a 40-document chunk projects about $0.98, under the unchanged $2 cap. `config/models.yaml` gains the `Qwen/Qwen3-32B-FP8` H100 row. Journals must still pass expert calibration downstream before ingest.
- `_VENDOR_PINS` names the `v0.27.2` Dojo tag again, now that it is published on GitHub. The SHA check is unchanged (`1cd4aba7`); vendor bytes are unchanged. `vendor/llm-dojo-scoring/VENDOR.md` and `tests/test_eval.py` match.
- llm-dojo-scoring vendor snapshot → `v0.27.2` (`1cd4aba7`, Dojo #121): tiered per-document-type scoring (`score_document`, new `score_archive_block` keys) from 0.27.0, 0.27.1's no-raise field scoring and CMS `cms_source_table` derived from `doc_subclass`, and 0.27.2's fixes for this PR's review findings (no-raise, linear-time parsing of deeply nested or brace-heavy text; any `Mapping` prediction is adherent; prose-wrapped Python repr sets `prose_wrapper`; `rescore` reports the CUAD/MAUD headline). Refreshed with `sandbox fetch-deps` (SHA-verified; only the Dojo snapshot changed, llm-mailroom stays `a7d7bf0`). `_VENDOR_PINS`, `requirements/dojo-release.txt`, `vendor/README.md`, `vendor/llm-dojo-scoring/VENDOR.md` and `tests/test_eval.py` updated to match. Unblocks the Digital-Mailroom hub import of Dojo 0.27.1.
- llm-dojo-scoring vendor snapshot → `v0.26.0` (`2fea5ea7`, the release merge of Dojo #112): reviewer-lane scoring and `dojo-rescore`, the CMS #93 mapping (`claim_type` and `cms_source_table` scored separately), and the five-class extraction schema registry. Dojo modules moved into subpackages; legacy flat imports keep working through Dojo's aliases. Refreshed through `cli._refresh_vendor` (SHA-verified, Dojo only; the llm-mailroom snapshot is unchanged). `_VENDOR_PINS`, `requirements/dojo-release.txt`, `vendor/README.md`, `vendor/llm-dojo-scoring/VENDOR.md` and `tests/test_eval.py` updated to match. The vendored llm-mailroom (`a7d7bf0`) still declares Dojo 0.25.0 until its own pin bump is re-vendored.
- Vendor pins aligned with the workspace repos: llm-mailroom `main` `a7d7bf0` (#141: v0.8.1 + a0ed476 + #135 + #136 with review fixes), refreshed by `sandbox fetch-deps` (SHA-verified, adds `agents/extraction_gate.py`); llm-dojo-scoring then stayed on its published `v0.25.0` (`e35504db`, superseded by the `v0.26.0` bump above). `vendor/README.md` no longer lists the stale `175e6711077f`.
- `scripts/setup_t3.sh`: guided checkout setup (venv, editable install, `.env`, vendor import check, Modal/HF credential status, overlay check, optional git worktree, subagent stubs). `--dry-run` changes nothing; every step records its real outcome (ok / failed / skipped / planned) in `data/runtime/setup/evidence.jsonl` and a run card in `data/runtime/setup/card.json` (gitignored). `.env` is loaded without overriding exported variables; the script exits 1 when any step failed.

### Added

- **Pipeline extraction gate** (`extraction_gate:` in a `task: pipeline` run spec). It is advisory.
  - Preflight freezes the question set into the lock.
  - Activation registers `decision_backends.extraction_gate_backend` with llm-mailroom's `agents.extraction_gate` hook (llm-mailroom #136). An activation without the block clears it.
  - The gate reads the **sorter's** `doc_subclass` from the pipeline handoff, with no fallback to the labelled subclass.
  - Pipeline records carry `doc_subclass` and `extraction_gate`.
  - Gate calls count against the run budget and the OpenRouter key reserve.
  - The spec hash changes only for specs that set the block.

- Vendor pins after merging `main`: llm-mailroom `d1e2811`, which is `v0.8.1` merged into llm-mailroom #135 (sorter V15), and llm-dojo-scoring by its published `v0.25.0` tag (SHA-verified `e35504db`).
- CI lint: drop an unused counter in `scripts/export_sorter_handoff.py`; `scripts/refresh_api_prices.py` accepts only an `https://` catalog URL (bandit B310).
- PR #226 review fixes:
  - Interim labels: a null truth label is written as `gt_presence` `schema_documented_absence` (was `interim_absent`), so the Dojo's corporate scorer counts it as expected-empty instead of dropping it as unlabeled.
  - `scripts/interim_labels.py check --prune` still exits 1 when integrity or stale-run problems remain, and rewrites the manifest `counts` from the pruned files. `build` and `--prune` replace each file atomically and remove old class files only after every replacement is written.
  - `--prune` is refused while the overlay fails its integrity check (it would otherwise re-hash a hand-edited file and hide the mismatch); each atomic write stages to a unique temp file, and the counts tolerate a label with no status.
  - `key_field_score` scores every key field the gate asked. A missing or non-numeric answer counts as support 0.0, so it can never raise the gating score. Calibration skips a document (`key_support_missing:<class>`) when some key fields have no support, for example `--key-set` fields an older run never asked.
  - The serving report's TTFT note says "hosted API" for OpenRouter runs. It said "served locally" for every run.
- Spend guard: a fixed 3.00 USD reserve of the OpenRouter key's remaining limit is never spent. `require_key_headroom` and `scripts/estimate_spend.py` compare caps/estimates with `remaining - reserve`; `OPENROUTER_KEY_RESERVE_USD` can raise the floor, never lower it.

### Added

- **Decision-reviewer reports (`reports/decisions/`).** Five reports, 17 theme-aware SVG figures with CSV table twins, a self-contained dashboard and `build_decisions_report.py` (stdlib only; `--check` fails on stale outputs).
  - Prices every reviewer arm against one Qwen 3.7 Flash call as 1x, per document, on the same 323 held-out test documents. Qwen is priced per call against the tiered OpenRouter sheet: $0.2513, where the handoff manifest's flat figure is $0.1298.
  - **Measured Qwen reviewer** (`config/runs/reviewer-validation-qwen-flash-test.yaml`, signed JB, 323 of 323 answered, $0.2099 at the sheet, $0.2146 billed): 0.84x of the agent call, 93.8% class accuracy, all 20 wrong answers at confidence 0.90 or higher, 8 wrong documents routed with no person (24.8 per 1,000 against 3.1 for Decisions). Results are tracked in `reports/reviewer-calibration/reviewer-validation-qwen-flash-test.{json,items.jsonl}` (no document text).
  - A Decisions review is 0.91x (v3.0.0) to 1.14x (v2) of a Qwen review, so agent plus Decisions is 1.76x to 1.95x against 1.84x for agent plus the Qwen reviewer: 4% cheaper to 7% dearer, and dearer at flat Qwen prices. The case for Decisions is accuracy and usable confidence, not cost.
  - Calibrated reviewers cut documents needing a person from 356 to 15 per 1,000 (Decisions v2); the extraction gate shows no ranking signal (pooled AUROC 0.41).
  - Source inconsistencies found on the way are listed in `reports/decisions/05-method-and-data-quality.md`; none was edited at the source.
- **Question set 3.1.0 with the sorter handoff, measured on half the train split** (`config/runs/reviewer-calibration-luna-decisions-v3.1.0-train-half.yaml`, signed JB, 1,491 of 2,979 train documents drawn per class in proportion, seed 42, `openai/gpt-6-luna-decisions`).
  - 1,491 of 1,491 answered, $1.0648 billed (10.65M input tokens), median 0.62 s. Every request carried the sorter's primary type, subclass and confidence.
  - Against the verified targets: primary type 98.7% vs the sorter's 95.9% (45 fixed, 4 broken), subclass 84.0% vs 72.4% (266 fixed, 96 broken); 98.3% and 82.8% on the 1,096-document clean subset.
  - Routing at the v2 cutoffs: 1,367 of 1,488 scored documents routed correctly with no person under the pipeline's rule (1,398 if the reviewer alone decides), 2 misrouted, 119 (88) parked. The sorter alone would misroute 61.
  - Results are tracked in `reports/reviewer-calibration/reviewer-calibration-luna-decisions-v3.1.0-train-half.{json,routing.json,run.json,items.jsonl}` (no document text); `reports/decisions/` now has 17 figures.
- **Preflight: the same-model reviewer guard no longer applies to `task: sorter_reviewer` runs.** The sorter never runs there and the engine model is the reviewer by rule, so a reviewer on the sorter's own model (Qwen reviewing for Qwen, with `allow_chat_model: true`) is a valid measurement there; pipeline runs keep the guard. Test: `test_api_reviewer_may_share_the_sorter_model_on_a_calibration_run_only`.
- **Extraction-gate question set 1.3.0: per-template rules from a field-by-field GT vetting** (`docs/EXTRACTION_GATE_VETTING.md`).
  - `subclass_fields` replaces a class rule with the rule of the document's own template or record kind. The subclass comes from the handoff (`doc_subclass`, the sorter's) or, in calibration runs, the labelled subclass.
  - Agreement with the dojo field truth: insurance claim_type 0.87 → 0.98, insurer 0.85 → 0.95, date_filed 0.57 → 0.80, corporate intent 0.76 → 0.90 (false accepts 47 → 0).
  - Contracts: parties judged on legal names; CUAD clauses judged on precision only.
  - `decide_extraction` emits `key_field_score`, the product of key-field supports, and calibration reports it. It is the gating score. Key-field AUROC: overall 0.764 against the verdict's 0.667; insurance 0.865, corporate 0.891, contract 0.844 on corrected truth. The verdict ignores the field rules and was unchanged from 1.2.0.
  - `calibrate --corrected-truth` corrects the documented CUAD parties and effective-date defects from the Hub's own evidence, without consulting the gate.
  - Runs:

    | Run | Documents | Cost |
    | --- | --- | ---: |
    | `extraction-gate-luna-v1.3.0` | 1,596 | $0.87 |
    | `extraction-gate-luna-v1.2.0-rereview` | 880 | $0.41 |
    | `extraction-gate-luna-v1.2.0-r3` | 686 | $0.25 |

    The insurance round-3 extraction (686 new documents, condensed v3 prompt) had an exact match of 0.896.
- **Extraction-gate question set 1.2.0.** The verdict judges key fields only; class scopes are named, and ungrounded free-text fields are dropped.
  - `calibrate` adds a key-field target (`keyfields`, `--key-set` to compare sets on one target).
  - Insurance key-field AUROC 0.63 → 0.78.
- **Interim GT labels** (`data/labels/interim/`, `mailroom_sandbox.interim_labels`, `scripts/interim_labels.py`). These are the unpublished enhancements expected in the next dataset revision:
  - gap fills for the key fields the Hub leaves unlabelled: corporate, correspondence and merger (dojo #52/#94/#95);
  - derived `cms_source_table` (dojo #93), and `record_type` / `communication_type` from the subclass;
  - CUAD parties and effective-date corrections;
  - `disputed` correspondence intents for human review, which are not truth.
  - Every label carries its provenance and the hash of the document text it was read from.
  - Opt-in per run (`dataset.interim_labels: true`), hashed into the spec and recorded in the lock.
  - `build --add-run` keeps the labels current; `check` refuses stale or hand-edited files and prunes labels a Hub revision publishes.
- **Extraction-gate round 2: 690 new real documents, no repeats.** `scripts/extraction_gate.py expand` draws documents no finished specialist run has extracted, checked by id and by whitespace/case-folded text (the run refuses when it finds no history to exclude).
  - insurance_claim +240, correspondence +240, corporate_record +160: each subclass drawn from its shorter half first.
  - contract +40 and merger_agreement +10: drawn representatively at full length; contracts cover all 26 CUAD subtypes, mergers only labelled consideration subclasses (no `other`).
  - Merger specialist input limit raised to 1,000,000 chars, so the longest (739,511 chars) is read in one call.
- **Specialist-condensed prompt lineage** (`config/prompts/specialist_condensed_lineage.yaml`, `<agent>_condensed_v<N>.txt`). Each version is validated against the frozen prompt on the baseline documents with `scripts/compare_specialist_prompt.py`; those validation runs are never handed to the gate.
  - insurance v3: a per-template field map for all six corpus templates (Medicare Part A/B/carrier notices, Part D pharmacy statements, auto decision letters, auto system claim extracts, property FNOL). Mean 0.770 → 0.899, better on 60/60 documents. v1 was superseded; v2 was adopted, then replaced by v3.
  - correspondence v2: mean +0.002, −28% input tokens. v1 was rejected: it over-predicted `update`.
  - corporate v1: mean 0.352 → 0.427.
  - Contracts and mergers keep their frozen prompts.
- **Extraction-gate question set 1.1.0.** Every document is read whole (limit 1,000,000 chars for every class); 1.0.0 cut 24 of the 220 baseline documents at 120k (merger 240k). The request timeout scales with document length.
  - `calibrate` pools several gate runs (`--run` repeated, `--name`) and refuses overlapping documents or mixed question sets.
  - Pooled 910-document calibration: `reports/extraction-gate/extraction-gate-luna-v1.1.0-pooled.calibration.json`. Its insurance extractions mix two prompts: the baseline round used the frozen specialist prompt and round 2 (240 documents) used `insurance_claims_specialist_condensed_v2`, the frontrunner when it ran; v3 came after.
- `scripts/estimate_spend.py` sizes a pinned local prompt file from the file itself.
- **Dojo: installed release first, vendored snapshot as fallback** (`mailroom_sandbox/dojo_source.py`).
  - When a `llm-dojo-scoring` release is installed (`pip install -r requirements/dojo-release.txt`, the pinned GitHub release) and matches the snapshot's version and commit, it is the scoring source.
  - The snapshot under `vendor/llm-dojo-scoring` takes over when the release is missing, off-pin or fails to import, so scoring keeps working through a broken install or outage.
  - `SANDBOX_DOJO_SOURCE=auto|installed|vendored` picks the policy; `DOJO_SRC` still overrides. The run lock records the source as `versions.llm_dojo_scoring_source`.
  - The release pin lives in `requirements/`, not `pyproject.toml`, so the base install stays offline (DMR-057).
- **Full API price sheets (`config/api_prices.yaml`).** Qwen 3.7 Flash, GPT-6 Luna, Luna Decisions, DeepSeek V4 Flash and Qwen3.5-9B each carry their complete OpenRouter sheet:
  - every long-prompt tier (Qwen 3.7 Flash: $0.03/$0.13 per 1M below 32k prompt tokens, $0.10/$0.40 from 32k, $0.20/$0.80 from 256k), input-cache read/write, context length and max completion tokens.
  - `call_price` / `call_cost` price each call at its own tier; the built-in table is the fallback if the file is missing.
  - `scripts/refresh_api_prices.py` rewrites the file from `GET /api/v1/models` (`--check` reports drift, `--add MODEL` adds one).
  - The openrouter profile lists the callable models under `api_models`.
- **Extraction-gate baseline results.** Five Qwen 3.7 Flash specialist runs (220 real dataset documents, all five classes, one call per document, no chunking) and the `openai/gpt-6-luna-decisions` gate over their handoffs; calibration in `reports/extraction-gate/extraction-gate-luna-v1.0.0-baseline.calibration.json`.
- **Run ledger (`reports/run-ledger.md`).** Every paid run that passes the spend gate appends one row:
  - columns: UTC time, the signer's initials, `start` or `resume`, run id, config, spec hash, rows, API cap and result;
  - the result cell is filled when the run reaches a terminal state (`✓` done, `✗` failed). For a Modal run this happens when `sandbox run status` syncs it back;
  - it is a Markdown table that `mailroom_sandbox.job.ledger.rows()` parses back;
  - tests write to a temporary ledger, never the tracked one.
- **Key-headroom spend gate.** A paid OpenRouter run refuses to start when its `job.api_cost_cap_usd` exceeds the key's remaining limit (`GET /api/v1/key`). The check fails closed when the limit cannot be read.
- `scripts/estimate_spend.py` estimates the planned runs' token spend and checks the total against the key's live remaining limit. (Its accuracy against a measured run is unverified: no comparison is recorded.)
- **Sorter-condensed lineage, the sorter mutation surface.**
  - `config/prompts/sorter_condensed_v1.txt` is V15's class boundaries and subclass conventions, condensed.
  - Its system prompt renders to 3,681 chars against V15's 25,074, about 5.3k fewer prompt tokens per call. Per-key meanings stay in the Dojo catalog in the user message.
  - `sorter_condensed_lineage.yaml` lists the versions and the frontrunner. `tests/test_sorter_condensed_prompt.py` holds the 4,000-char budget and the V15 conventions.
  - Validation run: `config/runs/sorter-condensed-v1-qwen-train-errors.yaml`, the same 1,003 documents as the V15 run.
- **Extraction quality gate (`task: extraction_gate`).**
  - `openai/gpt-6-luna-decisions` reads a document together with the specialist's real extraction of it, under question set `config/decisions/extraction_gate_v1.0.0.yaml`.
  - It answers a verdict (`accept`, `retry_extraction` or `human_review`) plus one yes/no support question per key field, for all five classes.
  - Contract and merger_agreement fields cover entity extraction and the native CUAD clauses / MAUD answers.
  - `reviewer.handoff_run` names the finished specialist runs. Preflight refuses mock, unfinished or non-specialist runs.
  - The gate's truth is the dojo score of the extraction it judged. `scripts/extraction_gate.py` builds the 220-document stratified train baseline and calibrates per class and per field (AUROC, accept cutoff at a target precision).
  - Specs: `config/runs/extraction-gate-specialist-<class>-qwen.yaml` (qwen/qwen3.7-flash) and `config/runs/extraction-gate-luna-v1.0.0-baseline.yaml`.

### Changed

- Vendored llm-dojo-scoring 0.25.0, the release merge commit `e35504db` of Dojo PR #91, replacing the interim `db15b7c5`.

- **SAND-085 — sorter V15 with the V14 subclass fixes, scored on verified targets.**
  - The vendored sorter prompt V15 (llm-mailroom PR #135) now carries subclass conventions S1-S5 alongside its class boundaries. They cover:
    - CMS carrier vs outpatient;
    - Certificates of Designation as officer_certificate;
    - charter amendments vs the charter;
    - board-adopted bylaw amendments;
    - the correspondence marker precedence;
    - contract family over `other`.
  - The sorter's subclass catalog is the Dojo sorter guide. The Dojo pin moves to `db15b7c`, which adds `sorter_guide`, stops scoring the unannotated merger `other`, and adds the `arbitrate-classification` node.
  - `scripts/calibrate_reviewer.py` scores against `data/handoff/<name>/<split>.targets.jsonl` next to the lock's `handoff_run`, with `--targets` or `--labels` to override. It also reports reviewer subclass accuracy and records the truth it used.
  - `scripts/compare_sorter_prompt.py` builds the V15 validation set and scores it: every V14 error plus 200 controls, 1,003 train documents.
  - `config/runs/sorter-v15-qwen-train-errors.yaml` raises its API cap to $1.20, since the cap prices tokens at the profile's DeepSeek route (about $0.83).
- **Fixed: decision review parked every document.** A decision backend behind a `**kwargs` wrapper (a Mock or a forwarding decorator) was passed `handoff=` and raised `TypeError`, so every document parked as `reviewer_unavailable`. The handoff now goes only to a backend that declares a `handoff` parameter (vendored llm-mailroom, PR #135). The routing matrix walks the new classification-arbiter edges, and the stale V14 CLI test and CLI reference are updated.

- **SAND-092 — Smoke audit fixes.** `llm-mailroom` re-vendored at `16ddd08`: corporate, insurance and correspondence extractions now report confidence, an unsure extraction reaches the judge before a person, and the judge checks accuracy against the source. `run_limits.max_total_output_tokens` rises to 200000 per document. An aborted document is now recorded as failed and no longer fails the whole run, and tests can no longer rewrite the real repo's git config from a commit hook.
- **SAND-085 — OpenRouter decision reviewer.** A new `api` decision backend (`--decision-reviewer api:openai/gpt-6-luna`, with `--decision-class CLASS=CUTOFF`) runs `sorter_reviewer` through OpenRouter on `agent_routes.sorter_reviewer`. Only pinned provider ids are accepted: `-latest`, `~`, `:floor` and `openrouter/*` ids are refused, because a tuned cutoff is tied to one model. The `local` backend runs the same agent on the run's own serving route. Decision classes reach their reviewer at any sorter confidence after the sorter's retries; agreement at the cutoff goes to `extract`, a sorter below its low band may be corrected at the cutoff, and an unsure reviewer or a disagreement with a medium or high sorter parks for human review. Cutoffs are provisional until issue #208. `config/runs/pipeline-luna-qwen-smoke.yaml` is a 7-document pipeline smoke with the reviewer on all five classes. `scripts/calibrate_reviewer.py --run <id>` picks each class's cutoff from a finished calibration run. `activate` defaults `MAILROOM_CHECKPOINTER=sqlite`, so parked reviews survive a restart. The vendored llm-mailroom pin moves to `45e7075` for the decision-reviewer routing fixes (SAND-090).
- **Named Modal image.** `sandbox modal publish-image` publishes the vLLM serving image to the active workspace as `sandbox-vllm:v0.29.0`, and `sandbox modal deploy --named-image` deploys from it without rebuilding. `sandbox experiment create` turns this on through `engine.modal.named_image`; `--no-named-image` opts out. A named image belongs to one workspace, so publish once per Modal account.
- **Correspondence on every decision backend (SAND-086 cancelled).** No backend refuses correspondence; the Enron correspondence is public.
- **`sandbox modal status` lists scoped apps.** Besides `sandbox-vllm` and `sandbox-job`, it lists every other `sandbox-*` app that is not stopped (except the `sandbox-image-builds` app, which holds no function), and shows the container count for deployed apps.
- **`sandbox doctor --live` checks the Modal account.** The `modal` row lists the apps in the active account (`MODAL_PROFILE`, read-only). For `modal-vllm`, an account check that fails or finds no deployed app fails the row.
- **Venv tools without activation.** `.venv/bin/sandbox` puts its own venv's `bin` first on `PATH`, so its pinned `modal` is used even when the venv is not activated.
- **`SANDBOX_SKIP_DOTENV=1` (tests only).** `tests/conftest.py` sets it so a developer's `.env` never loads into the suite.
- **SAND-089 — API token spend ceiling and recommended run ceilings.** Every paid run needs `job.max_wall_seconds`; a run that warms a Modal GPU also needs `job.cost_cap_usd`; a run that sends any agent to OpenRouter needs `job.api_cost_cap_usd` and a token price for every API model, or it is refused. The GPU cap never limited OpenRouter spend. The API ceiling prices observed tokens at the highest API model price and is checked before each document. `sandbox experiment create` fills unset ceilings from the design (`src/mailroom_sandbox/job/budget_advice.py`); flags win. Prices added for `qwen/qwen3.5-9b`, `qwen/qwen3.5-35b-a3b`, `qwen/qwen3.5-27b` and `openai/gpt-4o`. Experiment reports show API-only runs without a GPU cost and report estimated API spend separately.
- **SAND-079 — specialist tiers.** `sandbox experiment create --specialist-tier {base,mid,full}` moves the five specialists off the base model. `mid` is `Qwen/Qwen3.5-35B-A3B` (fp8, `L4:2`); `full` is the judge's `Qwen/Qwen3.5-27B` and shares the judge's Modal app. On OpenRouter the tiers use `qwen/qwen3.5-35b-a3b` and `qwen/qwen3.5-27b`. An explicit per-specialist route or model wins; the frozen `sand42` study refuses the flag.
- **SAND-078 — larger judge on Modal.** Modal pipeline experiments route the judge to `Qwen/Qwen3.5-27B` (fp8, text-only) on its own `L40S` app, defined once in `config/models.yaml` `critical_tier`. An explicit `--agent-route` or `--agent-model` for the judge wins. OpenRouter runs keep the `deepseek/deepseek-v4-flash` judge. Unverified until the first spend-gated deploy: `/health` and the VRAM peak on L40S.
- **SAND-077 — Qwen3.5-9B is the default model.** `modal-vllm`, `vllm-local` and `vllm-remote` default to `Qwen/Qwen3.5-9B`, served with online fp8 and text-only `--limit-mm-per-prompt` (deploy script, run spec, `sandbox runbook show serve`, `modal-matrix`). The `openrouter` profile defaults to `qwen/qwen3.5-9b`, the same weights, so API runs compare directly with Modal runs. `config/models.yaml` `openrouter_preference` ranks the OpenRouter picks: `qwen/qwen3.5-9b`, `qwen/qwen3.5-35b-a3b`, `qwen/qwen3.5-27b`. Frozen Qwen3-8B studies keep their model and spec hash. A served-model pin now re-points both the old and new default ids, so a Qwen3-8B serve never leaves the champion on Qwen3.5-9B. Unverified on L4: `/health`, VRAM peak, and the Gated-DeltaNet kernels missing from the deploy image.
- **SAND-076 — live pipeline floor.** `task: pipeline` runs record each graph node a document enters, as it starts and ends, in `nodes.jsonl`. They use a LangChain configure hook, so no vendored code changes. `sandbox watch` (terminal) and `watch --web` show the newest document's route and the previous document's full route, with latency, routed agent and model, and per-node totals. Decision nodes record typed decisions (`noul` / `choice` / `score`) that match the incoming Decisions-API model (`openai/gpt-6-luna-decisions`, Discussion #193). A native `decisions` list passes through validated. `sandbox dev --pipeline` demos it.

- `sandbox eval` has two primary tasks with two levels: `specialist [TARGET]` (all five
  live-class specialists, or one) and `pipeline [--class C]` (the full connected graph,
  every class or one). Run YAMLs take an optional `target`; `run --target` narrows it.
  Every other eval task still runs and is listed by `sandbox eval --all-tasks`.
- OpenRouter key probe (`/key`: limit, remaining credit, usage) in `sandbox health` and
  a `sandbox doctor --service openrouter` row; example API, Modal and hybrid pipeline
  run configs under `config/runs/examples/pipeline-*.yaml`.
- `sandbox tui`, a local interactive command terminal, and a browser live inspector with
  parser-derived nested CLI manuals. Full execution stays local and keeps the spend gates.

- `docs/cli-reference.md`: generated, complete reference for every parser node,
  argument, parser-required marker and choice, plus `python scripts/check_cli_surface.py
  [--check]` and parser-surface tests that exercise help, required arguments and
  handler dispatch for every leaf (no live services).
- `sandbox experiment designs|create|review|preflight|launch|watch|report`: single and
  SAND42 paired designs, pinned Hub slices/sample sizes, full pipeline or specialist
  jobs, explicit vLLM/GPU/decode/trace choices, separate bounded smoke subsets,
  managed-cell teardown, observer following, coverage and paired outcome reports.
- Per-agent `agent_routes` and `--agent-route NAME=PROVIDER:MODEL` (or a route YAML):
  API, Modal/vLLM, and hybrid pipelines through the native/LangChain shared seam.
  Resolved agent assignments and generation knobs are locked; vendor bytes stay intact.
- Configuration-bound, expiring initials receipts for paid run start/resume and live
  preflight; campaign receipts also bind smoke settings. Mock endpoint work stays
  unsigned. Initials attest operator review; they are not cryptographic identity proof.

- `tests/_fakebin.py` and the `fake_bin` fixture: fake `modal`/`vllm`/`hf`/`ssh`/
  `docker`/`ollama` executables on an isolated `PATH` (argv logged, canned output per
  subcommand), so CLI wrappers are tested without the real tools or a network.
- `mailroom_sandbox.services._exec`: one guarded way to run an external CLI
  (`require_tool`, `run_tool`; `ToolMissing`, `ToolFailed`, `ToolTimeout`).
  `main()` renders any `ServiceError` as a single `error:` line (exit 1).
- `sandbox modal deploy|prewarm|status|logs|stop|url|raw`: guarded passthrough to the
  Modal CLI. Injects the pinned `deploy/modal_vllm.py` entrypoint and the `--model`/`--gpu`
  row from `config/models.yaml`; `deploy`, `prewarm`, `stop` and `logs` have
  `--dry-run` (prints the argv, spends nothing); `deploy` prints the endpoint exports; `stop` is idempotent and verified
  against `modal app list --json`; an SDK other than the `modal==1.6.2` pin warns.
- `sandbox vllm probe|command|serve|metrics`: `probe` checks models, chat, `/health` and
  `/metrics` plus that the served model is the one a run will ask for; `command` prints
  the exact `vllm serve` argv the Modal app launches (loaded from
  `deploy/modal_vllm.py::build_vllm_command`, no Modal SDK needed); `serve` runs it on a
  local NVIDIA host bound to 127.0.0.1; `metrics` wraps `vllm_metrics.scrape`.
- `sandbox hf whoami|download|cache|raw`: guarded passthrough to the `hf` CLI. `download`
  defaults to the sandbox dataset at the pinned `FAMILY_HF_REVISION`; the cache is
  explicit (your own `HF_HOME`, or `--sandbox-cache` for `data/cache/hf`).
- `services._exec.stream_tool` / `passthrough_tool` (live-streamed and terminal-attached
  runs) and ANSI stripping in tool-failure messages.

- `sandbox doctor [--service NAME]… [--live] [--publish] [--json]`: one status table for
  modal, modal-auth, hf, hf-auth, docker, ollama, ssh, git, vllm, provider, langfuse,
  phoenix, tunnel and compose. Offline by default (binaries and config only); `--live`
  adds network probes and warns that a request to a scale-to-zero Modal URL wakes a
  billed GPU. Exit 1 only on a `fail` row. `--publish` writes the snapshot the board shows.
- TUI services panel: `sandbox board` renders the published `mailroom.services/v1`
  snapshot as a status strip (terminal and browser, `/api/services`), also in
  `sandbox watch --web`; a snapshot older
  than 15 minutes is marked stale. `board --probe-interval SECS` refreshes offline checks;
  add `--live` explicitly for network probes (can wake a billed GPU). Viewing snapshots stays network-free.
- Service beacons: `sandbox modal deploy|prewarm|stop`, `sandbox hf download`,
  `sandbox tunnel up`, `sandbox datasets pull`, `sandbox doctor`, `sandbox up` and
  Ollama `sandbox pull-models` publish a `mailroom.beacon/v1` job, so
  they appear on the board like `run start` does.

### Changed

- **Compose stack hardening.** Every published Compose port binds `127.0.0.1` (previously all interfaces). MinIO moves from `minio/minio:RELEASE.2025-09-07…` to the Chainguard image pinned by digest; a `minio_data` volume from the old image needs a one-time owner change ([docker-offline.md](docs/setting-up/docker-offline.md)). Langfuse web and worker pin `3.225.15` (were `3`). ClickHouse gets the `SYS_NICE` capability. The default `LANGFUSE_INIT_USER_EMAIL` is `sandbox@example.com` (was `sandbox@localhost`), in `config/.env.example` and the compose file.
- `sandbox doctor`: the `provider` row warns instead of failing on a Modal cold-start timeout, with the explanation; the `langfuse` row warns when the Langfuse SDK is not installed, because runs then record no traces.
- Spend caps price every Modal app a run keeps warm. `job.cost_cap_usd` on a routed run now sums the base engine and each distinct `modal-vllm` agent-route app (the SAND-078 judge's L40S, a SAND-079 `mid` specialist `L4:2` app), counting the GPUs in an `L4:2` suffix. It previously priced the base engine alone.
- An explicit `quantization: ""` (bf16) on a model whose serve default is fp8 now reaches the deploy as `MODAL_VLLM_QUANTIZATION=bf16`. It previously rendered as unset, so the deploy served fp8 while the run lock said bf16.
- The local `vllm` compose service and the `vllm-local` profile's `pull-models` hint now serve and name `Qwen/Qwen3.5-9B`, the profile's own default (bf16; compose has no quantization knob). Before this, a `vllm-local` run asked a Qwen3-8B server for Qwen3.5-9B. README, Quickstart, providers, deploy and remote-serving docs cover the SAND-074–079 model tiers, primary eval tasks and live pipeline view.
- Vendored llm-mailroom pin moves to `main` HEAD `175e6711` (snapshot bytes unchanged;
  the intervening commit is README-only). llm-dojo-scoring stays on `main` HEAD
  `718e326c` (0.24.2 plus the DMR-113 zero-token fix), the newest Dojo source.

- Observer numeric arguments, incompatible options and malformed beacon handling are
  hardened; campaign run-ID markers are followed and switch the associated log streams.
- The watch UI shows locked model/provider settings and campaign checkpoints instead of
  inherited demo labels, with log filters, follow controls and accessibility fixes.

- CLI startup loads the checkout's `.env` files (root `.env`, then `config/.env`) before
  building the parser, so profiles and secrets resolve from `config/.env.example`;
  exported variables still win, then root `.env`, then `config/.env`. The template is
  refreshed against the variables the CLI, deploy scripts and Modal app actually read
  (Modal workspace/app name, deploy knobs, per-agent route key variables).
- Serve through **Modal vLLM by default**: `SANDBOX_PROFILE=modal-vllm` and
  `DEFAULT_PROVIDER=vllm` (CLI, runtime fallbacks, `.env.example`, generated
  runbooks and README/quickstart). `--profile ollama` is the explicit
  offline/CPU opt-out. `sandbox profiles` marks the active default,
  `sandbox health` prints a deploy hint when `VLLM_BASE_URL` is unset, and
  `MODAL_WORKSPACE` derives the gateway URL when no endpoint is exported.
  New `serving` runbook (`sandbox runbook show serve`) covers pre-warm →
  deploy → point → verify → teardown and is the first entry in
  `docs/runbooks/`.

### Removed

- LegalBench: the `sandbox legalbench` command, the `legalbench` eval/run task, its
  loaders, scorer and fixtures.

### Fixed

- **Runtime taxonomy no longer becomes the next merge base.** After
  `patch_mailroom_config` pointed mailroom at `data/runtime/taxonomy.yaml`,
  a second `build_merged_taxonomy` in the same process merged onto that
  output and kept the previous run's served-model pins. The shipped path is
  now remembered before the patch (SAND-077).

- `sandbox matrix` plans the model you ask for. An id with no `config/models.yaml` row (e.g. `Qwen/Qwen3.5-9B`, `qwen/qwen3.5-9b`) used to be swapped silently for the serving family's default (`Qwen/Qwen3-8B`, `qwen/qwen3.7-flash`). Champion rows still map per family. The pipeline example configs now say where prompt versions live and how to pin one per role.
- **PR #192 review fixes (CodeRabbit).** Switching runs in `watch` / `watch --web` now closes the old log buffer, so the new buffer takes the writer lock and `--no-logs` still loads the saved dispatch log. `eval specialist <target> --prompt-version` accepts versions for that target's specialists. The tray configuration shows a prompt's identity and hash, never its text. `probe_openrouter_key` fails when the key response has no key record. The pipeline example configs no longer suggest `--dry-run` preflight, which skips the checks. The browser-test docs install Chromium first.
- Serving records follow the vendored Dojo's repaired usage rules. A cost the sandbox
  writes is authoritative in the Dojo, so `record_from_run` now applies the same gates.
  An ok item with no recorded usage makes the run cost unknown (Dojo 0.24.2): the
  record carries `usage_unobserved_items` and no `estimated_cost_usd`. Explicit zero
  usage on a priced model is a known `0.0` (DMR-113). OpenAI usage parsing keeps an
  explicit `prompt_tokens: 0` instead of falling through to `input_tokens`.
- The GPU telemetry sampler takes an optional stop event. Its test now stops the
  thread, which had outlived its monkeypatches and printed into a later test's
  captured `doctor --json` output (the CircleCI `test` failure).
- `sandbox board` rejects beacon counters and timestamps too large for a float
  instead of raising `OverflowError` for every job.
- Watch UI: the current phase's lane is never marked skipped; the no-campaign hint
  shows its `<experiment.yaml>` placeholder; a campaign keeps the run manifest and
  drops the SAND-032 program title; the single-stream dispatch title names the
  tailed app.

- Command-audit fixes: repeatable `--agent-model` accumulates across the root, group
  and leaf parsers (last value wins); `--mock` and `--local` are mutually exclusive;
  zero, negative, NaN and infinite sample/cost/concurrency inputs are rejected;
  options that would have been silently ignored (`--from-log`, `--group`,
  `--connected`, empty matrix lists, unknown agents) return a usage error; commands
  that cannot honor `--dry-run` reject it instead of acting; `pilot`, `legalbench`,
  `matrix` and `hf-pilot` forward agent overrides; matrix cells share one seeded draw
  and forward the seed.
- Direct live probes now persist `cold_boot.json` (preflight/start), per-agent Modal
  route probes wait out the boot budget, teardown keeps the original failure when
  cleanup also fails, the engine probe uses the credential of the resolved transport,
  model-only runs freeze `agent_assignments`, ambiguous credential URLs are rejected
  by redaction, and an unwritable snapshot root no longer stops the board.
- Complete SAND-064 review fixes: credential-free doctor URLs and fake-tool logs; `.env`
  loading for HF and local vLLM commands; malformed snapshot rejection; safe HTML
  attributes; independent doctor checks; per-app teardown guidance; trimmed workspaces;
  interrupted SSH startup cleanup and macOS zombie detection.
- Deploy startup detects an exited vLLM child and reaps failed children. Teardown
  refuses failed/malformed Modal listings, uses `MODAL_VLLM_APP_NAME`, and is idempotent.
- Opt-in real CLI contract tests (`SANDBOX_SERVICE_SMOKE=1`); a live endpoint probe
  additionally requires `SANDBOX_LIVE_PROVIDER_SMOKE=1` and an explicit endpoint.

- Review follow-ups on the Slice 1 fixes: `tunnel plan` accepts the shared flags after the
  subcommand; the health probe treats only 2xx as healthy (a 3xx is `HTTP 3xx`, and the
  non-JSON detail names the real status); a modal-vllm run spec with `engine.modal: null`
  resolves its gateway from `MODAL_VLLM_APP_NAME`/`sandbox-vllm` instead of raising.
- `sandbox beacon update --finish` clears the stale `phase`; a paused or still-running
  job's runner no longer stamps its beacon `done` (it publishes `PAUSED`/`RUNNING`).
- `sandbox watch` no longer leaks the `modal app logs -f` child it spawned when the
  watcher stops.
- Test suite: the vendored pipeline's fire-and-forget `relations-scan` threads are joined
  at the end of each test (`tests/conftest.py`). Their `schema_ready` log line used to
  land in a later test's captured stdout and intermittently broke
  `test_generation_protocol.py::test_idle_local_cancel_does_not_poison_next_resume`.
- `run preflight --live`, `run start` and `run scrape-metrics` no longer resolve the
  default `modal-vllm` profile to `http://localhost:8000/v1`: the run-spec resolver now
  uses `VLLM_BASE_URL`, then the `MODAL_WORKSPACE` gateway for the spec's Modal app, and
  fails with a clear error (`EndpointUnresolved`) instead of probing localhost.
- `sandbox health` no longer crashes with `JSONDecodeError` when an endpoint answers
  2xx with a non-JSON body; a model endpoint reports `non-JSON body`, and the Langfuse
  and Phoenix liveness probes treat any 2xx as healthy.
- `--profile`, `--model`, `--prompt` and `--agent-model` now work before or after the
  subcommand on every command, including `tunnel` and `run`; a value before the
  subcommand was previously overwritten by the leaf default.
- `sandbox tunnel up` reports a missing `ssh`, shows ssh's own error, waits for the
  forward port and cleans up a forward that never opened; `tunnel down` clears a stale
  pidfile instead of failing forever and never signals a process that is not ssh;
  `tunnel status` reports `pid_alive`; a non-numeric `SANDBOX_TUNNEL_PORT` is a clear
  error. A port already in use and a timed-out external tool are one-line errors.

- Review follow-ups on the Modal-default change: a `SANDBOX_PROFILE` set only in
  `.env` (e.g. `ollama`) is honoured when the CLI resolves its default; the
  `serve` script exports `VLLM_API_KEY` from the token it just deployed (and
  every runbook that defines and deploys with that token now does the same, so
  health no longer gets a 401), keeps its teardown commented because the script
  runs no eval, and marks the endpoint URL as required before health; docs and
  skills that told people to run a bare `sandbox pull-models` for Ollama now pass
  `--profile ollama`; `health`'s exit-code description no longer claims Langfuse
  or Phoenix gate it; activating `modal-vllm` with no endpoint no longer seeds
  `VLLM_BASE_URL` with the localhost fallback, so the pipeline's live-or-loud
  warning fires instead of a run quietly using whatever listens on :8000;
  `cost_cap_usd: .nan` is rejected instead of silently disabling the cap. Stale
  "Ollama is the default" wording is gone from the skills (router, ollama, modal,
  langfuse, index), `docs/setting-up/` and the `modal-vllm` profile comment, the
  `[deploy]` pin reads `modal==1.6.2`, trace tags and run records fall back to the
  default profile like activation does, and every function this PR touches has a
  docstring and test coverage.
- Record that Hub tag `v9.1` (`bc9eab28`) is published, and drop dead
  identical branches, constant conditions, and duplicated success returns
  flagged by CodeAnt (#144, #155–#159). `_cmd_run_cancel` already returns
  distinct codes and was left as-is. Review follow-ups: the dataset card and
  `SANDBOX-GUIDE.md` now label `ed7576b6` as the parquet data revision
  (`FAMILY_HF_DATA_REVISION`) and cite tag `v9.1` as `bc9eab28`; the Hub `v9.2`
  / `main` SHAs are marked unverified; `sandbox board --interval` is clamped to
  0.1 s so `0` no longer spins a core (TUI, SSE stream, demo loop); the floor is
  in the `--interval` help, `AGENTS.md` and the board docs. Docstrings now cover
  every function the PR touches, and `tests/test_cli_simplified_commands.py` pins
  the exit codes of the commands whose redundant returns were collapsed (it
  passes on `main` too). The two dated 2026-09-27 serving-ladder docs carry an
  as-of note for the `FAMILY_HF_REVISION` pin.
- DMR-111: refresh reviewed standalone snapshots to released Dojo v0.24.2,
  consuming source-owned cost/FNOL and document-ownership/storage corrections;
  provenance and loaded scorer identity agree with the generated bytes.
- DMR-112: freeze the vendored pipeline to `60cd5fa` and optional visualizer
  retrieval to `98ae227`, matching the reviewed DMR-112 source tips.
- DMR-113: return a failure code instead of escaping when the `.refresh`
  directory cannot be created, and refresh a clean visualizer checkout left at
  an earlier reviewed commit while still preserving local commits and dirty
  trees.
- DMR-113: freeze the tracked snapshots to pipeline `1a1ec3d` and the interim
  post-v0.24.2 Dojo commit `718e326` (explicit zero-token usage fix), and the
  optional visualizer to `cab7a41`; regenerate both snapshots and their
  provenance.

- DMR-111: delegate CUAD/MAUD benchmark engines and pooled headline scores to
  released Dojo 0.24.0. Null MAUD ground truth is unlabelled; real CUAD zero
  scores no longer disappear. Preserve existing public adapter/result names.
- Retrieve reviewed commit refs and peeled release tags immutably, validate
  before checkout/replacement, and preserve vendor recovery bytes if installation
  and rollback both fail. Use identical exclusion rules for Git/workspace copies.
- Refresh tracked pipeline/scoring snapshots and truthful source provenance;
  freeze optional visualizer retrieval and preserve existing local checkouts.

- Complete the SAND-062 dependency lock updates: pypdf 6.21.2, filelock 4.2.1, nbconvert 7.17.2 and OpenTelemetry API/SDK/exporters 1.45.1 (semantic conventions and shared HTTP transport 0.66b1). Initialize sandbox vendor paths in the cold-resume test subprocess before patching its real OpenAI client, and scope the API-evals import path to the test fixture so the module also passes independently; no runtime behavior changes. Related: DMR-097.

- Add the DMR-088 `fetch-deps` regression test (`tests/test_fetch_deps_rc.py`), previously carried only in the Digital-Mailroom hub copy: every vendor refresh runs after an earlier failure and the command exits non-zero if any failed.

- Make the ModernBERT feeder path tests hermetic: they build a fake `mailroom-ml` checkout under `tmp_path` instead of discovering a sibling on the developer's machine, and pin that `feeder_status()` reports not-ok when the eval entrypoint is missing.

- Bind locked execution and reusable API results to immutable generation/task,
  dataset and resolved prompt identity; freeze initial operator knobs and refuse
  damaged artifacts before activation. Keep every managed vendor refresh eligible
  after an earlier source failure.

### Fixed — DMR-091 source-owned sandbox lifecycle

- Preserve existing matching preflight generations and their live remote identity;
  refuse unsafe resets and archive cancellation/cold-boot artifacts with the generation.
- Activate frozen profile/model, per-agent model and full generation-knob maps,
  and prompt selections in cold workers and fresh-process resumes, including
  subsequent activations by existing eval runners.
- Add durable cooperative cancellation for row-resumable endpoint jobs: stop
  submissions, drain in-flight work, acknowledge paused, and resume pending rows.
- Require exact lock/spec/run identity for API-evals terminal reuse; safely append
  after a valid unterminated JSONL tail; report resumed run-wide error totals.
- Reconcile the corporate optional-subclass assertion with canonical detailed
  alignment using three hand-counted matching keywords and unlabeled entity GT.

### Fixed — `corporate_records_specialist_subclass_v2` amended before first run

- **`corporate_records_specialist_subclass_v2`** (eval-environment `corporate_records_specialist_v7`, now sha256
  `253559fc…`): `certificate_of_formation` moved to its own line and the `subsidiary_list` line states where the listing
  statement (`subject_matter`) and subsidiary names (`keywords`) go — resolving the PR #143 CodeRabbit finding; the
  lineage lock and all stem pins were refreshed in the same change. The default pin moved to `v7` in the follow-up
  re-freeze below (see "default-pin move").

### Changed — breaking (vendored dojo)

- **Vendored llm-dojo-scoring re-vendored when the scoring engine was bumped** (2026-10-17,
  the `feat/corporate-record-subclass-schemas` branch mechanics). Every vendored-pin claim
  (`vendor/README.md`, `vendor/llm-dojo-scoring/VENDOR.md`, README, QUICKSTART, SANDBOX-GUIDE, sister-repos,
  htcondor README, `deploy/modal_job.py`, `pyproject.toml`, the `fetch-deps` fallback pin) carries it. The snapshot
  ships the eval-environment prompt lineage API (`llm_dojo_scoring.prompts`: `get_prompt_version`,
  `list_prompt_versions`, ... and `eval_environment_lineage.json`).

### Changed — vendored dojo bump: per-subclass corporate scoring (sandbox #145)

- **Re-vendored llm-dojo-scoring past `v0.22.0`** at the dojo PR branch `feat/corporate-record-subclass-schemas`
  @ `8e6566c1d1c52efeb5ebbb57ddee90a94586f7da` (draft Exios66/llm-dojo-scoring#46) — the tag `a2862cec` was one
  sync cycle behind. New in the snapshot: `corporate_record_schema.py` (per-subclass `SUBCLASS_SCHEMAS` incl.
  `omit_entity_keys` + `core_guidance`), `corporate_record_relabel.py` (GT-row relabel CLI), `align_unlabeled` in
  `suites._score_extraction`, per-subclass `required_ftypes` (key entities score when the dataset labels them but
  are never required), and the amended `corporate_records_specialist_v7` (`253559fc…`) production template. See
  `vendor/llm-dojo-scoring/VENDOR.md` — the pin is recorded there. The lineage JSON in the snapshot was
  regenerated with the dojo's own `scripts/sync_eval_environment_lineage.py` against the sibling
  eval-environment checkout @ `22d217ab…`, so the vendored registry now carries **43 versions** (5 archived /
  15 frozen / 23 mutations) including `corporate_records_specialist_v7` **and** the SAND-042 frozen successors
  `insurance_claims_specialist_v4` (`1ca6e83c…`) / `merger_agreement_specialist_v4` (`da316691…`) the tag-era
  registry lacked.
- **`score_extraction_row` wires the subclass into the vendored suite score path** (closing the
  ISSUE_ALIGNMENT gap): `doc_subclass` / `expected_subclass` (the row's GT `expected_subclass`) flow into
  `suite.score(..., doc_subclass=...)`, so `align_unlabeled` drops blank unlabeled key-entity fields from both
  sides instead of scoring them as expected-empty, unlabeled extension keys are never spurious fills, and the
  row carries the vendored per-row `unlabeled_fields` payload (`tests/test_corporate_scoring.py` computes the
  dojo-side expectation IN TEST from the vendored module). Runner/agent call sites pass the row's
  `expected_subclass`; without it the alignment normalizes to `"other"` as before.
- **Emit provenance (dataset_revision)** — audited rather than changed: the gap is already closed upstream of the
  emitter by SAND-032 (`--dataset-revision` CLI handling; serving fixtures record the pinned `FAMILY_HF_REVISION`
  `bc9eab28…`; job records take the run-lock provenance), and the vendored `Emitter`/`serving.py` are untouched by
  the branch diff, so `emit_serving_scorecard` already receives a provenance source everywhere it is called
  (`validating` tests in `tests/test_serving_groups.py`).
- **Default-pin move — corporate_records_specialist default v6→v7** (deliberate re-freeze, following the
  coordinated amendment and the vendored scoring bump): the lineage lock's corporate default row now serves
  `corporate_records_specialist_v7` (`253559fc…`, canonical amended text, 5462 chars, via stem
  `corporate_records_specialist_subclass_v2`) — the text the vendored catalog's `production_prompts` template and
  the `corporate_record_schema` prompt renderer now ship, so default runs stopped serving v6 doctrine that
  conflicts with the per-subclass schema the scorer now enforces. The re-freeze keeps the successor chain honest:
  `parent_key` = `_v6` (its bytes remain pinned as stem `corporate_records_specialist_simplified`),
  `superseded` v1 block untouched, documented in the lock's `notes` + the row's `origin`. The vendored
  `llm-mailroom` `llm/frozen_v1/lineage.json` row (frozen-v1 specialist serving via the dojo
  `production_prompts` catalog) records the same promotion, and
  `config/prompts/corporate_records_specialist_production.txt` was re-exported to the v7 bytes
  (`scripts/sync_specialist_prompts.py`). Historical posture runs that pinned the then-default
  `_simplified` stem are now intentional non-catalog pins. `--prompt-version` now selects all three successor
  keys (`v7` + the two `*_v4`s) and `docs/prompts/` was re-rendered (43 versions).

### Changed — corrected v1 specialist stems (dojo #30)

- `correspondence_specialist_simplified.txt` / `corporate_records_specialist_simplified.txt` now carry the
  corrected text the dojo ships as `production_prompts` (eval-environment mutations
  `correspondence_specialist_v7` / `corporate_records_specialist_v6`; sha256 `2b0b81ff…` / `fe13501f…`,
  6113 / 5865 chars). `eval_environment_lineage.json` rows point at those keys with the new
  sha256/chars, a `refrozen_at` stamp and a `superseded` block holding the original v1 key, sha256, chars
  and `frozen_at`; the sibling check verifies both. **Runs that used these stems before this change
  scored the v1 bytes** (`*_v1`, `eab63b5a…` / `484e64dd…`); the default stem's logged eval-environment
  key is now `_v7` / `_v6` (corporate's default moved on to `_v7` via the successor stem in the vendor
  bump section below). The generated archived runbooks were re-rendered to the current key.

### Fixed — dojo v0.22 provenance + `identity_mixed`

- Serving records and fixtures carry `dataset_revision` (+ `split` / `draw_seed` where known) so the
  dojo's `emit_serving_scorecard` no longer raises `ProvenanceExportError` (4 tests). Job records take
  them from the run lock (`job.metrics.lock_dataset_provenance`); the serving fixtures carry
  `FAMILY_HF_REVISION`; token-price USD is labelled `cost_basis=token_price_estimate`. Never derived
  from the dataset fingerprint. `emit_local_vs_api_scorecard` accepts `provenance=`.
- `compare_from_records` (`sandbox eval local_vs_api --from-log`, `sandbox matrix`) and
  `sandbox metrics compare` group rows by full identity (`serving_groups.py`) and compare per comparable
  group instead of pooling every local/API row into one `identity_mixed` leg. New `--group`; one
  scorecard per group (`<name>.g<n>`).
- Scorecard tests now run the real `Emitter` + `LocalManifestSink`; `tests/test_serving_groups.py`
  covers multi-model logs.

### Changed — scorecards fail loudly

- A scorecard that cannot be emitted with honest provenance now RAISES instead of being reported as
  "refused": `emit_local_vs_api_scorecard` / `emit_group_scorecards` raise `ScorecardEmissionError`
  (subclass of the dojo's `ProvenanceExportError`; `.field`, `.group`, sandbox hint) for a missing
  `dataset_revision` or an incomparable (`identity_mixed`) group. All groups are validated against an
  in-memory sink before any is written, so a late failure leaves no partial manifest, and
  `run_local_vs_api_eval` raises before appending its log record. `scores.scorecards_refused` and the
  `emitted: False` entries are gone. `sandbox` exits 1 with `error: scorecard not emitted: <reason>` on
  stderr (job runs fail with the same reason). New `sandbox eval local_vs_api --dataset-revision <sha>`
  (full 40-hex only) supplies a real revision for log/fixture rows that have none; it never overrides a
  recorded one. Reverses the report-don't-raise policy of the provenance fix above.

### Added

- **Prompt catalog `docs/prompts/`** (generated, deterministic): an index of all 43 eval-environment versions
  (5 archived, 15 frozen, 23 mutations; 15 roles) and one page per role with, per version oldest -> newest, the
  metadata, the full memo, what changed against the predecessor (sections, +/- lines, chars delta, dojo notes such
  as the `sorter_v3` duplicated block, non-monotonic dates), a unified diff, the full text and the exact
  `--prompt-version` command. The index marks the sandbox default / eval-environment default / latest per role and
  explains the name collisions (the `sorter_v1` stem and the mailroom `sorter_v0..v14` / `contracts_specialist_v1..v33`
  registry are not eval-environment keys). `python scripts/render_prompt_catalog.py [--check]`;
  `tests/test_prompt_catalog.py` fails when the pages drift from the vendored dojo.
- `sandbox prompts list-versions [--role R] [--lineage L] [--json]` and `sandbox prompts show <key> [--diff <other-key> | --memo | --json]`.
- The `prompt_versions` seam is wired to the real dojo lineage (`llm_dojo_scoring.prompts.get_prompt_version`);
  `tests/test_prompt_versions_dojo.py` checks all 43 versions, the sorter `v1..v4` and every specialist mutation
  against the lineage (and a sibling eval-environment checkout via `EVAL_ENVIRONMENT_ROOT` when present), that every
  accepted lineage role is a sandbox pipeline role, and that `pipeline_quality` / `pipeline_verdict` are refused.
  Finding, since resolved by the vendor bump: the lineage lock's `insurance_claims_specialist_v4` /
  `merger_agreement_specialist_v4` keys were not in the tag-era registry; those stems ran with `--prompt <stem>`
  and now resolve through `--prompt-version` as well.
- **Run with any eval-environment prompt version** (archived `_v0`, frozen `_v1`, every GEPA / manual
  mutation, sorter included): `sandbox eval <task> --prompt-version [role=]key` (repeatable),
  `sandbox run ... --prompt-version`, and `prompt.versions` in a run spec. New seam
  `mailroom_sandbox/prompt_versions.py` (`resolve_prompt(role, key=None) -> (key, text, sha256)`); the
  dojo lookup is the single function `lookup_prompt_version` (the vendored dojo does not ship the
  lineage API yet, so a selection fails loudly until it is re-vendored). Unknown key, key/role
  mismatch, non-pipeline role, sha mismatch, `--prompt` vs `--prompt-version` clash: hard error. The
  key + sha256 land in the run lock (`prompt_versions`, `source: eval-environment`), `spec_hash`, and
  every record (`prompt_version`, `prompt_sha256`, `eval_environment_prompt_key`, `prompt_versions`).
  `serving_groups` now also keys legs and pairs on `prompt_sha256`, so mutations never pool (and the
  mailroom-text stem `sorter_v1` never pools with eval-environment `sorter_v1`). Default behaviour is
  unchanged.
- **SAND-042 repaired specialists frozen.** `insurance_claims_specialist_simplified_v2` and
  `merger_agreement_specialist_maud_v2` are frozen in eval-environment as
  `insurance_claims_specialist_v4` and `merger_agreement_specialist_v4`, and pinned under
  `frozen_successors` in `config/prompts/eval_environment_lineage.json` (sha256 `1ca6e83c…58ea` / 8461
  chars and `da316691…1946` / 33125 chars). `assert_catalog_sha` and `verify_local_catalog` refuse drift
  in either stem; `eval_environment_key_for(stem=…)` reports the v4 key on run records; the sibling check
  reads eval-environment `prompts/mutations.json`. The default v1 stems are unchanged.

## [0.3.0] - 2026-10-17

### Added

- **`corporate_records_specialist_subclass_v2`** frozen successor (eval-environment `corporate_records_specialist_v7`, sha256 `253559fc…`): per-subclass
  key-entity lines generated from the dojo's `corporate_record_schema`. The default pin is unchanged.

### Changed — v1 specialist stems re-frozen (Exios66/llm-dojo-scoring#30)

- `config/prompts/correspondence_specialist_simplified.txt` and
  `config/prompts/corporate_records_specialist_simplified.txt` now mirror the
  dojo's corrected `production_prompts` v1 text (provenance comment stripped). `eval_environment_lineage.json`
  rows carry the new `sha256`/`chars` plus `previous_sha256`, `previous_chars` and `refrozen_at`
  (2026-10-15); `frozen_at` is unchanged. Correspondence `eab63b5a…`→`2b0b81ff…` (6061→6113 chars);
  corporate-records `484e64dd…`→`fe13501f…` (5801→5865 chars). **Scores on these two stems are not
  comparable to earlier cards without re-scoring.**

### Fixed — SAND-042 schema-adherence RCA (`docs/SAND42-SCHEMA-ADHERENCE-RCA.md`)

- Vendored `InsuranceClaimExtraction` (`insurer`, `insured_party`, `claim_type`, `damages_description`,
  `coverage_determination`), `CorporateRecordExtraction` (`entity_name`, `record_type`) and
  `CorrespondenceExtraction.communication_type` are contract-nullable; `claimed_amount` / `demand_amount`
  accept currency phrases. Insurance schema-valid 0.26–0.34 was this bug, not the model.
- Structured-output `intent` hints list the scored vocabulary (were `demand_payment`, `acknowledge`,
  `coverage_denial`, … — none scorable).
- `eval/maud_scoring.py`: chunk-merged answers are reduced (non-answers dropped, conflicts counted as
  `maud_conflicts`) instead of first-chunk-wins; multi-class answers compare as sets; `{q: null}` is unanswered.
- Vendored llm-dojo-scoring refreshed from v0.15 to the dojo `claude/schema-adherence-rca` branch (label
  intents, stringified-GT parsing, MAUD catalog + fold/parse fixes, CMS `claim_type` ≡ `health`). Four tests
  that pinned v0.15 empty-list / Modal serving-kind behavior now pin the dojo contract.
  **Scores are not comparable to SAND-032…SAND-042 cards without re-scoring.**

### Added

- `tests/test_schema_contract.py` (dojo `contract_violations` over every vendored schema) and
  `tests/test_specialist_intent_vocab.py`.
- Candidate stems `insurance_claims_specialist_simplified_v2`, `merger_agreement_specialist_maud_v2`
  (generated: `scripts/gen_maud_v2_prompt.py [--check]`) and `config/runs/rca/` re-check configs.

### Added — local-first job traces (pack → upload → prune)

- Endpoint-mode runs (`sandbox run start`, the Modal-vLLM grid and SAND runs) now build a tracer; before this
  they always passed `tracer=None`, so no job spans were ever emitted whatever the locked sink said.
- Each run gets a `job.run` span with its `job.item` children nested across worker threads, carrying
  item id, ok/error, attempts and token usage.
- Spans are mirrored to `data/traces/<run_id>.spans.jsonl.gz` even with `sink: none`
  (`SANDBOX_TRACE_LOCAL=0` disables); Phoenix/Langfuse/OTLP export is unchanged.
- `sandbox traces pack <run_id> [--dest DIR] [--prune]` zips the mirror as zstd Parquet + manifest, copies it
  to a synced upload folder (`SANDBOX_TRACE_UPLOAD_DIR`, e.g. the Drive LOGS folder) under a date
  subfolder, verifies the copy by SHA-256, and only then deletes the local copies. See `docs/tracing.md`.

### Changed — SAND-040 runs on one 32K deploy; † merger keeps the optimized settings

- `sandbox runbook show sand40` deploys the SAND-037 2×L4 engine once (native 32768 window, no 64K
  redeploy). Correspondence, insurance claims, corporate records and contracts run n=100 on the aligned spec
  unchanged. Merger runs the same 50 agreements as SAND-37 2×L4 with the optimized † settings: chunked
  whole-document extraction (47,000-char windows + 6,500 overlap, sized to the 32K window), the MAUD v1
  prompt, Qwen3 sampling (0.7 / top_p 0.8 / top_k 20 / presence 1.0), a 6,144 cap and one length re-sample.
- A 5-agreement gate cell (`sand40-check-5-merger-specialist-awq-2l4`) runs first on the same deploy;
  `sandbox run card --gate` fails unless every document is ok and vLLM accepted every chunk the documents need
  (`extract_chunked` skips a rejected chunk silently). On failure the script tears down and stops.
- Runbook catalog: optional `gate: {config: …}` renders the gate before the scored loop.
- Master card: new *Merger † settings* table (SAND-37 vs SAND-40, changed settings in bold, result and
  matched-agreement delta once measured); SAND-40 column reads 100 (merger 50†).
- Removed the unrun 64K long-phase cells and the `sand40-short` / `sand40-long` runbooks. The executed 64K
  probes stay as a matched-document appendix.

### Changed — SAND-040 master score & cost card validated and fully detailed

- Validated `reports/SAND-37/SAND-37-MASTER-SCORE-COST-CARD.md` three ways: a fresh `sandbox run card --master`
  render is identical to the committed card; every pooled and per-specialist figure recomputes from the
  per-document rows in the 15 cell cards (ok counts, tokens, busy-window cost, throughput, p50 latency, MAUD
  accuracy and coverage, CUAD F1); every finding's numbers match the cards. Card p95 latency is nearest-rank.
- Contracts is now labeled as what it measures: the per-document CUAD clause-presence F1 averaged over
  successful documents with CUAD labels (micro F1 in parentheses). The run reports count unlabeled documents
  as 0, which is why they read about 0.10 lower.
- New master sections: per-cell detail for each posture (errors by kind, schema-valid rate, score sd, p50/p95,
  tokens per document, completion p95/max, wall, busy GPU $, $ per 1M tokens, tokens/s/GPU); clause scoring
  detail (CUAD precision, recall, value accuracy; MAUD questions, answered, correct, precision); vLLM engine
  telemetry (requests, length-capped finishes, preemptions, prefix-cache hit rate, TTFT); run conditions by
  specialist; pooled wall, token split, length finishes and preemptions.
- SAND-40 validation probes appear in an appendix with a matched-document comparison against the SAND-37
  2×L4 cell, never in the pooled columns. On matched documents the 64K contracts probe is flat (−0.002,
  8 better / 7 worse); the merger probe gains +0.081 MAUD accuracy (14 / 3) while reading 11.5× the prompt
  tokens through chunked extraction.
- The SAND-40 header no longer commits the run to a 64K YaRN redeploy; each SAND-40 card records its window.

### Added — SAND-037 aligned specialist grid and runbooks

- All 20 Qwen3-8B-AWQ specialist grid cells (5 classes × n = 20/50 × 1×L4 C8 / 2×L4 C32) now share one spec:
  the SAND-032 frozen L5 engine (`awq_marlin`, fp8 KV, CUDA graphs, `max_num_seqs` 16 per replica, thinking off,
  `max_inputs` 32), `split: all` single-class draws at seed 42 (n = 20 nests in n = 50), the frozen v1
  `*_simplified` prompts, and `max_tokens` 8192. Only n, replicas and concurrency vary. Previously the 1×L4 cells
  ran plain `awq` eager at `max_num_seqs` 8, the 2×L4 cells plain `awq`, and the n = 20 insurance / corporate /
  merger draws were stratified on `split: test` / `train`.
- `docs/SPECIALIST-GRID-PLAN.md`: the aligned spec, the length-error analysis, all 20 cell run ids, and the
  existing records each cell supersedes.
- Runbooks `grid-1l4` and `grid-2l4` (new `grid` catalog family, serving variants that differ only in replica
  count): one warm deploy per fleet shape, ten cells each.
- Eight new run YAMLs (the n = 20 cells the grid lacked, plus `grid-20-merger-specialist-awq-1l4-rerun` and
  `grid-50-contracts-specialist-awq-2l4-rerun`, which leave the executed cells' reports intact); every grid YAML
  is generated from one template.

- SAND-37 score & cost cards (`mailroom_sandbox.job.grid_cards`): every grid run writes
  `reports/SAND-37/<1L4|2L4>/<specialist>/<run_id>.card.{md,json}` (conditions; run, time, cost, tokens,
  throughput, latency, per-replica vLLM telemetry, quality and CUAD/MAUD clause scoring; error ledger;
  per-document rows), and `sandbox run card --runbook grid-1l4|grid-2l4` writes the finalized
  `L4x1-` / `L4x2-SCORE-COST-CARD.{md,json}` from the committed card JSON. The runner writes the card at the end of
  each grid run; `sandbox run card --config` re-renders it after the `/metrics` after-scrape, reusing the runner's
  busy wall. The grid runbooks bracket each start with `scrape-metrics` before/after and end with the suite card
  (catalog flags `scrape_metrics`, `export_card`).

### Fixed — SAND-037 runaway decoding on contracts and merger

- Every LengthFinishReasonError on record is a contracts or merger document that used its whole cap (4096, 8192
  or 16384), while successful outputs top out at 4,055 tokens and the failing documents change between runs.
  Those two specialists decode under the JSON-schema grammar at a call-site `temperature=0.1`; near-greedy
  decoding loops and job retries replay the loop. Grid contracts and merger cells now run at temperature 0.7
  (Qwen3's documented non-thinking setting); the json_object classes keep 0.1.
- `mailroom_sandbox.sampling`: applies a run-scoped `temperature` knob to the vendored specialists, whose call
  sites pass `temperature=0.1` as a literal (previously a configured temperature never reached the request).
  Installed at `activate()`; agents without a knob are untouched.
- `sandbox runbook check` fails when a grid runbook's export block disagrees with `sandbox run deploy-env` for any
  of its configs; `sandbox run benchmark-check` applies its deploy-env drift gate to grid cells as well as
  SAND-032 runs. The `preflight_force` catalog flag renders `preflight --live --force` to re-lock a drifted run.

### Added — SAND-036 warm vs cold GPUs, cost per 1M tokens, Modal vs API break-even, mailroom-issues Pages site

- `reports/dashboard/gpu_report.py`: cost per 1M tokens on three bases (warm busy-window, one cold batch, program-loaded),
  warm-fleet cost per token at falling utilization with the break-even busy share, and a warm vs cold section (boot
  measurements, warm vs cold $/doc and $/1M per workload, the batch size that amortizes a cold start, keep warm vs
  scale to zero with the threshold = scale-down + L5 boot). Every setup value and date in the report is read from the
  serving exports and run reports; the hub `fleet` extract gains `scaledown` and each run's own score.
- `reports/dashboard/breakeven.py`: one per-document Modal-vs-API calculation (verdict per class, every measured Modal
  configuration against the cheapest hosted model, warm and cold break-even volumes, the optimal measured deployment)
  quoted by the cost comparison's §3, the GPU report and the site, so no two reports disagree.
- Dark, high-contrast figures: `scripts/sand032/viz.py` renders every chart as a dark card on the reference palette's
  dark steps (validated `--mode dark`: ALL PASS), with a fixed color per model (`ENTITY`) and a legend whenever
  bars carry more than one color; subtitles in sentence case. All 51 SAND-032 figures re-rendered
  (`rerender.py`, data unchanged). The Pages site and the hub dashboard are dark by default.
- `reports/dashboard/source_charts.py`: the eval-environment and mailroom-ml charts the reports used to copy are
  redrawn from hub data in the same kit, so every report figure shares one theme.
- `reports/dashboard/export_pngs.py`: 2× PNG of every report figure for slides (`mailroom-issues/reports/viz/`).
- The per-token comparison includes the Qwen3.7-Flash n = 50 legs (token counts now extracted and cross-checked
  against their reports); the sorter table lists every hosted model's largest run (Qwen3-8B: n = 20).
- Model per route made explicit: Qwen3-8B-AWQ is the only model self-hosted on Modal; Qwen3.7-Flash and every other
  hosted model ran through the API only. The cost comparison's §3.2 adds the same-model comparison (Qwen3-8B-AWQ on
  Modal vs Qwen3-8B via the API), isolating the route from the model.
- `reports/dashboard/pages_site.py` + `export_hub_reports.py --site`: the three reports as a static GitHub Pages site
  for `mailroom-issues/docs/` (inline SVG, no JavaScript, no external requests; covered by `--check`).
- Hub snapshot re-pinned to eval-environment `86b4e54` (main, including the qwen3.7-flash suite README); `markdown-it-py`
  joins `[dev]` (requirements regenerated with `scripts/sync_requirements.py`).
- `tests/test_gpu_report.py`: the $/1M identity, the keep-warm threshold, the amortizing batch, the break-evens and the
  optimal row, and site integrity (no scripts, every internal link and anchor resolves).

### Added — SAND-035 cross-repo report audit + Modal vs API cost comparison

- `scripts/sand032/viz.py` sizes label columns by measured text width (middle ellipsis, full label in
  `<title>`), gives reference-line labels their own lane, and spaces dumbbell legends by measured width;
  `dumbbell(val=...)` overrides the end-of-row label. `scripts/sand032/rerender.py` re-lays all 51
  committed SAND-032 figures from their embedded data and asserts the data is unchanged (`--check`).
- Reports hub: **Modal vs API** tab (cost vs quality per specialist and for the sorter); snapshot synced to
  eval-environment `f6bb510` / mailroom-ml `d3ad222` (the merged chart-layout fixes; source SHAs only, no
  values changed); Qwen3.7-Flash n = 50 legs cross-checked; the merger
  leg eval-environment files under Qwen3-8B is labelled by its logged model (Qwen3.7-Flash, frozen prompts).
- `reports/dashboard/export_hub_reports.py` writes `COST-COMPARISON-MODAL-VS-API.md`, `MASTER-REPORT.md` and
  figures for `mailroom-issues/reports/`; `report_audit.json` records the sweep (0 overflow / 0 collisions /
  0 broken links across the three repos).

- `reports/dashboard/gpu_report.py` writes `MODAL-VLLM-GPU-REPORT.md` for `mailroom-issues/reports/`: cost per token,
  GPU spend breakdown, client-slot occupancy, per-replica vLLM metrics and the second-L4 analysis. The hub gains a
  `fleet` section (`hub_extract.sand032_fleet`): all 24 SAND-032 serving exports cross-checked against their run
  reports (wall, tokens, throughput, busy and billed GPU $, slot occupancy, replica request split). `viz.hbar` gains
  `domain_max` so small multiples can share one scale.

### Fixed — SAND-036

- Hub stratum means and the legacy spend total use `math.fsum`, so `hub_data.json` is identical whether it is
  rebuilt on Python 3.11 or 3.12 (3.12's `sum()` compensates, 3.11's does not; the two differed in the last digit).

### Fixed — SAND-035

- `build_hub.py --check` crashed (`KeyError: 'run_id'`) on eval-environment log rows without a run id.
- Latency/subclass figure labels overflowed the left edge; p50/p95 labels collided with each other and
  the subtitle.
- Broken relative links in CHANGELOG, docs, RUN-20 serving reports and agent prompts.
- SAND-032 spend: the program summary's header gave the stage 1–5 ledger ($1.21) while its closing ledger read $2.80;
  the runs alone bill $2.18. The header is corrected, and the hub checks it against the closing ledger and the runs'
  billed GPU $.
- The S6 sorter's $/doc was the billed figure (with its 131 s cold boot); the hub now uses the busy-window basis like
  every other run and records the report's figure as a documented source issue.

### Changed — governance: DMR-068 hub tracker + SAND board reconciliation

- `docs/scale-matrix.md` status line cites the DMR-068 hub tracker
  (LLM-Mailroom-Services/mailroom-issues#205) for owner and spend decision.
- `governance/TASKS.md` gains rows for SAND-021..025, which existed only as
  GitHub issues (#27-#31), and states that the board is the SAND numbering
  authority (highest id in use: SAND-033). Closes mailroom-issues#194.

### Added — SAND-031 centralized operator runbooks

- **Single edit surface:** [`config/runbooks/catalog.yaml`](config/runbooks/catalog.yaml).
  Change pins / steps there, then `sandbox runbook check` (catalog vs
  `deploy/modal_vllm.py` + `config/models.yaml` + cited run YAMLs) and
  `sandbox runbook write` (regenerates `docs/runbooks/`).
- **Singular 1×L4 / 1-container Qwen3-8B:** `sandbox runbook show l4-qwen3-8b`
  (plus Operator A/B tracks and the SAND-018 N=20 probe).
- **Improved configs:** AWQ, AWQ-c8, correspondence AWQ/c8, FP16 isolation twin
  (blocked), Granite 4.2-8B FP8 swap-in, second-L4 data parallel, scale-matrix
  cells — `sandbox runbook list --family improved`.
- CLI: `sandbox runbook list|show|check|write`. Tests:
  `tests/test_runbooks.py`. `docs/modal/benchmark-l4.md` is now the pointer;
  operator scripts are generated.

### Changed — monorepo target Digital-Mailroom (2026-09-24)

- Subagent propagate/materialize docs and package ids use **`digital-mailroom`**
  ([LLM-Mailroom-Services/Digital-Mailroom](https://github.com/LLM-Mailroom-Services/Digital-Mailroom));
  `mailroom-dev` remains a legacy CLI alias only.

### Fixed — SAND-027-3 eval-environment prompt versions on Modal + vLLM specialist evals

- Family A specialists (`correspondence`, `corporate_records`, `insurance_claims`,
  `merger_agreement`) bind `get_managed_prompt` at import time. Preflight
  imports those modules via `prompt_templates()`, so patching only
  `llm.prompts.get_managed_prompt` left Modal runs on vendor/Langfuse
  production text. `apply_runtime_overrides` now rebinds every loaded module
  and writes LangChain `PROMPT_VERSIONS` role + `{role}_v*` keys (same
  injection as eval-environment `evals.prompts.registry.activate`).
- Isolated specialist evals default to the frozen v1 sandbox stems. Job locks
  that pin `prompt.agents.<task>` now pass that stem into `activate`.
- Experiment / serving records log `contracts_specialist_v1` (etc.) + sha256
  when the pin is a catalog stem.
- Hermetic lock: `config/prompts/eval_environment_lineage.json` (sha256 +
  opening line). `tests/test_eval_environment_lineage.py` fails on drift;
  sibling eval-environment checkout is compared when present.

### Changed — SAND-030 Modal L4 long-prompt vLLM posture

- Deploy defaults (`deploy/modal_vllm.py` + compose parity):
  `max_num_seqs=6` (was 256), explicit `--enable-prefix-caching`,
  `--enforce-eager` (faster cold boot). `gpu_memory_utilization=0.90` and
  HF/vLLM Volumes unchanged.
- Second L4 = **data parallel**: raise `MODAL_VLLM_MAX_CONTAINERS=2` (Modal
  `@web_server` round-robins). Do not use `GPU=L4:2`+TP for 8B-class.
- `VLLMSpec` gains `enable_prefix_caching` / `enforce_eager`; specialist and
  cost-eval run YAMLs pin the new posture. Scale-matrix cells keep
  `max_num_seqs: 256` and must export `MODAL_VLLM_MAX_NUM_SEQS=256` at deploy.
- Docs: `deploy/README.md`, `docs/modal/benchmark-l4.md`, `docs/scale-matrix.md`
  (container topology), `docs/modal/modal-serving-ops.md`, skill knobs.

### Added — SAND-020 correspondence extraction-quality diagnosis (issue #21)

- **`eval/schema_adherence.py`** — parse-failure / schema-adherence checks
  (`parse_error`, `schema_valid`, `schema_adherence`) separate from
  `overall_extraction_score` / `extraction_f1`. Wired into
  `score_extraction_row`, isolated / extract / pipeline summaries, and
  `sandbox metrics` quality extraction (additive keys only).
- **Empty-field + partial-credit tests** pinning dojo behavior: empty
  scalars are not events; empty-list inventions zero overall; F1 TP requires
  typed score ≥ 1.0; isolated `exact_match` is a runner alias of overall.
- **Offline diagnosis** of `run-20-correspondence-awq-c8` (fingerprint
  `285f423d3708`): [`docs/archive/extraction-quality-diagnosis.md`](docs/archive/extraction-quality-diagnosis.md)
  (best/worst docs, token evidence, owner-locked 0.25 / 0.50 gates).
- **FP16 twin YAML** [`config/runs/legacy/run-20-correspondence-fp16-c8.yaml`](config/runs/legacy/run-20-correspondence-fp16-c8.yaml)
  — same draw, `Qwen/Qwen3-8B`, **not run** (spend/auth blocked). Runbook:
  [`docs/jobs.md`](docs/jobs.md) §AWQ vs FP16 isolation.

### Changed — SAND-026 simplified specialist extraction prompts (issue #32) (2026-09-25)

- Parallel `*_simplified` stems under `config/prompts/` for the five live
  specialists. Each stem is **class-specific** (live schema, typical
  document shape, class-local empty rules, class traps) — not a shared
  generic extract template. Vendor mirrors (`contracts_specialist_v33`,
  `*_production`) stay byte-identical for sync.
- Correspondence no longer dual-lists retired `key_points` /
  `referenced_communications` as registered fields; contracts no longer
  trains `key_obligations` / `termination_clauses` then forbids them.
- Run-20 / run-30 specialist YAMLs + `specialist_posture.prompt_file` pin
  the simplified stems. `scripts/sync_specialist_prompts.py` default write
  cannot clobber experiment pins (`--overwrite-experiment` is the opt-in).
- **Empty / class-mismatched Hub GT is not a miss.**
  `eval.extraction_scope` drops empty placeholders and other-class keys
  (and aliases correspondence `claimed_amount` → `demand_amount`) before
  `score_extraction_row` calls the dojo suite, so empty insurance-claim
  fields on non-claim rows cannot pull down `overall_extraction_score` /
  F1. Vendor `score_extraction` still treats `[]` as an event — we do not
  edit `vendor/` (hub#62). Lock: `tests/test_extraction_scope.py`. Docs:
  [`docs/evals.md`](docs/evals.md) §Extraction scoring.
- Inventory + operator path: [`config/prompts/README.md`](config/prompts/README.md).
  Catalog promotion remains in `LLM-Mailroom-Services/eval-environment`
  issues 4–8 — not this package.

### Added — SAND-018 single-class 20-contract Modal run + full-corpus logged sample (2026-09-25)

- **`config/runs/legacy/run-20-contracts-specialist.yaml`** — the runbook's
  [`docs/modal/benchmark-l4.md`](docs/modal/benchmark-l4.md) L4 Qwen pins (`Qwen/Qwen3-8B`,
  L4, `v0.29.0`, `max_model_len=16384`, scaledown 120, `contracts_specialist_v33`
  local prompt) applied to a **20-contract** single-class run drawn as a seeded
  random sample (`sample_seed=42`) from the **full** corpus (`split: all`, 3,302
  rows). Preflight records the draw (seed, rows, sha256) in `spec.lock.json`
  and writes it to `dataset.jsonl` — the logged random sample.
- **`job/specialist_posture.py`** — `run-20-contracts-specialist` posture row
  (concurrency 4, `cost_cap_usd` 0.55, `max_wall_seconds` 3200) plus
  `SPECIALIST_LIMIT_BY_RUN` / `expected_limit()`, so the per-doc-type pins cover
  the 20-doc variant.
- **`job/benchmark_check.py`** — the specialist `limit` + local-prompt-pin
  enforcement now keys on the posture map (covers `run-20-*`), not only the
  `run-30-*` prefix; a 20-doc YAML that forgot `limit: 20` fails the loud gate
  instead of passing it silently.
- Tests: `tests/test_specialist_posture.py` (posture coverage + gate rejects a
  wrong limit).

### Added — SAND-017 central subagent roster (2026-09-24)

- **`config/subagents/family-roster.yaml`** — family-wide manifest (home package,
  package membership, harness metadata) shared across Digital-Mailroom /
  llm-mailroom / llm-entity-extraction / local-mailroom-sandbox.
- **`.opencode/agents/`** — family prompt-engineer / eval-judge /
  experiment-log-sync / trace-log-analyst / mailroom-arch-optimizer /
  legal-changelog-auditor prompts plus sandbox-native **`harness-doctor`** and
  **`adversarial-reviewer`**.
- **Harness adapters:** `sandbox subagents sync --harness opencode|cursor|all`
  (OpenCode frontmatter merge + Cursor stub generation);
  **`sandbox subagents materialize --package … --root …`** copies the manifest and
  missing prompts into sibling checkouts (`governance/subagents/` on digital-mailroom).
- **`sandbox subagents propagate`** + [`config/subagents/checkout-map.yaml`](config/subagents/checkout-map.yaml)
  — materialize + sync all mapped checkouts; monorepo hook
  [`scripts/monorepo/after_packages_sync.py`](scripts/monorepo/after_packages_sync.py)
  (wire via [`scripts/monorepo/INTEGRATION.md`](scripts/monorepo/INTEGRATION.md)).
- Docs: [`docs/subagents-family-sync.md`](docs/subagents-family-sync.md).
- Tests: `tests/test_subagents.py`.

## [0.2.0] - 2026-09-24

### Added — Modal/vLLM ↔ dojo cost-compare metrics parity (SAND-016)

- **`sandbox metrics compare --fixture`** scores the Grant-style local /
  Modal / API triple (`data/fixtures/serving/cost_compare.json`) through
  both sandbox `job.metrics.compare` and vendored
  `get_suite("local_vs_api")` / `compare_serving` (no GPU).
- Adapter `mailroom_sandbox.eval.serving_parity` converts `latency_ms` /
  `ttft_ms`, stamps champion token $ for `Qwen/Qwen3-8B`, and keeps
  `serving_kind=modal` out of the local bucket (`eval local_vs_api --from-log`
  now compares Modal↔API).
- Three-way `$/doc` aggregation uses 8 decimal places (4 dp previously
  rounded Grant token-proxy rates to 0).

### Added — full Hub corpus cache + per-class Modal samples (2026-09-24)

- **`sandbox datasets pull`** defaults to the full
  `Lucius-Morningstar/mailroom-dataset` `ground_truth` **train+test** pin
  (3,302 rows at `FAMILY_HF_REVISION`) under `data/cache/`. `--max-rows 50
  --split test` remains for tiny slices.
- **`sandbox datasets sample --per-class N`** draws 20/40/100+ per live
  class from that local JSONL (offline; merger_agreement ceiling is 152).
- Corpus loader accepts `split: all`. Class-bucket quotas above availability
  now hard-fail (same as nested sub_buckets). Template:
  `config/runs/examples/example-per-class.yaml`.

### Added — SAND-001 local SAND board prefix (2026-09-24)

- **Sandbox-isolated governance** uses prefix **`SAND-NNN`** on
  `governance/TASKS.md` (rules in `governance/README.md` +
  `governance/PREFIX.md`). Family **`DMR-*`** cards stay on
  llm-entity-extraction's MESSAGE_BOARD — do not open DMR cards on the
  local board.
- Legacy `SANDBOX-050-*` mission archived → epic `SAND-010` (+ sub-cards).
- Docs: `AGENTS.md`, `docs/setting-up/sister-repos.md`, `docs/modal/modal-doc-jobs.md` gate
  rows (`SAND-014`). Drift guard: `tests/test_governance_sand.py`.

### Added — DMR-078b requirements completeness (2026-09-24)

- **`[pipeline]` extra** now declares `aiosqlite` + `greenlet` (required for
  the vendored graph's default `sqlite+aiosqlite://` URL — DMR-067 left
  sqlalchemy alone) and PDF/page deps (`pypdf`, `pdfplumber`, `pillow`).
- **`requirements/`** mirrors of every pyproject extra (`base`, `dev`,
  `pipeline`, `deploy`, `observability`, `hf`, `notebooks`, `modal-job`,
  `all`) plus root `requirements.txt` → `requirements/dev.txt`. Generated by
  `scripts/sync_requirements.py` (`--check` for drift).
- **`deploy/modal_job.py`** `uv_pip_install` expanded to the specialist worker
  surface (dojo scoring + pipeline + observability) so Modal jobs boot with
  numpy/sqlalchemy/langchain/aiosqlite present.

### Added — DMR-078 Qwen Modal specialist posture + merger specialist (2026-09-24)

- **Per-doc-type Modal L4 runbooks** for all five `run-30-*-specialist.yaml`:
  concurrency / `cost_cap_usd` / `max_wall_seconds` sized by typical token
  length (correspondence/insurance c=5; corporate/contracts c=4; merger c=3).
  Source of truth: `job/specialist_posture.py` (also drives estimate-suite
  tables + overlay generation budgets).
- **Qwen/Qwen3-8B context-fit budgets** in `config/taxonomy.overlay.yaml`:
  specialist `max_tokens` / `max_input_chars` no longer advertise windows
  larger than L4 `max_model_len=16384` (contracts was 100k chars).
- **Runner abort guards:** `JobSpec.cost_cap_usd` + `max_wall_seconds` fail
  the run loud when wall×L4 $/hr or wall seconds exceed the pin.
- **`merger_agreement_specialist` plumbing** (issue #9 Phase 2): vendored
  upstream draft agent + schema/registry from llm-mailroom PR #64; sandbox
  taxonomy / components / eval registry / prompt sync / run-30 merger YAML
  now use the dedicated specialist (not `contracts_specialist` on MAUD).
- **`sandbox run benchmark-check`** enforces posture concurrency, task 1:1
  map, cost_cap, and max_wall for every run-30 specialist YAML.

### Added — DMR-077 two-operator specialist tracks (2026-09-23)

- **Suite manifests** under `config/runs/suites/`: `track-a` (contracts →
  corporate_records → correspondence), `track-b` (merger → insurance_claims),
  and `full` (single-operator five-run alternative). Separate Modal accounts
  via `SANDBOX_MODAL_PROFILE_TRACK_A` / `_TRACK_B` (Hermes default on A only).
- **CLI:** `sandbox run suite --suite track-a|track-b|full` (runbook /
  `--print-loop` / `--check` / `--execute`); `sandbox metrics estimate-suite
  --suite …`; `sandbox run benchmark-check --suite …`.
- **Docs:** two-operator runbook in `docs/modal/benchmark-l4.md` + `.env.example`
  profile-name placeholders (no secrets). Spend posture unchanged: scaledown
  120, c=4, L4, max_containers=1, warm-once per track.

### Added — DMR-076 cut-spend specialist suite (2026-09-23)

- **Attended scaledown 120s** pinned in all five `run-30-*-specialist.yaml`
  (`engine.modal.scaledown_seconds`) + deploy default
  `MODAL_VLLM_SCALEDOWN_SECONDS=120`; restore **600** for unattended/overnight.
- **Loud warm-once headers** on every run-30 YAML + `docs/modal/benchmark-l4.md`
  (one `sandbox-vllm` app through all five runs; teardown only after the fifth).
- **`sandbox run benchmark-check`** enforces spend posture: scaledown=120,
  min_containers=0, max_containers=1, concurrency=4, limit=30, DMR-074 local
  prompt pins; AWQ accepted as optional path (warning), bf16 remains default.
- **`sandbox metrics estimate-suite`** / extrapolate defaults align to 120 so
  pre-flight $ matches the attended suite YAMLs.
- AWQ stays optional (`sandbox modal-matrix env Qwen/Qwen3-8B-AWQ`) — DMR-068
  accuracy gate not green for flipping the default bf16 suite.

### Added — DMR-061 live-or-loud sweep (2026-09-14)

- **Vendored pins (DMR-057, now reflected in this changelog):** llm-mailroom
  **v0.7.1** (`2a212e76`, `vendor/llm-mailroom/VENDOR.md`), llm-dojo-scoring
  **v0.15.0** (`9db1417b`, vendor snapshot refreshed with the emitter
  counters in the same commit so the hub#62 drift guard stays byte-identical);
  the corpus pin is **v9 `46a4d3c2`** (`FAMILY_HF_REVISION`).
- **Tracing loudness:** `eval/tracing.py` now warns on every silent-degrade
  path (dojo constants fallback, mailroom-setup/SDK unavailability,
  `propagate_attributes` failure) and COUNTS lost score emissions + failed
  flushes (`tracing_failure_counts()`).
- **Engine-base resolution:** a typo'd run-spec profile now raises with the
  available list; `modal-vllm` without `MODAL_WORKSPACE` raises instead of
  emitting a literal `<workspace>` URL.
- **hub#41 double-fire guard:** a malformed `fired_at` FAILS CLOSED (refuses
  the re-fire) instead of silently bypassing the cooldown.
- **Honest provenance:** a live intake failure falls back AND labels the row
  `offline_fallback=True`; `_live_intake` never re-labels a degraded output
  as a real prediction.
- **No unknown-as-ok:** a live pipeline returning no `doc_type` raises on
  the sorter + pipeline + job-runner paths (was scored `ok=True` "unknown").
- **Corrupt GT is loud:** malformed `expected_fields` JSON raises with row
  context in `datasets.py` + `corpus.py` (was silently scored as empty).
- **Methodology transparency:** `eval/scoring.py` stamps `scoring_method`
  and warns on every silent suite→generic fallback; the chained composite
  refuses a 0-sentinel when either half produced no scores.
- **Failure counters with test seams:** `job/otel.py` (OTLP flush errors),
  `job/metrics.py` (dojo cost fallback), `job/remote.py` (state-Dict/lock
  probes) all log instead of swallowing; `tracing_failure_counts()` and
  `llm_dojo_scoring.emitter.sink_failure_counts()` are test-pinned.
- **CLI/deploy:** `sandbox health` rc=1 on probe failure is pinned; the
  visualizer pull rc is honored; `tunnel down` raises on a failed kill;
  metrics compare refuses a run without a lock; compose vllm gained a
  bearer-aware healthcheck; HTCondor `.sub` files opt into
  `notification = Error`; `run_batch_eval.sh` writes the failing rc into
  `run.log` and fixes the elapsed-time off-by-one; `modal_job.py` re-raises
  when the terminal failure state cannot be published (the CLI watch would
  stall forever).
- **New tests:** `tests/test_live_or_loud_sweep.py` (13 pins) + the
  vendored-family counter pins in the dojo emitter suite.

### Planned (not yet shipped — hub#54)

- **DMR-059 — Modal doc-pipeline job queue plan**: `docs/modal/modal-doc-jobs.md`
  designs a `sandbox-doc-jobs` Modal app modeled on the Modal docs tutorial
  (`09_job_queues/doc_ocr_jobs.py`) — a CPU-side document job queue whose LLM
  is the already-deployed `sandbox-vllm` endpoint: bytes staged on a
  `sandbox-doc-inbox` Volume, `extract_text` (pdf/image → text via the
  vendored transcriber surface) + `process_document` (connected mailroom
  graph through `DEFAULT_PROVIDER=vllm`) stages, `sandbox-doc-state` Dict
  progress mirror, `modal run` local-entrypoint smoke, and
  `Function.from_name(...).spawn(...)` consumption. Three phases (mock
  smoke → live vLLM → CLI). **Not yet shipped** — the card is still
  `in_progress` on the board and neither `docs/modal/modal-doc-jobs.md` nor
  `.opencode/agents/` now ships the coding subagent roster (SAND-017); Modal
  doc-jobs code remains unshipped — this entry documents the queue plan only.

### Added

- **DMR-066 — subclass-stratified sorter evals + loud strata guards (SHIPPED
  2026-09-16)**: the DMR-063 50-run exposed a stratification no-op —
  `expected_doc_class` is constant `contract` in the joined `ground_truth`,
  so the legacy `strata.expected` FILTER silently truncated to contract×N.
  New `strata.field`/`values`/`counts` form draws per-stratum sub-seeded
  buckets over any row field (`expected_subclass` default) with
  class-aware normalized matching (raw CUAD surfaces like
  `License_Agreements` match catalog tokens like `license` — via the vendored
  dojo normalizer, both sides normalized per-row doc class, with an
  `other`-fallback guard that stopped cross-class candidate inflation).
  Preflight now hard-fails (exit 1) on: requested strata absent from the
  data, a constant stratum field with >1 requested value (the run-50 trap,
  named), and a draw/limit that drops a requested stratum; the lock records
  `strata_actual` (drawn distribution) so a lock proves what was drawn.
  Delivered: `config/runs/legacy/run-50-subclass.yaml` (13 strata · Service 8, …
  Manufacturing 2 · 50 rows; `preflight --force` locked with `strata_actual`
  matching exactly; old generation archived per DMR-049), spec validation
  (unknown keys / counts length / positive ints), 6 new corpus tests + 3
  spec tests. 271 passed / 3 skipped.

- **DMR-067 — sqlalchemy restored to the live pipeline surface (SHIPPED
  2026-09-16)**: added `sqlalchemy>=2.0` to the sandbox `[pipeline]` extra —
  the vendored graph's `storage.catalog` / `storage.audit_log` imports
  failed without it (every live doc logged `catalog_upsert_error` /
  `latest_audit_hash_fetch_failed`, loud but non-fatal, and the agent roster
  degraded to the static 18 via `vendored llm.prompts not importable`).
  Verified: `sqlalchemy 2.0.54` installed; `storage.catalog`,
  `storage.audit_log`, `llm.prompts` all importable from the vendored tree.
  One live sorter row with the full surface is the designated DMR-063
  300-run preflight step.

- **DMR-068 — L4 scale-matrix protocol + exemplar specs (READY, runs
  pending spend approval)**: `docs/scale-matrix.md` — run-50 analysis
  (8.7–13.9 tok/s/engine vs the ~18 tok/s fp16 HBM ceiling on L4; scheduler
  caps non-binding below ~2048 decodes; chunked prefill on by default at
  v0.29.0), the AWQ lever (v0.29.0 docs mark AWQ ✅ Ada; official Qwen3-8B
  benchmark 1.76× decode; `Qwen/Qwen3-8B-AWQ` drop-in; accuracy gate
  ≥98 %), fixed-doc-size fixture plan (2k/6k/12k char buckets from run-50
  rows), and a 7-cell matrix {1,2,4}×L4 × concurrency {8,16,32} + AWQ cell —
  est. **$13.08 ≤ $15** at $0.80/GPU-hr, teardown per cell via
  `deploy/teardown_vllm.sh`, measurement contract (items.jsonl primary,
  engine `/metrics` + log windows secondary, billing per cell). Exemplar
  specs `config/runs/scale/scale-c1-4xl4-c16.yaml` (bf16 baseline) +
  `scale-d1-awq-4xl4-c16.yaml` (quant-only delta); fleet pinning via
  `MODAL_VLLM_MIN_CONTAINERS=4` (already supported by the deploy app).

- **DMR-063 — 50-doc Modal vLLM scale-out run + teardown safeguards (SHIPPED
  2026-09-16)**: `config/runs/legacy/run-50-modal-hf.yaml` — 50 contract-class rows
  (19 subclasses; Hub pinned revision), concurrency 16, `max_containers: 4`
  (2–3 warm L4s), `scaledown_seconds: 600`. Result: **49/50 = 98.0 %**,
  0 run errors, 0 timeouts; one out-of-set misclassification
  (contract → corporate_record). Per-item E2E mean 971 s (median 883, p90
  1520, max 2054 — queueing-dominated at 16-way); aggregate ≈ 0.65 docs/min;
  engine generation 8.7–13.9 tok/s per L4, prefix-cache hits 56–58 %, KV ≤ 30
  %; Modal metered **$7.98 → credited → billed $0.00** (≈ $0.16/doc metered).
  **Timeout fix**: vendored `llm_call_timeout_seconds` 120 → 300 s (the
  vendored taxonomy is the live source — the base file is shadowed; both kept
  in sync) — killed the `APITimeoutError` retry storms (attempt A cancelled at
  cursor 0). **Driver resilience proven**: orphaned runner loss at cursor 31 →
  `sandbox run resume` re-attached and drove 50/50 to `done` with all items
  intact (checkpoint/`items.jsonl` self-heal). **Teardown**: new
  `deploy/teardown_vllm.sh` (stop → verify zero deployments → volumes persist
  → billing best-effort; TTY-aware `--yes` for headless) + README guard
  matrix + `TestTeardownScript`. Full breakdown: `reports/RUN50-MODAL-HF-REPORT.md`.
  Findings spawned: strata no-op (expected_doc_class constant → 19-subclass
  coverage instead of 3-class strata), missing `sqlalchemy` in the pipeline
  extra (loud non-fatal catalog/audit degrade), scale-out flatness at 4×L4.
  262 passed / 3 skipped.

- **DMR-062 — Modal HF-secret wiring + v0.29.0 live parity pilot (SHIPPED
  2026-09-16)**: the deploy app now attaches the Modal named secret
  `huggingface-secret` (`Secret.from_name(..., required_keys=["HF_TOKEN"])`,
  override via `MODAL_HF_SECRET_NAME`) to BOTH `serve` and `download_model`;
  `HF_TOKEN` was dropped from the local-env knob secret (Modal applies
  function secrets in list order — last wins — so a local `HF_TOKEN` would
  have silently overridden the named secret). vLLM pinned to **v0.29.0**
  across Modal + local compose + HTCondor after the live parity pilot
  passed (Qwen/Qwen3-8B L4: 7/7 sorter rows, F1=1.0, `json_object` verified,
  `serving_kind=modal` records; vllm-specialist docs-verified the v0.29.0
  flag set). Preflight engine probe fixed: it appended `/v1/models` to a
  base that already carries the `/v1` seam (`.../v1/v1/models` → live 404);
  the probe now normalizes (pinned by `test_engine_probe_url_seam_normalizes_v1_suffix`).
  `test_vendor` stale-pin scan no longer trips on pip-installed venv wheels.
  First live pilot spec: `config/runs/examples/pilot-sorter-modal-hf.yaml`.
  260 passed / 3 skipped.

- **DMR-058 — full CLI verification sweep + quickstart**: every `sandbox`
  command exercised against a fresh in-repo `.venv` (offline + live Hub
  paths); `docs/setting-up/QUICKSTART.md` is the verified full command reference
  (install, flag-placement rules, workflows, exit codes, troubleshooting).
  New extras: `[pipeline]` (vendored langchain stack for the legalbench
  suite / live mailroom paths), `[dev]` now carries the Hub client
  (`huggingface_hub`, `pyarrow`); the vendored dojo runtime surface
  (`numpy`, `pandas`, `matplotlib`, `openpyxl`) moved into BASE deps so a
  clean `pip install .` boots the CLI. Clean degradations (no tracebacks):
  compose/ollama/ssh failures (`up`/`down`/`pull-models`), `datasets pull`
  without the Hub client (points at `[hf]`/`[dev]`), `legalbench` loud
  guards (suite without `--n`, missing corpus, missing `[pipeline]`), and
  Modal job mode without the SDK (points at `[deploy]`). `sandbox fetch-deps`
  is now layout-aware and non-destructive (the llm-dojo-scoring clone ships
  the package at the repo root; the old `work/name` fallback half-wiped the
  tracked tree before crashing). `run status/resume/cancel --config`
  resolves the embedded `run_id` (previously demanded `--run-id` even with a
  config). `config/runs/examples/example.yaml` fixture path is CWD-relative again.
  ~6 new network-free tests (230 passed / 1 skipped).

- **HUB-026 — remote-serving integration completeness**: `vllm-remote`
  profile with a `tunnel:` block + `mailroom_sandbox/tunnel.py`
  (network-free argv builders, pidfile lifecycle, double-forward guard) +
  `sandbox tunnel plan/up/status/down`; `deploy/conda/environment.yml`
  (CPU-first portable env, vLLM deliberately external);
  `deploy/htcondor/` CHTC job templates — batch eval (in-job vLLM, works
  on the shared GPU Lab where `condor_ssh_to_job` is unavailable) and an
  owned-GPU server variant tied to the tunnel profile
  (`docs/setting-up/remote-serving.md` is the overview).
- **Modal deploy hardening (SDK 1.5.5 / vLLM v0.28.0)**: `deploy/modal_vllm.py`
  now pins the Modal SDK (`modal==1.5.5` in the `[deploy]` extra), defaults to
  `vllm/vllm-openai:v0.28.0` (matching the local compose pin), caches vLLM
  JIT/CUDA-graph artifacts in a `sandbox-vllm-cache` Volume, pre-warms weights
  with `modal run deploy/modal_vllm.py::download_model` (HF cache Volume +
  explicit commit), tags the app for cost allocation, and bounds cost with
  `max_containers=1` / `min_containers=0` plus configurable scaledown and
  startup timeouts (`MODAL_VLLM_SCALEDOWN_SECONDS`,
  `MODAL_VLLM_MAX_CONTAINERS`, `MODAL_VLLM_MIN_CONTAINERS`,
  `MODAL_VLLM_STARTUP_TIMEOUT_SECONDS`) and an optional
  `MODAL_VLLM_REVISION` pin. New network-free contract tests
  (`tests/test_modal_vllm.py`) pin the argv builder, bearer env mapping,
  secret construction, cost guards, and the SDK/image pins. Docs:
  `deploy/README.md` (deploy → verify → cost → security → troubleshooting),
  `.cursor/skills/modal/SKILL.md`, `docs/setting-up/remote-serving.md`,
  `config/.env.example`.

- **DMR-027 — sandbox job CLI (`sandbox run`)**: a spec-driven, locked,
  resumable eval runner over vLLM + Modal + an OTEL trace sink. New
  `src/mailroom_sandbox/job/` (`spec`, `checkpoint`, `preflight`, `runner`,
  `otel`, `metrics`, `remote`), `src/mailroom_sandbox/corpus.py`
  (revision-pinned HF full-corpus/subset loader: default+ground_truth parquet
  join, `content_sha256` integrity, deterministic strata/limit selection,
  offline `file://` path), and `src/mailroom_sandbox/prompt_registry.py`
  (every pipeline agent's prompt: local variants + Langfuse integer-version
  pins + code default; `sorter`/`contracts_specialist` Family-B
  `PROMPT_VERSIONS` injection). Preflight resolves/validates all domains,
  prepares the subset, and writes an immutable `spec.lock.json` (drift
  refused on resume unless `--force`); the runner checkpoints per item
  (`items.jsonl` source of truth, atomic `checkpoint.json`, torn-tail
  self-healing) and resumes after pause/failure. `sandbox run
  preflight|start|status|resume|cancel|list`, `sandbox prompts list|show`,
  `sandbox metrics compare` (local/Modal/API buckets, deltas vs API, dojo
  pairwise comparisons). Modal mode: `deploy/modal_job.py` worker
  (`sandbox-runs` Volume + `sandbox-job-state` Dict polling, resume via
  FunctionCall re-attach/re-spawn lease). Deps: `observability` +
  `opentelemetry-sdk`/`opentelemetry-exporter-otlp-proto-http`; new `hf`
  extra (`huggingface_hub`, `pyarrow`). Docs: `docs/jobs.md`. ~52 new
  network-free tests.

## [0.1.0] - 2026-09-10

### Changed

- **HUB-015 — reduced agent profile + current-pipeline alignment**: the
  **reporter agent is retired** (moved to `retired_agents`; the compile stage
  is the computational procedural `compile_report` node — deterministic
  matter-record assembly, **zero LLM calls**, and the sandbox eval no longer
  acquires an LLM client for it). **Reviewers stay enabled.** Sandbox surfaces
  aligned to llm-mailroom **v0.6.0** (`fetch-deps`, docs) and dojo **v0.12.2**.
  HF fixtures (`data/fixtures/hf/docclass_mini.jsonl`) now carry full
  docclass-merged ground-truth targets: corpus-strata `expected_subclass` for
  all 5 doc types + `expected_fields` from the 27-key GT schema (correspondence
  intent + provenance; insurance claim entities), propagated into every eval
  row. Dockerfile gains a non-root user + HEALTHCHECK; all four `:latest`
  compose images pinned (ollama 0.33.2, vllm v0.28.0, phoenix version-20.4.0,
  minio RELEASE.2025-09-07…).

### Fixed

- **Modal SDK 1.5.5 removed `Secret.from_local`** — `deploy/modal_vllm.py`
  used it and would fail at import/deploy. Knobs are now built with
  `Secret.from_dict`, which skips absent keys, preserving the optional
  `HF_TOKEN` / `MODAL_VLLM_API_TOKEN` contract (`from_local_environ` raises
  on missing names). Regression-guarded by `tests/test_modal_vllm.py`.

### Added

- Local-first LLM-Mailroom experiment sandbox: provider profiles (Ollama, vLLM
  local, Modal vLLM, llama.cpp, LM Studio, opt-in OpenRouter), taxonomy overlay
  with OpenRouter→local model map, Docker Compose (Phoenix / Ollama / vLLM /
  llama.cpp / optional Langfuse), Modal deploy wrapper (`sandbox-vllm`),
  fixture catalog + tiny HF / LegalBench slices, eval runners (sorter /
  extract / chained / pipeline / legalbench), provider×model×prompt matrix,
  llm-dojo-scoring emission, Langfuse v4 `document-pipeline` tracing, append-only
  `reports/experiment_log.jsonl`, and a `sandbox` CLI.
- Isolated evals for every live agent/node (`sandbox eval judge`,
  `contracts_specialist`, `arbiter`, …) plus connected pipeline scoring
  (class / stage / extraction / routing).
- Per-agent overlay knobs and `sandbox cutover --agent-model NAME=tag`.
- Langfuse 3 compose (web + worker + postgres + clickhouse + redis + minio)
  with headless `LANGFUSE_INIT_*` keys matching The-Mailroom filters.
- Scoring + pipeline are **vendored snapshots** (DMR-057): `llm-dojo-scoring
  @ v0.12.2` (local vs API serving table + scorecard + cost from
  [#10](https://github.com/Exios66/llm-dojo-scoring/pull/10); aligned with
  llm-mailroom v0.6.0's own pin) and llm-mailroom **v0.6.0** ship under
  `vendor/` (tracked); `sandbox fetch-deps` refreshes them from the pinned
  tags — the `[pipeline]` extra is gone.
- `sandbox eval local_vs_api --mock` compares offline (Ollama/vLLM) vs API-key
  (OpenRouter) serving metrics via `get_suite("local_vs_api")` without needing
  `OPENROUTER_API_KEY`. The comparison returns a full T0/T1 **table** (missing
  stays `None`), a **scorecard** with identity tags, and token × price-table
  **cost**. Local and API values emit as separate scorecards (`run_id:local` /
  `run_id:api`). Sorter T0 stays `accuracy` + `f1_macro`; TTFT is never
  inferred from e2e / n_tokens. GPU/KV/VRAM stay `None` on API-key records.
- Offline Docker image (`deploy/Dockerfile` → `mailroom-sandbox:offline`) and
  Compose profile `jupyter` for Jupyter Lab on `:8888`, plus dedicated notebooks
  (`notebooks/01`–`03`) and `sandbox datasets prepare` to load/clean/write
  fixtures under `data/runtime/prepared/`.
- Project Agent Skills under `.cursor/skills/` for tool selection: router plus
  Langfuse, Braintrust, Apache Phoenix, Ollama, Modal, and Hugging Face
  (offline-first Hub usage).

### Fixed

- ClickHouse compose healthcheck no longer passes database credentials
  as CLI flags (GitGuardian generic CLI secret detector).
