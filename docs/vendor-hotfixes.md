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
| HF-002 | `agents.judge.CompletenessJudge.judge_completeness` | A completeness-judge parse failure raises instead of returning a real "incomplete 0.0" verdict, so the graph takes its judge-error path (human review, counted by the gate) instead of sending the document to the arbiter as if it were judged incomplete. | [Exios66/llm-mailroom#315](https://github.com/Exios66/llm-mailroom/issues/315) |
| HF-003 | `agents.intake.IntakeAgent.intake_run` | A single-window intake `cleaned_text` replaces the document only when it keeps 90% of its length and its words: aligned in order, no run of 8 or more source words and no more than 5% of them may be lost, so a reply that drops a clause is refused even at full length. Context fit reads a long document in one window while intake's output allowance stays ~2k tokens, and the graph replaces the whole document with any accepted cleaned text. With HF-014 installed the prompt no longer asks for a clean, so this guard is latent: it stays as a backstop for a model that returns `cleaned_text` anyway. | [Exios66/llm-mailroom#316](https://github.com/Exios66/llm-mailroom/issues/316) |
| HF-004 | `pipeline.limits.record_usage` | Every returned chat call is priced against the run's `job.api_cost_cap_usd` as it returns (`job/call_guard.py`). The provider-pin wrappers refuse the next OpenRouter call once the cap or the per-document call ceiling is reached (40 for `pipeline`, 16 otherwise). A call already in flight can still return, so spend stops within one call per concurrent document of the cap; a document the guard cut short becomes an error row, never a score. A Decisions response is priced once, in the Decisions transport; while HF-004 is installed the usage accumulator is the unwrapped function, so that response is not priced again. Isolated `sorter_reviewer` and `extraction_gate` rows enter that document scope and use the default ceiling of 16. The R01 smoke's two merger agreements ran ~140 calls past the between-document check. | [Exios66/llm-mailroom#317](https://github.com/Exios66/llm-mailroom/issues/317) |
| HF-005 | `pipeline.watcher._DispatchPool.submit` | Backpressure. The watcher queues an inbox file for a worker slot only while the in-memory dispatch queue and `processing/` (and `review/`, when limited) are below their `MAILROOM_MAX_QUEUE_DEPTH_<STAGE>` limits (`mailroom_sandbox.backpressure`). Over a limit the file stays in `inbox/` and the next 1-second rescan offers it again, so intake slows and nothing is dropped. Upstream queued every inbox file with no bound. | [Exios66/llm-mailroom#318](https://github.com/Exios66/llm-mailroom/issues/318) |
| HF-006 | `langchain_agents.specialist_agents._SpecialistBase._confidence_missing` | Preserve an explicit numeric `0.0` in single and chunked extraction. Only missing confidence receives the existing evidence-derived fallback; a zero-confidence window cannot be lifted by that fallback. | [Exios66/llm-mailroom#279](https://github.com/Exios66/llm-mailroom/issues/279) |
| HF-007 | `graph.routing.judge_gate` | A confidence at or above `judge_band_high` still reaches the judge. `MAILROOM_JUDGE_VERIFY=off` still disables the lane. `MAILROOM_JUDGE_HIGH_BAND=off` restores the vendored band. The API cap still bounds spend. | [Exios66/llm-mailroom#278](https://github.com/Exios66/llm-mailroom/issues/278) |
| HF-008 | `langchain_agents.specialist_agents.merge_chunk_windows` | Records each surviving window's confidence on `_window_confidences` and its character length on `_window_lengths`. The merged confidence stays the vendored minimum (the old max-confidence merge is already gone). Scoring ignores the underscore key. | [Exios66/llm-mailroom#255](https://github.com/Exios66/llm-mailroom/issues/255) |
| HF-009 | `graph.build_graph._run_chunked_extraction` | An API-routed specialist (OpenRouter or any hosted provider) reads the whole document in one `extract` call and never chunks. A document longer than its input budget fails with `WholeDocumentTooLong`, which the extract node records as a parse failure and sends to review, so it is never chunked or silently truncated. Context fit sizes that budget to the model's context. Modal, vLLM and other self-hosted routes keep the vendored chunking for models whose context cannot hold the document. | [Exios66/llm-mailroom#319](https://github.com/Exios66/llm-mailroom/issues/319) |
| HF-010 | `agents.intake.sliding_windows` | When an API-routed sorter or intake would need more than one window for a document, the read fails with `WholeDocumentTooLong` instead. The sorter failure takes the graph's review path; intake fails soft and the deterministic clerk output stays. Calls from Modal, vLLM or other self-hosted routes, and calls from no agent, keep the vendored windows. | [Exios66/llm-mailroom#319](https://github.com/Exios66/llm-mailroom/issues/319) |
| HF-011 | `graph.routing.after_judge` (also bound to `after_arbiter`) | With `confidence.judge_exhausted_to_arbiter: true` (the overlay default), two `graph.route_spec` rules: a `partial` verdict on the last judge pass goes to the arbiter for a final ruling instead of straight to a person, unless `after_arbiter` would park it anyway (extraction still unsure, or an unadjudicated conflict), so no call is spent on a foregone park; and the arbiter cannot order a re-extraction once the judge passes are spent, because that retry could not be judged. `accept_with_caveats` archives through the vendored checks; anything else parks with the `judge_partial` cause. `incomplete`, judge errors and transient errors keep the vendored routes. The router itself is unchanged: `route_spec` binds routers at import, so its rule registry is the hook. Without the key both rules are inert. | [Exios66/llm-mailroom#320](https://github.com/Exios66/llm-mailroom/issues/320) |
| HF-012 | `graph.routing._transient_decision` | `confidence.transient_retry_max`, when set, is the number of times a node re-runs after a transient provider error (overlay: 1). `retry_chat_completion` already retries inside each call (5 attempts plus the SDK's own), so the vendored two node-level re-runs repeated whole extractions and judge passes. Unset keeps the vendored budget; counters and the `transient_exhausted` cause are unchanged. | [Exios66/llm-mailroom#320](https://github.com/Exios66/llm-mailroom/issues/320) |
| HF-014 | `agents.intake.IntakeAgent.system_prompt` (also swaps `agents.intake.INTAKE_SCHEMA`) | Intake returns triage and the section map only. The prompt the agent serves has its CLEAN block replaced by "set `cleaned_text` to null" (the rewrite runs on the served text, so a Langfuse-managed or locally overridden prompt gets it too; a text with no CLEAN block loses any line asking for the full or repaired `cleaned_text` and gets an explicit override appended), and the schema sent with every call drops `cleaned_text`. Upstream asks a messy document's model to re-emit the whole text, but intake's output allowance is 2,048 tokens, so any document over about 2-3k characters was cut off mid-JSON: the triage, the section map and the clean were lost and the input was still paid. A document's working text is now always the deterministic clerk output. HF-003 stays installed and is latent unless a model returns a `cleaned_text` anyway. If the vendored prompt's CLEAN block or the schema's `cleaned_text` moves, the hotfix is reported `stale` and preflight fails. | upstream issue to be filed (J-8) |
| HF-015 | `agents.intake.validate_intake` (also wraps `agents.intake.format_intake_prior` and `agents.intake._merge_triage`) | A failed intake read has no triage, so the sorter gets no prior. A reply with a parse error, no `triage` object or no `primary_doc_class` (a cut-off JSON, prose, a JSON list) used to become a truthy triage of `unknown`, confidence 0.0 and no gist, which `format_intake_prior` fed to the sorter as an advisory read. It is now an empty triage and `format_intake_prior` returns "". `_merge_triage` also drops empty reads before it merges, so a failed window never hides another window's honest `unknown` read (upstream's all-unknown fallback was `reads[0]`). A model that answers `unknown` with a gist is a real read and keeps its prior. The prior's `subclass:` line is printed only for a token in the sorter's catalog for that primary class (`valid_sorter_subclasses`); an invented subtype is dropped, and so is any subclass for a class with no catalog. | upstream issue to be filed (J-9) |

### Confidence decisions

- **HF-008.** The adopted merge stays the weakest window. `compare_window_rules` reports that minimum, the maximum, and the length-weighted value from recorded `(confidence, character length)` windows. The routing audit's `window_rules` block reads those windows from each scored prediction and gives each rule's AUROC for separating documents that met the target from those that did not. Until a labelled chunked run reports it, the rule is not replaced.
- **HF-007.** A confidence at or above `judge_band_high` still reaches the judge. `above_band_quality` reports, per class, how many scored documents at or above that band met the target and the 95% exact interval. The band changes only when a labelled run's table shows that confidence separates quality. This checkout does not contain that table.
- **HF-006.** Every live extraction schema registers `confidence`. Production `slice-0100` pins `corporate_records_specialist_condensed_v1`, `correspondence_specialist_condensed_v3`, and `insurance_claims_specialist_condensed_v3`; each asks for the share of fields found. Contracts and merger use the code-default schema, which includes the same field. A stated `0.0` stays `0.0` on the four LangChain specialists, and a missing value there uses the evidence share. Insurance keeps a stated `0.0`; a missing insurance confidence becomes the schema default `0.0`. The frozen `corporate_records_specialist_simplified.txt` still says confidence is unregistered. It is not the production pin, and its bytes stay frozen.

### Upstream llm-mailroom issues

- **J-1** ([#315](https://github.com/Exios66/llm-mailroom/issues/315)) `CompletenessJudge.judge_completeness` turns a structured-output parse failure into an
  `incomplete` 0.0 verdict instead of a judge error.
- **J-2** ([#316](https://github.com/Exios66/llm-mailroom/issues/316)) `IntakeAgent.intake_run` accepts a single-window `cleaned_text` with no length or content check, and
  `build_graph` replaces the document with it.
- **J-3** ([#317](https://github.com/Exios66/llm-mailroom/issues/317)) `pipeline.limits` bounds a document's output tokens but not its spend or call count:
  `record_usage` has no hook for a caller's cost ceiling, so a looping document is unbounded.
- **J-4** ([#318](https://github.com/Exios66/llm-mailroom/issues/318)) The filesystem bins are unbounded queues: `_DispatchPool.submit` queues every inbox file the
  rescan sees, and nothing slows `POST /v1/upload` or Gmail intake when `processing/` backs up. Each stage
  needs a maximum depth, with intake held (never dropped) at the limit.
- **J-5** ([#319](https://github.com/Exios66/llm-mailroom/issues/319)) `_run_chunked_extraction` windows any document longer than the specialist's budget whatever the
  provider, so a hosted API route pays one call per window. Chunking should be limited to self-hosted serving
  with a small context, and an API route should refuse an oversize document. The sorter and intake
  `sliding_windows` reads have the same gap.
- **J-6** ([#320](https://github.com/Exios66/llm-mailroom/issues/320)) The judge/arbiter lane has no shared loop budget. With the defaults (`retry_max` 2,
  `arbiter_retry_max` 2, `judge_max_passes` 3, two transient node re-runs) one unsure document can make
  five extractions, three judge passes and two arbiter calls and still park, because confidence retries
  and arbiter retries share `extraction_attempts` and interleave. A `partial` verdict on the last pass
  parks without the arbiter's ruling, and the transient node budget sits on top of the call-level retry
  ladder. Budgets should be per lane and a last-pass `partial` should reach the arbiter once.
- **J-7** ([#321](https://github.com/Exios66/llm-mailroom/issues/321)) Agent input and output budgets are not provider-aware. One `max_tokens` and
  `max_input_chars` per agent, sized for small self-hosted windows, truncate whole-document JSON on a
  long-context API route, and the judge/arbiter source excerpts are module constants. The sandbox covers
  it with context fit and source windows, not a hotfix.

- **J-8** (upstream issue to be filed) `INTAKE_SYSTEM_PROMPT` asks for the FULL repaired text in `cleaned_text` while intake's `max_tokens`
  is 2,048 on every route; a document over about 2-3k characters is cut off mid-JSON and the whole read (triage, section map) is lost.
  The clean should be optional and bounded, or removed from the model's job (the deterministic clerk already runs first).
- **J-9** (upstream issue to be filed) `validate_intake` turns a parse failure into a truthy `unknown` / 0.0 triage that `format_intake_prior`
  sends to the sorter, and `format_intake_prior` prints any `doc_subclass` the model invented (`validate_triage` only truncates it).
  A failed read should carry no triage; the subclass should be checked against the sorter's catalog for the primary class.

When llm-mailroom ships one of these and the sandbox vendors it, retire the matching hotfix in the
same vendor refresh.

## Adding one

1. Reproduce the defect against the vendored code in a test.
2. Add a `Hotfix` to `HOTFIXES` with the target's current source sha256
   (`hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()`), an upstream reference and a
   wrapper that changes only the defect.
3. Add a row above and a CHANGELOG entry, and open the upstream issue.

A hotfix that rewrites text rather than behavior (HF-014 rewrites the served intake prompt) cannot be
fingerprinted by the target's source alone: its `install` raises `HotfixDrift` when the text it expects is gone,
and `apply_hotfixes` reports the fix `stale`, so the run fails preflight instead of running on a prompt the fix
no longer matches.

## Intake hotfixes in run provenance

`run.lock.json` records the hotfix set under `vendor_hotfixes` (every id, target and fingerprint, plus the sha256 of
`vendor_hotfixes.py`), so a lock written with HF-014 and HF-015 names them and a lock written before them carries
neither and refuses resume until `--force`. The prompt lock does **not** show HF-014: for the default
`code-default` intake prompt it stores no text and no hash, and for a local or Langfuse prompt it hashes the text
the run was given, not the text HF-014 serves after rewriting it. The served prompt differs from the locked one by
exactly the CLEAN block. Read the intake behavior from the hotfix set, not from `prompt` in the lock.

Every pipeline item record carries an `intake` block (`pred.intake` in `items.jsonl`), with no document text:
`gate_fired` (a prep is present, or the gate would have fired on the state's messy flag and length although the call raised and left no prep; that case is also `read_failed`), `windows`, `triage_class`, `triage_confidence`, `prior_sent` (an intake prior reached the sorter),
`clean_refused` (HF-003 refused a clean) and `read_failed` (the read ran and produced no triage). A cost estimate
counts the same gate: preflight's `context_plan` reports an `intake` block (`docs_gated`, `calls`, `input_usd`)
and adds the costliest gated document's read to each class's `clean`, `judged` and `worst` input cost. The term prices windows that HF-010 would refuse on an API route, so it errs high there. A gated document on an intake model with no API price leaves the class envelope unpriced (null), never $0.

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
