# Floor Read Ranges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record which character ranges of each document's normalised working text every agent's
request contained, and show them, with the text and every field's values, in a floor debug document
inspector.

**Architecture:**

- A new `job/read_ranges.py` holds a per-document context, a shingle matcher and two writers:
  `reads.jsonl` (ranges only) and `doc_texts/<doc>.txt` (the working text, in the local run store).
- Two thin observers feed it: an outermost `_call_structured` wrapper, and the decision transport.
- The floor digest attaches the ranges as numbers. A new loopback endpoint serves text and field
  values to a DOCUMENT panel.

**Tech Stack:**

- Python 3.11, pytest, LangChain callbacks (`NodeTracker`).
- The floor dashboard: vanilla JS in `reports/dashboard/floor.template.html`, served by
  `tui/floor_app.py`'s `http.server`.
- Playwright for screenshots.

**Spec:** `docs/superpowers/specs/2026-11-25-floor-read-ranges-design.md` (approved, rev 2).

## Global Constraints

- Ranges are measured against the **normalised working text**: the intake node's returned `doc_text`
  (`vendor/llm-mailroom/src/graph/build_graph.py:753`). Calls made before intake returns are matched
  against the raw row text and marked `basis: "raw"`.
- No text in `nodes.jsonl`, `items.jsonl`, `reads.jsonl`, `floor_digest.json`/`.js`, the digest
  export, Langfuse or git. The working text goes only to `<run store>/doc_texts/<doc>.txt`
  (gitignored `data/runtime`).
- Do not edit `vendor/**`, `vendor_hotfixes.py`, `requirements/*.txt`, `uv.lock`, `.env*`,
  `data/runtime`, `data/cache`. Do not lower coverage (`fail_under = 84`).
- Observers never change a request or a result. Every exception inside recording is swallowed and
  counted (`read_errors`).
- Recording is on by default for pipeline runs. `job.trace_reads: false` disables it.
- No paid or live work: no `sandbox run start`, modal, `--real` or `--live`. Tests use named files
  with `-n 0 --no-cov`.
- Commits use the `.gitmessage` shape, ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No `Claude-Session:` trailer, claude.ai
  link or "Generated with" footer.

## Review Focus

1. **Re-activation stacking.** A second `runtime.activate()` with different sampling overrides must
   still leave exactly one read-range layer, outermost, with one sampling layer under it. Pinned in
   Task 3.
2. **Concurrent documents.** Two documents on worker threads must never write ranges into each
   other's context. Pinned in Task 2 (a thread test with two contexts).
3. **A document with an empty, missing or non-string working text** (an intake failure) records
   `skipped: "no_text"` and never raises. Pinned in Task 1.
4. **Hostile ids on the doc endpoint.** `doc=../../etc/passwd`, an unknown run id, or a doc id that
   is not in `dataset.jsonl` get a 404, and the endpoint never reads outside the run dir. Pinned in
   Task 6.
5. **Very large input.** A 2M-character document with a 600k-character request stays under the size
   caps or records `skipped: "size"`, and the per-document recording time is bounded. Pinned in
   Task 1.

---

### Task 1: The range matcher

**Files:**

- Create: `src/mailroom_sandbox/job/read_ranges.py` (matcher section)
- Test: `tests/test_read_ranges.py`

**Interfaces:**

- Produces:
  - `SHINGLE = 48`, `STRIDE = 16`, `MAX_RANGES = 64`, `MAX_DOC_CHARS = 3_000_000`,
    `MAX_REQUEST_CHARS = 3_000_000`
  - `class ShingleIndex: __init__(self, text: str)`
  - `match_ranges(index: ShingleIndex, request: str) -> MatchResult`
  - `MatchResult` (a `TypedDict`) with keys `ranges: list[list[int]]`, `request_chars: int`,
    `matched_chars: int`, `doc_chars: int`, `skipped: str | None` (`"size"`, `"no_text"` or `None`).

- [ ] **Step 1: Write the failing tests**
  - `test_sliding_windows_map_to_exact_offsets`:
    - Build a 120k-character synthetic text (numbered paragraphs).
    - Cut it with vendored `agents.intake.sliding_windows(text, 30_000, 2_000)`.
    - For each `(window, start)`, `match_ranges(ShingleIndex(text), "PROMPT HEADER\n" + window)`
      gives `ranges == [[start, start + len(window)]]` and `matched_chars == len(window)`.
  - `test_split_chunks_map_per_paragraph`:
    - Use a text with whitespace-only paragraphs.
    - Cut it with vendored `_SpecialistBase._split_chunks(text, 20_000, 1_000)`.
    - Every chunk's ranges lie inside `[0, len(text))`, and together they cover every
      non-whitespace character of that chunk's source paragraphs.
  - `test_unrelated_request_has_no_ranges`: `ranges == []` and `matched_chars == 0`.
  - `test_empty_or_missing_text_is_skipped`: `ShingleIndex("")` and `ShingleIndex(None)` give
    `skipped == "no_text"`.
  - `test_oversized_input_is_skipped`: a text longer than `MAX_DOC_CHARS` gives `skipped == "size"`.
    A 2M-character doc with a 600k-character request finishes in under 2 s.
  - `test_ranges_are_capped_and_merged`: more than `MAX_RANGES` disjoint hits are merged into at most
    `MAX_RANGES` ranges, sorted, with no overlap.

- [ ] **Step 2: Run them and see them fail**

  Run: `.venv/bin/python -m pytest tests/test_read_ranges.py -n 0 --no-cov -q`

  Expected: ImportError / FAIL.

- [ ] **Step 3: Implement the matcher**
  - The index maps hash(`text[i:i+SHINGLE]`) to positions, for `i` in `range(0, n - SHINGLE + 1, STRIDE)`.
  - The scan slides over the request one character at a time. On a hit, it verifies the strings are
    equal and extends left and right while characters match, then jumps the request cursor to the
    match end.
  - Overlapping and adjacent doc ranges are merged.
  - Past `MAX_RANGES`, the smallest gaps are merged first.

- [ ] **Step 4: Run them and see them pass.** Same command; expected: all pass.

- [ ] **Step 5: Commit**: `feat(trace): match a request against the document's working text`.

### Task 2: Document context, recorder and run-store writers

**Files:**

- Modify:
  - `src/mailroom_sandbox/job/read_ranges.py` (context and recorder sections)
  - `src/mailroom_sandbox/job/node_trace.py:47-61` (`NODE_AGENTS`), plus `NodeTracker.on_chain_end`
    (~line 185)
  - `src/mailroom_sandbox/job/checkpoint.py` (~569, next to `append_node`)
  - `src/mailroom_sandbox/job/runner.py:312-315` (sink wiring)
  - `src/mailroom_sandbox/eval/runners.py` (~1300-1325, `_process`)
  - `src/mailroom_sandbox/job/spec.py` (`job.trace_reads`)
- Test:
  - `tests/test_read_ranges.py`
  - `tests/test_node_trace.py` (create it if absent; otherwise extend the existing node-trace test file)
  - `tests/test_job_spec.py`

**Interfaces:**

- Consumes: `ShingleIndex` and `match_ranges` from Task 1.
- Produces:
  - `document(doc_id: str, raw_text: str | None, sink: Callable[[dict], None], text_sink: Callable[[str, str], None]) -> ContextManager[None]`
    Sets a `ContextVar`. A `None` sink makes every recorder call a no-op.
  - `set_working_text(text: str) -> None`: builds the index once and calls `text_sink(doc_id, text)`
    once.
  - `record(agent: str, request: str, *, node: str | None = None) -> None`: appends
    `{doc, call, agent, node, ts, basis, ranges, request_chars, matched_chars, doc_chars, skipped?}`.
    `call` is a per-document counter starting at 1.
  - `stats() -> dict`: returns `{read_calls, read_errors, read_ms}` for the current document.
  - `current_node() -> str | None`: the innermost open tracked node. `NodeTracker` sets this via
    `read_ranges._NODE` on start, end and error.
  - `RunStore.append_read(record: dict) -> None` and `RunStore.write_doc_text(doc: str, text: str) -> None`.
    The filename is `doc_texts/<sha1(doc)[:16]>.txt`, plus an index line `{doc, file}` in
    `doc_texts/index.jsonl`. Filenames never use the raw doc id.

- [ ] **Step 1: Write the failing tests**
  - `test_working_text_replaces_raw_basis`: a `record` before `set_working_text` gives
    `basis == "raw"`; a `record` after it gives `basis == "working"`. Offsets are against the
    working text.
  - `test_recording_errors_never_raise`: a sink that raises makes `record` return `None` and adds 1
    to `stats()["read_errors"]`.
  - `test_contexts_are_per_thread`: two threads, each in `document(...)` with its own sink, record
    50 calls each. Each sink sees only its own `doc`.
  - `test_reads_hold_no_text`: no string value in a `reads.jsonl` line is longer than 64 characters.
  - `test_tracker_hands_intake_text_over`: `NodeTracker.on_chain_end` for node `intake`, with outputs
    `{"doc_text": "X"*500}`, calls `set_working_text` exactly once.
  - `test_classification_arbiter_is_tracked`: `NODE_AGENTS["classification_arbiter"] == "classification_arbiter"`,
    and a chain start/end for that node emits running and done records.
  - `test_trace_reads_knob`:
    - `job.trace_reads: false` validates and disables recording;
    - a non-boolean value is refused;
    - the knob's absence means on.

- [ ] **Step 2: Run them and see them fail.**

  Run: `.venv/bin/python -m pytest tests/test_read_ranges.py tests/test_node_trace.py tests/test_job_spec.py -n 0 --no-cov -q`

- [ ] **Step 3: Implement the context, recorder and writers.**
  - In `_process`, enter `read_ranges.document(row id, row["doc_text"], ...)` inside the same
    `ExitStack`, only when `node_cb is not None` and `trace_reads` is on.
  - Pass the sinks from `runner.py` next to `_node_sink`.
  - After the document finishes, merge `stats()` into the item's metrics through the existing
    `merge_item_metrics` path in `usage_capture`, under the key `reads`.

- [ ] **Step 4: Run them and see them pass**, then run the existing
  `tests/test_job_runner.py tests/test_floor_digest.py tests/test_agent_routes.py`. All pass.

- [ ] **Step 5: Commit**: `feat(trace): record each agent's read ranges per document`.

### Task 3: Chat-agent observer, outermost and stable across re-activation

**Files:**

- Modify:
  - `src/mailroom_sandbox/job/read_ranges.py` (seam section)
  - `src/mailroom_sandbox/sampling.py:283-300` (look through the observer layer)
  - `src/mailroom_sandbox/runtime.py` (after `apply_sampling_overrides`, ~line 608)
- Test:
  - `tests/test_read_ranges.py`
  - `tests/test_sampling.py` (or the existing sampling test file)

**Interfaces:**

- Consumes: `record` and `current_node` from Task 2.
- Produces:
  - `install_call_observer() -> int`: returns the number of classes patched. Idempotent: it removes
    an existing observer layer (`__sandbox_read_ranges__`) through `__wrapped__`, then wraps the
    current attribute once.
  - Targets are `sampling._TARGETS`.
  - The observer records `agent_name`, `system_prompt` and `user_message` joined by `"\n"`, then calls
    the wrapped function with the same arguments.

- [ ] **Step 1: Write the failing tests**
  - `test_observer_sees_every_call_and_changes_nothing`:
    - Patch a fake `BaseAgent`, and assert the wrapped function receives identical args and kwargs.
    - The return value is the same object.
    - One read record per call.
  - `test_observer_stays_outermost_across_reactivation`:
    - Call activate with no sampling overrides, then with overrides, then with none again.
    - Each time the attribute's outermost layer is the observer, and exactly one sampling layer sits
      below it whenever overrides are on.
    - Check by walking `__wrapped__`.
  - `test_native_endpoint_calls_are_seen`: with LangChain extra knobs (the native path in
    `sampling.py:237-240`), one call is still recorded.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement the observer.**
  - In `sampling.py`, when the current attribute carries `__sandbox_read_ranges__`, patch its
    `__wrapped__` instead, and restore the observer on top.
  - Call `install_call_observer()` at the end of `runtime.activate`.

- [ ] **Step 4: Run the new tests plus `tests/test_agent_routes.py tests/test_vendor_hotfixes.py tests/test_default_model.py`. All pass.**

- [ ] **Step 5: Commit**: `feat(trace): observe every chat agent request without changing it`.

### Task 4: Decision-backend observers

**Files:**

- Modify: `src/mailroom_sandbox/decision_backends.py`: `_post_decision` (~736, after #413/#414),
  and the Jev pydantic_ai call (~149-172).
- Test: `tests/test_decisions_backend.py`, `tests/test_decision_transport.py`

**Interfaces:**

- Consumes: `record` from Task 2.
- `_post_decision` records the lane from the request body as agent `decisions:<lane>`, and the
  question and context text as the request. It records once per logical request, never once per
  transport retry. The Jev call records agent `jev`.

- [ ] **Step 1: Write the failing tests**
  - `test_post_decision_records_once_per_request`: a transport that fails twice and then succeeds
    gives exactly 1 read record.
  - `test_masked_digits_leave_a_gap_not_an_error`: a request with a masked card number gives 2
    ranges around the masked span, and `read_errors == 0`.
  - `test_jev_request_is_recorded`: the mock pydantic_ai agent receives the same prompt, and 1 record
    has `agent == "jev"`.

- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass, plus the full `tests/test_decision_transport.py tests/test_decision_windows.py`.**

- [ ] **Step 5: Commit**: `feat(trace): record decision-model requests' read ranges`.

### Task 5: Invariance harness and remote file lists

**Files:**

- Modify: `src/mailroom_sandbox/job/remote.py:203-204, 413` (add `reads.jsonl` and `doc_texts/`)
- Create: `tests/test_read_ranges_invariance.py`

**Interfaces:**

- Consumes: Tasks 2–4.

- [ ] **Step 1: Write the failing tests**
  - `test_recording_on_and_off_give_identical_results`:
    - Run mock pipeline documents through `eval.runners` with a node sink, twice: `trace_reads` on and
      off.
    - Use 3 fixture rows plus one synthetic 150k-character row with inline `doc_text`, so windowing
      fires.
    - `items.jsonl` and `nodes.jsonl` are equal after dropping `ts`, `ms`, `latency_ms`, `started_ns`,
      `ended_ns` and the item metric key `reads`.
    - Only the on-run has `reads.jsonl` and `doc_texts/`.
  - `test_a_raising_matcher_leaves_the_document_unchanged`: monkeypatch `match_ranges` to raise. The
    items equal the off-run's.
  - `test_remote_pull_includes_reads`: the remote pull list contains `reads.jsonl` and `doc_texts`.

- [ ] **Step 2: Fail. Step 3: Implement (the remote lists; copy `doc_texts/` as a directory). Step 4: Pass, plus `tests/test_job_remote.py`.**

- [ ] **Step 5: Commit**: `test(trace): prove read recording never changes a run`.

### Task 6: Digest rows and the loopback document endpoint

**Files:**

- Modify:
  - `reports/dashboard/build_floor_digest.py` (~1531, read `reads.jsonl`; ~1621, attach to `debug`)
  - `src/mailroom_sandbox/tui/floor_app.py` (`_FloorHandler`, `make_server`, `serve_floor`)
- Test:
  - `tests/test_floor_digest.py`
  - `tests/test_floor_app.py`
  - `reports/dashboard/selftest_floor_digest.py`

**Interfaces:**

- Produces:
  - Digest field `doc_row["debug"]["reads"]`:
    `{"calls": [{agent, node, basis, ranges, matched, request}], "union": {agent: ranges}, "doc_chars": int}`,
    or absent when the run has no `reads.jsonl`.
  - Endpoint `GET /api/floor/doc?run=<run_id>&doc=<doc_id>` returns JSON with these keys:
    - `working`: the text, or `null`;
    - `original`: the row's `doc_text`, or `null`;
    - `expected`: the row's expected fields;
    - `extracted`: the item's `extracted_data`;
    - `class`: `{gt, pred}`;
    - `rewritten`: bool;
    - `overlap`: float, the verbatim coverage of the working text in the original.

    A 404 is returned for an unknown run or doc.
  - The handler gets `runs_root: Path | None`. The run id must be one that the digest builder's run
    scan found under it.

- [ ] **Step 1: Write the failing tests**
  - `test_digest_attaches_reads_without_text`:
    - A fixture run dir with `reads.jsonl` gives `debug.reads.calls` with ranges.
    - The serialised `floor_digest.json` contains no substring longer than 40 characters taken from
      the fixture's working text.
    - The same holds for the export payload.
  - `test_doc_endpoint_serves_text_and_fields`: a known run and doc give a 200 with all keys.
  - `test_doc_endpoint_refuses_hostile_ids`: `doc=../../etc/passwd`, an unknown run, an unknown doc
    and an absolute path all give a 404, and nothing outside the run dir is opened. Assert this by
    patching `Path.read_text`.
  - `test_server_still_binds_loopback`: `make_server(...).server_address[0] == "127.0.0.1"`.

- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass, plus `reports/dashboard/selftest_floor_digest.py` (all cases).**

- [ ] **Step 5: Commit**: `feat(floor): serve a run's working text and fields to the debug view`.

### Task 7: DOCUMENT panel in floor debug mode

**Files:**

- Modify:
  - `reports/dashboard/floor.template.html`
  - `docs/floor.md`
- Test:
  - `reports/dashboard/selftest_floor_digest.py`
  - `tests/test_floor_app.py`
  - a Playwright script in scratch, kept out of the repo

**Interfaces:**

- Consumes: `debug.reads` and `/api/floor/doc` from Task 6.
- Flags, computed client-side:
  - `not read`: the expected value occurs (whitespace- and case-insensitive) in the working text, but
    in no union range of the specialist agents that ran.
  - `misrouted`: no specialist for `class.gt` ran; this replaces `not read`.
  - `not in text`: the expected value has no occurrence in the working text.

- [ ] **Step 1: Write the failing selftest cases**
  - A synthetic doc with a value outside every specialist range is `not read`.
  - A value inside a range carries no flag.
  - A misrouted doc's fields are all `misrouted`.
  - A value absent from the text is `not in text`.
  - Without the server, the panel says the text is unavailable, and the band map still renders.

- [ ] **Step 2: Fail. Step 3: Implement the panel.**
  - Working-text pane with a ranges minimap.
  - Per-agent toggles: intake, sorter, reviewer, specialist, judge, arbiter, classification arbiter,
    decisions lanes. Per-call toggles when an agent has more than one call.
  - A Working/Original toggle, and a rewritten badge showing the overlap.
  - Field rows with flags; clicking a row scrolls to its occurrence.
  - Every control reachable by keyboard. Also fix the #411 finding: Enter/Space on confusion cells.
  - Band colours follow the `experiment-figures` colour roles.

- [ ] **Step 4: Pass, then take screenshots.** Use Playwright at deviceScaleFactor 2, with a synthetic
  run only, capturing a `not read` case and a read-but-missed case. Save the screenshots under
  `.evidence/` and look at them.

- [ ] **Step 5: Commit**: `feat(floor): inspect a document's text and each agent's reads in debug mode`.

### Task 8: Docs, changelog and repo gates

**Files:**

- Modify: `docs/floor.md`, `docs/jobs.md` (`job.trace_reads`, `reads.jsonl`, `doc_texts/`),
  `CHANGELOG.md` `[Unreleased]`, and `docs/critical-regressions.md` (only if a row applies).

- [ ] **Step 1: Document for future runs.**
  - What gets recorded and where.
  - That text stays in the local run store only.
  - The knob.
  - That remote runs record after the next worker deploy (unverified until then).
  - The intended new `classification_arbiter` records in `nodes.jsonl`.
- [ ] **Step 2: Run the gates on a clean tree** and quote each exit code:
  - `ruff check src tests scripts deploy reports notebooks`
  - `python scripts/check_hotfixes.py`
  - `python scripts/sync_requirements.py --check`
  - `python reports/dashboard/build_hub.py --check`
  - `python scripts/check_cli_surface.py --check`
  - `python -m mailroom_sandbox.cli runbook check`
  - pytest on every test file touched by Tasks 1–7, plus `test_job_runner test_floor_digest test_floor_app test_api_floor test_agent_routes test_vendor_hotfixes test_decisions_backend test_decision_transport test_job_remote`
  - `sandbox pilot --mock`, with the stages unchanged from main
- [ ] **Step 3: Commit**: `docs(floor): document read ranges and the document inspector`.
