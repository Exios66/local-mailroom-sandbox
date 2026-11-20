# Vendor hotfixes

`vendor/` holds byte-identical snapshots of the pinned family repos (`tests/test_vendor_drift.py`),
so it is never edited. A pipeline fix an experiment needs before llm-mailroom ships it lives in
[`src/mailroom_sandbox/vendor_hotfixes.py`](../src/mailroom_sandbox/vendor_hotfixes.py): each
hotfix wraps one vendored function at activation, and every run that starts from this checkout
gets it. Scoring corrections have their own fingerprinted, dual-reported layer in
[scoring-hotfixes.md](scoring-hotfixes.md). The combined conditions are in the
[campaign contract](EXPERIMENT-CAMPAIGN-CONTRACT.md).

## How a hotfix stays honest

- **Bound to the code it fixes.** A hotfix records the sha256 of the target's source. After a
  vendor refresh changes that function, the hotfix is not installed (`stale`) and
  `sandbox run preflight` fails on the `vendor_hotfixes` check until it is re-validated against
  the new code or retired.
- **Recorded in every run lock.** `vendor_hotfixes` in `run.lock.json` holds the module sha256
  and each fix's id and target fingerprint. A resume refuses a lock whose hotfix set differs;
  locks from before the layer carry no key and resume as before. The process that executes the
  run (locally, or the Modal job worker from its deployed image) re-checks at run start
  (`runner.verify_locked_hotfixes`): it refuses a hotfix set other than the lock's, or a hotfix
  that is not in effect there, so a worker deployed from older code never runs a locked job.
- **Tracked upstream.** Each hotfix names the llm-mailroom issue or PR that will make it
  unnecessary. When the fix is vendored, the fingerprint no longer matches: delete the hotfix,
  its tests and this table row in the same change as the vendor refresh.

## Active hotfixes

Run `python scripts/check_hotfixes.py` before a campaign checkpoint. Required fixes marked
`unavailable` now fail alongside stale fixes. HF-005 is optional only where the watcher is
not installed; `--require-watcher` requires it to be applied. G0 invokes this combined
pipeline/scoring check, and run execution still verifies the locked identities.

| Id | Target | Fix | Upstream |
| --- | --- | --- | --- |
| HF-001 | `langchain_agents.doc_inventories.enrich_extraction` | A null corporate `record_type` is filled from every corporate subclass through Dojo's subclass → `record_type` map. Upstream fills it only for the five Hub tokens, so indenture, board_resolution, officer_certificate, subsidiary_list, charter_amendment and certificate_of_formation left it null. | [Exios66/llm-mailroom#313](https://github.com/Exios66/llm-mailroom/issues/313) |
| HF-002 | `agents.judge.CompletenessJudge.judge_completeness` | A completeness-judge parse failure raises instead of returning a real "incomplete 0.0" verdict, so the graph takes its judge-error path (human review, counted by the gate) instead of sending the document to the arbiter as if it were judged incomplete. | draft J-1 below (not filed) |
| HF-003 | `agents.intake.IntakeAgent.intake_run` | A single-window intake `cleaned_text` replaces the document only when it keeps 90% of its length and its words: aligned in order, no run of 8 or more source words and no more than 5% of them may be lost, so a reply that drops a clause is refused even at full length. Context fit reads a long document in one window while intake's output allowance stays ~2k tokens, and the graph replaces the whole document with any accepted cleaned text. | draft J-2 below (not filed) |
| HF-004 | `pipeline.limits.record_usage` | Every returned chat call is priced against the run's `job.api_cost_cap_usd` as it returns (`job/call_guard.py`). The provider-pin wrappers refuse the next OpenRouter call once the cap or the per-document call ceiling is reached (40 for `pipeline`, 16 otherwise). A call already in flight can still return, so spend stops within one call per concurrent document of the cap; a document the guard cut short becomes an error row, never a score. A Decisions response is priced once, in the Decisions transport; while HF-004 is installed the usage accumulator is the unwrapped function, so that response is not priced again. Isolated `sorter_reviewer` and `extraction_gate` rows enter that document scope and use the default ceiling of 16. The R01 smoke's two merger agreements ran ~140 calls past the between-document check. | draft J-3 below (not filed) |
| HF-005 | `pipeline.watcher._DispatchPool.submit` | Backpressure. The watcher queues an inbox file for a worker slot only while the in-memory dispatch queue and `processing/` (and `review/`, when limited) are below their `MAILROOM_MAX_QUEUE_DEPTH_<STAGE>` limits (`mailroom_sandbox.backpressure`). Over a limit the file stays in `inbox/` and the next 1-second rescan offers it again, so intake slows and nothing is dropped. Upstream queued every inbox file with no bound. | draft J-4 below (not filed) |
| HF-006 | `langchain_agents.specialist_agents._SpecialistBase._confidence_missing` | Preserve an explicit numeric `0.0` in single and chunked extraction. Only missing confidence receives the existing evidence-derived fallback; a zero-confidence window cannot be lifted by that fallback. | [Exios66/llm-mailroom#279](https://github.com/Exios66/llm-mailroom/issues/279) |

### Draft llm-mailroom issues (not filed)

- **J-1** `CompletenessJudge.judge_completeness` turns a structured-output parse failure into an
  `incomplete` 0.0 verdict instead of a judge error.
- **J-2** `IntakeAgent.intake_run` accepts a single-window `cleaned_text` with no length or content check, and
  `build_graph` replaces the document with it.
- **J-3** `pipeline.limits` bounds a document's output tokens but not its spend or call count:
  `record_usage` has no hook for a caller's cost ceiling, so a looping document is unbounded.
- **J-4** The filesystem bins are unbounded queues: `_DispatchPool.submit` queues every inbox file the
  rescan sees, and nothing slows `POST /v1/upload` or Gmail intake when `processing/` backs up. Each stage
  needs a maximum depth, with intake held (never dropped) at the limit.

Filing these upstream is an owner decision.

## Adding one

1. Reproduce the defect against the vendored code in a test.
2. Add a `Hotfix` to `HOTFIXES` with the target's current source sha256
   (`hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()`), an upstream reference and a
   wrapper that changes only the defect.
3. Add a row above and a CHANGELOG entry, and open the upstream issue.

## Isolated specialist runs and the subclass

The pipeline's extract node names the sorter's subclass in the specialist handoff and derives
fields from it (insurance `cms_source_table`, corporate `record_type`). An isolated specialist
run sees no subclass unless `job.specialist_subclass` names one (it needs
`job.pipeline_handoff: true`):

| Value | Subclass in the handoff | Use |
| --- | --- | --- |
| `none` (default) | none | prompt lineages written for "no subclass is given" |
| `gold` | the row's expected subclass (contracts: the CUAD family; refused for the merger specialist, whose subclass is its scored answer) | the specialist behind a correct sorter; derived fields copy the truth, so report them apart |
| `sorter` | a saved sorter pass (`job.specialist_subclass_file`, hashed by content) | the specialist behind that sorter, as the pipeline runs it |

## Queue-depth limits (backpressure)

Each pipeline bin has a maximum depth. When a stage reaches it, intake waits; nothing is dropped.

| Stage | Variable | Default | Who waits at the limit |
| --- | --- | --- | --- |
| `inbox` | `MAILROOM_MAX_QUEUE_DEPTH_INBOX` | 256 | The sandbox's in-process pipeline runs wait before writing a document into the shared inbox. `sandbox api eval` keeps at most this many uploads unfinished at once. |
| `dispatch` | `MAILROOM_MAX_QUEUE_DEPTH_DISPATCH` | 32 | The watcher's in-memory queue (HF-005): new inbox files stay in `inbox/`. |
| `processing` | `MAILROOM_MAX_QUEUE_DEPTH_PROCESSING` | 32 | The watcher (HF-005), as for `dispatch`. It gates new dispatch: a worker claims a queued file into `processing/` only when its slot frees, so the bin passes the limit only through claims left behind by crashed workers, and then nothing new is queued. |
| `review` | `MAILROOM_MAX_QUEUE_DEPTH_REVIEW` | 0 (off) | The watcher (HF-005). Only a person drains `review/`, so a limit there would stall an unattended batch; set one only where a reviewer is on hand. |

`0` turns a limit off; a value that is not a non-negative integer falls back to the default, with a warning.
An in-process pipeline run waits at most `MAILROOM_BACKPRESSURE_TIMEOUT_SECONDS` (default 600; `0` = no limit) for
room in a full inbox, so a stalled inbox cannot hold a run past `job.max_wall_seconds`, which is checked only
between documents. Past it the document raises `BackpressureTimeout` like any document error: a job run
(`sandbox run start`) records an error row for it and goes on, rerunning it on resume; a direct eval stops after
its in-flight documents, as it does on any failure.
`sandbox api eval` also retries an upload that the API's pause gate refused (HTTP 503 "paused") after the rate-limit
back-off. If its window stays full for `doc_timeout`, it stops sending and reports the rows it did not send.
