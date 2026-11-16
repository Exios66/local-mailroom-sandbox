# Production Slice Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A gate that decides offline whether a CLI slice run of the mailroom dataset passes the
production bars (≤ 5% review, ≤ 2% wrong archives, no crashes, fully auditable). It ships with
held-out nested slice configs, cause buckets and threshold evidence, and the two known
mechanism bugs are diagnosed.

**Architecture:** `sandbox run gate` reads a finished run directory and writes `gate.json` /
`gate.md`. It needs no LLM.
- **Scoring** reuses `job/pair_report.py`: the Dojo aggregate, with the templated fields
  dropped.
- **Cause buckets** come from `items.jsonl` / `nodes.jsonl`.
- **The audit check** reads the local span mirror and the hash archive.
- **Slice configs** draw nested, per-class seeded prefixes, after excluding every
  tuning-run document id listed in a committed file.

**Tech Stack:** Python 3.11+, pydantic v2 (`RunSpec`), argparse CLI (`src/mailroom_sandbox/cli.py`),
pytest, the vendored Dojo suite (`mailroom_sandbox.eval.scoring`).

**Spec:** `docs/superpowers/specs/2026-11-16-production-slice-gate-design.md`

## Global Constraints

- **Bars:**
  - quality bar 0.90 on labelled fields;
  - wrong-archive rate ≤ 0.02, pooled over the gated classes;
  - review rate ≤ 0.05, pooled over the gated classes;
  - 0 run errors and 0 `judge_error`.
- **Gated classes:** `contract`, `corporate_record`, `correspondence`, `insurance_claim`.
  `merger_agreement` is reported but never gated.
- **Per-class bars** apply only from slice size 500 on. Below that, per-class rates are
  diagnostic.
- **Minimum labelled fields** for a document to be scorable: 2.
- **Templated fields** dropped before scoring: `job.pair_report.TEMPLATED_FIELDS`.
- **Every production slice config sets** `job.blind_routing: true`, `dataset.interim_labels: true`,
  the r3 prompt/agent/confidence/reviewer blocks, `job.max_wall_seconds` and
  `job.api_cost_cap_usd`.
- **Dataset:** `Lucius-Morningstar/mailroom-dataset`, `ground_truth`, revision
  `bc9eab280044befb51e19dda3071d290a8677f42`, `require_task_gt: true`.
- **Never** edit `vendor/**` or `requirements/*.txt` by hand. Never launch paid runs; a human runs
  `sandbox run start`.
- **Local checks:** explicit test files, `-n 0 --no-cov`, with `env -u CLAUDECODE PYTHONPATH=$PWD/src`;
  lint with `uvx ruff check src tests scripts deploy reports`. Coverage floor 84 (hosted CI).
- **Worktree:** a `git worktree` of this repo (`mailroom-slice-gate` beside the main checkout), branch `feat/slice-gate`
  (stacked on #303). Verify the branch before each commit, and push only with an explicit
  refspec.

## Review Focus

1. **A run interrupted or resumed mid-slice:** the gate must count only the latest record per
   document, never a duplicate. Documents in `dataset.jsonl` with no item count as crashes, and
   the slice FAILs rather than passing on fewer documents. *(Tests in Task 3.)*
2. **A document archived under the wrong class:** it is scored against its expected class and
   counts as a wrong archive with cause `classification`, never as unscorable. *(Test in
   Task 4.)*
3. **A slice with no gated documents, or a gated class with 0 archived documents:** rates are
   `None`, not a division by zero. The verdict FAILs with "no gated documents" rather than
   PASS. *(Test in Task 3.)*
4. **Spans missing for some documents** (a crashed trace writer, `trace.sink` changed): the
   audit check names the documents and FAILs the slice. A run with no span file at all FAILs
   with one clear reason. *(Test in Task 5.)*
5. **The excluded-ids file edited between two slices:** the lock hash changes and preflight of
   a resumed run refuses. Excluded ids that are not in the dataset are ignored, but counted in
   the lock report. *(Test in Task 1.)*

---

### Task 1: Exclude tuning documents from the draw (`dataset.exclude_ids_file`)

**Files:**
- Modify: `src/mailroom_sandbox/job/spec.py` (`DatasetSpec`, `spec_core`)
- Modify: `src/mailroom_sandbox/corpus.py` (`select_rows`)
- Modify: the preflight path that calls `select_rows` (`src/mailroom_sandbox/job/preflight.py`), so
  that it passes the ids and reports the excluded count in the dataset check
- Test: `tests/test_exclude_ids.py`

**Interfaces:**
- Produces:
  - `DatasetSpec.exclude_ids_file: str | None = None`: a repo-relative path to a text file with
    one document `id` per line; `#` comments and blank lines are ignored.
  - `corpus.read_id_list(path: Path) -> list[str]`
  - `corpus.select_rows(..., exclude_ids: set[str] | None = None)`: rows whose `id` is in the
    set are dropped **before** any stratified draw.
  - `spec_core` hashes `{"exclude_ids_sha256": <sha256 of file bytes>}` in the dataset block,
    only when the field is set. A set field whose file is missing raises `ValueError` at
    preflight.

- [ ] **Step 1: Write the failing tests** in `tests/test_exclude_ids.py`:
  - `test_excluded_ids_are_never_drawn`: 30 synthetic rows across two classes, exclude 5 ids, a
    bucket draw of 10 per class → no excluded id in the result.
  - `test_draws_stay_nested_under_exclusion`: same rows and exclusions, seed 7. The ids of the
    `{count: 4}` draw ⊂ the `{count: 9}` draw, for each class.
  - `test_exclude_file_is_hashed_only_when_set`: two specs with different file contents →
    different `core_hash`; unset → no `exclude_ids_sha256` key.
  - `test_unknown_excluded_ids_are_ignored_and_counted`: excluding ids absent from the rows does
    not raise, and preflight's dataset detail reports `excluded=<n matched>/<n listed>`.
  - `test_missing_exclude_file_fails_preflight`: `pytest.raises(ValueError, match="exclude_ids_file")`.
- [ ] **Step 2: Run** `env -u CLAUDECODE PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q -n 0 --no-cov tests/test_exclude_ids.py`.
  Expected: FAIL (unknown field / unexpected keyword).
- [ ] **Step 3: Implement** the field, `read_id_list`, the pre-draw filter in `select_rows`, the
  hash in `spec_core`, and the preflight wiring.
- [ ] **Step 4: Run** the new file plus `tests/test_job_spec.py tests/test_dataset_registry.py`.
  Expected: PASS.
- [ ] **Step 5: Commit** `feat(dataset): exclude_ids_file drops listed documents before the draw`.

### Task 2: Committed held-out exclusion list

**Files:**
- Create: `scripts/build_excluded_ids.py`
- Create: `config/production/excluded-ids.txt` (generated, committed)
- Test: `tests/test_build_excluded_ids.py`

**Interfaces:**
- Consumes: the `corpus.read_id_list` format from Task 1.
- Produces: `build(run_dirs: list[Path]) -> list[str]` (sorted unique `id`s from each run's
  `dataset.jsonl`) and a CLI:
  `python scripts/build_excluded_ids.py --runs-dir <dir> --run <id>... --out <file> [--check]`.
  The file header lists each source run id and its row count, as `#` lines. `--check` exits 1
  when the file differs from a rebuild.

- [ ] **Step 1: Write the failing tests:**
  - `test_build_unions_and_sorts_ids`: two fake run dirs with overlapping ids → sorted, unique.
  - `test_header_names_each_source`: the header has `# <run_id>: <n> rows` for each run.
  - `test_check_detects_drift`: `--check` returns 1 after one id is removed from the file.
- [ ] **Step 2: Run them.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the script.
- [ ] **Step 4: Generate the list** from every tuning run with a `dataset.jsonl`.
  - **Runs:** `pipeline-qwen-flash-25`, `-fit`, `-fit-r2`, `-fit-r3`, `-e1-contract-control`,
    `-e1-contract-chunk`, `-e2-corporate-control`, `-e2-corporate-judge`, `-e2-corporate-rejudge`,
    `-e3-mix-control`.
  - **Where they live:** both `~/Downloads/local-mailroom-sandbox/data/runtime/runs` and this
    worktree's `data/runtime/runs`, so use one `--runs-dir` per root and repeat `--run`.
  - **Also add** any prompt-tuning draw JSONL under `data/datasets/` that a lineage file in
    `config/prompts/` names as a tuning set. Record each one in the header.
- [ ] **Step 5: Run** the tests plus `python scripts/build_excluded_ids.py ... --check`.
  Expected: PASS, exit 0.
- [ ] **Step 6: Commit** `feat(production): held-out exclusion list of tuning documents`.

### Task 3: Gate core: bars, per-document status and slice verdict

**Files:**
- Create: `config/production/bars.yaml`
- Create: `src/mailroom_sandbox/job/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes:
  - `pair_report.load_arm(run_dir) -> {doc_id: {"row", "item", "nodes"}}`;
  - `pair_report._score(row, pred) -> float | None`;
  - `pair_report.without_fields(row, drop)`;
  - `pair_report.TEMPLATED_FIELDS`;
  - `mailroom_sandbox.eval.extraction_scope.scope_extraction_pair(doc_type, predicted, expected)`.
- Produces:
  - `@dataclass(frozen=True) class Bars`, with these fields and defaults:
    - `quality: float = 0.90`
    - `wrong_archive_max: float = 0.02`
    - `review_max: float = 0.05`
    - `gated: tuple[str, ...] = ("contract", "corporate_record", "correspondence", "insurance_claim")`
    - `min_labelled: int = 2`
    - `per_class_from_n: int = 500`
  - `load_bars(path: Path | None = None) -> Bars` (default `config/production/bars.yaml`).
  - `labelled_count(row: Mapping, doc_class: str) -> int`: the number of non-empty expected
    values left after `scope_extraction_pair` and after the templated fields are dropped.
  - `doc_status(doc: Mapping, bars: Bars) -> dict` with these keys:
    - `id`, `class`, `stage` (`archived` | `review` | `crashed`);
    - `score: float | None`, `scorable: bool`;
    - `outcome`: one of `correct_archive`, `wrong_archive`, `review`, `unscorable_archive`, `crashed`;
    - `tokens`.
  - `gate_report(run_dir: Path, bars: Bars) -> dict` with these keys:
    - `run_id`, `n`, `bars` (as a dict);
    - `classes: {cls: {n, review_rate, wrong_archive_rate, correct_archive_rate, unscorable, tokens_per_doc, gated}}`;
    - `pooled: {review_rate, wrong_archive_rate, review_upper95, wrong_archive_upper95, crashes, judge_errors}`;
    - `verdict: {"pass": bool, "reasons": [str]}`;
    - `docs: [doc_status...]`.
  - **Rate definitions:**
    - review rate = reviews / documents;
    - wrong-archive rate = wrong archives / scorable archives;
    - Wilson 95% upper bounds;
    - a `None` rate when its denominator is 0.

- [ ] **Step 1: Write the failing tests.** Reuse the `_arm` helper pattern from
  `tests/test_pair_report.py` and monkeypatch `gate._score`.
  - `test_outcomes_follow_score_and_stage`: archived 0.95 → `correct_archive`; archived 0.6 →
    `wrong_archive`; `stage: review` → `review`; archived with 1 labelled field →
    `unscorable_archive`.
  - `test_pooled_rates_and_pass`: 40 gated documents, 1 review, 0 wrong →
    `review_rate == 0.025`, `verdict["pass"] is True`.
  - `test_wrong_archive_bar_fails`: 1 wrong of 30 scorable archives (0.033) → pass False,
    reasons contain `"wrong_archive_rate 0.033 > 0.02"`.
  - `test_mergers_are_reported_not_gated`: 5 merger wrong archives → `classes["merger_agreement"]["gated"] is False`,
    pooled rates unchanged, pass True.
  - `test_per_class_bar_applies_from_500`: n = 120 with one class at 0.05 wrong → pass decided
    by the pooled rate only; the same data with `per_class_from_n=100` → pass False with a
    class-named reason.
  - `test_missing_items_are_crashes_and_fail` (Review Focus 1): a dataset row without an item →
    `stage == "crashed"`, `pooled["crashes"] == 1`, pass False.
  - `test_duplicate_items_keep_latest` (Review Focus 1): two items for one document → it is
    counted once, from the last line.
  - `test_judge_error_fails`: an item whose `review_causes` contains `judge_error` →
    `pooled["judge_errors"] == 1`, pass False.
  - `test_no_gated_documents_fails` (Review Focus 3): only mergers → rates `None`, pass False,
    reason `"no gated documents"`.
- [ ] **Step 2: Run** `tests/test_gate.py`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `bars.yaml` (the Global Constraints values) and `gate.py`.
  `pair_report.load_arm` already keeps the last item per id via its dict. Crashes are the
  `dataset.jsonl` ids missing from `items.jsonl`, or items with `error` set.
- [ ] **Step 4: Run** `tests/test_gate.py tests/test_pair_report.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(gate): slice bars, per-document outcomes and pooled verdict`.

### Task 4: Cause buckets

**Files:**
- Create: `src/mailroom_sandbox/job/gate_causes.py`
- Modify: `src/mailroom_sandbox/job/gate.py` (attach `cause` to every `review`, `wrong_archive` and
  `crashed` status, and add `buckets` to the report)
- Test: `tests/test_gate_causes.py`

**Interfaces:**
- Consumes: the `doc_status` dicts and the `load_arm` doc records (`item["pred"]["review_causes"]`,
  `item["pred"]["doc_type"]`, `nodes`) from Task 3.
- Produces:
  - `primary_cause(doc: Mapping, status: Mapping) -> str`, with this precedence:
    1. `mechanism:<x>`, for `judge_error`, `crashed` or `transient`;
    2. `classification:<x>`, for `wrong_class`, `reviewer_unknown`, `reviewer_disagreement` or
       `arbiter_escalated`;
    3. `judge:<x>`, for `partial_exhausted` or `judge_rejected`;
    4. `extraction:<x>`, for `missing_field`, `wrong_value`, `out_of_enum` or `date_format`;
    5. `label_suspect`.
  - `extraction_miss(row: Mapping, pred: Mapping) -> str`: from the per-field comparison of the
    scoped expected and predicted values. The type of the lowest-scoring labelled field:
    - empty prediction → `missing_field`;
    - a value outside the Dojo enum for that field → `out_of_enum`;
    - a date-typed field whose value fails ISO parsing → `date_format`;
    - otherwise → `wrong_value`.
  - `label_suspect(row, pred, field) -> bool`: the lowest field's label is heuristic
    (`intent_source == "heuristic"` for intent) **and** the predicted value appears verbatim in
    `row["doc_text"]`.
  - `gate_report(...)["buckets"]`: `{cause: {"count": int, "docs": [{"id", "archive", "trace_id"}]}}`,
    sorted by count, descending.

- [ ] **Step 1: Write the failing tests:**
  - `test_precedence_mechanism_beats_judge`: causes `["judge_error", "judge_partial"]` →
    `mechanism:judge_error`.
  - `test_reviewer_unknown`: `reviewer_doc_type == "unknown"` → `classification:reviewer_unknown`.
  - `test_wrong_class_archive` (Review Focus 2): archived with `doc_type != expected_doc_class` →
    `classification:wrong_class`, and outcome `wrong_archive`, not `unscorable_archive`.
  - `test_partial_exhausted`: causes `["judge_partial", "retries_exhausted"]` → `judge:partial_exhausted`.
  - `test_extraction_out_of_enum`: corporate `record_type: "indenture"` against label `other` →
    `extraction:out_of_enum`.
  - `test_label_suspect`: heuristic intent label `governance_rules`, prediction `investor_rights`,
    and "investor rights" present in `doc_text` → `label_suspect`.
  - `test_buckets_sorted_with_audit_links`: the report's buckets are ordered by count and every
    doc entry has `archive` and `trace_id` keys. Task 5 fills their values.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `gate_causes.py` and wire it into `gate_report`. Field enums come from
  the vendored Dojo schemas through `suite_for_doc_type(cls).field_types`, whose enum metadata the
  implementer inspects. A field with no enum metadata never yields `out_of_enum`.
- [ ] **Step 4: Run** `tests/test_gate_causes.py tests/test_gate.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(gate): one primary cause per review and wrong archive`.

### Task 5: Audit-trail check (spans, node log, hash archive)

**Files:**
- Create: `src/mailroom_sandbox/job/gate_audit.py`
- Modify: `src/mailroom_sandbox/job/gate.py` (fill `archive` / `trace_id`; add `audit` to the
  report; audit failures add verdict reasons)
- Test: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes:
  - the run's `spec.lock.json` (`run_id`, trace path);
  - `data/traces/<run_id>.spans.jsonl.gz`, one JSON span per line, with
    `attributes.item_id` and `trace_id`;
  - `nodes.jsonl`;
  - the archive root `data/archive/`. Its directory is
    `SANDBOX-sandbox_pipeline_<run_id>-DOC-<hash>` for a document id `DOC-<hash>`, and holds a
    `<class>/` subdirectory.
- Produces:
  - `audit_trail(run_dir: Path, doc_ids: list[str], archived: set[str], *, traces_dir: Path, archive_dir: Path) -> dict`,
    with keys:
    - `trace_ids: {doc_id: str | None}`;
    - `archives: {doc_id: str | None}`;
    - `missing_spans`, `missing_nodes`, `missing_archive` (each `list[str]`);
    - `ok: bool`.
  - `archive_path_for(run_id: str, doc_id: str, archive_dir: Path) -> Path`.

- [ ] **Step 1: Write the failing tests:**
  - `test_links_each_document_to_trace_and_archive`: a fake spans gz with two item ids and two
    archive dirs → both linked, `ok is True`.
  - `test_missing_spans_fail_and_are_named` (Review Focus 4): one document without spans →
    `missing_spans == ["DOC-b"]`, `ok is False`, and `gate_report` reasons contain `"missing spans: 1"`.
  - `test_no_span_file_fails_once` (Review Focus 4): no gz file → a single reason
    `"no span mirror at data/traces/<run_id>.spans.jsonl.gz"`.
  - `test_review_documents_need_no_archive`: a document in review with no archive dir is not in
    `missing_archive`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `gate_audit.py` (stream the gz; never load the whole file into memory)
  and wire it in.
- [ ] **Step 4: Run** `tests/test_gate_audit.py tests/test_gate.py tests/test_gate_causes.py`.
  Expected: PASS.
- [ ] **Step 5: Commit** `feat(gate): audit-trail check links every decision to its trace and archive`.

### Task 6: Step-up section and threshold evidence

**Files:**
- Create: `src/mailroom_sandbox/job/gate_compare.py`
- Test: `tests/test_gate_compare.py`

**Interfaces:**
- Consumes: `gate_report` (Task 3) and `pair_report.paired_report(control_dir, treatment_dir)`.
- Produces:
  - `step_up(prev_dir: Path, next_dir: Path, bars: Bars) -> dict`, with keys:
    - `new_docs: list[str]` (in `next` and not in `prev`);
    - `new_docs_gate`: the `gate_report` restricted to `new_docs`;
    - `shared_paired`: the `paired_report` over the shared documents;
    - `nested: bool`: every `prev` id is in `next`. When it is `False`, the step-up FAILs with
      the reason `"slices do not nest"`.
  - `threshold_evidence(run_dir: Path, bars: Bars, *, grid: tuple[float, ...] = (0.90, 0.92, 0.94, 0.96, 0.98, 1.01)) -> dict`:
    - for each gated class and each candidate `t`, replay offline only the threshold-only
      decision "an archived document with `extraction_confidence < t` would have gone to the
      judge";
    - report `{t: {"extra_judged": int, "wrong_archives_caught_upper_bound": int, "correct_archives_disturbed": int}}`;
    - label the result `"upper bound: assumes the judge rejects every caught wrong archive"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_new_docs_lane_uses_only_new_documents`: prev ids {a, b}, next ids {a, b, c, d} → the
    `new_docs_gate` n is 2.
  - `test_non_nested_slices_fail`: prev contains an id absent from next → `nested is False`.
  - `test_threshold_evidence_counts`: three archived documents at confidences 0.95, 0.95 and 1.0,
    one of them wrong at 0.95 → at `t=0.96`, `extra_judged == 2`,
    `wrong_archives_caught_upper_bound == 1`, `correct_archives_disturbed == 1`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `gate_compare.py`.
- [ ] **Step 4: Run** the test file plus `tests/test_pair_report.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(gate): step-up verdict on new documents and threshold evidence`.

### Task 7: `sandbox run gate` CLI, artifacts and ledger line

> **As built:** the ledger row was dropped. `sandbox run gate` writes only `gate.json` and
> `gate.md` into the run directory, and `ledger.py` is unchanged.

**Files:**
- Modify: `src/mailroom_sandbox/cli.py` (a `gate` subparser next to `routing`, near line 1163, and
  a `_cmd_run_gate` handler next to `_cmd_run_routing`, near line 3673)
- Create: `src/mailroom_sandbox/job/gate_render.py`
- Modify: `src/mailroom_sandbox/job/ledger.py`, only if `record_signed` cannot record an unsigned
  `gate` action. Otherwise reuse it with `action="gate"` and no initials.
- Test: `tests/test_gate_cli.py`

**Interfaces:**
- Consumes: `gate_report`, `step_up`, `threshold_evidence` and `load_bars`.
- Produces:
  - **Command:**
    `sandbox run gate --run-id <id> [--prev-run-id <id>] [--bars <path>] [--json] [--thresholds]`.
  - **Writes:** `<run_dir>/gate.json` and `<run_dir>/gate.md`.
  - **`gate.md`:** the verdict line, the per-class table, the bucket table and the unpaired /
    new-docs section.
  - **Exit codes:** 0 on PASS, 2 on FAIL, 1 on a missing run.
  - **Ledger:** appends a `gate` row with the verdict.
  - `render_markdown(report: dict) -> str` in `gate_render.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_gate_cli_writes_artifacts_and_exit_code`: a fake passing run → exit 0, `gate.json`
    has `verdict.pass is True`, and `gate.md` starts with `"PASS"`.
  - `test_gate_cli_fail_exit_2`: a run with a crash → exit 2, and `gate.md` starts with
    `"FAIL"` followed by the reasons.
  - `test_gate_cli_prev_run_adds_step_up`: `--prev-run-id` → `gate.json` has `step_up.new_docs`.
  - `test_gate_cli_missing_run`: exit 1 with a `failed` status JSON.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the subparser, the handler and the renderer.
- [ ] **Step 4: Run** `tests/test_gate_cli.py` and `env -u CLAUDECODE PYTHONPATH=$PWD/src .venv/bin/sandbox run gate --run-id pipeline-qwen-flash-25-e3-mix-control`
  (offline, on the real E3 run).
  Expected: PASS tests. The real-run gate exits 2 with a reason for wrong archives, matching
  the spec's E3 numbers (6/9 correspondence below 0.7, so it is well over 2%).
- [ ] **Step 5: Commit** `feat(cli): sandbox run gate writes gate.json/gate.md and a ledger row`.

### Task 8: Production slice configs

**Files:**
- Create: `config/runs/production/slice-0100.yaml`, `slice-0250.yaml`, `slice-0500.yaml` and
  `slice-full.yaml`
- Create: `config/runs/production/slice-0100-modal-host.yaml`, `slice-0250-modal-host.yaml` and
  `slice-0500-modal-host.yaml`
- Test: `tests/test_production_slices.py`

**Interfaces:**
- Consumes: `exclude_ids_file` (Task 1), `config/production/excluded-ids.txt` (Task 2) and the
  r3 blocks from `config/runs/pipeline-qwen-flash-25-fit-r3.yaml`.
- Produces:
  - **Run ids:** `production-slice-0100`, `-0250`, `-0500`, `-full`, and the `-modal-host` twins.
  - **Seed:** `sample_seed: 3302` for every slice.
  - **Strata:** per-class `buckets`, proportional to the dataset (3,302 rows: corporate 450,
    contract 600, correspondence 1000, insurance 1100, merger 152) and capped at what is
    available after `require_task_gt` and the exclusions:

    | Slice | contract | corporate | correspondence | insurance | merger |
    |---|---|---|---|---|---|
    | 0100 | 18 | 14 | 30 | 33 | 5 |
    | 0250 | 45 | 34 | 76 | 83 | 12 |
    | 0500 | 91 | 68 | 151 | 167 | 23 |

    `slice-full` has no strata and no limit.
  - **Caps:** `api_cost_cap_usd` is 2, 5, 10 and 70 for 0100, 0250, 0500 and full. These come
    from E3's measured 76k prompt tokens per document, about 2× headroom. Confirm each against
    the preflight cost estimate, and raise a cap only if the estimate exceeds half of it.
    `max_wall_seconds` is 7200, 10800, 14400 and 86400.
  - **Modal host twins:** identical except `run_id` and `job.mode: modal`, with the engine still
    OpenRouter.

- [ ] **Step 1: Write the failing tests:**
  - `test_slices_validate_and_share_settings`: every file loads as a `RunSpec`. Each has
    `job.blind_routing is True`, `dataset.interim_labels is True`,
    `dataset.exclude_ids_file == "config/production/excluded-ids.txt"`, the same `prompt`,
    `confidence` and `reviewer` blocks as r3, and caps set.
  - `test_slices_nest`: offline, using the cached
    `Lucius-Morningstar__mailroom-dataset__bc9eab280044/ground_truth_all.jsonl` when present
    (skip otherwise), draw each slice through `select_rows` → ids(0100) ⊂ ids(0250) ⊂ ids(0500).
  - `test_slices_hold_out_tuning_documents`: no drawn id is in `excluded-ids.txt`.
  - `test_modal_twins_differ_only_in_mode_and_id`: the specs are equal after removing `run_id`
    and `job.mode`.
- [ ] **Step 2: Run them.** Expected: FAIL (files missing).
- [ ] **Step 3: Write the seven configs.** Each header comment states: the spec path, the bars
  and the launch commands
  (`sandbox run preflight --config …`, `sandbox run start --config … --initials <XX>`,
  `sandbox run gate --run-id … [--prev-run-id …]`).
- [ ] **Step 4: Run** the tests, then preflight `slice-0100.yaml` offline (expect only the API-key
  check to fail without the key).
  Expected: tests PASS; preflight `prepared` with `rows=100` and the excluded count reported.
- [ ] **Step 5: Commit** `feat(production): nested held-out slice configs and Modal job-host twins`.

### Task 9: Diagnose the contract second-pass judge `TypeError`

**Files:**
- Test: `tests/test_judge_second_pass.py`
- Modify: wherever the root cause lives. If it is in `vendor/`, do not edit: file the issue on
  llm-mailroom with the reproduction and mark the test `xfail(strict=True)`, citing the issue.

**Interfaces:**
- Consumes:
  - the archived state of `DOC-2fbe8b3db2901e16` (E3) and `DOC-47d391f2646c0506` (r3) in their
    run dirs (`items.jsonl`, `nodes.jsonl`);
  - the `judge_failed` exception that `graph/build_graph.py` logs near line 2233.
- Produces: a reproduction test, the root cause and either a sandbox fix or an upstream issue
  number.

- [ ] **Step 1: Reproduce.** Use superpowers:systematic-debugging.
  - **Get the traceback:** rebuild the judge input from the second judge call
    (`extracted_data` after the retry, `doc_type: contract`, `doc_text` from `dataset.jsonl`).
    Call the judge's verify function offline with a stub LLM client that returns the recorded
    response shape, and capture the `TypeError` traceback.
  - **If the stub cannot reproduce it:** add a sandbox-side `logger.exception` capture
    (`traceback` into the node record) so the next run records it, and stop this task with
    that capture plus a test for it.
- [ ] **Step 2: Write the failing test** `test_second_pass_judge_accepts_retried_contract_extraction`,
  asserting the judge returns a verdict, not `judge_error`, on the reproduced input.
- [ ] **Step 3: Fix the root cause**, in the sandbox if it is sandbox wiring. If it is vendored,
  file the upstream issue: an executive summary, no requester quotes or names, and the
  reproduction attached.
- [ ] **Step 4: Run** the test (it passes, or it xfails with the issue link).
- [ ] **Step 5: Commit** `fix(judge): …` or `test(judge): reproduce second-pass TypeError (llm-mailroom #N)`.

### Task 10: Diagnose the decision reviewer's `unknown` on correspondence email

**Files:**
- Test: `tests/test_reviewer_unknown.py`
- Modify: per the root cause: the reviewer question set (`reviewer_decisions_v2`), its label
  mapping, or an upstream issue.

**Interfaces:**
- Consumes: `DOC-49642fa25902b91e` (E3) and its r3 counterpart: the items with
  `reviewer_doc_type == "unknown"` and the reviewer request/response recorded in the spans.
- Produces: the root cause, and a fix or an issue.

- [ ] **Step 1: Find the reviewer's raw answer** for the two documents in the span mirror (the
  decision-review span attributes), and see where it maps to `unknown`. It could be a label
  outside the mapping, an empty answer, or a refusal.
- [ ] **Step 2: Write the failing test** for that mapping, for example
  `test_reviewer_email_answer_maps_to_correspondence`, with the recorded answer as input.
- [ ] **Step 3: Fix the mapping** or question set on the sandbox side. If the answer itself is
  wrong (a model limit), record it as a cause bucket finding instead, and keep the test as
  documentation of the expected mapping.
- [ ] **Step 4: Run** the test plus `tests/test_reviewer_spec.py`. Expected: PASS.
- [ ] **Step 5: Commit** `fix(reviewer): …` or `test(reviewer): pin the unknown-label case`.

### Task 11: Operator docs and changelog

**Files:**
- Create: `docs/runbooks/production-slices.md`
- Modify: `docs/jobs.md` (a `sandbox run gate` section, `dataset.exclude_ids_file`),
  `CHANGELOG.md` and `AGENTS.md` (the command reference line for `run gate`)

**Interfaces:**
- Consumes: the CLI and file names from Tasks 1–8.

- [ ] **Step 1: Write the runbook.**
  - **Fix loop, step by step:** for slice N, preflight, then start (human initials), then gate,
    then read the buckets, then fix, then re-run the same slice and run
    `gate --prev-run-id` for the paired check. When it passes, move to the next slice.
  - **The bars table**, and when a fix lands upstream versus here.
  - **The Modal job-host parity check:** run the twin, then compare `dependency_sources` and
    the per-class rates within the paired CI.
  - **Stage 2** (self-hosted vLLM) is out of scope until the OpenRouter slices pass.
- [ ] **Step 2: Update** `docs/jobs.md`, `CHANGELOG.md` and `AGENTS.md`.
- [ ] **Step 3: Run** `uvx ruff check src tests scripts deploy reports` and
  `env -u CLAUDECODE PYTHONPATH=$PWD/src .venv/bin/python reports/dashboard/build_hub.py --check`, plus the gate test
  files. Expected: clean and ok.
- [ ] **Step 4: Commit** `docs(production): slice-gate runbook, jobs reference and changelog`.

## Not in this plan

- **Running the slices and the fix iterations:** a human launches them, and each bucket fix
  gets its own small plan or PR.
- **Stage 2, the self-hosted vLLM ladder:** it gets its own plan once `production-slice-0500`
  passes on OpenRouter.
