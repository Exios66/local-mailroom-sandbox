# Phase 5 part 1: attempt hygiene implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** On the OpenRouter production route, a run can keep the best-judged extraction attempt and drop
unevidenced list items from one-call reads, both opt-in, with an offline replay that measures each from a
finished run.

**Architecture:**

- **A** is configuration only. `job.confidence.keep_best_attempt` reaches the vendored #254 selection
  through the existing confidence overlay.
- **B** is a sandbox vendor hotfix, HF-029. It wraps `graph.build_graph._enrich_contract_result` and reuses
  the vendored single-window evidence test (`_item_support`). It is switched on by `job.evidence_check`.
- **The replay** is a tested module plus a thin script. It reads a finished run store and rescores each
  document's latest extraction, its selected attempt and its filtered extraction with the gate's own
  scorer.

**Tech stack:** Python 3.11+, pydantic v2 (`StrictBool`), pytest, and the vendored `llm-mailroom` graph.

**Spec:** [`docs/design/specs/2026-11-27-phase5-attempt-hygiene-design.md`](../specs/2026-11-27-phase5-attempt-hygiene-design.md).
It is part 1 of Phase 5 of [`2026-11-26-correcting-judge-design.md`](../specs/2026-11-26-correcting-judge-design.md).

## Global constraints

- Never hand-edit `vendor/`. HF-029 is a sandbox hotfix in `src/mailroom_sandbox/vendor_hotfixes.py`, with
  its rows in `docs/vendor-hotfixes.md` and `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md` in the same change.
- Both switches are off by default, and a spec without them keeps its `spec_hash`. `job.evidence_check` is
  hashed only when set. `keep_best_attempt` lives in `confidence`, which is hashed as it is today.
- `job.evidence_check` is refused unless `task: pipeline`.
- `keep_best_attempt` is refused with `judge: mode: correct`, both globally and under `by_class`.
- Only a real boolean is accepted for `keep_best_attempt`: a quoted `"true"` is refused.
- Filtered fields are `cuad_clauses` and `claim_checklist`, the vendored `_DEFAULT_EVIDENCE_FIELDS` whose
  items are `"<Category>: <quoted span>"` (narrowed at review: `action_items` and `denial_reasons` are
  summaries, and a whole-item quote test drops true ones).
- An item is dropped only when `_item_support` returns `False`.
- No paid or live run. The replay is offline. Local tests run named files only, with `-n 0 --no-cov`.
- HF-029 takes the next free ID. `docs/numbering-reservations.md` then says the next free vendor hotfix
  ID is `HF-030`.
- Commits use the `.gitmessage` shape: no claude.ai links, no session trailer, no footer, and only
  `Co-Authored-By`.

## Review focus

1. **Two wrappers on one function.** HF-027 and HF-029 both wrap `_enrich_contract_result`. Applying the
   hotfixes twice must not double either layer, and a field-only retry with the check on must give the
   merged extraction with the fresh fields filtered.
2. **Malformed reasoning.** A result whose `reasoning` is missing, `None`, a list, or holds non-dict
   entries must not raise. The check then relies on the quote fragments alone.
3. **Non-string items.** A dict, number or `None` inside an evidence field is kept unchanged. `str()` of a
   dict yields checkable "fragments", which would drop it wrongly.
4. **Replay inputs.** The replay must handle an errored item with no `pred`, a human-sourced extraction,
   an item with no attempt history, and the review-versus-archive split. Each is skipped or handled with
   a count, and `scored_n` is reported.
5. **Selection matching the graph.** An archived document must use the vendored
   `_attempt_selection(pred, for_archive=True)`. That guard keeps the latest attempt when an earlier one is
   unsure or below the coverage floor. A review document uses `for_archive=False`.

---

### Task 1: `job.confidence.keep_best_attempt`

**Files:**

- Modify: `src/mailroom_sandbox/job/spec.py`: `_THRESHOLD_FLAG` (about line 1175), and a new
  `@model_validator(mode="after")` on `RunSpec` beside `_judge_in_pipeline` (about line 1400).
- Modify: `src/mailroom_sandbox/job/routing_audit.py`: the `thresholds` key tuple (about line 355), and
  `_unknown_unless_explicit` for the legacy lock path (about line 423).
- Test: `tests/test_keep_best_attempt.py` (new).

**Interfaces:**

- Produces:
  - the spec key `confidence.keep_best_attempt: bool`, also under `confidence.by_class.<class>`;
  - the routing audit's `report["thresholds"]["keep_best_attempt"]`, which is `True`, `False` or
    `"unknown"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_keep_best_attempt.py`. Build the spec the way
  `tests/test_job_spec.py::_spec` does, as a pipeline run.

```python
def test_the_flag_is_accepted_globally_and_per_class():
    assert _spec(confidence={"keep_best_attempt": True}).confidence["keep_best_attempt"] is True
    spec = _spec(confidence={"by_class": {"contract": {"keep_best_attempt": True}}})
    assert spec.confidence["by_class"]["contract"]["keep_best_attempt"] is True

def test_a_quoted_flag_is_refused():
    with pytest.raises(ValidationError, match="keep_best_attempt must be true or false"):
        _spec(confidence={"keep_best_attempt": "true"})

def test_the_flag_is_refused_with_the_correcting_judge():
    for confidence in ({"keep_best_attempt": True}, {"by_class": {"contract": {"keep_best_attempt": True}}}):
        with pytest.raises(ValidationError, match="keep_best_attempt.*judge.mode correct"):
            _spec(confidence=confidence, judge={"mode": "correct"})
    assert _spec(confidence={"keep_best_attempt": True}, judge={"mode": "verify"})  # verify mode is fine

def test_a_spec_without_the_flag_keeps_its_hash():
    # The committed stage-1 baseline's spec_hash must not change.
    assert spec_hash(load_run_spec("config/runs/p4-s1-verify-gov-off.yaml")) == (
        "7293c6342d502a2d42f2d052a0e985031f7343723baf242c983ba2313c0bb288")  # main at 1dcafd5

def test_the_flag_reaches_the_vendored_switch(...):
    # Activate a lock whose confidence has by_class.contract.keep_best_attempt true, as
    # tests/test_subclass_extraction.py::test_the_lock_activates_the_note does. Then:
    from graph.routing import keep_best_attempt_enabled
    assert keep_best_attempt_enabled({"doc_type": "contract"}) is True
    assert keep_best_attempt_enabled({"doc_type": "invoice"}) is False

def test_the_routing_audit_reports_the_flag():
    # A locked effective_confidence with the flag gives True. A legacy lock that only froze
    # overrides without it gives "unknown", never today's default.
```

The hash is a literal taken on main at `1dcafd5`, so the test catches a change that two computed hashes
would both pick up. Task 2 must leave it unchanged too.

- [ ] **Step 2: Run the tests and watch them fail.**
  - Run: `.venv/bin/python -m pytest -q tests/test_keep_best_attempt.py -n 0 --no-cov`
  - Expected: FAIL. The spec refuses the key ("unsupported thresholds ['keep_best_attempt']"), and the
    audit has no key.
- [ ] **Step 3: Implement.**
  - Add `"keep_best_attempt"` to `_THRESHOLD_FLAG`.
  - Add `RunSpec._keep_best_needs_verify_judge`: it raises "confidence.keep_best_attempt keeps an earlier
    attempt, but judge.mode correct applies fixes the attempt history does not hold; use judge.mode
    verify or drop the flag" when the flag is true globally or in any `by_class` block, and
    `self.judge` is set with `mode == "correct"`.
  - Add the key to the audit tuple, and pass it through `_unknown_unless_explicit` on the legacy path.
- [ ] **Step 4: Run the tests and watch them pass.** The same command, plus `tests/test_job_spec.py`
  and `tests/test_routing_calibration.py`. Expected: PASS.
- [ ] **Step 5: Commit** as `feat(spec): job.confidence.keep_best_attempt selects the best-judged attempt`.

### Task 2: HF-029 evidence check for one-call reads

**Files:**

- Create: `src/mailroom_sandbox/evidence_check.py`.
- Modify: `src/mailroom_sandbox/vendor_hotfixes.py`: the install function, and a `Hotfix(id="HF-029", ...)`
  entry appended after HF-027.
- Modify: `src/mailroom_sandbox/job/spec.py`:
  - `JobSpec.evidence_check: StrictBool = False`, after `subclass_field_note`, with a comment in its
    style;
  - the pipeline-only refusal in `_subclass_schemas_in_pipeline`, or a sibling validator;
  - the hashed-only-when-set tuple (about line 1583).
- Modify: `src/mailroom_sandbox/runtime.py`: call `evidence_check.activate(bool(locked_job.get("evidence_check")))`
  next to `governor.activate`. An unlocked eval is off.
- Modify: the docs listed under Step 5.
- Test: `tests/test_evidence_check.py` (new).

**Interfaces:**

- Produces:
  - `evidence_check.activate(enabled: bool) -> None` and `evidence_check.active() -> bool`, as module
    state reset on every activation;
  - `evidence_check.fields() -> tuple[str, ...]`: `cuad_clauses` and `claim_checklist`, each kept only
    while the vendored `_DEFAULT_EVIDENCE_FIELDS` still lists it;
  - `evidence_check.filter_one_read(result: Any, doc_text: str | None, *, keeps=None) -> Any`.
- How `filter_one_read` behaves:
  - It returns `result` unchanged when `result` is not a mapping, carries `_n_chunks` (a chunked read) or
    `_parse_error`, or when `doc_text` is empty.
  - Otherwise it returns a new dict. Each list in `fields()` keeps every non-string item, and every string
    item for which `_item_support(item, field, entries, _fold(doc_text))` is not `False`.
  - `entries` is `result["reasoning"]["entries"]` when that is a list, filtered to dict entries, and `[]`
    otherwise.
  - When anything is dropped, it adds `_evidence_dropped: {field: [items...]}`, merged into any earlier
    value.
  - When the filtered extraction would fail `pipeline.guards._has_substantive_content` and the input
    passed it, it returns the input with `_evidence_skipped: "would_empty"` instead.
- The hotfix: when `evidence_check.active()`, the wrapper calls
  `original(filter_one_read(result, state.get("doc_text")), state)`.
  - Idempotency comes from the registry's `_sandbox_hotfix` mark, which is set to `HF-029`. HF-027's own
    inner check reads the same attribute, and because HF-029 is installed after HF-027, the outer layer
    is never re-wrapped by HF-027.
  - `also` pins `extract_node`, `retry_extract_node` and
    `langchain_agents.specialist_agents:_item_support`, `:_evidence_fragments` and `:_fold`.

- [ ] **Step 1: Write the failing tests** in `tests/test_evidence_check.py`. `DOC` holds the quoted clause
  text. `REAL` is `"Governing Law: This Agreement shall be governed by the laws of Delaware"`, quoted
  from `DOC`. `FAKE` is `"Non-Compete: The Supplier shall not compete in any territory worldwide"`, not
  in `DOC`.

```python
def test_an_unevidenced_item_is_dropped_and_recorded():
    out = ec.filter_one_read({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}, DOC)
    assert out["cuad_clauses"] == [REAL] and out["_evidence_dropped"] == {"cuad_clauses": [FAKE]}

def test_a_short_unverifiable_item_is_kept():          # "Governing Law: Delaware" -> _item_support None
def test_a_reasoning_quote_evidences_an_item():         # entry {"field": "cuad_clauses", "evidence": <in DOC>}
def test_label_lists_are_never_filtered():              # maud_clauses / parties / keywords untouched
def test_a_chunked_read_is_left_to_the_merge_policy():  # {"_n_chunks": 3, ...} returned unchanged
def test_non_string_items_are_kept():                   # [{"x": FAKE}, 7, None] kept as is
def test_malformed_reasoning_never_raises():            # reasoning None / [] / {"entries": "x"} / [1]
def test_a_filter_that_would_empty_the_extraction_is_skipped():
    out = ec.filter_one_read({"cuad_clauses": [FAKE]}, DOC)
    assert out["cuad_clauses"] == [FAKE] and out["_evidence_skipped"] == "would_empty"
def test_the_filter_is_idempotent():                    # filter(filter(x)) == filter(x)
def test_off_changes_nothing(...):                      # inactive: bg._enrich_contract_result output unchanged
def test_hf029_is_registered_with_a_pinned_source():    # as test_hf023_...; apply twice -> same wrap depth
def test_a_field_retry_with_the_check_filters_the_fresh_fields(...):
    # HF-027 pending (previous={"cuad_clauses": [REAL], "parties": ["Acme"]}, names={"cuad_clauses"}),
    # specialist returns {"cuad_clauses": [REAL, FAKE]} -> enriched has cuad_clauses [REAL], parties kept
def test_the_check_flag_is_hashed_only_when_set():
def test_the_check_requires_a_pipeline_task():
def test_the_lock_activates_the_check(...):
```

- [ ] **Step 2: Run the tests and watch them fail.**
  - Run: `.venv/bin/python -m pytest -q tests/test_evidence_check.py -n 0 --no-cov`
  - Expected: FAIL with `ModuleNotFoundError: mailroom_sandbox.evidence_check`.
- [ ] **Step 3: Implement** `evidence_check.py`, the hotfix entry, the spec flag and the runtime
  activation, as the Interfaces block says.
- [ ] **Step 4: Run the tests and watch them pass.**
  - Run the new file, plus `tests/test_vendor_hotfixes.py`, `tests/test_correcting_judge.py`,
    `tests/test_subclass_extraction.py`, `tests/test_job_spec.py`, `tests/test_vendor_drift.py` and
    `tests/test_docs_drift.py`, then `python scripts/check_hotfixes.py`.
  - Expected: PASS.
- [ ] **Step 5: Docs.**
  - The HF-029 row in `docs/vendor-hotfixes.md` and in `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md`.
  - In `docs/numbering-reservations.md`: an `HF-029` row ("Phase 5 evidence check, landed with this PR"),
    and the next free ID becomes `HF-030`.
  - Re-run `tests/test_docs_drift.py`.
- [ ] **Step 6: Commit** as `feat(hotfix): HF-029 evidence check drops unquoted list items from one-call reads`.

### Task 3: Offline replay

**Files:**

- Create: `src/mailroom_sandbox/job/attempt_replay.py`.
- Create: `scripts/replay_attempt_hygiene.py`, an argparse wrapper: `--run <run_id|path>` and
  `--out <json>`, with the default `data/runtime/replays/<run_id>.attempt_replay.json` (beside the run
  store, never inside a run; an `--out` inside the source run is refused). It prints the digest.
- Test: `tests/test_attempt_replay.py`, which builds a fixture run store in `tmp_path`.

**Interfaces:**

- Consumes:
  - `rescore.locate(run) -> RunFiles` (the lock, `dataset.jsonl` and `items.jsonl`);
  - `graph.build_graph._attempt_selection(state, *, for_archive: bool) -> dict`;
  - `evidence_check.filter_one_read`;
  - `job.gate._score(row, pred) -> float | None` with `without_fields(row, TEMPLATED_FIELDS.get(cls, ()))`,
    as `gate.py` scores an archive;
  - `eval.cuad_scoring.score_cuad(predicted, labels)` with `scope_extraction_pair` and
    `gate._unit_labels(_fields(row).get(_UNIT_FIELD["contract"]))`, as `gate_causes.extraction_miss` does.
- Produces: `replay(run: str | Path) -> dict`, which is JSON-serializable:
  - `label`: `"offline replay (estimate)"`;
  - `run_id`;
  - `counts`: `items`, `scored_n`, and skips by reason (`no_pred`, `human_source`, `no_history`,
    `no_labels`);
  - `selection`: per class and overall, `scored_n`, `latest` and `selected` mean quality, `changed`
    (documents where selection restored an earlier attempt) and `reasons` (a `Counter` of
    `selected_attempt_reason`);
  - `evidence`: per class and overall, `scored_n`, `before` and `after` mean quality, `dropped` per field,
    `would_empty`, and for contracts `cuad_fp_before`, `cuad_fp_after`, `cuad_fn_before` and
    `cuad_fn_after`;
  - `bars`: `selection_meets` and `evidence_meets_confirming_arm`, booleans per the design's adoption bars:
    - A: no class with `scored_n >= 10` is lower, and the overall mean is higher;
    - B: CUAD false positives fall by at least 25%, CUAD false negatives rise by no more than
      2 per 100 documents, and no class with `scored_n >= 10` loses filtered quality.
- Rules:
  - An archived item (`pred["stage"] != "review"`) uses `for_archive=True`.
  - The filter's document text is `pred.get("doc_text")`, falling back to `row["doc_text"]`. The
    fallback count is reported.
  - B is applied to the latest extraction, which is the one the run scored.
  - Missed and false items are counted for CUAD clauses only, the one filtered field with an item scorer
    in the gate (`gate_causes.extraction_miss`). The other filtered fields are reported by dropped
    counts and quality. This narrows the design's "CUAD and checklist" wording; record it as a ruling.

- [ ] **Step 1: Write the failing tests.** The fixture holds four contracts and one review item:
  - a contract whose first attempt was `complete` and whose second was `partial` (selection restores
    attempt 1);
  - a contract with one attempt;
  - an errored item;
  - a human-sourced item;
  - a review item.

```python
def test_a_stored_pipeline_answer_keeps_the_attempt_history(...):
    # Run one mock pipeline document through eval.runners._run_pipeline_doc (mock=True) and
    # assert "extraction_attempt_history" in the result and in the item the runner persists.
def test_selection_restores_the_better_judged_attempt():
def test_an_archived_unsure_earlier_attempt_is_not_selected():  # for_archive guard -> latest kept
def test_the_filter_counts_dropped_items_and_cuad_errors():
def test_skips_are_counted_and_scored_n_reported():
def test_the_bars_follow_the_design():                       # one pass and one fail case for each bar
def test_the_replay_is_labelled_an_estimate_and_writes_its_file():
def test_the_replay_never_writes_the_source_run():           # source dir bytes unchanged
```

- [ ] **Step 2: Run the tests and watch them fail.**
  - Run: `.venv/bin/python -m pytest -q tests/test_attempt_replay.py -n 0 --no-cov`
  - Expected: FAIL with `ModuleNotFoundError`. If the first test fails because the history is not
    persisted, stop and record a ledger ruling: the design's measurement of A rests on it.
- [ ] **Step 3: Implement** `attempt_replay.replay` and the script.
- [ ] **Step 4: Run the tests and watch them pass.**
  - Run the new file and `tests/test_rescore.py`, then `ruff check src tests scripts`.
  - Expected: PASS.
- [ ] **Step 5: Commit** as `feat(replay): offline replay of best-attempt selection and the evidence check`.

### Task 4: Confirming-arm config, docs and gates

**Files:**

- Create: `config/runs/p5-s1-evidence-on.yaml`: a copy of `config/runs/p4-s1-verify-gov-off.yaml` with
  `run_id: p5-s1-evidence-on`, `job.evidence_check: true` and an extra tag. Its header comment says to
  launch it only when the replay's `evidence_meets_confirming_arm` is true, and to launch it with a
  person's initials.
- Modify:
  - `docs/jobs.md`: two subsections, "Keep the best-judged attempt (`confidence.keep_best_attempt`)"
    and "Evidence check (`job.evidence_check`)", with the replay command.
  - `docs/critical-regressions.md`: guard names on rows 6 (`test_hf029_is_registered_with_a_pinned_source`),
    8 (`test_the_replay_is_labelled_an_estimate_and_writes_its_file`) and 15
    (`test_the_replay_never_writes_the_source_run`).
  - `CHANGELOG.md`.
  - `docs/README.md`: the "Phase 5 attempt hygiene" row already links the design and this plan; drop "(draft)" wording if any remains.
- Test: `tests/test_evidence_check.py::test_the_confirming_arm_differs_from_its_baseline_only_in_the_check`,
  modelled on `test_the_note_ab_arm_differs_from_its_baseline_only_in_the_note`.

- [ ] **Step 1: Write the failing arm test, run it, and watch it fail.** The file is missing.
- [ ] **Step 2: Add the config and docs.** The test then passes.
- [ ] **Step 3: Run the gates.** Each must exit 0:
  - `ruff check src tests scripts deploy reports notebooks`;
  - `python scripts/sync_requirements.py --check`;
  - `python reports/dashboard/build_hub.py --check`;
  - `python scripts/check_cli_surface.py --check`;
  - `sandbox runbook check`;
  - `python scripts/check_hotfixes.py`;
  - `npx markdownlint-cli2@0.18.1` on the changed docs.
- [ ] **Step 4: Run an offline preflight.**
  - Run: `sandbox run preflight --config config/runs/p5-s1-evidence-on.yaml`
  - Expected: it fails exactly as the baseline does in this container (the dataset strata check), or it
    passes. Record the result as "not verified" if it fails on the environment.
- [ ] **Step 5: Commit** as `docs(phase5): evidence-check confirming arm, docs and guard names`.

## Verification

- Every named test file runs with `-n 0 --no-cov`, and all of Task 4's gates exit 0.
- Hosted CircleCI (lint, checks, pytest, coverage, notebook regressions, no-session-links) is green on
  the PR head before merge.
- No paid run. The owner runs the replay on `p4-s1-verify-gov-off` after stage 1, and launches the
  confirming arm only if its bar is met.
