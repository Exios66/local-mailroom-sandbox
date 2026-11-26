# Phase 1: spend safety — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** A resumed run never pays again for a finished document, and a paid run's API spend stops at its cap
rather than one call per concurrent document past it.

**Architecture:** S1 — the whole-run delegates (`run_pipeline_eval`, `run_isolated_eval`) take a `replay` map of
the items an earlier attempt persisted. Each replayed document goes through the normal scoring path with its
stored answer and no model call, so run-level scores still cover every locked document. S2 — the call guard
reserves each request's worst-case cost before it goes out and settles it when the request ends. A failed
request that may have been billed is charged at its reservation, and that charge is persisted for a later
resume.

**Tech stack:** Python 3.11, pytest. No vendor edits: every change is in `src/mailroom_sandbox/`.

**Spec:** `docs/superpowers/specs/2026-11-26-correcting-judge-design.md`, "The hardening programme", rows S1 and S2.

## Resuming this work

Any agent can pick this up where the last one stopped. The owner approved the design. Execution is native
(`superpowers:executing-plans`), chosen to save usage.

- **Branch:** `claude/phase1-spend-safety`; the draft PR points here. Work only on this branch. Never push to
  `main`, and never merge without the owner.
- **Where it stopped:** every task commits on its own, ticks its boxes in this file in the same commit, and puts
  `(phase1 task N)` in the commit subject. `git log --oneline origin/main..HEAD` shows the last finished task.
  The first task with an unticked box is next.
- **Confirm before continuing:** run the "Run the tests again" command of the last ticked task. If it fails,
  fix that task before starting the next one.
- **Uncommitted changes:** a task left half done shows in `git status`. Read its diff against the task's steps,
  then finish it or discard it (`git stash`) and redo it from Step 1.
- **Context to read first:** `CLAUDE.md`, the spec section named above, then this file from "Global
  constraints". Line numbers here are from `e344b0b`, so search by name if they have moved.
- **When every task is ticked:** do the hand-over steps at the end, then ask the owner whether to mark the PR
  ready for review.

## Global constraints

- Never launch paid or live work. Every test is offline: fakes for `_run_pipeline_doc`, `_predict_spec` and the
  transport.
- Never hand-edit `vendor/`. Never lower the coverage floor (84).
- Local checks: named test files only, `-n 0 --no-cov`. The full suite and coverage run in CircleCI.
- Commits use the `.gitmessage` shape. No `Claude-Session` trailer or claude.ai link; `Co-Authored-By` is fine.
- Critical regressions rows 5 (spend guard, understated cost) and 9 (resume corrupting a measurement) apply. The
  PR fills both.

## Changes from the design (decided while reading the code)

- **S1.** The design said "pass only unfinished documents to the run". That would silently score a resumed run
  on its new documents only, because the delegates compute run scores and the experiment-log record over the
  rows they are given (`eval/runners.py:1520-1597`, `:520-560`). Replay keeps every row in the run and removes
  only the model call.
- **S1 side effect: scores now match the saved answers.** Today a resumed run's run-level scores come from the
  re-run answers, while `items.jsonl` keeps the first answers. After S1 both come from the first answers.
- **S2: in-flight documents are already counted.** In-flight documents are already counted at the mean finished
  cost (`ApiBudget.projected_usd`). What is missing is a bound below one call: the first wave has no mean yet,
  and a single long-document call can cost more than a small cap. The per-request reservation closes both.
- **S2: two items move to phase 2.** Capping the transport timeout at the node deadline, and counting every HTTP
  attempt inside `retry_chat_completion`, go to L1 (retry layers). Both change the vendored retry path that L1
  rewrites. Until then, a request that succeeds after internal retries is settled once, as today.
- **S2: no change to the preflight estimate.** With a hard per-request bound, the preflight estimate no longer
  controls spend. A cap too small for the largest document now fails that document at its first call with a
  reason naming the estimate. A preflight warning for this is a follow-up, not phase 1.

## Review focus

1. A resume where every locked document was already persisted. No model call is made, the run ends `done`, and
   the scores cover all documents.
2. Replayed rows must not count as new spend. They do not call `ApiBudget.add_usage`, which would lower the
   mean-cost projection, and they write no `RERUN_USAGE_EVENT`, which would double-count spend on the next
   resume.
3. A stored item with no dict `pred` (written by an older runner) is not replayed: it re-runs, as today.
4. A reservation is always settled, including on the LangChain exception path; a leaked reservation would block
   every later call.
5. A request rejected by the provider (HTTP 4xx) or never connected is released, not charged. A timeout, 5xx or
   dropped response is charged at its reservation.

---

### Task 1: Replay persisted documents in `run_pipeline_eval`

**Files:**

- Modify: `src/mailroom_sandbox/eval/runners.py` (`run_pipeline_eval`, `_record` at :1448, both loops at
  :1468-1515)
- Test: `tests/test_pipeline_concurrency.py`

**Interfaces:**

- Produces: `run_pipeline_eval(..., replay: Mapping[Any, Mapping[str, Any]] | None = None)`. `replay` maps a row
  id to its persisted item, which has `pred`, `latency_ms` and the usage keys.
- Produces: `REPLAY_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "llm_calls", "call_usage",
  "usage_by_agent", "cached_tokens", "cache_write_tokens", "reported_cost_usd")` and
  `replayable(item: Mapping[str, Any] | None) -> bool` in `eval/runners.py`: True when `pred` is a dict.

- [x] **Step 1: Write the failing tests** in `tests/test_pipeline_concurrency.py`, using `_install`:
  - `test_a_replayed_document_is_scored_without_a_model_call`. Use 4 rows; `replay` holds rows "0" and "2" with
    `pred` = the fake's result and `prompt_tokens: 100`; concurrency 2. Assert `state["started"] == ["1", "3"]`
    (sorted), `result["scores"]["class_correct"] == 1.0` and `len(result["docs"]) == 4`. Assert that the row_cb entries for "0" and "2" carry `replayed: True` and `prompt_tokens: 100`.
  - `test_replayed_documents_are_not_added_to_the_api_budget`. Use a stub budget recording `add_usage` and
    `check` calls; assert `add_usage` is called for "1" and "3" only.
  - `test_a_run_that_is_all_replay_makes_no_model_call`. Every row is replayed; assert `state["started"] == []`
    and the scores are as in a full run.
  - `test_an_item_without_a_dict_pred_is_run_again`. `replay` holds `{"0": {"pred": None}}`; assert "0" is in
    `started`.
- [x] **Step 2: Run them and see them fail**
  `.venv/bin/python -m pytest -q tests/test_pipeline_concurrency.py -n 0 --no-cov`. Expected: TypeError (no
  `replay` kwarg).
- [x] **Step 3: Implement.**
  - Before either loop, record every replayable row on the main thread: call `_record(index, dict(item["pred"]),
    usage, float(item.get("latency_ms") or 0.0), window, replayed=True)`. Here `usage` holds the
    `REPLAY_USAGE_KEYS` present, and `window` comes from the item's `started_at_ns` / `finished_at_ns` when
    both are ints.
  - `_record` gains `replayed: bool = False`. When True, skip `api_budget.add_usage` and add `"replayed": True`
    to the row_cb entry.
  - Both loops iterate only the indices not yet in `by_index`, and `_check_caps` runs only before those.
  - `results`, the scores and the experiment-log record are unchanged: they read `by_index` for every index.
- [x] **Step 4: Run the tests again; they pass.** Run the same command plus `tests/test_dojo_cost_alignment.py`.
- [x] **Step 5: Commit** `feat(resume): replay persisted pipeline documents instead of re-running them (phase1 task 1)`.

### Task 2: Replay persisted rows in `run_isolated_eval`

**Files:**

- Modify: `src/mailroom_sandbox/eval/runners.py` (`_run_rows_bounded` :149, `run_isolated_eval` :287, its
  `_record` :479)
- Test: `tests/test_job_runner.py` (next to the `_run_rows_bounded` tests at :353)

**Interfaces:**

- Consumes: `REPLAY_USAGE_KEYS` and `replayable` (Task 1).
- Produces: `run_isolated_eval(..., replay: Mapping[Any, Mapping[str, Any]] | None = None)`.
- Produces: `_run_rows_bounded(..., skip: Collection[int] = ())`. Skipped indices never start and never call
  `guard`. `order`, when given, must be a permutation of the indices that are not skipped.

- [x] **Step 1: Write the failing tests.**
  - `test_run_rows_bounded_skips_indices` (workers 1 and 3): `skip={1}`; assert `run_one` saw only 0 and 2, and
    `guard` was called twice at most.
  - `test_an_isolated_replay_keeps_the_stored_answer_and_score`. Monkeypatch `eval_runners._predict_spec` to
    count calls. Use 3 sorter fixture rows with row 0 replayed (`pred`, `score` `{"match": 1.0}`, `error: None`).
    Assert one fewer predict call, `scores["n"] == 3`, and that the replayed entry's score is the stored one.
- [x] **Step 2: Run and see them fail**
  `.venv/bin/python -m pytest -q tests/test_job_runner.py -k "run_rows_bounded or isolated_replay" -n 0
  --no-cov`.
- [x] **Step 3: Implement.** Before `_run_rows_bounded`, record each replayable row on the main thread with
  `_record(index, entry, replayed=True)`. The entry is `{"id", "pred", "score", "error",
  "offline_fallback": False, "replayed": True, latency and usage from the item}`; the stored score is kept
  because the scorer and truth are locked. `_record` skips `api_budget.add_usage` when replayed. Then pass
  `skip=` the replayed indices.
- [x] **Step 4: Run the tests again; they pass.**
- [x] **Step 5: Commit** `feat(resume): replay persisted isolated rows instead of re-running them (phase1 task 2)`.

### Task 3: The job runner passes the replay map, and replayed rows are not re-billed

**Files:**

- Modify: `src/mailroom_sandbox/job/runner.py`. This covers `_run_whole_run` at :262-470, where `replay` is built
  next to `persisted` (:327) and passed to `run_pipeline_eval`, `_isolated`, the `isolated` branch and the agent
  branch, but not to `extract`, `chained`, `local_vs_api` or `sorter_vs_modernbert`, which persist nothing
  mid-run. It also covers `_persist_isolated_items` at :867 and `_row_sink`.
- Modify: `docs/jobs.md`, or the page that describes whole-run resume (find it with `grep -rn "resume" docs/jobs.md`).
  Say that a resume replays finished documents.
- Test: `tests/test_job_runner.py`

**Interfaces:**

- Consumes: `replay=` on both delegates (Tasks 1 and 2).

- [x] **Step 1: Write the failing tests.**
  - `test_a_resumed_pipeline_run_bills_only_unfinished_documents`. Use `_prepped_store(rows=4, job={"mock": True,
    "concurrency": 1})` with the lock task set to `pipeline` (as at :205). On the first attempt the fake
    `_run_pipeline_doc` raises on `d2`. On the second, it counts calls. Assert the second attempt called it for
    `d2` and `d3` only, the final state is `done`, `len(store.load_items()) == 4`, and `summary["cursor"] == 4`.
  - `test_a_replayed_row_writes_no_rerun_usage_event`. Call `_persist_isolated_items` with a row that has
    `replayed: True` and an id in `rebilled`; assert no `RERUN_USAGE_EVENT`.
  - Keep `test_a_resumed_whole_run_counts_the_tokens_of_a_document_it_billed_again` passing unchanged: a fake
    delegate that ignores `replay` still gets the safety net.
- [x] **Step 2: Run and see them fail**
  `.venv/bin/python -m pytest -q tests/test_job_runner.py -k "resume or rerun or rebill" -n 0 --no-cov`.
- [x] **Step 3: Implement.**
  - `replay = {i["item_id"]: i for i in prior_items if i.get("item_id") is not None and replayable(i)}`.
  - In `_persist_isolated_items`, a row with `replayed` skips the `rebilled` branch.
  - `_row_sink` does not echo replayed rows; progress still moves.
  - Update the comment at :327-329.
- [x] **Step 4: Run the tests again; they pass.** Also run `tests/test_console_log.py`.
- [x] **Step 5: Commit** `fix(resume): stop re-billing finished documents on a whole-run resume (S1) (phase1 task 3)`.

### Task 4: `ApiBudget` reservations and unreported charges

**Files:**

- Modify: `src/mailroom_sandbox/job/api_budget.py` (`ApiBudget` :140-219, `usage_records` :226, `budget_for`
  :233)
- Test: `tests/test_api_budget.py`

**Interfaces:**

- Produces on `ApiBudget`:
  - `estimate_call_usd(prompt_tokens: float, completion_tokens: float) -> float`, which is `_cost(p, c, 1)`;
  - `reserve(usd: float) -> None` and `release(usd: float) -> None`, which keep `reserved_usd` and floor it at 0;
  - `charge_unreported(usd: float) -> None`, which adds to `live_usd` and to `unreported_usd`;
  - `exceeded(in_flight: int = 0, extra_usd: float = 0.0)`, whose projection is
    `max(projected_usd(in_flight), live_total_usd() + reserved_usd + extra_usd)`. The message names the
    reservation when it is non-zero.
- Produces: `UNREPORTED_CHARGE_EVENT = "api_unreported_charge"`. `usage_records` includes its details, and
  `add_usage` adds a record's `unreported_usd` without counting a document when `kind == "unreported_charge"`.
  The live window of a resumed run is unaffected: `start_live` keeps reading `spent_usd`.

- [x] **Step 1: Write the failing tests:**
  - `test_a_reservation_counts_against_the_cap_until_released`;
  - `test_extra_usd_refuses_a_call_that_would_pass_the_cap`;
  - `test_an_unreported_charge_is_spend_and_survives_a_resume`. Use a store event with `unreported_usd: 0.05`,
    so `budget_for(lock, usage_records(store)).spent_usd == 0.05` and `documents == 0`;
  - `test_release_never_goes_below_zero`.
- [x] **Step 2: Run and see them fail** `.venv/bin/python -m pytest -q tests/test_api_budget.py -n 0 --no-cov`.
- [x] **Step 3: Implement** under the existing `self._lock`.
- [x] **Step 4: Run the tests again; they pass.**
- [x] **Step 5: Commit** `feat(api-budget): reserve in-flight calls and keep unreported charges (phase1 task 4)`.

### Task 5: The call guard reserves before a request and settles after it

**Files:**

- Modify: `src/mailroom_sandbox/job/call_guard.py`, including its module docstring: spend now stops before the
  cap, within the estimate's error.
- Modify: `src/mailroom_sandbox/job/runner.py` at :1131-1135. Before `call_guard.disarm()`, persist the armed
  budget's `unreported_usd` as an `UNREPORTED_CHARGE_EVENT` when it is non-zero.
- Test: `tests/test_call_guard.py`

**Interfaces:**

- Consumes: Task 4's `ApiBudget` methods.
- Produces in `call_guard`:
  - `TOKENS_PER_CHAR = 0.25`, the same estimate as `decision_backends.DECISIONS_TOKENS_PER_CHAR`;
  - `DEFAULT_COMPLETION_RESERVE_TOKENS = 4096`, used when a request sets no output cap;
  - `request_tokens(messages: Any, max_tokens: Any) -> tuple[int, int]`. It counts string contents and list
    parts' `text`, and returns `(ceil(chars * TOKENS_PER_CHAR), max_tokens if positive else the default)`;
  - `before_call(prompt_tokens: int = 0, completion_tokens: int = 0) -> float`. It refuses when
    `budget.exceeded(extra_usd=estimate)` or the document ceiling trips, then reserves and returns the estimate.
    It returns 0.0 when unarmed. Zero-argument callers keep today's behaviour;
  - `settle(reserved_usd: float, *, billed: bool) -> None`. It releases the reservation and, when `billed`,
    calls `charge_unreported`;
  - `billed_failure(exc: BaseException) -> bool`. It is False for an HTTP status below 500 (`status_code` on the
    exception or its `response`) and for `httpx.ConnectError` / `httpx.ConnectTimeout`, including as `__cause__`
    of an `openai.APIConnectionError`. It is True otherwise;
  - `current_budget() -> ApiBudget | None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_call_whose_estimate_passes_the_cap_is_refused_before_it_goes_out`. Cap 0.05, nothing spent, one
    call estimated at about $0.06; the reason names the estimate;
  - `test_concurrent_reservations_stop_the_next_call_below_the_cap`. Two reservations of $0.03 under cap $0.05
    mean the second `before_call` is refused;
  - `test_a_settled_success_releases_and_after_call_prices_the_real_usage`;
  - `test_a_timeout_is_charged_and_a_4xx_is_released`. Parametrize over `httpx.ReadTimeout`, a fake
    `status_code=500`, `status_code=400` and `httpx.ConnectError`;
  - `test_request_tokens_counts_text_parts_and_defaults_the_output_cap`;
  - `test_the_runner_persists_unreported_charges_when_it_disarms`.
- [ ] **Step 2: Run and see them fail** `.venv/bin/python -m pytest -q tests/test_call_guard.py -n 0 --no-cov`.
- [ ] **Step 3: Implement.** `_refusal` takes the estimate. The ceiling check is unchanged.
- [ ] **Step 4: Run the tests again; they pass.** Also run `tests/test_api_budget.py`.
- [ ] **Step 5: Commit** `feat(call-guard): reserve each request's worst-case cost before it goes out (S2) (phase1 task 5)`.

### Task 6: Wire the reservation into the three guarded transports

**Files:**

- Modify: `src/mailroom_sandbox/provider_pins.py`:
  - `_guard_call` at :101 gains `(prompt_tokens: int = 0, completion_tokens: int = 0) -> float`;
  - `pinned_retry_chat_completion` at :345 sizes from `kwargs["messages"]` and `max_tokens` /
    `max_completion_tokens`, then calls `settle` in `try/except/else`;
  - `PinnedChatOpenAI` at :398 sizes from the payload in `_get_request_payload`, keeps the reservation in a new
    ContextVar `_LC_RESERVED`, and settles it in `_create_chat_result`. A new override of `_generate`, and of
    `_agenerate` if the parent defines it, settles it on an exception, so it cannot leak.
- Modify: `src/mailroom_sandbox/decision_backends.py` at :821. Each attempt calls `before_call` sized from the
  body; 200 → `after_call`, then `settle(billed=False)`; a transport error or non-200 → `settle(billed=
  billed_failure(...))`. For a non-200, decide from the status code.
- Modify: `docs/vendor-hotfixes.md`, the HF-004 row: replace "spend stops within one call per concurrent document
  of the cap" with the reservation rule.
- Modify: `docs/critical-regressions.md`. Row 5 names the new call-guard tests; row 9 names
  `test_a_resumed_pipeline_run_bills_only_unfinished_documents`.
- Test: `tests/test_provider_pins.py`, `tests/test_call_guard.py`, `tests/test_decision_transport.py`

- [ ] **Step 1: Write the failing tests:**
  - `test_pinned_chat_completion_releases_on_success_and_charges_on_timeout`. Use a fake `original` that
    returns, then raises `httpx.ReadTimeout`; assert `reserved_usd == 0` after both and `unreported_usd > 0`
    after the timeout only;
  - `test_langchain_reservation_is_settled_when_generate_raises`. Use the existing LangChain fake in
    `tests/test_provider_pins.py`;
  - `test_decisions_attempt_reserves_and_settles` in `tests/test_decision_transport.py`.
- [ ] **Step 2: Run and see them fail.** `.venv/bin/python -m pytest -q tests/test_provider_pins.py
  tests/test_decision_transport.py tests/test_call_guard.py -n 0 --no-cov`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests again; they pass**, together with `tests/test_vendor_hotfixes.py -k hf004` and the
  files from Tasks 1-5.
- [ ] **Step 5: Gates.** Run `ruff check src tests scripts deploy reports notebooks` and `npx --yes
  markdownlint-cli2@0.18.1` on the changed docs; both must be clean. If any doc is in the CLI reference or the
  runbooks, run `python scripts/check_cli_surface.py --check` and `sandbox runbook check`.
- [ ] **Step 6: Commit** `feat(spend): reserve and settle every guarded OpenRouter and Decisions request (S2) (phase1 task 6)`.

### Hand-over

- [ ] Push `claude/phase1-spend-safety` and update the draft PR description; fill the template's Critical
  regressions section with rows 5 and 9 and the tests above.
- [ ] Note in the PR that unfinished runs locked before this change resume under the lock's own checks, and
  that a lock that refuses the new code needs a new run, as for any code change.
