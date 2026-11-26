# Phase 2: loop governor and loop fixes — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** No document can stack retries, judge rounds, arbiter rounds and boss entries without limit. A
document whose budget runs out goes to a named outcome (`human_review` with a reason, or
`archive_with_caveats`) instead of crashing at the hard call ceiling. Five known wasted-call loops (L1-L5) are
closed.

**Architecture:** A new module, `src/mailroom_sandbox/governor.py`, holds the per-document budgets. It is
switched on by `job.governor`, which is saved in the lock. One hotfix, HF-018, wraps
`graph.route_spec.decide_route`, the single function every conditional edge calls (`route_spec.py:479-490`).
So the governor sees each final routing decision, after the router and the HF-011/HF-014 rules. Before a step
that adds a round, it either lets the step through and counts it, or redirects the document to its stop
outcome. Per-document counters live in the call guard's document scope (`job/call_guard.py:105`), next to
`judge_reasks`. The runner already merges that scope into the result, so `governor_stop` lands there too.

**L1-L5:**

- **L1:** a single transport retry layer, with every HTTP attempt counted.
- **L2:** no classify retry above the sorter's measured confidence ceiling.
- **L3:** a judge re-ask that carries a repair note.
- **L4:** duplicate linking before the conflict check.
- **L5:** a near-empty floor before any model call.

L1 is sandbox code (`provider_pins.py`); L3 changes HF-002/HF-013; L4 is HF-019; L2 is part of HF-018; L5 is in
the runner.

**Tech stack:** Python 3.11, pytest, the offline arbiter harness (`tests/_arbiter_harness.py`). No vendor edits.

**Spec:** `docs/superpowers/specs/2026-11-26-correcting-judge-design.md`, the sections "The loop governor (whole
pipeline)" and "The hardening programme", rows L1-L5. The governor's role in the judge is in "Plan" step 5.

## Resuming this work

Any agent can pick this up where the last one stopped. Phase 1 (#427) is merged. Execution is native
(`superpowers:executing-plans`), to save usage, unless the owner chooses otherwise.

- **Branch:** `claude/phase2-governor`; the draft PR points here. Work only on this branch. Never push to `main`,
  and never merge without the owner.
- **Where it stopped:** every task commits on its own, ticks its boxes in this file in the same commit, and puts
  `(phase2 task N)` in the commit subject. `git log --oneline origin/main..HEAD` shows the last finished task.
  The first task with an unticked box is next.
- **Confirm before continuing:** run the last ticked task's "Run the tests again" command. If it fails, fix that
  task first.
- **Uncommitted changes:** a half-done task shows in `git status`. Read its diff against the task's steps, then
  finish it, or stash it and redo it from Step 1.
- **Context to read first:** `CLAUDE.md`, the spec sections above, then this file from "Global constraints".
  Line numbers are from `5978123`; search by name if they have moved.
- **When every task is ticked:** do the hand-over in Task 8. The PR stays draft until CircleCI is green on its
  head; then ask the owner.

## Global constraints

- Never launch paid or live work. Every test is offline: the arbiter harness, fakes and `httpx.MockTransport`.
- Never hand-edit `vendor/`. Pipeline behaviour changes go in `vendor_hotfixes.py` with a pinned
  `source_sha256`.
- Never lower the coverage floor (84). Local checks run named files only, with `-n 0 --no-cov`.
- Commits use the `.gitmessage` shape. No `Claude-Session` trailer or claude.ai link; `Co-Authored-By` is fine.
- The governor is **off** unless `job.governor` is set. With it off, every routing decision and every result
  field is unchanged. L1 and L3 change always-on behaviour; they are bug fixes, recorded in the hotfix
  fingerprint.
- Any change to `vendor_hotfixes.py` changes the locked hotfix set. An unfinished run locked before this PR then
  resumes only with `--force` (spec "Safety rules"). Finished runs are unaffected.
- Spec defaults:
  - 2 retries per document;
  - 30 model calls per document, 36 for `merger_agreement`, below the hard ceiling of 40 (`CALL_CEILING`);
  - spend budget off until measured;
  - `transient_retry_max` keeps its own limit, and transient calls still count toward calls and spend.
- Critical regressions:
  - rows 5, 9, 10, 11, 12, 14 and 17 apply;
  - row 22 applies: a routing change that moves a document between review and archive needs a mark. Here
    `governor_stop` and `duplicate_of` are the marks.

## Changes from the design (decided while reading the code)

- **Where the governor hooks in.** The spec says "routing rules on the existing routers". A `RouteRule` only
  sees a read-only copy of the state (`route_spec.py:433`), and registered rules run in order, so a rule cannot
  see the final destination after HF-011 and HF-014. Wrapping `decide_route` sees the final answer for every
  node in one place. The counters stay out of graph state, in the document scope.
- **`archive_with_caveats` in this phase.** There are no judge fixes before phase 4. In this phase, "passed the
  judge and every field named wrong has a verified fix" means `judge_verdict == "complete"` with no
  `judge_findings`. The outcome routes to `compile_report`, the router's own archive path. Phase 4 adds verified
  fixes to the condition.
- **L1: no vendor patch is needed for the SDK retries.** The LangChain and Decisions paths already set
  `max_retries=0`. The native path builds `OpenAI()` with the SDK default (`llm/client.py:228-235`).
  `pinned_retry_chat_completion` turns SDK retries off only for the client it is given
  (`client.with_options(max_retries=0)`), so any other caller of that client keeps its own retries.
- **L1: the transport timeout is capped at the run deadline.** Nodes have no per-node deadline. The only
  deadline is the run's (`state["run_deadline"]`, `pipeline.limits.get_run_deadline()`), and Decisions already
  caps its timeout at it (`decision_backends.py:799-807`). This finishes the S2 item phase 1 moved here.
- **L2: the "measured ceiling" is a new governor setting.** No ceiling exists in config. `sorter_ceiling`
  (`job.governor.sorter_ceiling`, default off) is set per run, from the sorter's measured top confidence: 0.95
  for the Qwen sorter (audit `2026-11-15-pipeline-qwen-flash-25-failure-modes.md:73,147`). The retry prompt
  does differ from the first pass (it adds a preamble), but the audit shows it returns the same answer.
- **L3: the `TypeError` is already fixed.** The contract second pass `TypeError` came from a 200 response with
  `choices: null`. It was fixed upstream (`EmptyChoicesError`, `llm/retry.py:82-112`; llm-mailroom #261). L3
  here is only the repair re-ask. The no-`TypeError` test in `tests/test_judge_second_pass.py` stays as the
  guard.
- **L4: duplicates come from two sources.**
  - An exact duplicate has the same `file_sha256`. The state carries it (`build_graph.py:768`), and the
    catalog stores it per document.
  - A near duplicate has a word 5-shingle Jaccard similarity of at least 0.9 with a document seen earlier in
    the same process. Archived rows carry no text, so the index is in-process. After a restart, earlier copies
    escalate as they do today (no worse than now).
  - A conflict is cancelled only when **every** archived same-matter row of the same type is a duplicate. A
    genuine conflict with a third document is never hidden.
- **L5: the floor is in the runner, not the graph.** `entry_route` cannot reach `human_review`, and
  intake→classify is a plain edge, so the graph has no earlier hook. The runner has the text before
  `run_pipeline` (`eval/runners.py:1836`). The default floor is 64 characters. The near-empty documents seen so
  far are 32-56 characters (`docs/runbooks/production-slices.md:169-172`). That is well below the 200-character
  `input:near_empty` cause label, which stays as it is.
- **The cited L4 evidence moved.** `reports/dashboard/FLOOR_RUN_REPORT.md` has 63 lines. The evidence is at
  :36-39 and :46-48 (17 boss escalations, 34 calls, same-document re-ingestion).

## Review focus

- With the governor **off**, routing is identical. Pinned by Task 4's
  `test_governor_off_routes_every_harness_case_exactly_as_before`.
- A governor stop never crashes and never names a destination the node cannot reach. It falls back to
  `human_review`, which every round-adding node can reach. Pinned by Task 4's
  `test_every_stop_destination_is_wired_for_its_node`.
- Transient self-loops (`dest == node`) are not rounds, and HF-012 still bounds them. Pinned by Task 4's
  `test_a_transient_self_loop_is_not_counted_as_a_round`.
- Concurrent documents do not share counters (the scope is a `ContextVar`), and the near-duplicate index is
  locked. Pinned by Task 2's `test_two_threads_keep_separate_governor_counters` and Task 6's
  `test_the_near_duplicate_index_is_safe_across_threads`.
- A near duplicate never hides a conflict with another document. Pinned by Task 6's
  `test_a_conflict_with_a_non_duplicate_row_still_escalates`.

---

### Task 1: The `job.governor` switch

**Files:**

- Modify: `src/mailroom_sandbox/job/spec.py` (new `GovernorSpec`; `JobSpec.governor`; `spec_core` exclusion at
  :1423-1428; validator next to `_blind_in_pipeline` :1261)
- Create: `src/mailroom_sandbox/governor.py`
- Modify: `src/mailroom_sandbox/runtime.py:640-668` (activate from the lock)
- Modify: `src/mailroom_sandbox/job/preflight.py` (refuse the governor outside `task: pipeline`, like
  `_blind_routing_failure` :1381)
- Test: `tests/test_governor.py` (new)

**Interfaces:**

- Produces:
  - **`GovernorSpec`** (pydantic, `extra="forbid"`):
    - `retries: int = 2` (ge 0);
    - `calls: int = 30` (ge 1, lt 40);
    - `calls_by_class: dict[str, int] = {"merger_agreement": 36}` (each value ge 1, lt 40);
    - `spend_usd: float | None = None` (gt 0);
    - `sorter_ceiling: float | None = None` (gt 0, le 1);
    - `near_empty_chars: int = 64` (ge 0; 0 turns it off);
    - `link_duplicates: bool = True`;
    - `near_duplicate_jaccard: float = 0.9` (gt 0, le 1).
  - **`JobSpec.governor: GovernorSpec | None = None`:** a validator turns `True` into `GovernorSpec()` and
    `False` into `None`.
  - **In `governor.py`:**
    - `activate(spec: GovernorSpec | Mapping | None) -> None`;
    - `active() -> GovernorSpec | None`;
    - `call_budget(doc_type: str | None) -> int`.

- [x] **Step 1: Write the failing tests** in `tests/test_governor.py`:
  `test_governor_true_means_the_spec_defaults` (`GovernorSpec()` values as above, `calls_by_class ==
  {"merger_agreement": 36}`), `test_governor_is_hashed_only_when_set` (a spec without it keeps its
  `spec_core` hash), `test_governor_refuses_a_call_budget_at_the_hard_ceiling` (`calls=40` raises),
  `test_governor_is_refused_outside_pipeline` (preflight `{"name": "governor", "ok": False}` for `task:
  extract`), `test_the_lock_activates_the_governor` (`runtime.locked_runtime({..., "job": {"governor":
  {"retries": 1}}}, {})` → `governor.active().retries == 1`; an old lock without the key →
  `governor.active() is None`), `test_merger_call_budget_is_36` (`call_budget("merger_agreement") == 36`,
  `call_budget("contract") == 30`, `call_budget(None) == 30`).
- [x] **Step 2: Run them; they fail.** `.venv/bin/python -m pytest -q -n 0 --no-cov tests/test_governor.py`.
  Expected: errors on the missing `GovernorSpec` / `governor` module.
- [x] **Step 3: Implement** the spec model, the validator, the `spec_core` exclusion (`governor` excluded when
  `None`), the preflight refusal, `governor.activate/active/call_budget` (a module-level global under a lock, as
  `_ACTIVE_PIPELINE_HANDOFF`) and the activation in `runtime.py` (`governor.activate(locked_job.get("governor"))`;
  `None` when absent).
- [x] **Step 4: Run the tests again; they pass.** Same command, plus `tests/test_schema_guide.py
  tests/test_job_spec.py`.
- [x] **Step 5: Commit** `feat(governor): job.governor switch, spec defaults and lock activation (phase2 task 1)`.

### Task 2: Per-document counters in the call guard

**Files:**

- Modify: `src/mailroom_sandbox/job/call_guard.py` (`document()` :105-113, `after_call` :259-273, `settle`
  :212)
- Modify: `src/mailroom_sandbox/eval/runners.py:1758-1766` (merge the new scope fields into the result)
- Test: `tests/test_call_guard.py`, `tests/test_governor.py`

**Interfaces:**

- Consumes: nothing from Task 1.
- Produces:
  - **The `document()` scope** gains `llm_calls: int`, `spend_usd: float` and `governor: {"retries": 0,
    "boss": 0, "skipped_classify_retries": 0}`.
  - **`call_guard.scope() -> dict | None`:** the public accessor for the current document scope.
  - **`call_guard.note_failed_attempt() -> None`:** adds 1 to `calls` and to `llm_calls`.
  - **Counting rules:**
    - `after_call` adds 1 to `llm_calls` and the call's priced USD to `spend_usd` **before** the
      unarmed early return. `calls` keeps its current meaning: it is counted only when armed, for the ceiling.
    - A billed `settle` adds the charged reservation to `spend_usd`.
  - **Result fields** (present only when set):
    - `governor_stop` (the dict from Task 4);
    - `duplicate_of` (from Task 6);
    - `governor_skips` (`{"classify_retry": n}`, when n > 0).

- [x] **Step 1: Write the failing tests:**
  - `test_unarmed_calls_still_count_for_the_governor`: in a document scope with no budget armed,
    `after_call(usage)` twice gives `llm_calls == 2` and `calls == 0`.
  - `test_a_billed_failure_adds_its_charge_to_document_spend`;
  - `test_note_failed_attempt_counts_toward_the_ceiling`;
  - `test_two_threads_keep_separate_governor_counters`: two threads, each in its own `document()`, increment
    `scope()["governor"]["retries"]`, and each sees only its own;
  - `test_the_runner_merges_governor_stop_into_the_result`: a fake `_run_pipeline_doc` sets
    `call_guard.scope()["governor_stop"]`, and the item carries it.
- [x] **Step 2: Run them; they fail.** `.venv/bin/python -m pytest -q -n 0 --no-cov tests/test_call_guard.py
  tests/test_governor.py`.
- [x] **Step 3: Implement** the scope fields, `scope()`, `note_failed_attempt()`, the counting in `after_call` and
  `settle`, and the result merge next to `judge_reasks`.
- [x] **Step 4: Run the tests again; they pass.** Same command, plus `tests/test_job_runner.py
  tests/test_api_budget.py`.
- [x] **Step 5: Commit** `feat(call-guard): per-document calls, spend and governor counters (phase2 task 2)`.

### Task 3: L1 — one retry layer, every HTTP attempt counted, timeout capped at the run deadline

**Files:**

- Modify: `src/mailroom_sandbox/provider_pins.py:355-381` (`pinned_retry_chat_completion`)
- Test: `tests/test_provider_pins.py`

**Interfaces:**

- Consumes: `call_guard.note_failed_attempt()` (Task 2), and `_guard_call(prompt_tokens, completion_tokens) ->
  float` plus `call_guard.settle` / `billed_failure` from phase 1.
- Produces: `_AttemptGuardedClient(client)`, a proxy whose `.chat.completions.create(**kw)` does four things:
  - reserves through `_guard_call`;
  - caps `kw["timeout"]` at `pipeline.limits.get_run_deadline() - time.time()`, with a 1-second floor; past
    the deadline it raises `RunDeadlineExceeded` before sending;
  - sends through `client.with_options(max_retries=0)` (the client itself when it has no `with_options`);
  - on an exception, settles with `billed=billed_failure(exc)` and calls `note_failed_attempt()`; on a return,
    settles with `billed=False`.

  Every other attribute is passed through.

- [x] **Step 1: Write the failing tests:**
  - `test_each_http_attempt_reserves_and_settles_once`: a fake client fails twice with a 5xx, then returns.
    That gives 3 reservations; 2 are charged and 1 is released, and `calls` rises by 2 for the failures.
  - `test_sdk_retries_are_off_under_the_wrapper`: the fake records the `max_retries=0` passed to
    `with_options`.
  - `test_the_attempt_timeout_never_outlives_the_run_deadline`: with the deadline 5 s ahead and a 600 s
    request timeout, the sent timeout is ≤ 5.
  - `test_no_attempt_is_sent_past_the_run_deadline`;
  - `test_a_client_without_with_options_still_works`.
- [x] **Step 2: Run them; they fail.** `.venv/bin/python -m pytest -q -n 0 --no-cov tests/test_provider_pins.py`.
- [x] **Step 3: Implement** `_AttemptGuardedClient`, and pass it to the vendored `retry_chat_completion` in place
  of the single `_guard_call` around the whole loop.
- [x] **Step 4: Run the tests again; they pass.** Same command, plus `tests/test_call_guard.py
  tests/test_decision_transport.py tests/test_stress_harness.py`.
- [x] **Step 5: Commit** `fix(provider-pins): one retry layer, every HTTP attempt guarded, deadline-capped timeout (phase2 task 3)`.

### Task 4: The governor (HF-018), with L2

**Files:**

- Modify: `src/mailroom_sandbox/governor.py` (budgets, outcomes, L2)
- Modify: `src/mailroom_sandbox/vendor_hotfixes.py` (HF-018 on `graph.route_spec.decide_route`, after HF-017
  in `HOTFIXES`)
- Test: `tests/test_governor.py` (harness cases), `tests/test_vendor_hotfixes.py` (registry and source pin)

**Interfaces:**

- Consumes: `active()`, `call_budget()` (Task 1); `call_guard.scope()` (Task 2).
- Produces:
  - **`ROUND_DESTINATIONS = frozenset({"retry_classify", "retry_extract", "arbiter", "boss_escalation"})`.**
  - **`govern(node: str, state: Mapping, proposed: str, destinations: Collection[str]) -> str`**, in this
    order:
    1. Governor off, or no document scope: return `proposed`.
    2. **L2:** node `classify`, `proposed == "retry_classify"`, `sorter_ceiling` set,
       `state["classification_confidence"] >= sorter_ceiling` and `"review_classify"` in destinations. Return
       `"review_classify"` and add 1 to `skipped_classify_retries`. This is not a round.
    3. `proposed` not in `ROUND_DESTINATIONS`, or `proposed == node` (a transient self-loop): return
       `proposed`.
    4. Stop reasons, first match wins:
       - `boss_repeat`: `proposed == "boss_escalation"` and `boss >= 1`;
       - `retry_budget`: `retries >= spec.retries`;
       - `call_budget`: `llm_calls >= call_budget(state.get("doc_type"))`;
       - `spend_budget`: `spend_usd` set and the document's spend is at least that.
    5. On a stop, return `stop_destination(state, destinations)`: `"compile_report"`
       (`archive_with_caveats`) when `state["judge_verdict"] == "complete"`, `not state.get("judge_findings")`
       and `"compile_report"` is in destinations; otherwise `"human_review"`. Record `scope["governor_stop"] =
       {"reason", "outcome", "node", "proposed", "calls", "retries", "spend_usd"}` on the first stop only.
    6. Otherwise add 1 to `retries` (and to `boss` for a boss entry) and return `proposed`.
  - **HF-018** wraps `decide_route(spec, state)`: `dest = original(spec, state)`, then `return
    governor.govern(spec.node, state, dest, tuple(spec.destinations))`.

- [ ] **Step 1: Write the failing tests**, using `tests/_arbiter_harness.py` (`Script`, `run`) with
  `governor.activate(...)` and a `call_guard.document()` scope around each run:
  - **Governor off:** `test_governor_off_routes_every_harness_case_exactly_as_before`. For each
    `test_arbiter_termination.CASES` case, the path with HF-018 installed and the governor off equals the path
    with HF-018's wrapper bypassed.
  - **Each stop outcome:**
    - `test_the_retry_budget_sends_a_third_round_to_review`: judge partial ×3 with a retrying arbiter. Stage
      `review`, `governor_stop.reason == "retry_budget"`, `retries == 2`.
    - `test_the_call_budget_stops_before_a_round` (pre-set `llm_calls` to 30): `reason == "call_budget"`.
    - `test_mergers_get_36_calls`: at 30 calls a `merger_agreement` still retries; at 36 it stops.
    - `test_a_second_boss_entry_is_boss_repeat`;
    - `test_spend_budget_off_by_default_and_on_when_set`;
    - `test_a_passed_extraction_stops_as_archive_with_caveats`: `judge_verdict "complete"`, no findings, budget
      spent at a boss entry. Stage `archived`, `outcome == "archive_with_caveats"`.
  - **Wiring and safety:**
    - `test_every_stop_destination_is_wired_for_its_node`: for each `ROUTE_SPECS` node that can propose a
      round destination, `human_review` is in its destinations.
    - `test_a_transient_self_loop_is_not_counted_as_a_round`;
    - `test_the_hard_ceiling_still_backs_up_the_governor`: `CALL_CEILING["pipeline"] == 40` and the governor's
      largest budget is 36.
  - **L2:**
    - `test_l2_skips_a_classify_retry_at_the_sorter_ceiling`: contract at 0.95 with `sorter_ceiling` 0.95. Path
      `classify → review_classify`, no `retry_classify`, `governor_skips == {"classify_retry": 1}`.
    - `test_l2_off_keeps_the_classify_retry`.
  - **Registry:** `test_hf018_is_registered_with_a_pinned_source` in `tests/test_vendor_hotfixes.py`.
- [ ] **Step 2: Run them; they fail.** `.venv/bin/python -m pytest -q -n 0 --no-cov tests/test_governor.py
  tests/test_vendor_hotfixes.py`.
- [ ] **Step 3: Implement** `govern`, `stop_destination` and HF-018, with the `source_sha256` of the vendored
  `decide_route`, computed as `_source_sha` does.
- [ ] **Step 4: Run the tests again; they pass.** Same command, plus `tests/test_arbiter_termination.py
  tests/test_pipeline_routing_matrix.py tests/test_arbiter_floor_route_differential.py`.
- [ ] **Step 5: Commit** `feat(governor): HF-018 per-document round budgets and stop outcomes, L2 classify skip (phase2 task 4)`.

### Task 5: L3 — the judge re-ask carries a repair note (HF-002, HF-013)

**Files:**

- Modify: `src/mailroom_sandbox/vendor_hotfixes.py:110-135` (`_ask_once_more`)
- Test: `tests/test_vendor_hotfixes.py`, `tests/test_arbiter_termination.py` (existing parse cases stay green)

**Interfaces:**

- Produces: `JUDGE_REPAIR_NOTE`, a module constant:

  ```text
  Your previous reply could not be read as the required JSON object. Reply again with only that JSON object, no
  other text. Your previous reply began:
  <first 1,000 characters of the raw reply>
  ```

  `_ask_once_more` captures the first attempt's `_raw` and appends the note to the user message of the re-ask
  only. Both judge modes (completeness, correctness) use it.

- [ ] **Step 1: Write the failing tests:**
  - `test_the_completeness_reask_carries_the_repair_note_and_the_first_reply`: patch `_call_structured` to
    return `{"_raw": "not json", "_parse_error": True}` once, then a valid answer. The second user message
    ends with the note and contains `not json`.
  - `test_the_correctness_reask_carries_the_repair_note`: the same, for correctness.
  - `test_a_first_answer_that_parses_sends_no_note`.
- [ ] **Step 2: Run them; they fail.** `.venv/bin/python -m pytest -q -n 0 --no-cov tests/test_vendor_hotfixes.py`.
- [ ] **Step 3: Implement** the capture and the note in `_ask_once_more`, keeping its current counting
  (`note_judge_reask/parked/recovered`) and its `JudgeParseError` on a second failure.
- [ ] **Step 4: Run the tests again; they pass.** Same command, plus `tests/test_arbiter_termination.py
  tests/test_judge_second_pass.py`.
- [ ] **Step 5: Commit** `fix(judge): HF-002/HF-013 re-ask with a repair note instead of the same request (phase2 task 5)`.

### Task 6: L4 — link duplicates before the conflict check (HF-019)

**Files:**

- Modify: `src/mailroom_sandbox/governor.py` (duplicate index)
- Modify: `src/mailroom_sandbox/vendor_hotfixes.py` (HF-019 on `graph.build_graph._detect_conflict`)
- Test: `tests/test_governor.py`, `tests/test_vendor_hotfixes.py`

**Interfaces:**

- Consumes: `active()`, `call_guard.scope()`.
- Produces:
  - **`shingles(text: str) -> frozenset[str]`:** word 5-shingles of the casefolded, whitespace-collapsed text.
  - **`note_seen(matter_id, doc_id, text) -> None`:** records the document in the in-process index, under a
    lock. `activate()` resets the index.
  - **`duplicate_of(state, archived_rows: list) -> dict | None`:** returns `{"doc_id", "kind":
    "exact"|"near", "similarity"}` when every archived same-matter row of the state's `doc_type` is a
    duplicate, by equal `file_sha256` or Jaccard ≥ `near_duplicate_jaccard`. Otherwise `None`.
  - **HF-019** wraps `_detect_conflict(state, extracted)`:
    - calls the original;
    - with the governor on, `link_duplicates` set and a conflict found, it reads
      `storage.catalog.get_matter_documents` through `module._run_coro` and asks `duplicate_of`;
    - on a match it records `scope["duplicate_of"]` and returns `(False, [])`;
    - it always calls `note_seen` for the current document.

- [ ] **Step 1: Write the failing tests:**
  - `test_an_exact_re_ingestion_is_linked_not_escalated`: the same `file_sha256` gives no boss call,
    `duplicate_of.kind == "exact"`, and an archived stage.
  - `test_a_near_duplicate_is_linked`: one word changed in a 300-word document gives `kind == "near"` and
    similarity ≥ 0.9.
  - `test_a_conflict_with_a_non_duplicate_row_still_escalates`: one duplicate row plus one different
    same-type row reaches `boss_escalation`.
  - `test_duplicates_are_not_linked_with_the_governor_off`;
  - `test_the_near_duplicate_index_is_safe_across_threads`: 8 threads each call `note_seen`, and every entry
    is present.
  - `test_hf019_is_registered_with_a_pinned_source`.
- [ ] **Step 2: Run them; they fail.** `.venv/bin/python -m pytest -q -n 0 --no-cov tests/test_governor.py
  tests/test_vendor_hotfixes.py`.
- [ ] **Step 3: Implement** `shingles`, `note_seen`, `duplicate_of` and HF-019 (pinned source of
  `_detect_conflict`).
- [ ] **Step 4: Run the tests again; they pass.** Same command, plus `tests/test_arbiter_termination.py`.
- [ ] **Step 5: Commit** `feat(governor): HF-019 links exact and near duplicates before the conflict check (phase2 task 6)`.

### Task 7: L5 — near-empty documents go to review before any model call

**Files:**

- Modify: `src/mailroom_sandbox/eval/runners.py` (`_run_pipeline_doc_once`, about :1836)
- Test: `tests/test_governor.py`

**Interfaces:**

- Consumes: `active()` (Task 1); the result shape from Task 2.
- Produces: with the governor on and `near_empty_chars > 0`, a document whose `len(text.strip()) <
  near_empty_chars` returns, without calling `run_pipeline`, an item with:
  - `stage "review"`;
  - `review_causes ["near_empty"]`;
  - `governor_stop {"reason": "near_empty", "outcome": "human_review", "node": "intake", "calls": 0,
    "retries": 0, "spend_usd": 0.0}`.

  It goes through the same item builder as every pipeline result.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_40_character_document_goes_to_review_with_no_model_call`: `run_pipeline` is a fake that fails if
    called.
  - `test_a_64_character_document_runs_normally`;
  - `test_near_empty_is_off_with_the_governor_off`;
  - `test_near_empty_rows_are_scored_as_review`: `job/gate.py` gives the outcome `review` for the row.
- [ ] **Step 2: Run them; they fail.** `.venv/bin/python -m pytest -q -n 0 --no-cov tests/test_governor.py`.
- [ ] **Step 3: Implement** the floor check and the review item.
- [ ] **Step 4: Run the tests again; they pass.** Same command, plus `tests/test_job_runner.py
  tests/test_pipeline_concurrency.py`.
- [ ] **Step 5: Commit** `feat(governor): L5 near-empty documents go to review before any model call (phase2 task 7)`.

### Task 8: Gate report, docs and hand-over

**Files:**

- Modify: `src/mailroom_sandbox/job/gate.py:487-501` (aggregate `governor_stop` by reason and outcome,
  `duplicate_of` by kind, `governor_skips`), `src/mailroom_sandbox/job/gate_causes.py:256-280` (the mechanism
  cause `governor:<reason>` for a row with `governor_stop`)
- Modify: `docs/vendor-hotfixes.md` (HF-018 and HF-019 rows; the HF-002/HF-013 rows mention the repair note),
  `docs/jobs.md` (a `job.governor` section: fields, defaults, outcomes, the `--force` note),
  `docs/critical-regressions.md` (cite the row 17 and row 22 guards), `CHANGELOG.md`
- Test: `tests/test_gate.py` (or the existing gate test file that covers `judge_reasks`)

- [ ] **Step 1: Write the failing tests:**
  - `test_the_gate_counts_governor_stops_by_reason`;
  - `test_a_governor_stop_is_its_own_cause`;
  - `test_duplicates_are_counted_in_the_gate`.
- [ ] **Step 2: Run them; they fail.** Run the gate test file with `-n 0 --no-cov`.
- [ ] **Step 3: Implement** the aggregation and the cause, then write the docs.
- [ ] **Step 4: Run every file this phase touched:**

  ```bash
  .venv/bin/python -m pytest -q -n 0 --no-cov tests/test_governor.py tests/test_call_guard.py \
    tests/test_provider_pins.py tests/test_vendor_hotfixes.py tests/test_arbiter_termination.py \
    tests/test_judge_second_pass.py tests/test_job_runner.py tests/test_pipeline_concurrency.py \
    tests/test_job_spec.py <the gate test file>
  ```

  Also run ruff, markdownlint, `scripts/check_cli_surface.py --check` and `sandbox runbook check`.
- [ ] **Step 5: Commit** `docs(governor): gate counts, causes, hotfix rows and job.governor guide (phase2 task 8)`.
- [ ] **Step 6: Hand over.**
  1. Have one fresh reviewer on the most capable model review the whole branch, and fix its Critical and
     Important findings with tests.
  2. Fill the PR's critical-regressions rows 5, 9, 10, 11, 12, 14, 17 and 22.
  3. Draft the upstream llm-mailroom issues (HF-018, HF-019, L3) in the PR body, unfiled.
  4. Wait for CircleCI green on the head, then ask the owner about ready-for-review.
