# Phase 5, part 1: attempt hygiene on the OpenRouter route

**Status.** Approved 2026-11-27; implemented per the [plan](../plans/2026-11-27-phase5-attempt-hygiene.md). Part 1 of Phase 5 of the
[correcting-judge design](2026-11-26-correcting-judge-design.md) (rows D1 and D2), re-scoped to the
production route: OpenRouter, `qwen3.7-flash`, context-fitted whole-document reads.

**Goal.** Better results on the production route at no extra model calls, measured first offline from
runs the owner is already going to launch.

## Why the scope changed

The spec's D1 and D2 fixes were written for chunked reads. The production route no longer chunks:

- context fit sizes every budget to the model's 1M-token window, so a specialist reads the document in
  one call, and the judge and arbiter read the whole source;
- the production slices' `*-modal-host.yaml` twins only host the job on Modal, and every model call
  still goes to OpenRouter;
- since #253, a retry is primed with the judge's findings and field names, never the earlier values.

So on this route the chunk-merge fixes (`chunking.merge.policy: evidence`, best-supported scalars) never
run. Two D2 problems remain:

| Problem | Evidence | Fix in this design |
| --- | --- | --- |
| The last attempt always wins, even when the judge rated an earlier one higher | `graph/attempts.py` ships selection off; `keep_best_attempt` cannot be set from a run spec | **A.** Make `keep_best_attempt` a run-spec flag |
| False list items on whole-document reads | E1 control (whole-document reads): 27 false CUAD clauses on 20 contracts, 12 to 15 on the 8 single-window ones (`docs/audits/2026-11-15-contract-recall-routing-ladder.md`, E1 result) | **B.** Evidence-check list items from a one-call read |

Part 2, the merger cost (about 410k tokens per merger document for MAUD 0.10), is a separate design.
It waits for stage 1's per-node token counts, which will show whether that cost comes from document
length or from repeated reads. Phase 4's correct mode (no arbiter call, field-only retries) may already
remove much of it.

## A. Keep the best-judged attempt (`job.confidence.keep_best_attempt`)

The vendored selection already exists (#254, `graph/attempts.py`). Every attempt is recorded with its
judge verdict. When selection is on, `compile_report` and the review handoff use the best attempt:

- candidates are attempts with a verdict that passed the schema and quality gate;
- they rank `complete` > `partial` > `incomplete`, then by confidence, and a tie keeps the latest;
- a Boss conflict pins the latest attempt;
- for the archive, an earlier attempt that is still unsure or below the coverage floor is not used
  (`earlier_attempt_requires_review`).

Routing never reads the flag. The only gap is the sandbox: `job.confidence` refuses the key. The change:

- add `keep_best_attempt` to the run spec's boolean threshold flags (`_THRESHOLD_FLAG` in
  `job/spec.py`), globally and per class, as a real boolean only;
- hash it and lock it the way the other threshold flags are; a spec without it hashes as before;
- the routing audit reports it, and `unknown` stays `unknown` unless the lock sets it;
- **refuse it with `judge: mode: correct`.** HF-025 applies verified fixes to `extracted_data`
  without writing them into the attempt history, so restoring an earlier attempt could drop them.
  Correct mode already bounds a document to two rulings with a field-only retry in between, which
  leaves little for selection to do. Lifting the refusal is a follow-up: HF-025 records applied
  fixes in the history entry first.

No vendor hotfix is needed: this is configuration of vendored behaviour.

## B. Evidence check for one-call reads (HF-029)

The vendored evidence test (`_item_support` in `langchain_agents/specialist_agents.py`) works on a
single window: it checks each item's quote fragments against the window text, or a reasoning entry
for that field whose quote is in the text. A one-call read never reaches it, because `merge_chunk_windows`
runs only for two or more windows.

HF-029 wraps `graph.build_graph._enrich_contract_result`, which both `extract_node` and
`retry_extract_node` call on every specialist result:

- **Scope.** Only an extraction read in one call. A chunked extraction keeps the configured merge
  policy, so the filter never runs twice.
- **Fields.** The vendored `_DEFAULT_EVIDENCE_FIELDS`: `cuad_clauses`, `claim_checklist`,
  `action_items` and `denial_reasons`. Label lists (`maud_clauses`, parties, keywords) are never
  filtered, so mergers are unaffected.
- **Rule.** The document text is the window. An item is dropped only when the vendored test returns
  `False`, i.e. it has a checkable quote and none of it is found. An evidenced or unverifiable item
  (`True` or `None`) is kept.
- **Record.** Dropped items go into the extraction's metadata (`_evidence_dropped`, per field), so the
  report counts them and a reviewer can see them. Nothing else in the extraction changes.
- **Order.** The check is idempotent, so composing it with HF-027's field-only retry merge gives the
  same result in either order.
- **Switch.** `job.evidence_check: true`. It is a `StrictBool`, off by default, hashed only when set, and
  refused unless `task: pipeline`. It follows `job.schema_guide` and `job.subclass_field_note`.

The judge then sees the filtered extraction, which is the point: it no longer rates false clauses.

## Measurement: offline first, from the stage-1 verify run

Both changes can be estimated with no new spend, from `p4-s1-verify-gov-off` (stage 1, 300 dev-look1
documents), which the owner is already going to launch:

- **A** changes no routing, so it is exact offline. A pipeline item's stored answer is the graph's
  final state (`graph.invoke` in `_execute_run`), which carries every attempt and its verdict, so
  scoring the selected attempt against the latest one is the A/B. The plan's first task pins that the
  item record keeps the history, with a test.
- **B** is an estimate offline. Filtering each recorded extraction against its dataset text and
  rescoring gives the precision and recall change. What it cannot show is the downstream effect: the
  judge rated the unfiltered extraction, so routing could differ. A paid confirming arm is needed
  only if the replay shows a gain worth adopting.

A replay script, `scripts/replay_attempt_hygiene.py --run <run_id>`, reads a finished run store and
prints, per class and overall:

- latest-versus-selected quality, and how many documents selection changed;
- CUAD and checklist missed or false items, and quality before and after the filter;
- items dropped per field;
- `scored_n` throughout.

It runs offline only and is tested on a fixture run store.

**Adoption bars** (the owner decides; each is a paired comparison on the same documents):

- **A** ships if quality is not lower on any class with `scored_n` of at least 10, and is higher
  overall.
- **B** goes to a paid confirming arm if false items fall by at least 25% while missed items rise by
  no more than 2 per 100 documents. It is adopted on that arm's result.

## Out of scope

- Chunking on OpenRouter. E1 showed that chunked reads recover recall, with missed clauses falling
  from 58 to 34 on chunked contracts, but at 1.8× tokens. It is a candidate for part 2 with the
  `evidence` merge, not for this part, which adds no calls.
- The Modal and local routes' 16k windows, low output caps and chunked judge coverage (SAND-093). They
  matter only off the production route.
- Editing any frozen prompt.

## Risks

- **The judge is uncalibrated.** Selection trusts its verdicts. The offline replay measures exactly
  that trust on stage 1's documents before anything ships.
- **A paraphrased true clause is dropped.** The vendored test folds typography but not wording, so
  recall can fall. The replay reports missed items, and the bar caps the rise.
- **An emptied list.** A field whose every item is dropped becomes `[]`. The plan pins how the
  guardrail's non-empty check treats that, with a test.

## Files

- `src/mailroom_sandbox/job/spec.py`: the `keep_best_attempt` flag, the correct-mode refusal and
  `job.evidence_check`.
- `src/mailroom_sandbox/job/routing_audit.py`: report the flag.
- `src/mailroom_sandbox/vendor_hotfixes.py`: HF-029. `docs/vendor-hotfixes.md`,
  `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md` and `docs/numbering-reservations.md` get the rows.
- `scripts/replay_attempt_hygiene.py` and its tests.
- Docs: `docs/jobs.md`, `docs/critical-regressions.md` (guard names), `CHANGELOG.md` and the
  `docs/README.md` index row.
