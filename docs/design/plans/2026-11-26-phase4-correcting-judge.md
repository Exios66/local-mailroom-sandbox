# Phase 4: Correcting Judge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Behind a new optional `judge:` section, the judge makes one ruling per pass: **accept** (applying fixes it can quote), **retry these fields**, or **human review**. Every fix is checked against the source before use. A document gets at most two rulings and one field-only retry, the arbiter passes the ruling on without a model call, and each result records what the judge did.

**Architecture:**

- `vendor/` is not edited. Three new vendor hotfixes do the work:
  - **HF-025** on `graph.build_graph.judge_verify_node`: the ruling, plus recording for both judge modes.
  - **HF-026** on `arbiter_node`: passes the ruling on.
  - **HF-027** on `retry_extract_node`: the field-only retry, plus the route back to the judge.
- New sandbox modules hold the logic. The hotfixes only map it onto the vendored state keys and routers:
  - `correcting_judge.py`: prompt, ruling, models;
  - `judge_fixes.py`: fix checking;
  - `judge_references.py`: reference pool and examples.
- Records travel through the document's call-guard scope into the result (the phase 2 `governor_stop` route). LangGraph drops undeclared state keys.

**Tech Stack:** Python 3.11, pydantic (job spec), `contextvars`, pytest. The vendored `llm-mailroom` graph and the vendored Dojo scorer are unchanged.

**Spec:** [`docs/design/specs/2026-11-26-correcting-judge-design.md`](../specs/2026-11-26-correcting-judge-design.md), sections "How it works" to "The test, in stages", "Plan" (phase 4 steps 1–9) and "Calls I made".

**Branch:** `claude/phase4-correcting-judge`, rebased on `main` after #438 (phase 3) was squash-merged. One PR, which points at this plan.

**Status:** approved by the owner (2026-11-27), with a quality and completeness sweep (rulings 13–18, the added tests in Tasks 1, 3, 5 and 7, and the comparison in Task 7).

## Where the spec and the code disagree (rulings)

A code map taken before this plan found these points. The spec is the authority, and each ruling keeps its intent.

1. **No new graph state keys.** LangGraph keeps only `DocumentState` keys.
   - The ruling is mapped onto declared keys:
     - accept → `judge_verdict: "complete"`, with the verified fixes written into `extracted_data`;
     - retry → `"partial"`;
     - human review → `"incomplete"`.
   - The full record goes to `call_guard.scope()["judge_rulings"]` and `["before_judge"]`. `eval/runners._run_pipeline_doc` (not pinned by SHF-012) copies them onto the result.
2. **The judge cannot route straight to a retry.** Only `arbiter` can reach `retry_extract`, so the arbiter pass-through is how a retry ruling travels.
3. **The governor.** With `judge.mode: correct`:
   - `arbiter` is not a round, because it makes no model call;
   - `retry_extract` still is;
   - two rulings are guaranteed by the node itself: a second ruling can never ask for a retry.

   `_passed_judge` already accepts a `complete` verdict recorded on the latest attempt, so an accept ruling archives with caveats when the governor stops the document.
4. **Matter conflicts.** The spec says they "still go to the boss, as today". Today an unadjudicated conflict after the judge or the arbiter goes to `human_review`, and only a retry extraction reaches the Boss. That routing is kept unchanged; "as today" governs.
5. **The whole document.**
   - **Today:** the judge reads 16,000 characters (80,000 on context-fitted routes).
   - **Spec:** "the whole document", and its costs (76k and 570k tokens) assume it. The correcting judge reads the whole document.
   - **Too long:** a document whose estimate (`call_guard` token estimate plus the completion reserve) exceeds the judge model's `context_length` gets a `human_review` ruling with reason `judge_input_too_long`. It is never silently truncated.
6. **A retry the judge asks for comes back to the judge.** The vendored re-judge is opt-in (`judge_rejudge_retry`). HF-027 adds a route rule on `retry_extract`: after a judge-ordered retry, the route is `judge_verify` while the pass budget allows. Transient, `human_review` and `boss_escalation` routes are kept.
7. **Recording.** Runs without `judge:` are byte-identical to today ("Any run without the `judge:` section … will not change"). `judge.mode: verify` is today's judge plus the record.
8. **`references: catalog` is refused in phase 4.** No catalog source exists yet, and the spec allows it only on unscored real mail (phase 6).
9. **OpenRouter only** ("Calls I made"). Preflight refuses `mode: correct` when the judge's route is not OpenRouter.
10. **Pins and prices.**
    - `qwen/qwen3.7-plus` is priced but not pinned. OpenRouter's public endpoint list shows one provider, Alibaba, so the pin is `order: [alibaba]`, `allow_fallbacks: false`.
    - The smoke test is live, so it is handed to the owner.
    - `deepseek/deepseek-v4.1-flash-1017` is already pinned (`together`).
11. **Labels.**
    - Every near-gold catalog row has `use_as_truth: false`, so "near-gold" means `status == "near_gold"`. `disputed` and `rejected` rows are left out.
    - Interim truth is `interim_labels.TRUTH_STATUSES`, with `disputed` excluded.
    - All insurance interim labels are `derived`, so insurance examples are thin; the pilot reports it.
    - `dev-look1` holds 300 documents, not 302.
12. **Hotfix IDs.** HF-025 to HF-027: #425 holds HF-020 to HF-022, #437 HF-021, and #438 (merged) HF-023/HF-024. #439 adds none.
13. **Verify mode uses no judge model of its own.** `mode: verify` is today's judge, which runs on the pipeline's configured judge model. `model`, `models_by_class` and `references` therefore apply to `mode: correct` only: a verify section that sets a non-default model, a class override or references is refused, so a lock never names a model that did not run. The price, pin and OpenRouter checks, and the spend-cap pricing, cover the judge models in correct mode only.
14. **Open PRs that touch what this phase consumes.**
    - #439 (stacked on #425) gives `gold_labels.evidence_support` a `doc_subclass` keyword, with per-subclass target fields, merger value rules and a per-member quote rule for lists. `verify_fix` takes the predicted subclass and passes `doc_subclass=` when the function accepts it, so merger and corporate fixes get those checks once #439 lands, with no change here.
    - #439 also rebuilds `config/extraction/subclass_schemas.json`. Whichever of #439 and this PR lands second regenerates `config/extraction/subclass_extraction_fields.json` (`scripts/build_subclass_fields.py`). That changes the field-list sha every pipeline lock carries, so the stage configs are preflighted again after it.
15. **"Marked judge corrected."** A result whose accepted extraction applied at least one verified fix carries `judge_corrected: true`. It stays in every total and denominator.
16. **Fix accuracy is scored in the gate only.** Whether a verified fix was right or wrong is decided by scoring that field's fixed value against the run's ground truth in the gate report. Labels for a scored document never reach the judge.
17. **"Judge-related calls"** (the success rule's 50% cut) are the judge, arbiter and judge-ordered `retry_extract` calls of a judged document, counted from the usage records' node. Classify, extract and boss calls are not judge-related.
18. **The 2-point margin is a non-inferiority test.** Stage 2 passes on score only when the lower bound of the paired bootstrap interval (`sand42_cards.paired_delta`, judged documents of either arm, same ids) is at or above −2 points. The point estimate alone is not enough.

## Global Constraints

- No edits to `vendor/`. Every pipeline change is a hotfix in `src/mailroom_sandbox/vendor_hotfixes.py`, with a row in `docs/vendor-hotfixes.md` and `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md` in the same change.
- Off by default: "Nothing changes for any existing run." Without `judge:`, `spec_hash`, every request and every result are unchanged. The one lock change: HF-025 to HF-027 join every lock's `vendor_hotfixes`, so a run locked before this branch refuses to resume until `--force`.
- At most two judge rulings and one retry per document. A document that reaches the limit goes to human review, so it stays in the scored results.
- A fix can never blank a field. A field the judge calls wrong with no verified fix blocks the archive: it is retried on the first ruling, or sent to a person on the second.
- The judge never sees labels for the document it judges or for any test document. Examples come only from runbook-v2 `calibration` and `pool`, at most two, matched by type and subtype; labels merge in the scorer's own order (interim first, near-gold on fields interim does not give and over an interim gate-gap fill; an interim correction and an `original_header` fill stand).
- Judge models: `qwen/qwen3.7-plus` by default, `deepseek/deepseek-v4.1-flash-1017` for `merger_agreement`. Both need a price and a provider pin, or preflight refuses.
- No paid or live runs by an agent. Stage 1 and 2 configs are written and preflighted offline; a person launches them with their initials.
- Local checks: named test files, `-n 0 --no-cov`. Full suite and coverage (`fail_under = 84`, never lowered) run in hosted CircleCI.
- Never edit `_run_pipeline_doc_once` or `_pipeline_item` (SHF-012), or `eval/extraction_scope.applicable_expected_fields` (SHF-001, SHF-015).
- The PR checks critical-regression rows 1, 3, 5, 6, 9, 12, 14, 15, 17 and 22.

## Review Focus

1. **A fix whose quote is real but whose value is not supported** (a date quoted, a different date set). Expected: not applied, recorded as `unsupported`. Pinned by `test_a_value_the_quote_does_not_support_is_rejected` (Task 3).
2. **A judge reply that names a field outside the requested schema, or a metadata key** (`_report`, `reasoning`, a subclass-dropped field). Expected: rejected as `not_requested`, never written into `extracted_data`. Pinned by `test_a_fix_outside_the_requested_fields_is_rejected` (Task 3).
3. **A retry ruling on the second pass.** Expected: human review, never a second retry and never a third ruling. Pinned by `test_a_second_ruling_cannot_retry` (Task 5).
4. **A merger longer than the judge's context.** Expected: a `judge_input_too_long` human-review ruling, no truncated call. Pinned by `test_a_document_over_the_judge_context_goes_to_review` (Task 4).
5. **A test document that shares a leak component with a reference example** (thread, matter or text). Expected: preflight refuses the run. Pinned by `test_a_drawn_document_sharing_a_component_with_the_pool_is_refused` (Task 6).

---

### Task 1: The switch, the lock and the preflight refusals

**Files:**

- Modify: `src/mailroom_sandbox/job/spec.py`: `JudgeSpec`, a `RunSpec.judge` field, a validator, and `spec_core`.
- Modify: `src/mailroom_sandbox/job/preflight.py`: `_judge_errors(spec)` in `_engine_errors`; the pool leak check in `_prepare_dataset_rows`.
- Modify: `src/mailroom_sandbox/job/api_budget.py`: `api_models` and `spec_api_models` include the judge models.
- Modify: `src/mailroom_sandbox/runtime.py`: activate from the lock.
- Create: `src/mailroom_sandbox/correcting_judge.py`: `activate`, `deactivate`, `active`, `judge_model(doc_type)`.
- Test: `tests/test_correcting_judge.py`.

**Interfaces:**

- Produces:
  - `JudgeSpec` (pydantic, `extra="forbid"`):
    - `mode: Literal["verify", "correct"] = "verify"`;
    - `model: str = "qwen/qwen3.7-plus"`;
    - `models_by_class: dict[str, str] = {"merger_agreement": "deepseek/deepseek-v4.1-flash-1017"}`;
    - `references: Literal["off", "train_pool", "catalog"] = "off"`;
    - `reference_pool: str | None = None`;
    - `max_examples: int = 2` (bounded 0..2);
    - `max_attempt_chars: int = 4000`;
    - `max_example_chars: int = 3000`.
  - `RunSpec.judge: JudgeSpec | None = None`, valid only with `task: pipeline`.
  - `spec_core` adds `{"judge": {...dump, "reference_pool_sha256": ...}}` only when set.
  - `correcting_judge.activate(spec: Mapping | None, *, pool_sha256: str | None) -> None` refuses a pool whose sha differs from the lock's.
  - `correcting_judge.judge_model(doc_type: str) -> str`.
  - `correcting_judge.active() -> Mapping | None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_judge_section_leaves_the_spec_hash_unchanged(): ...        # "judge" not in spec_core(base); spec_hash(base) == spec_hash(base with judge=None)
def test_a_judge_section_is_hashed_with_the_pool_sha(tmp_path): ...    # pool file bytes change -> spec_hash changes
def test_judge_requires_a_pipeline_task(): ...                         # ValidationError match "pipeline"
def test_preflight_refuses_an_unpriced_or_unpinned_judge_model(): ...  # detail names the model; covers models_by_class too
def test_preflight_refuses_correct_mode_off_openrouter(): ...
def test_preflight_refuses_a_missing_or_changed_pool(tmp_path): ...
def test_catalog_references_are_refused(): ...                         # match "catalog"
def test_train_pool_is_refused_on_a_draw_with_calibration_or_pool_rows(): ...
def test_the_spend_cap_prices_the_judge_models(): ...                  # api_models(lock) ⊇ {model, *models_by_class.values()}
def test_the_lock_activates_the_judge_and_refuses_a_changed_pool(tmp_path, monkeypatch): ...
def test_judge_model_picks_the_class_override(): ...                   # merger -> deepseek-v4.1-flash-1017, contract -> qwen3.7-plus
def test_verify_mode_refuses_judge_models_and_references(): ...        # ruling 13: a non-default model, override or references -> ValidationError
def test_verify_mode_is_not_price_or_route_checked(): ...              # a verify section on a Modal profile preflights
```

- [ ] **Step 2: Run them to verify they fail.** Run: `.venv/bin/python -m pytest -q tests/test_correcting_judge.py -n 0 --no-cov`. Expected: FAIL, because `JudgeSpec` is not defined.
- [ ] **Step 3: Implement the spec, the refusals and the activation.**
  - Follow the `governor` pattern: a validator, `spec_core` hashing only when set, and `runtime` activation after `governor.activate`.
  - Price and pin checks reuse `api_budget.unpriced` and `provider_pins.load_pins` (`order: []` is unpinned). They run in correct mode only (ruling 13).
  - Leak and train-pool checks sit beside `heldout_seal.leak_errors` in `_prepare_dataset_rows`. The row's set and component come from `config/splits/runbook-v2/assignments.jsonl`.
- [ ] **Step 4: Run them to verify they pass.** Same command. Expected: PASS. Also run `tests/test_job_spec.py tests/test_job_preflight.py tests/test_governor.py`; expected: PASS.
- [ ] **Step 5: Commit.** `feat(judge): judge section, lock and preflight refusals (phase 4 step 1)`.

### Task 2: The record for both judges

**Files:**

- Create: `src/mailroom_sandbox/judge_record.py`.
- Modify: `src/mailroom_sandbox/vendor_hotfixes.py`: HF-025 install `_install_judge_node`, verify-mode branch only.
- Modify: `src/mailroom_sandbox/eval/runners.py` (`_run_pipeline_doc` only; find it by name, the line moves): copy `judge_rulings`, `before_judge` and `judge_corrected` from the scope.
- Test: `tests/test_correcting_judge.py`, `tests/test_vendor_hotfixes.py`.

**Interfaces:**

- Produces:
  - `judge_record.note_before(extracted: Mapping) -> None`: the first pass's cleaned extraction only; later passes do not overwrite it.
  - `judge_record.note_ruling(entry: Mapping) -> None`, which appends to `scope["judge_rulings"]`.
  - An entry holds: `{"pass": int, "mode": "verify"|"correct", "ruling": str, "score": float|None, "reason": str, "fixes": [FixCheck dicts], "retry_fields": [str], "wrong_fields": [str], "model": str}`.
  - In verify mode, `ruling` holds the vendored verdict.
  - `judge_record.note_corrected() -> None` sets `scope["judge_corrected"] = True` (ruling 15); Task 4 calls it when an accept applies a verified fix.

- [ ] **Step 1: Write the failing tests.**
  - `test_verify_mode_records_the_verdict_and_the_extraction_before_the_judge`: through `tests/_arbiter_harness.run`, a partial and then complete script. Expect two entries and `before_judge` equal to the first pass's cleaned extraction.
  - `test_no_judge_section_records_nothing`: the result has no `judge_rulings` key.
  - `test_hf025_is_registered_with_a_pinned_source`: pins `judge_verify_node`, `after_judge` and `agents.judge:CompletenessJudge.judge_completeness`; idempotent.
- [ ] **Step 2: Run to verify they fail.** Expected: FAIL, because HF-025 is missing.
- [ ] **Step 3: Implement HF-025 (verify branch) and the runners merge.** The node wrapper calls the original, then records the verdict when `correcting_judge.active()` is set.
- [ ] **Step 4: Run to verify they pass.** Expected: PASS, along with `tests/test_governor.py`.
- [ ] **Step 5: Commit.** `feat(judge): record rulings and the before-judge extraction (step 2)`.

### Task 3: Fix checking

**Files:**

- Create: `src/mailroom_sandbox/judge_fixes.py`.
- Test: `tests/test_judge_fixes.py`.

**Interfaces:**

- Consumes:
  - `gold_labels.locate(quote, doc_text) -> {start, end, text} | None`;
  - `gold_labels.evidence_support(doc_class, name, value, quotes) -> (bool, str)`.
- Produces:
  - `FixCheck = TypedDict(field, value, quote, verified: bool, why: str)`. `why` is one of `ok`, `not_requested`, `blank`, `quote_not_found`, `unsupported`.
  - `verify_fix(doc_class: str, doc_text: str, fix: Mapping, *, requested: Collection[str], subclass: str | None = None) -> FixCheck`. It passes `doc_subclass=subclass` to `evidence_support` when that function accepts the keyword (ruling 14).
  - `apply_fixes(extracted: Mapping, checks: list[FixCheck]) -> dict`: only verified fixes, with every other key kept.

- [ ] **Step 1: Write the failing tests.** Each uses a real two-sentence document text.
  - `test_a_quoted_supported_fix_is_verified`
  - `test_a_fix_can_never_blank_a_field`: `None`, `""` and `[]` give `blank`, even though `evidence_support` calls an empty value supported.
  - `test_a_quote_not_in_the_document_is_rejected`
  - `test_a_value_the_quote_does_not_support_is_rejected`
  - `test_a_fix_outside_the_requested_fields_is_rejected`: covers `_report`, `reasoning`, a field missing from `requested`, and a name outside `DEFAULT_FIELD_TYPES`.
  - `test_apply_fixes_writes_only_verified_values`
  - `test_verify_fix_passes_the_subclass_when_evidence_support_takes_it`: monkeypatch `evidence_support` with and without a `doc_subclass` keyword; the subclass reaches it only in the first case, and neither raises.
- [ ] **Step 2: Run to verify they fail.** Run: `.venv/bin/python -m pytest -q tests/test_judge_fixes.py -n 0 --no-cov`. Expected: FAIL (import error).
- [ ] **Step 3: Implement.** Check in this order: requested, blank, `locate`, then `evidence_support` on the located text.
- [ ] **Step 4: Run to verify they pass.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(judge): verify judge fixes against the source (step 3)`.

### Task 4: The correcting judge and its ruling

**Files:**

- Modify: `src/mailroom_sandbox/correcting_judge.py`: `CorrectingJudge`, `build_prompt`, `rule`.
- Modify: `src/mailroom_sandbox/vendor_hotfixes.py`: the HF-025 correct-mode branch.
- Modify: `src/mailroom_sandbox/mock_llm.py`: a `fake_structured_payload` branch for the correcting judge prompt, so `sandbox pilot --mock` stays offline.
- Test: `tests/test_correcting_judge.py`.

**Interfaces:**

- Consumes: Task 3 `verify_fix` and `apply_fixes`; Task 2 `note_ruling` and `note_before`; HF-024's `subclass_extraction.review_fields` (the requested fields).
- Produces:
  - `CorrectingJudge(BaseAgent)` with `agent_name = "judge"`. Its `self.model` is set from `judge_model(doc_type)`, and the client is the judge's OpenRouter client.
  - `build_prompt(*, doc_text, doc_type, subclass, extracted, requested_fields, guide, examples, attempts) -> str`. The **document comes first**, for provider caching, then guide definitions, examples, earlier attempts, the extraction and the instructions. The prompt starts with the fixed marker `"Rule on this extraction."`, which the mock and the harness match on.
  - `RULING_SCHEMA` holds `ruling` (enum `accept`, `retry_fields`, `human_review`), `score` (0..1), `reason`, `wrong_fields`, `retry_fields`, and `fixes` [{field, value, quote}].
  - `rule(state: Mapping, *, pass_no: int) -> dict` returns the entry from Task 2. A parse failure gets one re-ask with `JUDGE_REPAIR_NOTE`; a second failure raises `JudgeParseError`, which becomes `judge_error` and goes to review.
- **Node mapping (HF-025, correct mode):**
  - The node makes one call; there is no second accuracy call.
  - Accept with no unfixed wrong field: writes `judge_verdict: "complete"` and `extracted_data = apply_fixes(...)`. It also writes `judge_source_verified: True`, because the whole document was read.
  - Accept with an unfixed wrong field is treated as `retry_fields` on pass 1 and `human_review` on pass 2.
  - `retry_fields` writes `"partial"`; `human_review` writes `"incomplete"`.
  - Every case writes `judge_pass_count` (+1), `judge_score`, `judge_findings = [reason]`, and `attempt_history.record_verdict(...)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_prompt_puts_the_document_first`
  - `test_an_accept_applies_only_verified_fixes`
  - `test_an_accept_with_an_unfixed_wrong_field_retries_on_the_first_ruling`
  - `test_a_ruling_is_one_call`
  - `test_a_parse_failure_is_asked_once_then_reviewed`
  - `test_a_document_over_the_judge_context_goes_to_review`: fake model `context_length = 1000`, a 10,000-character document, zero calls, ruling `human_review`, reason `judge_input_too_long`.
  - `test_merger_documents_are_judged_by_the_class_model`
  - `test_the_judge_sees_only_the_requested_fields`: a subclass-dropped field is absent from the prompt and from `requested`.
- [ ] **Step 2: Run to verify they fail.** Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse `_with_model_call` and `_ask_once_more` for the re-ask. The token estimate is `call_guard.estimate_tokens`, and the context comes from `config/api_prices.yaml` `context_length`.
- [ ] **Step 4: Run to verify they pass.** Expected: PASS, along with `tests/test_vendor_hotfixes.py` and `tests/test_subclass_extraction.py`.
- [ ] **Step 5: Commit.** `feat(judge): one-step correcting ruling with verified fixes (step 4)`.

### Task 5: Arbiter pass-through, field-only retry, the two-ruling limit and the governor

**Files:**

- Modify: `src/mailroom_sandbox/vendor_hotfixes.py`:
  - HF-026 `_install_arbiter_passthrough` on `arbiter_node`;
  - HF-027 `_install_field_retry` on `retry_extract_node`, plus the route rule `"HF-027:judge_retry_rejudges"` on `retry_extract` (registered through `refresh`, like HF-011).
- Modify: `src/mailroom_sandbox/subclass_extraction.py`: a `fields_only(names)` context manager. `record_choice` restricts the chosen schema to `names` plus `confidence`/`reasoning`, so the retry asks only for the named fields.
- Modify: `src/mailroom_sandbox/governor.py`: in correct mode `arbiter` is not a round.
- Test: `tests/test_correcting_judge.py`, `tests/test_governor.py`.

**Interfaces:**

- Consumes: Task 4's last ruling from `scope["judge_rulings"][-1]`.
- Produces:
  - HF-026 (correct mode) makes no model call. It writes:
    - for a retry: `arbiter_decision: "retry_extraction"`, `arbiter_fields_to_fix`, `arbiter_retry_count` (+1);
    - for anything else: `"human_review"` with `arbiter_reasoning = ruling reason`.

    Verify mode passes through to the original.
  - HF-027 re-extracts with `fields_only(retry_fields)`. It merges the result into the previous `extracted_data`, replacing only the named fields, and records `kind="retry_extract"` history as the vendored node does.

- [ ] **Step 1: Write the failing tests.** They use `tests/_arbiter_harness.py`, extended with a `judge_rulings=[...]` script branch keyed on `"Rule on this extraction."`.
  - `test_the_arbiter_makes_no_call_in_correct_mode`
  - `test_a_retry_asks_only_for_the_named_fields`: the captured schema properties equal the named fields plus meta.
  - `test_a_retry_keeps_every_other_field`
  - `test_a_retry_returns_to_the_judge`
  - `test_a_second_ruling_cannot_retry`: rulings retry, then retry. Expected: stage `review`, 2 rulings, 1 retry.
  - `test_every_path_ends_within_two_rulings_and_one_retry`: a parametrized grid over rulings {accept, accept+unfixed, retry, human_review} × second rulings, with `VISIT_BOUND` never hit.
  - `test_a_matter_conflict_after_the_judge_goes_to_review_as_today`
  - `test_a_pass_through_arbiter_is_not_a_governor_round`
  - `test_call_counts_per_path_match_the_design` (stage 0, "call counts per path match the design"). Counted through the call guard:
    - accept, with or without fixes: 1 judge call;
    - human review: 1 judge call;
    - retry then any second ruling: 2 judge calls and 1 extraction call;
    - every path: 0 arbiter calls.
  - `test_every_governor_outcome_is_reached_with_the_correcting_judge` (spec step 5): parametrized over `archive_with_caveats`, `retry_budget`, `call_budget`, `spend_budget` and `boss_repeat`. Each ends at its outcome with `governor_stop` recorded and no hard-ceiling crash.
  - `test_rulings_and_retries_count_toward_the_governor_budgets`: a ruling's call is in the call budget, and a judge-ordered retry is a round.
- [ ] **Step 2: Run to verify they fail.** Expected: FAIL.
- [ ] **Step 3: Implement HF-026, HF-027, `fields_only` and the governor change.**
- [ ] **Step 4: Run to verify they pass.** Expected: PASS, along with `tests/test_governor.py`, `tests/test_vendor_hotfixes.py`, `tests/test_subclass_extraction.py` and `tests/test_experiments.py`.
- [ ] **Step 5: Commit.** `feat(judge): arbiter pass-through, field-only retry and governor budgets (steps 4-5)`.

### Task 6: Extra information: earlier attempts, guide definitions, the reference pool

**Files:**

- Create: `src/mailroom_sandbox/judge_references.py`.
- Create: `scripts/build_judge_reference_pool.py` (`--check`).
- Create: `config/judge/reference-pool-runbook-v2.jsonl` (generated, committed).
- Modify: `src/mailroom_sandbox/correcting_judge.py`, which feeds `build_prompt`.
- Test: `tests/test_judge_references.py`.

**Interfaces:**

- Produces:
  - `build_pool(assignments, interim, near_gold) -> list[dict]`. Rows hold `{doc_id, doc_class, subclass, set, component, fields: {name: {value, source: "near_gold"|"interim", evidence: [str]}}}`. Only `set ∈ {"calibration", "pool"}`; fields merge in the scorer's order (`gold_labels.apply_near_gold`, SHF-010), so an interim correction and an `original_header` fill stand over near-gold; `disputed` is excluded.
  - `examples(pool, doc_class, subclass, *, k, max_chars) -> list[dict]`: deterministic (sorted by doc id), same class and subtype, at most `k`.
  - `pool_leaks(pool, drawn: Mapping[id, component]) -> list[str]`.
  - `guide_for(doc_class, subclass) -> dict[str, str]`: `schema_guide.GUIDE_DESCRIPTIONS`, then the subclass field-list guide.
  - `attempts_for(state, *, max_chars) -> list[dict]`: `extraction_attempt_history`, bounded.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_pool_holds_only_calibration_and_pool_documents`
  - `test_the_pool_follows_the_scorers_truth_precedence` (shipped in place of `test_near_gold_wins_over_interim_on_a_field`)
  - `test_disputed_labels_are_left_out`
  - `test_examples_match_type_and_subtype_and_are_capped_at_two`
  - `test_a_drawn_document_sharing_a_component_with_the_pool_is_refused`: through preflight.
  - `test_the_committed_pool_is_current`
  - `test_the_label_counts_match_the_spec_table`: contract 94, corporate 122, correspondence 550, insurance 322, merger 5 (rebuilt after the 2026-11-28 rc.13 full-slice contract round; contract 44 after the rc.12 label rounds, 33 and corporate 120 after the corporate calibration gate-gap round, 32/118/4 for contract/corporate/merger before the 2026-11-27 corporate label integration, and corporate 119 after it).
  - `test_without_examples_the_prompt_has_none`
- [ ] **Step 2: Run to verify they fail.** Expected: FAIL.
- [ ] **Step 3: Implement, then generate the pool** with `.venv/bin/python scripts/build_judge_reference_pool.py`.
- [ ] **Step 4: Run to verify they pass.** Expected: PASS; `--check` exits 0.
- [ ] **Step 5: Commit.** `feat(judge): reference pool, examples, attempts and guide definitions (step 6)`.

### Task 7: Reports

**Files:**

- Modify: `src/mailroom_sandbox/job/gate.py`: `_judge_fields(out, row, pred)` in `_status`, and a `_judge_block(statuses)` beside the governor block.
- Modify: `src/mailroom_sandbox/job/routing_audit.py`: a `judge` block.
- Modify: `src/mailroom_sandbox/job/gate_compare.py`: `judge_compare(baseline_dir, judge_dir, bars)`, the success rules for stages 1 and 2.
- Test: `tests/test_correcting_judge.py`, `tests/test_gate_compare.py`.

**Interfaces:**

- Produces a gate `judge` block with:
  - `docs_judged`;
  - `rulings` by kind and pass;
  - `fixes` {proposed, verified, rejected by `why`, and, for verified fixes on scored fields, `right` and `wrong` against the ground truth (ruling 16)};
  - `judge_corrected`: the count of documents marked by ruling 15;
  - `retries`;
  - `score_before` and `score_after` on judged documents, labelled "after judge": `_score_pipeline_extraction(row, {"extracted_data": before_judge})` against the final score;
  - `calls_per_judged_doc` and `judge_related_calls_per_judged_doc` (ruling 17), `cost_per_judged_doc` by class, and `cached_prompt_tokens` when the usage reports them (the pilot measures caching);
  - `review_rate`, `wrong_archive_rate` and `crashes` on judged documents, using the gate's own outcomes;
  - `matter_conflicts`: judged documents with an unadjudicated conflict ("Each one is counted");
  - `governor_stops` by reason.
- `judge_compare` returns one check per success rule, each with its numbers and `pass`:
  - judge-related calls per judged document cut by at least 50%;
  - judge cost per judged document no higher, by class;
  - the paired score delta on judged documents, with its interval (ruling 18; stage 2 only, and reported but not gating in stage 1);
  - no more wrong archives;
  - no hard-ceiling crashes.

  It refuses two runs that drew different documents (`same_documents`).

- [ ] **Step 1: Write the failing tests.**
  - `test_the_gate_reports_rulings_fixes_and_scores_before_and_after`: two synthetic items.
  - `test_runs_without_a_judge_section_report_no_judge_block`
  - `test_fix_accuracy_scores_verified_fixes_against_the_truth`: one right fix and one wrong fix give `right: 1, wrong: 1`.
  - `test_judge_compare_applies_every_success_rule` (test_gate_compare): synthetic baseline and judge runs. Each rule passes once and fails once.
  - `test_judge_compare_refuses_runs_with_different_documents`
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify they pass.** Also run `tests/test_gate.py`, `tests/test_gate_causes.py`, `tests/test_gate_compare.py` and `tests/test_routing_calibration.py` (the routing audit's tests); expected: PASS.
- [ ] **Step 5: Commit.** `feat(judge): judge block in the gate and routing reports (step 7)`.

### Task 8: Models, pins and the stage configs

**Files:**

- Modify: `config/provider_pins.yaml`: `qwen/qwen3.7-plus: {order: [alibaba], allow_fallbacks: false}`.
- Create: stage 1 configs in `config/runs/`. All use the production setup, `dev-look1` (300), the governor on, and `judge_max_passes: 2`, `arbiter_retry_max: 1`:
  - `p4-s1-verify-gov-off.yaml`
  - `p4-s1-verify-gov-on.yaml`
  - `p4-s1-correct-refs.yaml`
  - `p4-s1-correct-norefs.yaml`
- Create: stage 2 configs on `dev` (900): `p4-s2-verify.yaml` and `p4-s2-correct-refs.yaml`.
- Test: `tests/test_correcting_judge.py`.

**Spend caps:**

- Each config's `job.api_cost_cap_usd` = 1.5 × (docs × the production pipeline cap per document + 2 rulings × the per-ruling cost, summed over the draw's documents by class).
- The production pipeline cap per document is $0.02 (`config/runs/production/slice-0250.yaml`: $5 for 250 documents).
- Per-ruling cost: $0.03 for qwen, $0.17 for mergers.
- Counting every drawn document as judged keeps the cap safe. The verify configs price only the pipeline term, since their judge is today's.
- Every config also has `job.max_wall_seconds`.

- [ ] **Step 1: Write the failing tests.**
  - `test_both_judge_models_are_priced_and_pinned`
  - `test_every_stage_config_preflights_offline`: preflight with network-free checks only; status ok; never `run start`.
  - `test_stage_caps_cover_two_rulings_per_document`
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Add the pin and write the configs.**
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit.** `feat(judge): judge model pins and stage 1/2 configs (step 8)`.

### Task 9: Docs and hand-over

**Files:**

- Modify:
  - `docs/jobs.md`: a section "Correcting judge (`judge:`)";
  - `docs/vendor-hotfixes.md` and `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md`: rows for HF-025 to HF-027;
  - `docs/critical-regressions.md`: guards named on rows 1, 3, 5, 6, 9, 12, 14, 15, 17 and 22;
  - `CHANGELOG.md`;
  - `docs/README.md`: index the upstream issues doc (this plan is already indexed).
- Create: `docs/design/specs/2026-11-26-correcting-judge-upstream-issues.md`, with drafts of the five upstream issues.
- Test: `tests/test_docs_drift.py`, `tests/test_doc_paths.py`.

- [ ] **Step 1:** Run the docs tests. Expected: FAIL on the missing HF-025 to HF-027 rows.
- [ ] **Step 2:** Write the docs.
- [ ] **Step 3:** Run them again. Expected: PASS.
- [ ] **Step 4: Commit.** Then open the PR with the template, pointing at this plan. Hand stage 0 (the offline proof is this PR's tests), stage 1 and stage 2 to the owner to launch.

## Risks and follow-ups

- **Field-only retry.** It depends on the specialists accepting a schema with only a few properties. The offline tests prove the request; the pilot proves the replies.
- **Caching savings.** These are provider-dependent. The caps assume no caching.
- **Insurance examples.** They are all `derived` interim labels, so their effect may be small.
- **Upstream issues.** Five drafts in the companion doc, for the owner to file.
- **#439 / #425 order.** See ruling 14. Whichever lands second regenerates the field lists and re-preflights the stage configs.
- **Label counts.** `test_the_label_counts_match_the_spec_table` pins the spec's table. If the built pool differs (labels changed since the spec), record a ruling, update the spec table with the built counts, and keep the test pinned to the committed pool.
