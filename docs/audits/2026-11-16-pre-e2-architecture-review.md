# Pre-E2 architecture review: routing, escalation and scoring (2026-11-16)

Review of the vendored pipeline (llm-mailroom `abb1ccf`, Dojo `13adc8e`, the #302 pins) and the
sandbox harness before E2 and E3 run. It looks for flaws that are **not** already fixed, filed or
prepared. Evidence comes from the code and from the r2 and E1 artifacts in `data/runtime/runs/`.

**Vendor state:** both upstream `v0.30.0` branches are still at the #302 pins, and all 369
vendored files are byte-identical to them. No `fetch-deps` refresh is needed.

## Summary

| # | Area | Finding | Already covered? | Effect on E2/E3 | Fix before E2/E3 |
|---|---|---|---|---|---|
| 1 | Scoring | Corporate-record ground truth labels only 3 of 9 scored fields, and those 3 are heuristic or templated | Partly: Dojo #52 (entity fields); the sandbox interim overlay exists, but no ladder config enables it | **E2 cannot measure the judge as designed** | Yes, in config: `dataset.interim_labels: true` and a field-level report |
| 2 | Routing | Routing reads ground truth when it is in state (class-miss gate, coverage-floor retry) | Yes: llm-mailroom #207 (open, not fixed); no sandbox switch | Every arm is oracle-assisted; thresholds may not transfer | Decide: run blind, or report it as oracle-assisted |
| 3 | Escalation | A retry primes every chunk window with the whole previous extraction | No | Plausible source of E1's extra false clauses; token cost grows with windows | Upstream issue; E3's chunked arm inherits it |
| 4 | Escalation | The last attempt always wins: a retry replaces the extraction even when it is judged worse | No | The archived extraction may be worse than an earlier attempt | Upstream issue; measure per attempt in E2/E3 |
| 5 | Extraction | Chunk merge: lists are unioned with no precision filter, and scalars take the first non-null window | Noted in the E1 write-up; not filed upstream | E1's +20 false clauses; E3 inherits it | Upstream issue |
| 6 | Routing | The coverage floor uses the global `low` (0.70), not the class or run threshold | No | Small: the floor ignores the run's `confidence` block | Fold into #207 |

Checked and not a sandbox problem: llm-mailroom #191 (grounded scoring gets empty `doc_text`) and
#192 (Dojo wiring) affect only the in-graph trace scorer. The sandbox scores outside the graph,
passes `doc_text` and uses the Dojo suite's `field_types` directly. The Boss path was not
exercised (0 escalations in r2 and E1), so it is not reviewed in depth here.

## 1. Corporate-record ground truth cannot score most of the extraction

Dojo scores nine corporate fields (`doc_classes.py`). In the 450 corporate rows at dataset pin
`bc9eab28`:

| Field | Rows with a label | What the label is |
|---|---|---|
| entity_name, record_type, effective_date, signatories, jurisdiction, filing_number | **0** | — |
| intent | 450 | `intent_source: heuristic`, `intent_status: auto_labeled` on every row |
| subject_matter | 450 | 412 are the template `"<subclass> of <Company>"` |
| keywords | 450 | 412 are filing metadata: `["charter_amendment", "EX-3.1", "S-1/A", "<accession>"]` |

A correct extraction therefore scores low. In r2, a certificate of amendment scored 0.16 at
confidence 1.0: the model's real keywords ("Certificate of Amendment", "Reverse Stock Split") do
not match the metadata tokens, and its intent disagrees with a heuristic label. The corporate
mean of 0.44 is mostly a label ceiling, so E2's bar ("the judge rejects most extractions
scoring < 0.5") would reward a judge that agrees with the templates.

**Prepared but unused:** `dataset.interim_labels: true` (the sandbox interim overlay,
`data/labels/interim/`) adds gate-accepted, grounded labels. For the E2 draw it covers 13 of 18
documents: record_type 13, filing_number 13, jurisdiction 11, entity_name 10, signatories 10,
effective_date 8. None of the six ladder configs set it.

**Recommendation for E2:**
- Enable `interim_labels` in every arm. It is recorded in the lock, so all arms stay paired.
- Report quality twice: on all fields, and without `keywords` / `subject_matter`.
- Judge the judge only on the documents and fields with real labels.
- Upstream: extend Dojo #94 (templated correspondence GT) or #52 to cover corporate `keywords` /
  `subject_matter` / heuristic `intent`.

## 2. Ground-truth-assisted routing (llm-mailroom #207)

`eval/runners.py` passes `expected_doc_class` and `expected_fields` into the graph's
`ground_truth`. The router then reads them:

- `class_misses_ground_truth` sends a wrong class to review in `after_classify`,
  `after_retry_classify`, `after_review_classify` (two arms) and `after_classification_arbiter`.
  In experiments a misclassification can never archive. In production it can.
- `coverage_below_floor` (`after_extraction`) retries, then parks, an extraction whose coverage of
  the **labelled** fields is below `low`. In production there are no labels, so this retry never
  happens.

In E1 the extraction gates (schema, hollow, lost chunk, coverage, low confidence) caused 3 retries
in the control arm and 10 in the chunk arm, against 24 and 28 arbiter retries. The node log does
not record which gate fired, so the coverage oracle's share is unknown.

Both arms of a pair get the oracle, so paired differences are still valid comparisons. However:
- The oracle already retries incomplete extractions, which hides part of the judge's value.
- Absolute quality, review rates and any calibrated threshold describe an oracle-assisted
  pipeline.

**Sandbox-side fix (no vendor edit):** a run switch that passes only the public ground truth
(no `expected_doc_class` / `expected_fields`) into the graph, while the sandbox keeps scoring
against the full row. This is a decision for the ladder owner. A blind E2/E3 matches production
but breaks comparison with E1/r2, which are being re-baselined on the #302 pins anyway.

## 3. Retry priming in chunked extraction

`retry_extract_node` builds its handoff as
`"RE-EXTRACTION REQUESTED ... Previous attempt found: {prev_extracted}"`. This is the raw dict,
including `_`-prefixed metadata, with no size bound. `extract_chunked` prefixes the handoff onto
**every** window (`agents/base.py`, "handoff_context is prefixed onto every window"), and the
merge is a list union. Each window is therefore shown clause claims from every other window, and
any claim it repeats survives the union.

- **Size:** E1 chunk-arm extractions are about 10k characters at p50 and 27k at most. For a
  13-window contract, one retry re-sends up to about 350k characters. This is an upper bound,
  because the final payload also includes the report.
- **Attribution:** in E1, 18 of 20 chunk-arm documents retried. Chunked documents averaged 2.8
  false clauses after a retry against 2.0 without, but the no-retry group has only n = 2, so
  E1 cannot separate the effect.
- **To test:** an E1-chunk arm with `arbiter_retry_max: 0`, or scoring each attempt.

**Upstream fix:** give the retry a bounded summary (the judge's findings or fix list), not the
full previous payload. Never send it to every window.

## 4. The last attempt always wins

`retry_extract_node` overwrites `extracted_data` with the new result. No verdict comparison picks
the best attempt, so the archived extraction is always the last one. In the E1 control, the
judge passed 1 of 32 calls and 15 re-judged retries improved a verdict once. The arbiter retries
almost every time, so a document can end on an attempt that is worse than its first.
`judge_rejudge_retry` raises the number of judged retries, but it still archives the last
attempt.

**Upstream fix:** keep the best-judged attempt (verdict rank, then confidence) and archive that
attempt. **Measure in E2/E3:** record each attempt's payload so it can be scored offline.

## 5. Chunk merge without a precision filter

`_merge_extractions` takes the union of list fields and the first non-null scalar across windows.
E1 showed the cost: false clauses on chunked contracts rose from 15 to 32. Taking the first
non-null scalar also lets an early window's guess (for example an effective date in a recital)
beat the window that actually states the value. Held llm-mailroom #204 (CR6) changes only how
window confidence is merged, not the field merge.

**Upstream fix:** keep a clause only when at least k windows assert it with an evidence span, or
let the judge check the union. Choose scalars by the window's evidence or confidence, not by
order.

## Proposed order before E2/E3

1. Decide blind versus oracle routing (finding 2), and add the run switch if blind.
2. Add `dataset.interim_labels: true` to the E2 and E3 arms, plus a field-level paired report
   (finding 1).
3. File upstream: retry priming (3), best attempt (4) and the merge precision filter (5). Fold the
   class-agnostic coverage floor (6) into #207. Extend Dojo #94/#52 for corporate templated GT.
4. Rerun r2 on the #302 pins with the same switches, then E2 (control, judge, rejudge) and E3.
