# Correcting judge: one decisive, evidence-cited ruling per routed document

Status: draft for owner review · approach 1 (sandbox hotfix first, upstream later) chosen by the
owner · 2026-11-26

## Why

The in-graph judge sits at the pipeline's critical decision point: it is the only call that decides
whether an uncertain extraction is archived, retried or sent to a person. Today it cannot settle
anything itself.

- It only diagnoses (`complete` / `partial` / `incomplete`), plus a second correctness call when it
  says `complete` (`judge_verify_node`, `vendor/llm-mailroom/src/graph/build_graph.py:2246`).
- The arbiter then makes the decision, and a retry re-extracts the **whole** document, after which
  the judge runs again. The overlay allows `judge_max_passes: 2` and `arbiter_retry_max: 1`
  (`config/taxonomy.overlay.yaml:75-83`).
- It sees only the class, the extracted fields and the source text: not the earlier passes the graph
  already holds (`extraction_attempt_history`, `graph/attempts.py`), not the labeling guide, and not
  how similar documents were labeled.

Measured cost of that indecision:

- Documents caught in the judge→arbiter→retry loop took 3 passes and about 40 specialist calls each,
  against about 14 for a judge-skipped one; contracts parked on `judge_partial` 4 of 5 times
  (`docs/audits/2026-11-15-pipeline-qwen-flash-25-failure-modes.md:23-38, :71-76`).
- R01 smoke mergers ran about 140 calls past the between-document spend check (HF-004 note,
  `docs/vendor-hotfixes.md:39`); a merger costs 20+ calls against 4-5 for correspondence
  (`reports/dashboard/FLOOR_RUN_REPORT.md:36-40`).

The owner wants the judge to be capable enough to handle a routed document itself, correcting fields
with cited evidence, so that indecisive or incompetent rounds stop generating calls. It must fit the
experimental design (no leakage, frozen per run, comparable KPIs) and be switchable into production.
**The sandbox is the production deployment environment**, so it is patched first; the
`llm-mailroom` fixes follow later through clearly written issues.

## Goals

1. **One decisive ruling.** A document routed to the judge gets a ruling of `accept` (with any
   verified fixes), `retry_fields` (one targeted retry of named fields) or `human_review`. The arbiter
   makes no LLM call when the new mode is on.
2. **Corrections with evidence.** Each fix names a field, a new value and a verbatim quote from the
   source. Code verifies every quote and value before a fix is applied; a fix that fails is dropped
   and recorded, never applied.
3. **Bounded by construction.** At most two judge rulings and one targeted retry per document. The
   second ruling cannot ask for another retry. A document that exhausts the lane goes to human review
   with a recorded reason, so it stays a scored review row instead of an unscored error.
4. **Better-informed rulings.** The judge reads the earlier passes, the labeling guide's field
   definitions for the class, and reference labels of similar documents from a leak-free pool.
5. **A stronger, pinned model** for the judge in this mode.
6. **KPIs stay easy to report**, with the judge's contribution separable (see KPIs below).
7. **A per-run toggle, off by default.** Past locks and runs without the block behave exactly as
   today. Production adopts it only through an explicit, reviewed config change after the A/B.
8. **Upstream follow-through.** Draft issues for `llm-mailroom` are part of the deliverable.

## Non-goals

- Changing who reaches the judge (the HF-007 gate and `judge_band_high` stay as they are).
- The classification judge (`judge_classification`) and the classification arbiter: this covers
  extraction only.
- The boss path (`boss_escalation`, after extraction fails twice or on a matter conflict). The owner
  has seen the boss loop; that gets its own investigation and upstream issue (the floor report shows
  boss at 17 documents and 34 calls in one window).
- Changing the global per-document call guard (`job/call_guard.py`), scoring truth, or any label.
- Embedding or vector search infrastructure.

## Anti-goals: results that technically work but fail

- A score lift that comes from the judge seeing the answer: its own document's labels, a thread
  sibling's, or any evaluation or held-out document's (`docs/critical-regressions.md` row 3).
- A "fix" without a quote that really appears in the document, or a quote that does not support the
  value.
- Documents leaving the scored set unmarked: an accept-with-fixes must carry a marker and stay in the
  denominators (row 22); a lane-exhausted document must be a review row, not a crashed one.
- A locked or resumed run silently changing behaviour (rows 6 and 9).
- More calls per judged document than today on any class.

## Approaches considered

1. **Sandbox vendor hotfix first, then upstream (chosen by the owner).** Built in
   `src/mailroom_sandbox/vendor_hotfixes.py` behind a run-spec block that is off by default,
   A/B-tested against today's judge, then adopted by production configs; `llm-mailroom` issues are
   opened for the permanent fix. Evidence comes before production changes; two implementations exist
   until upstream ships.
2. **Upstream first.** One implementation with a native toggle, but production code changes before
   any evidence, and the repository is not attached to this session.
3. Dropped: a post-pipeline re-judge stage (does not stop the in-graph loops) and context-only
   prompt changes (the owner rejected "more context, same loop").

## Design

### 1. The toggle: a `judge:` run-spec block

A new optional `RunSpec` field `judge: JudgeSpec` (`extra: forbid`), following the four-step path the
existing blocks use: a field on `RunSpec` (`job/spec.py:1177`), a hash-when-set entry in `spec_core`
(`:1391-1440`), a lock entry written in `preflight.py`, and a read in `runtime.activate()`'s locked
branch (`runtime.py:450-468`). Absent block = today's behaviour, and the spec hash of every existing
config is unchanged.

```yaml
judge:
  mode: correct              # verify (today) | correct
  model: qwen/qwen3.7-plus   # required in correct mode
  references: train_pool     # off | train_pool | catalog
  reference_pool: config/judge/reference-pool-runbook-v2.jsonl   # required for train_pool
```

Preflight refuses `mode: correct` when:

- `model` has no price in `config/api_prices.yaml`, or no provider pin with a non-empty `order` and
  `allow_fallbacks: false` in `config/provider_pins.yaml`;
- `references: train_pool` names no pool file, or the pool's sha256 differs from its manifest;
- the run's drawn ids intersect the pool, or share a leak component with it (see section 4);
- `references: catalog` is set on a run whose `job.mock` is false and whose draw is not marked as
  production (`catalog` is for production only).

The judge's model is also set as `agent_routes.judge` (or checked against it) so the provider pin,
served-model ledger, call guard and API budget all see the same id. The lock records the block, the
pool sha256 and the labeling-guide sha256.

### 2. HF-018: the correcting judge node

A new hotfix in `vendor_hotfixes.py`, always installed (as every hotfix is) and inert unless the
locked `judge.mode` is `correct`.

- **Target:** a wrapper on `graph.build_graph.judge_verify_node`, with `also` fingerprints on
  `graph.build_graph:arbiter_node`, `graph.routing:after_judge` and `graph.attempts` helpers it
  reads. The compiled graph is a process singleton that captures node functions at build time
  (`build_graph.py:110-126, :3748`), so the hotfix must be installed before the first compile, and
  a test must prove the compiled graph calls the wrapper.
- **One call per ruling.** The correct-mode prompt asks for completeness and correctness together,
  replacing today's two calls. HF-002's one re-ask on a parse failure still applies and is counted
  (`call_guard.note_judge_reask`).
- **Input:**
  - the source text, read whole as today (context fit);
  - the class and the cleaned extracted fields (`_clean_fields_for_judge`);
  - the field definitions for the class from `subclass_schemas.parse_guide()` (the guide has no
    insurance or merger sections, so those classes get the extraction schema's descriptions);
  - the earlier attempts from `extraction_attempt_history`: fields and verdicts, bounded in size;
  - the previous ruling and findings on a second ruling;
  - up to two reference examples (section 4), as field values and short quotes, never whole
    documents.
- **Output schema:**

  ```json
  {"ruling": "accept | retry_fields | human_review",
   "fixes": [{"field": "...", "value": "...", "quote": "..."}],
   "retry_fields": ["..."],
   "findings": ["..."],
   "reason": "..."}
  ```

  On a second ruling the schema drops `retry_fields` from the enum (the HF-015 pattern), so the model
  cannot ask for another round.
- **Fix verification (deterministic, no LLM):**
  - the field is in the class's extraction schema;
  - the quote is located in the source with `gold_labels.locate` (whitespace-insensitive, at most
    `MAX_QUOTE_CHARS` = 400);
  - the value passes `gold_labels.evidence_support` for that field's type.

  A passing fix overwrites `extracted_data[field]` and is recorded as
  `{field, before, after, quote, start, end}` in `judge_fixes`. A failing fix is recorded in
  `judge_fixes_rejected` with the check that failed, and is not applied. If every proposed fix fails
  on an `accept` ruling whose findings say a field is wrong, the ruling becomes `human_review`.
- **Ruling → existing routes** (no new graph edges; `judge_verify` can only reach `compile_report`,
  `arbiter` and `human_review`, `route_spec.py:189-196`):
  - `accept`: sets `judge_verdict: complete` and `judge_corrected` (true when fixes were applied), so
    the existing `after_judge` goes to `compile_report`.
  - `human_review`: the existing `human_review` route, with `escalation_reason` naming the ruling.
  - `retry_fields`: goes to `arbiter`. HF-018 also wraps `arbiter_node`: in correct mode it makes
    **no LLM call** and returns `arbiter_decision: retry_extraction` with the judge's fields and
    findings, so the existing `arbiter → retry_extract` edge runs the retry.
- **Targeted retry by merge.** The vendored retry re-extracts the whole document. In correct mode the
  hotfix keeps every field from the pre-retry extraction (with fixes applied) and takes only the
  `retry_fields` values from the new attempt. The judge then gives its second, final ruling.
- **Lane bound.** The hotfix counts rulings in state. A third entry into the node, or a second retry
  request, goes to `human_review` with `escalation_reason: judge_lane_exhausted`. HF-011's
  judge-exhausted rules and HF-014/HF-015's arbiter behaviour have no effect in correct mode, because
  the arbiter never runs its LLM there; tests cover that interplay.
- **Confidence.** Fixes do not change `extraction_confidence` (row 12); the ruling is recorded
  beside it.

### 3. What the item records

`eval/runners.py` copies into `pred` (bounded):

- `judge_mode`, `judge_ruling` (per ruling), `judge_rulings` (count), `judge_corrected`;
- `judge_fixes`, `judge_fixes_rejected`;
- `judge_lane_exhausted`;
- `extraction_pre_judge`: the fields of the first extraction attempt (`extraction_attempt_history[0]`),
  so a pre-judge score can be computed.

These fields are written in both modes where they apply, so the verify arm of an A/B also gets a
pre-judge score.

### 4. Reference labels without leakage

- **`train_pool` (experiments).** A pool file built by a new script from
  `data/labels/gold/*.jsonl` (`near_gold` records only), restricted to the documents of one split set,
  by default runbook-v2 `pool` (402 documents, `config/splits/runbook-v2/pool.ids`). The pool file has
  its own manifest with the source sha256s. Preflight refuses a run whose prepared ids intersect the
  pool or share any leak component the split uses (matter, group, email subject, identical text,
  content hash; row 3), reusing the split assignments' `component` field. The judged document itself
  can never be in the pool, by construction.
- **Selection (my call).** Same class and subclass, deterministic order (seeded by the run), at most
  two examples, each reduced to the fields under review with short evidence quotes. Embedding
  similarity (the vendored MiniLM in `pipeline/relations.py`) is a later option, not part of this
  design.
- **`catalog` (production).** The full near-gold catalog, always excluding the judged document by
  `doc_id` and `content_sha256`, and its leak components. Production slices are also gate-scored
  against labels, so a catalog-assisted run's gate report says "reference-assisted" beside every
  score.
- **Classes without labels.** There are no insurance-claim or merger labels, so those classes get no
  references; the judge uses the guide or schema and the earlier passes.

### 5. The judge model (my call)

`qwen/qwen3.7-plus`: listed in `config/api_prices.yaml` as supervisor tier 1 for judge, arbiter and
boss, with a 1M-token context, so it reads whole documents as the current judge does. It costs
$0.32/$1.28 per 1M tokens below 256k prompt tokens and $0.96/$3.84 above; a whole merger read (about
570k tokens) is about $0.55 per ruling. Before any paid arm it needs a provider pin
(`scripts/refresh_provider_pins.py`, owner choice of endpoint) and a verified R01 smoke row. The A/B
may add one frontier arm (for example `anthropic/claude-sonnet-5.5` at $2/$10) on a small slice to
show what more capability buys; that arm is optional.

### 6. KPIs and reports

Per run, per class, and for the A/B side by side:

| KPI | Source |
|---|---|
| Final extraction score and scored n | existing headline (unchanged) |
| Pre-judge score on judged documents | `extraction_pre_judge`, same scorer |
| Judge lift | final minus pre-judge, judged documents only |
| Fixes proposed / verified / applied; applied fixes right / wrong against truth | `judge_fixes`, `judge_fixes_rejected`, field scores |
| Rulings and retries per judged document | `judge_rulings`, `judge_ruling` |
| LLM calls and cost per document; calls in the judge lane | item `llm_calls`, tokens, priced at the lock's prices |
| Review rate, wrong-archive rate | gate `_class_rates` (unchanged) |
| Lane-exhausted count; call-guard trips | `judge_lane_exhausted`; gate `crashed` |

The gate gains a `judge_corrected` count (like `arbiter_caveats`), and `routing_audit` reports
rulings, retries and calls per judged document. Every score that includes judge fixes is labelled
post-correction (row 15).

### 7. The A/B and what counts as success

Two arms on the same draw, seed and prompts: `judge.mode: verify` (today) and `judge.mode: correct`.
They run on runbook-v2 `dev-look1`, mock first, then paid only with a human's initials at the spend
gate.

Success (my proposal, for the owner to confirm):

- LLM calls in the judge lane per judged document down by at least 50%;
- final extraction score on judged documents not lower than the verify arm, within the repo's
  existing non-inferiority margin convention;
- wrong-archive rate not higher;
- zero leakage refusals bypassed.

### 8. Production adoption

After a winning A/B, one reviewed change adds the `judge:` block to the production slice configs and
to `pipeline-qwen-flash-25-fit-r3.yaml`, and adds `judge` to the blocks
`tests/test_production_slices.py` asserts equal to r3 (`:93-96`). The Modal-host twins need the job
worker redeployed with the hotfix bundled, and both twins' locks must share `dependency_sources`
(`docs/runbooks/production-slices.md:178-191`).

### 9. Upstream issues (drafted with the change, opened later)

For `llm-mailroom`:

1. A judge ruling schema with cited field fixes, replacing diagnose-then-arbitrate.
2. A `judge_verify → retry_extract` edge with field-targeted retries.
3. Export `extraction_attempt_history` (or the first attempt) on the result.
4. A per-document call budget that ends in review, not an aborted document.
5. Boss escalation loops: investigation and a bound.

Each issue carries the A/B evidence. The sandbox hotfix is retired by a vendor refresh once
upstream ships.

## Constraints

- Never edit `vendor/`; the change lives in `vendor_hotfixes.py` with source fingerprints.
- Adding a hotfix changes `vendor_hotfixes.module_sha256`, so existing locks refuse resume until
  `--force` (`docs/vendor-hotfixes.md:99-150`); finished runs are unaffected.
- No paid or live runs by an agent; every paid arm needs a human's initials, `api_cost_cap_usd`
  priced with the judge model, and `max_wall_seconds`.
- Critical-regression rows to fill in the PR: 1, 3, 5, 6, 9, 12, 14, 15, 17, 22.
- Coverage floor 84; focused `-n 0 --no-cov` tests locally, the full suite in CircleCI.
- New work on a new branch.

## Verification (what "done" means)

- Spec: an absent block keeps every existing spec hash; invalid combinations are refused at preflight
  with the reasons above.
- HF-018: applied, stale and unavailable states; the compiled graph calls the wrapper; correct mode
  makes one judge call per ruling and no arbiter LLM call; verify mode is byte-for-byte today's
  behaviour (the existing judge and arbiter tests pass unchanged).
- Fix verification: a fabricated quote, a quote that does not support the value, and a field outside
  the schema are each rejected and recorded.
- Bounds: the offline compiled-graph harness (`tests/_arbiter_harness.py`) proves every correct-mode
  path ends within two rulings and one retry, and counts the calls.
- Leakage: preflight refuses a draw that intersects the pool or shares a component; the judged
  document never appears in its own references, in both modes.
- KPIs: item fields, gate `judge_corrected` and routing-audit counts are covered by tests; the
  pre-judge score is computed on a fixture.
- Gates: ruff, `check_hotfixes.py`, `build_hub.py --check`, the CLI-surface and runbook checks, and
  CircleCI green.

## Left to the builder

- Prompt wording for the correct-mode judge, within the output schema above.
- Exact size bounds for earlier passes and reference examples.
- The pool builder script's name and CLI, and the pool file format beyond "near-gold records of one
  split set with a manifest".
- Test file layout.
