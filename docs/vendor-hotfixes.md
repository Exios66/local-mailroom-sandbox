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
  locks from before the layer carry no key. Preflight resumes such a lock only while it has no
  checkpoint (a checkpoint would mix scoring bases), and a direct run refuses one whose work has
  started. The process that executes the
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
| HF-002 | `agents.judge.CompletenessJudge.judge_completeness` | A completeness-judge parse failure is asked once more (the same vendored method, same arguments). A second parse failure raises instead of returning a real "incomplete 0.0" verdict, so the graph takes its judge-error path (human review, counted by the gate) instead of sending the document to the arbiter as if it were judged incomplete. Only the parse-failure answer is re-asked: a transport error is not caught here (HF-012 bounds those), and a parsed answer, however low, is the verdict. A re-ask is recorded as `judge_reasks` on the run item. Since phase 2 (L3) the re-ask is not the same request: its user message ends with a repair note (`JUDGE_REPAIR_NOTE`: the reply could not be read as the required JSON object, reply with only that object) followed by the first 1,000 characters of the reply that failed, so the model sees what went wrong. | [Exios66/llm-mailroom#315](https://github.com/Exios66/llm-mailroom/issues/315) |
| HF-003 | `agents.intake.IntakeAgent.intake_run` | A single-window intake `cleaned_text` replaces the document only when it keeps 90% of its length and its words: aligned in order, no run of 8 or more source words and no more than 5% of them may be lost, so a reply that drops a clause is refused even at full length. Context fit reads a long document in one window while intake's output allowance stays ~2k tokens, and the graph replaces the whole document with any accepted cleaned text. With HF-016 installed the prompt no longer asks for a clean, so this guard is latent: it stays as a backstop for a model that returns `cleaned_text` anyway. | [Exios66/llm-mailroom#316](https://github.com/Exios66/llm-mailroom/issues/316) |
| HF-004 | `pipeline.limits.record_usage` | Every returned chat call is priced against the run's `job.api_cost_cap_usd` as it returns (`job/call_guard.py`). The provider-pin wrappers refuse the next OpenRouter call once the cap or the per-document call ceiling is reached (40 for `pipeline`, 16 otherwise). Each guarded request (OpenRouter chat, LangChain and Decisions) first reserves its worst-case cost (its text at 0.25 tokens per character, its output cap or 4096 tokens), and a request whose estimate would pass the cap with every reservation in flight is refused before it goes out. A request is settled when it ends: released on success or when the provider rejected it (HTTP 4xx) or it never connected, charged at its reservation after a timeout, a 5xx or a dropped response (kept as `api_unreported_charge`, so a resume counts it). Spend therefore stops at the cap, within the size estimate's error; a document the guard cut short becomes an error row, never a score. A Decisions response is priced once, in the Decisions transport; while HF-004 is installed the usage accumulator is the unwrapped function, so that response is not priced again. Isolated `sorter_reviewer` and `extraction_gate` rows enter that document scope and use the default ceiling of 16. The R01 smoke's two merger agreements ran ~140 calls past the between-document check. | [Exios66/llm-mailroom#317](https://github.com/Exios66/llm-mailroom/issues/317) |
| HF-005 | `pipeline.watcher._DispatchPool.submit` | Backpressure. The watcher queues an inbox file for a worker slot only while the in-memory dispatch queue and `processing/` (and `review/`, when limited) are below their `MAILROOM_MAX_QUEUE_DEPTH_<STAGE>` limits (`mailroom_sandbox.backpressure`). Over a limit the file stays in `inbox/` and the next 1-second rescan offers it again, so intake slows and nothing is dropped. Upstream queued every inbox file with no bound. | [Exios66/llm-mailroom#318](https://github.com/Exios66/llm-mailroom/issues/318) |
| HF-006 | `langchain_agents.specialist_agents._SpecialistBase._confidence_missing` | Preserve an explicit numeric `0.0` in single and chunked extraction. Only missing confidence receives the existing evidence-derived fallback; a zero-confidence window cannot be lifted by that fallback. | [Exios66/llm-mailroom#279](https://github.com/Exios66/llm-mailroom/issues/279) |
| HF-007 | `graph.routing.judge_gate` | A confidence at or above `judge_band_high` still reaches the judge. `MAILROOM_JUDGE_VERIFY=off` still disables the lane. `MAILROOM_JUDGE_HIGH_BAND=off` restores the vendored band. The API cap still bounds spend. | [Exios66/llm-mailroom#278](https://github.com/Exios66/llm-mailroom/issues/278) |
| HF-008 | `langchain_agents.specialist_agents.merge_chunk_windows` | Records each surviving window's confidence on `_window_confidences` and its character length on `_window_lengths`. The merged confidence stays the vendored minimum (the old max-confidence merge is already gone). Scoring ignores the underscore key. | [Exios66/llm-mailroom#255](https://github.com/Exios66/llm-mailroom/issues/255) |
| HF-009 | `graph.build_graph._run_chunked_extraction` | An API-routed specialist (OpenRouter or any hosted provider) reads the whole document in one `extract` call and never chunks. A document longer than its input budget fails with `WholeDocumentTooLong`, which the extract node records as a parse failure and sends to review, so it is never chunked or silently truncated. Context fit sizes that budget to the model's context. Modal, vLLM and other self-hosted routes keep the vendored chunking for models whose context cannot hold the document. | [Exios66/llm-mailroom#319](https://github.com/Exios66/llm-mailroom/issues/319) |
| HF-010 | `agents.intake.sliding_windows` | When an API-routed sorter or intake would need more than one window for a document, the read fails with `WholeDocumentTooLong` instead. The sorter failure takes the graph's review path; intake fails soft and the deterministic clerk output stays. Calls from Modal, vLLM or other self-hosted routes, and calls from no agent, keep the vendored windows. | [Exios66/llm-mailroom#319](https://github.com/Exios66/llm-mailroom/issues/319) |
| HF-011 | `graph.routing.after_judge` (also bound to `after_arbiter`) | With `confidence.judge_exhausted_to_arbiter: true` (the overlay default), two `graph.route_spec` rules: a `partial` verdict on the last judge pass goes to the arbiter for a final ruling instead of straight to a person, unless `after_arbiter` would park it anyway (extraction still unsure, or an unadjudicated conflict, and HF-014 would not archive the acceptance), so no call is spent on a foregone park; and the arbiter cannot order a re-extraction once the judge passes are spent, because that retry could not be judged. `accept_with_caveats` archives through the vendored checks; anything else parks with the `judge_partial` cause. `incomplete`, judge errors and transient errors keep the vendored routes. The router itself is unchanged: `route_spec` binds routers at import, so its rule registry is the hook. Without the key both rules are inert. | [Exios66/llm-mailroom#320](https://github.com/Exios66/llm-mailroom/issues/320) |
| HF-012 | `graph.routing._transient_decision` | `confidence.transient_retry_max`, when set, is the number of times a node re-runs after a transient provider error (overlay: 1). `retry_chat_completion` already retries inside each call (5 attempts plus the SDK's own), so the vendored two node-level re-runs repeated whole extractions and judge passes. Unset keeps the vendored budget; counters and the `transient_exhausted` cause are unchanged. | [Exios66/llm-mailroom#320](https://github.com/Exios66/llm-mailroom/issues/320) |
| HF-013 | `agents.judge.CompletenessJudge.judge_extraction_correctness` | An accuracy-judge parse failure raises `JudgeParseError` instead of returning "inaccurate 0.0". That answer used to turn a `complete` completeness verdict into `incomplete`, so a judge that never reached a verdict spent an arbiter call, a re-extraction and a second judge pass. The graph now takes the judge-error path HF-002 uses: `judge_verdict` `judge_error`, human review, counted by the gate. A parsed answer, however low, is unchanged. Like HF-002, it asks the judge once more after a parse failure and raises only when the second answer fails to parse too. Since phase 2 (L3) the re-ask is not the same request: its user message ends with a repair note (`JUDGE_REPAIR_NOTE`: the reply could not be read as the required JSON object, reply with only that object) followed by the first 1,000 characters of the reply that failed, so the model sees what went wrong. | to file (J-8) |
| HF-014 | `graph.routing.after_arbiter` (also bound to `_extraction_still_unsure`, `_unadjudicated_conflict`, `_chunks_lost`) | With `confidence.arbiter_full_source: true` (the overlay default) on a context-fitted route, a `graph.route_spec` rule after HF-011's: an arbiter `accept_with_caveats` goes to `compile_report` and archive instead of human review when the arbiter read the whole source and the extraction confidence reaches `confidence.arbiter_full_source_min_confidence` (a number in [0, 1]; unset, the class's own `low` band, by-class overrides included, read as routing reads it). A missing or non-numeric confidence never reaches it, and the judge verdict is not gated. Because the vendored route already archives an acceptance at or above `low`, HF-014 changes no route at the default floor; a run that sets the floor lower (e.g. 0.5) lets the arbiter's whole-source ruling count down to it. The floor can only lower the bar: HF-014 turns a park into an archive and never the reverse, so a floor above the class `low` is a silent no-op (the vendored route still archives an acceptance at or above `low`; `tests/test_arbiter_floor_route_differential.py` pins zero route changes at 0.95). Reading the whole source means the arbiter window was widened by context fit, `doc_text` fits in it, no chunked window was lost and no matter conflict is unadjudicated. The vendored route parks every acceptance whose extraction is still unsure (confidence under the class `low` band, no source-verified judge verdict); on a 16k-excerpt route that park guards against an arbiter that saw a fraction of the document, so Modal/vLLM and local routes keep it. Every caveat-accepted archive carries an `arbiter_caveats` marker on the run item (`decision`, `reasoning`, `judge_verdict`, `whole_source`, and `hf014` when the vendored route would have parked it); the gate report counts them, `floor_digest.json` carries them (`caveats` per document, `caveat_archives` per run; the floor viewer does not render them yet), and they are scored like any other archive. HF-011's skip check uses the same rule. | to file (J-9) |
| HF-015 | `agents.arbiter.ArbiterAgent.arbitrate` (also bound to `graph.build_graph.arbiter_node`) | With the same key on a context-fitted route, an arbiter call with no re-extraction budget left (HF-011's last judge pass spent, or `arbiter_retry_count` at `arbiter_retry_max`) is a final ruling: `retry_extraction` is dropped from the decision enum and the request says why, so the model chooses between `accept_with_caveats` and `human_review`. An answer that still names a retry (a provider that ignores the schema) becomes `human_review` with its own reason instead of the stale "ordered re-extraction" one. It finds the graph state from its `arbiter_node` caller, whose source is pinned by `also`, so a vendored change to that node makes HF-015 stale; called from anywhere else it is the vendored request. Every other call, and every Modal/vLLM or local call, is unchanged. | to file (J-10) |
| HF-016 | `agents.intake.IntakeAgent.system_prompt` (also swaps `agents.intake.INTAKE_SCHEMA` and wraps `agents.intake.validate_intake`) | Intake returns triage and a short section map only. The prompt the agent serves has its CLEAN block replaced by "set `cleaned_text` to null" (the rewrite runs on the served text, so a Langfuse-managed or locally overridden prompt gets it too; a text with no CLEAN block loses any line asking for the full or repaired `cleaned_text` and gets an explicit override appended), and the schema sent with every call drops `cleaned_text`. The prompt's "at most 40 sections" becomes "at most 12" (a served prompt that states another limit, or none, is capped too; the swapped schema copy gets `maxItems` 12 only if the sections array carries one, and the vendored schema carries none). Because a model can ignore the instruction, a wrapper on `validate_intake` (the one seam every reply passes through before the graph builds `prep["cleaned"]`) sets `cleaned_text` to None unconditionally and records `clean_refused` when it dropped a non-empty one, so a returned clean with an altered number or appended text never becomes the working text (a multi-window read never uses a clean, and records no refusal). HF-017 wraps the same function; the two are independent and install in the same order every time (HF-016 inside HF-017), one wrapper each however often hotfixes are applied or the module is reloaded. Upstream asks a messy document's model to re-emit the whole text, but intake's output allowance is 2,048 tokens, so a messy document of more than roughly 2-3k characters (estimated; it depends on the size of the section map) was cut off mid-JSON: the triage, the section map and the clean were lost and the input was still paid. The 40-section map was estimated at 1.9k to 2.5k tokens on its own; a 12-section reply with triage is estimated at 0.7k to 0.9k (JSON characters over 2.4 to 3.2 characters per token, not a tokenizer count), so a cut-off is much less likely, not impossible; intake's `max_tokens` is unchanged. A document's working text is now always the deterministic clerk output. HF-003 stays installed behind the null clean and is latent. If the vendored prompt's CLEAN block or its "at most 40 sections" limit, or the schema's `cleaned_text`, moves, the hotfix is reported `stale` and preflight fails. | upstream issue to be filed (J-11) |
| HF-017 | `agents.intake.validate_intake` (also wraps `agents.intake.format_intake_prior` and `agents.intake._merge_triage`) | A failed intake read has no triage, so the sorter gets no prior. A reply with a parse error, no `triage` object or no `primary_doc_class` (a cut-off JSON, prose, a JSON list) used to become a truthy triage of `unknown`, confidence 0.0 and no gist, which `format_intake_prior` fed to the sorter as an advisory read. It is now an empty triage and `format_intake_prior` returns "". `_merge_triage` also drops empty reads before it merges, so a failed window never hides another window's honest `unknown` read (upstream's all-unknown fallback was `reads[0]`). A model that answers `unknown` with a gist is a real read and keeps its prior. The prior's `subclass:` line is printed only for a token in the sorter's catalog for that primary class (`valid_sorter_subclasses`); an invented subtype is dropped, and so is any subclass for a class with no catalog. | upstream issue to be filed (J-12) |
| HF-018 | `graph.route_spec.decide_route` | The loop governor (phase 2). With `job.governor` set, every conditional route's final answer (after the base router and every registered rule, HF-011 and HF-014 included) passes `governor.govern`. A route that would add a round (`retry_classify`, `retry_extract`, `arbiter`, `boss_escalation`; a node re-run for a transient error is not a round, a second re-extraction is) is stopped, first match wins: `boss_repeat` (a second boss entry), `retry_budget` (2 rounds per document), `call_budget` (30 model calls, mergers 36, below the hard ceiling of 40), `spend_budget` (off unless `spend_usd` is set). A stopped document goes to `human_review`, or to `compile_report` (`archive_with_caveats`) when its latest recorded extraction attempt has a `complete` judge verdict and the vendored judge tail's archive guards hold (`routing._extraction_still_unsure` and `routing._unadjudicated_conflict` are both false); a stopped boss entry is never archived (the vendored `judge_findings` holds the judge's reasoning, so it is not read). The first stop is recorded as `governor_stop` on the result (reason, outcome, node, proposed route, calls, retries, spend). L2: with `sorter_ceiling` set, a classify retry at or above it goes to `review_classify` instead (counted under `governor_skips`, not a round). Off, or outside a document scope, the route is unchanged. Counters live in the call guard's document scope, never in graph state. | sandbox-only (upstream issue to be filed with the pilot's results) |
| HF-019 | `graph.build_graph._detect_conflict` (also pins `_fetch_matter_context`) | L4. With `job.governor` and `link_duplicates` on, a matter conflict whose every compared archived row (same class or none, another document, with extracted data) is the same file (`file_sha256`) or a near copy (word 5-shingle Jaccard at or above `near_duplicate_jaccard`, 0.9, and every archived value that differs from the new extraction appears in the new text, so template siblings with other parties or dates still conflict) is recorded as `duplicate_of` (`doc_id`, `kind` exact or near, `similarity`) and reported as no conflict, so it does not spend a boss entry. One non-duplicate row keeps the conflict, and a failure here keeps the original answer. The near-copy index is in-process and per run (reset on activation), a 256-hash bottom-k sketch per document, so near matches are found only among documents this process has seen; the estimate is exact for short documents and has about 0.02 noise near the threshold on long ones. | upstream issue to be filed (a re-ingested document reads as a matter conflict) |
| HF-023 | `graph.build_graph._instantiate_specialist` (also wraps `_build_handoff_context`; pins it, `extract_node`, `_run_chunked_extraction` and `retry_extract_node`) | X1. With `job.subclass_schemas` on (every pipeline run), the handoff wrapper picks the schema for the document's predicted subclass from `config/extraction/subclass_extraction_fields.json` (`subclass_extraction.choose_schema`), and the instantiate wrapper gives that extraction's one specialist instance an instance-level `_call_structured`, which sends the chosen schema in place of the class schema object. That covers every chunk window and never reaches another agent or document; the class method (read-range observer, sampling) still runs underneath. An unknown, `other` or unlisted subclass, or a class confidence below the `low` band, keeps the class schema, and so does a corporate specialist whose `extract` another hotfix wraps (that hotfix composes its own schema). Off, both wrappers pass through. It stacks with other `_build_handoff_context` wrappers in either order (`functools.wraps` carries each marker). | upstream issue to be filed (every subclass is asked for the whole class schema, including fields the Dojo marks not applicable) |
| HF-024 | `graph.build_graph._clean_fields_for_judge` (also wraps `agents.judge.CompletenessJudge._field_list`; pins it, `judge_verify_node`, `arbiter_node` and `_retry_handoff_summary`) | X1, review side. When HF-023 sent a document's extraction a narrowed schema, the fields the judge, the arbiter and the retry summary see, and the judge's expected-field list, are the ones that extraction was asked for: the dropped fields are left out and the added ones listed. The choice is kept in the document's call-guard scope, so it holds for every judge pass and arbiter call, and a later fallback extraction (unknown subclass, low confidence) restores the class fields. Off, both wrappers pass through. | upstream issue to be filed (the judge expects every class field, including fields the extraction was not asked for) |
| HF-025 | `graph.build_graph.judge_verify_node` (pins `graph.routing.after_judge` and `agents.judge.CompletenessJudge.judge_completeness`) | Phase 4 record. With a `judge:` section, every judge pass that rules (not a skip or a transient error) is recorded in the document's call-guard scope as `judge_rulings` (pass, mode, ruling, score, reason, fixes, retry and wrong fields, model), with `before_judge`, the first pass's cleaned extraction; `eval.runners._run_pipeline_doc` copies both into the result. `mode: verify` leaves the vendored judge unchanged. `mode: correct` replaces the completeness and accuracy calls with one ruling (`correcting_judge.rule`): the whole document first, then the extraction's requested fields; accept, retry named fields, or a person. Only fixes whose quote is in the document and supports the value (`judge_fixes.verify_fix`) are written; a wrong field with no verified fix is retried on the first ruling and sent to a person on the second; a prompt over the model's context is `judge_input_too_long` (no call); a reply that fails to parse after one re-ask is `judge_error`. Without the section the node is the vendored one and nothing is recorded. | sandbox-only (phase 4 correcting judge; upstream issue to be filed with the pilot's results) |
| HF-026 | `graph.build_graph.arbiter_node` (pins `graph.routing.after_arbiter`) | Phase 4. With `judge: mode: correct` the arbiter makes no model call: the judge's last recorded ruling becomes the arbiter's decision (`retry_extraction` with the named fields and `arbiter_retry_count` + 1, `accept_with_caveats`, or `human_review` with the judge's reason), which the vendored `after_arbiter` routes. The loop governor does not count this pass-through as a round. Verify mode and no section run the vendored arbiter. | sandbox-only (phase 4 correcting judge; upstream issue to be filed with the pilot's results) |
| HF-027 | `graph.build_graph.retry_extract_node` (also wraps `_enrich_contract_result`; pins it and `graph.routing.after_retry_extraction_gated`; route rule `HF-027:judge_retry_rejudges` on `retry_extract`) | Phase 4. With `judge: mode: correct`, a judge-ordered re-extraction sends the specialist the chosen schema restricted to the named fields (`subclass_extraction.fields_only`) and merges its answer into the previous extraction before the guard, conflict check and attempt history run, so only the named fields change; the judge still reviews the whole extraction. The route rule sends the re-read back to the judge for its second, final ruling (a transient self-loop or a Boss conflict keeps the router's answer). Any other retry is the vendored node. | sandbox-only (phase 4 correcting judge; upstream issue to be filed with the pilot's results) |

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
- **J-8** (to file) `CompletenessJudge.judge_extraction_correctness` has J-1's defect: a structured-output
  parse failure returns `inaccurate` 0.0, which `judge_verify` reads as an `incomplete` verdict instead of a
  judge error. HF-013 covers it. Neither judge re-asks an unparseable answer upstream; HF-002 and HF-013 ask
  once more before raising.
- **J-9** (to file) `after_arbiter` parks `accept_with_caveats` whenever the extraction is still unsure,
  whatever the arbiter read. With provider-aware source windows (J-7) an arbiter that read the whole
  document should be able to accept with caveats, with lost chunks and conflicts still parking. HF-014
  covers it on context-fitted routes.
- **J-10** (to file) `ArbiterAgent.arbitrate` always offers `retry_extraction`, even when the graph can no
  longer grant one, so the model's ruling is replaced by a park under the arbiter's "ordered
  re-extraction" reason. The caller should pass the remaining budget. HF-015 covers it on
  context-fitted routes. Modal/vLLM still reports an ungrantable retry as "ordered re-extraction";
  HF-011 still parks it.

### What a hotfix change means for run locks

Every hotfix added or changed after a run was locked changes that lock's `vendor_hotfixes` identity:

- **HF-013** (`agents.judge.CompletenessJudge.judge_extraction_correctness`) applies on every route and
  profile wherever the accuracy judge runs, which is only after a `complete` completeness verdict. A run
  records it in `run.lock.json` under `vendor_hotfixes.fixes` (id, target, source sha256), and the
  module sha256 changes with it. A run locked from this checkout records the new hashes automatically.
  A lock written before the change would need `sandbox run preflight --force` to re-lock before it could
  resume; no run needs that today.
- **HF-002 and HF-013 ask a judge once more after a parse failure.** The wrapper calls the vendored
  method again with the same arguments when it returns the parse-failure answer. The re-ask is a call
  like any other: it passes the API call guard (and counts toward the per-document ceiling), the provider
  pins, usage capture and the spend caps. One run of the judge node therefore holds at most two calls per judge method, four
  in all, and preflight's `worst` envelope prices four judge calls per pass (`clean` and `judged` keep two).
  The envelope counts per node run: a transient HF-012 re-run of the node (up to two more) can re-ask
  again, and, like transport retries, is not priced; the per-document call ceiling still bounds spend.
  The vendored targets are unchanged, so their source fingerprints are unchanged, but the module sha256
  in a lock changes with this edit. Each re-ask is counted per judge (`asked`, `recovered`, `parked`) in
  the document's call-guard scope, copied onto the run item's pipeline result as `judge_reasks` (only when
  one happened, no document text) and totalled in the gate report's `judge_reasks` block
  (`gate.json` and `--json`; `gate.md` does not render it), so a first live run measures the parse-failure
  rate and how often the second answer parses. Every re-ask ends in exactly one of three ways: `recovered`
  (the second answer parsed as JSON; a valid answer of the wrong shape, such as `{}`, also counts, because the wrapper sees only the vendored method's processed result), `parked` (it did not parse either, so the judge raised `JudgeParseError`) or
  `errored` (the second call itself raised, a transport error or the guard's refusal, and the error
  propagates unchanged). The scope records `asked` before the second call is made and the other two after,
  and the gate derives `errored = asked - recovered - parked`, so `asked = recovered + parked + errored`
  and `parked` counts only re-asks that parked on a second parse failure. A re-ask outside a document scope
  (the standalone per-agent `judge` eval in `eval/agents.py`) is made but not counted; no shipped config
  runs that path.
- **HF-014** (`graph.routing.after_arbiter`, with three helper predicates bound by `also`) and **HF-015**
  (`agents.arbiter.ArbiterAgent.arbitrate`) change routes and requests only where
  `confidence.arbiter_full_source` is `true` and context fit widened the arbiter's source window, that
  is OpenRouter and other context-fitted API routes. Modal/vLLM and local routes are byte-for-byte
  unchanged. A run records both under `vendor_hotfixes.fixes` with the module sha256, and the key in
  its frozen `effective_confidence` (plus `arbiter_full_source_min_confidence` when the run sets it;
  unset, the floor is each class's `low` and HF-014 changes no route); a new run locks the new hashes
  and the keys automatically. A lock
  written before the change needs `sandbox run preflight --force` to re-lock before it could resume
  (no run needs it today); a legacy lock with no frozen `effective_confidence` drops the key on resume
  (`routing_audit.OVERLAY_RETRY_KEYS`) unless its own `confidence` block set it, which leaves both
  hotfixes inert.

- **J-11** (upstream issue to be filed) `INTAKE_SYSTEM_PROMPT` asks for the FULL repaired text in `cleaned_text` while intake's `max_tokens`
  is 2,048 on every route; a long enough messy document is likely to be cut off mid-JSON and the whole read (triage, section map) is lost.
  The clean should be optional and bounded, or removed from the model's job (the deterministic clerk already runs first).
- **J-12** (upstream issue to be filed) `validate_intake` turns a parse failure into a truthy `unknown` / 0.0 triage that `format_intake_prior`
  sends to the sorter, and `format_intake_prior` prints any `doc_subclass` the model invented (`validate_triage` only truncates it).
  A failed read should carry no triage; the subclass should be checked against the sorter's catalog for the primary class.

When llm-mailroom ships one of these and the sandbox vendors it, retire the matching hotfix in the
same vendor refresh.

### Known limits

- **The re-ask count rests on the judge methods being the only retry.** The HF-002 and HF-013
  fingerprints cover `judge_completeness` and `judge_extraction_correctness`, not
  `BaseAgent._call_structured`. If llm-mailroom ever adds its own parse retry there, a pass would make
  more calls than the four priced per pass without a stale fingerprint; re-check the envelope at the
  next vendor refresh.
- **The re-ask counts miss a document that raises, and a resumed document's second attempt.** A document the pipeline returns as failed
  becomes an error item whose `pred` keeps its `judge_reasks`, and the gate counts them (outcome `crashed`).
  A document that raises (a crash, or the call guard's refusal, which `_run_pipeline_doc` turns into an
  exception) writes no item at all: the run fails, a resume runs the document again in a fresh scope, and
  the first attempt's re-asks are not counted anywhere, although they were made and billed (the billed
  tokens are kept for the API budget, SAND-089). A resumed document is the same: the first row stays the evidence, so the re-asks of the
  second attempt are made and billed but not added, for an error item and a good one alike. The counts are
  therefore a lower bound on re-asks made.
- **A judge that fails to parse twice still parks the document.** HF-002 and HF-013 ask once more, so a
  single unparseable answer no longer parks a correct document, but two in a row still raise
  `JudgeParseError` (human review, counted by the gate as `parked`). Since phase 2 (L3) the re-ask carries a
  repair note and the start of the unparseable reply, so it is not the same request. How often a live judge
  fails to parse and recovers on the re-ask is unmeasured offline (the harness answers its own scripted
  verdicts); the first spend-gated run reads it from `judge_reasks` on the items and in the gate report.
- **HF-014 answers before any later `decision_point:*` route rule.** `graph.route_spec.decide_route`
  returns the first rule that answers, and HF-014's rule is registered right after HF-011's, ahead of the
  `decision_point:*` rules that `graph.decision_points` appends. A veto from such a rule on the
  `arbiter` node (for example a gate slot such as `arbiter_veto`) is therefore never consulted for a
  document HF-014 archives, which is only one whose extraction is under the class `low` and whose floor
  was lowered. It is latent today: the sandbox overlay configures no decision points (`decision_points`
  stays `{}`), and the pinned vendor snapshot has no `graph/decision_slots.py`, which the job spec's
  `decision_slots` block refers to. At the vendor refresh that ships it, register HF-014 after the slot
  rules or make its rule defer to them, and extend `tests/test_arbiter_floor_route_differential.py` with a
  veto registered before relying on both.

## Adding one

1. Reproduce the defect against the vendored code in a test.
2. Add a `Hotfix` to `HOTFIXES` with the target's current source sha256
   (`hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()`), an upstream reference and a
   wrapper that changes only the defect.
3. Add a row above and a CHANGELOG entry, and open the upstream issue.

A hotfix that rewrites text rather than behavior (HF-016 rewrites the served intake prompt) cannot be
fingerprinted by the target's source alone: its `install` raises `HotfixDrift` when the text it expects is gone,
and `apply_hotfixes` reports the fix `stale`, so the run fails preflight instead of running on a prompt the fix
no longer matches.

## Intake hotfixes in run provenance

`run.lock.json` records the hotfix set under `vendor_hotfixes` (every id, target and fingerprint, plus the sha256 of
`vendor_hotfixes.py`), so a lock written with HF-016 and HF-017 names them and a lock written before them carries
neither and refuses resume until `--force`. The prompt lock does **not** show HF-016: for the default
`code-default` intake prompt it stores no text and no hash, and for a local or Langfuse prompt it hashes the text
the run was given, not the text HF-016 serves after rewriting it. The served prompt differs from the locked one by
the CLEAN block and the section limit. Read the intake behavior from the hotfix set, not from `prompt` in the lock.

Every pipeline item record carries an `intake` block (`pred.intake` in `items.jsonl`), with no document text:
`gate_fired` (a prep is present, or the gate would have fired on the state's messy flag and length although the call raised and left no prep; that case is also `read_failed`), `windows`, `triage_class`, `triage_confidence`, `prior_sent` (an intake prior reached the sorter),
`clean_refused` (HF-003 or HF-016 refused a clean) and `read_failed` (the read ran and produced no triage). A cost estimate
counts the same gate: preflight's `context_plan` reports an `intake` block (`docs_gated`, `calls`, `input_usd`)
and adds the costliest gated document's read to each class's `clean`, `judged` and `worst` input cost. The term prices windows that HF-010 would refuse on an API route, so it errs high there. A gated document on an intake model with no API price leaves the class envelope unpriced (null), never $0. The window count is an estimate (the document over the window span less its 15% overlap); it ignores paragraph packing, so it is not an upper bound. HF-010 limits an API-routed intake to one window, so priced runs are unaffected; only a Modal/vLLM or self-hosted intake slides windows.

Known limits of the intake hotfixes (no code change; each is upstream behavior or a heuristic):

- A model class outside the vocabulary is clamped to `unknown` by upstream `validate_triage` at the model's own
  confidence, and a triage with a gist is still sent to the sorter as a prior (an honest `unknown` read is kept on
  purpose). HF-017 does not change that.
- `gate_fired` for a call that raised inside the node (no prep) is a heuristic: it re-applies the gate to the final
  state's `doc_text` and `intake_messy` flag, not to the text the node saw, so it can differ for a document whose text
  the node replaced.
- `clean_refused` from HF-016 is recorded only for a single-window read; a multi-window read never uses a clean and
  keeps no refusal.

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
