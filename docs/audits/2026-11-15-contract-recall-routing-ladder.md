# Contract recall and judge routing: incremental experiment ladder (2026-11-15)

Follow-up to `pipeline-qwen-flash-25-fit-r2` (clean repeat of the 25-document Qwen 3.7
Flash OpenRouter run after context fit and run-scoped matter ids). Each step changes
**one** variable against r2, so a change in quality can be attributed to that change.

## Starting point (r2 vs the chunked baseline `pipeline-qwen-flash-25`)

| Class | Quality baseline → r2 | Note |
|---|---|---|
| contract | 0.83 → **0.76** | CUAD missed clauses 18 → 28; false positives 6 → 3 |
| corporate_record | 0.39 → 0.44 | never judged (self-reported 0.95–1.0 vs band 0.94); one 0.16 at conf 1.0 |
| merger_agreement | 0.09 → 0.13 MAUD | judge passed 0/3 |
| insurance_claim | 0.77 → 0.77 | the only class the judge passed |
| correspondence | 0.24 → 0.24 | 2 parked (one sub-200-char document) |

Observed mechanisms (from `items.jsonl` / `nodes.jsonl` of both runs):

1. **Contract recall.** The baseline extracted each contract in about 3 chunks per pass
   and unioned the clause lists across passes. With context fit, a contract is one
   whole-document call; output tokens per contract fell from 11–22k to 2–5k.
2. **Unjudged retry.** The retry extraction self-reports 1.0, which is at or above
   `judge_band_high`, so `after_retry_extraction_gated` archives without a re-judge.
3. **Corporate records skip the judge.** `judge_gate` fires only for
   `low <= conf < judge_band_high`; every corporate confidence was ≥ 0.95 with a
   band of 0.94. Self-reported confidence does not predict score here.

## Ladder

Each step is a **paired** control/treatment pair: both arms draw the same documents (same
strata and seed, verified identical ids at preflight) and differ only in the line marked
`TREATMENT`. Everything else copies r2: dataset pin `bc9eab28`, `require_task_gt`, caps,
reviewer. Offline preflight passes for all six configs except the API-key check, which
clears once the OpenRouter key is loaded in the shell.

**Model (fixed for the whole ladder):** `qwen/qwen3.7-flash` on OpenRouter for every agent
node (sorter, intake, specialists, judge, boss, arbiter). The decision reviewer is
`openai/gpt-6-luna-decisions` with the v2 cutoffs. Changing the model is a separate
experiment run after the ladder (for example, a transfer check on the Modal-served 9B), never a
ladder variable.

| Step | Configs (control → treatment) | Documents and mix | Change | Success bar |
|---|---|---|---|---|
| E1 | `pipeline-qwen-flash-25-e1-contract-control` → `-e1-contract-chunk` | **20 contracts**, 2 from each of the 10 largest CUAD subtypes (Supply, License, Consulting, IP, Service, Maintenance, Distributor, Strategic Alliance, Sponsorship, Development); seed 1115. At 15,750 chars, 12/20 split into 2–13 chunks and 8 fit one window. | `contracts_specialist.max_input_chars: 18000`; judge/arbiter keep full coverage | paired contract quality ≥ control + 0.05; fewer missed clauses; false positives no more than +2 |
| E2 | `-e2-corporate-control` → `-e2-corporate-judge` | **18 corporate records**, 2 from each of the 9 labelled subtypes (charter amendment, articles, officer certificate, indenture, subsidiary list, rights instrument, board resolution, bylaws, powers of attorney); seed 1115 | `corporate_record.judge_band_high: 1.01` (judge every extraction) | paired quality > control; judge rejects most extractions scoring < 0.5 |
| E2r | `-e2-corporate-control` → `-e2-corporate-rejudge` | the E2 draw (same 18 ids; the control arm is shared with E2) | `corporate_record.judge_rejudge_retry: true` (llm-mailroom #241, opt-in; control states `false`) | fires on at least one retry; paired quality no worse than control; added judge calls counted |
| E3 | `-e3-mix-control` → `-e3-chunk-judge-all` | **45 held-out documents**: 10 each of contract, corporate, correspondence, insurance and 5 mergers (untouched by the changes; 5 limits cost); seed 2026. No overlap with E1/E2 and 1 shared with r2. | E1 + E2 + `contract.judge_band_high: 1.01` (retries re-judged) | no class more than 0.03 below control; contract and corporate improve |

Why these sizes: the r2 class samples (n = 5) cannot show a 0.05–0.07 change. A paired
n of 18–20 over distinct subtypes can, at a few cents per arm. E1 and E2 tune on seed
1115. E3 confirms on seed 2026, which the tuning never saw, so a change that only fits
the tuning draw is caught there.

Estimated API spend, from r2 per-document costs: E1 about $0.15 control + $0.30 treatment;
E2 about $0.05 + $0.10; E3 about $0.70 per arm. Each config's `api_cost_cap_usd` is about 2× its
estimate (E1 0.60, E2 0.40, E3 1.75).

**Settings common to every E2/E3 arm (not treatments).** These follow the pre-E2 review
(`docs/audits/2026-11-16-pre-e2-architecture-review.md`):
- `job.blind_routing: true`: no labels in the graph's state;
- `dataset.interim_labels: true`: gap-fill labels, with corporate `record_type` re-derived to the
  enum;
- the adopted condensed prompts for the corporate, correspondence and insurance specialists.

Evaluate each pair with `python scripts/ladder_pair_report.py <control> <treatment>`. For corporate
records and correspondence it prints quality on all fields and without the templated
`keywords` / `subject_matter`. Read the second lane for corporate records.

**E2r, the `judge_rejudge_retry` on/off pair.** The switch re-judges a retry whose earlier
attempt was judged, whatever confidence the retry reports. It is paired with the control and
not with `-e2-corporate-judge`, because there it cannot change routing: an extraction reaches
the report only at confidence ≥ `low`, and with `judge_band_high: 1.01` every such extraction
is already judged. On the control band (corporate `judge_band_high` 0.94), only a first pass
between `low` (0.86) and 0.94 is judged, and r2's corporate first passes all reported ≥ 0.95,
so the switch may fire rarely or never. A zero-fire result is itself the answer for this
class; contracts, where #241 was observed, are the next place to test it. The run setting
accepts only an unquoted `true`/`false`, because the vendored router reads it by truthiness.

Run order: E1 and E2 are independent (different classes) and can run in either order. E2r
reuses E2's control arm, so it costs one more arm (about $0.05).
Run E3 only after both, and drop from it any treatment that lost its own step. Launch
(human-only, paid), control first:

```bash
sandbox run preflight --config config/runs/<config>.yaml
sandbox run start --config config/runs/<config>.yaml --initials <XX>
```

Evaluate each pair with `sandbox run routing --run-id <run_id>` and a per-class paired
summary: quality, CUAD missed/false clauses for contracts, judge verdicts against score,
prompt tokens, p50 latency, estimated cost. Record the result in
`reports/experiment_log.jsonl` and in the table below before starting the next step.

## Upstream fixes (llm-mailroom)

These need changing in `llm-mailroom` and then a vendor refresh. The ladder works around
the first two with run-scoped thresholds.

- Exios66/llm-mailroom#241: a confident retry extraction archives without a re-judge
  (E3's `contract.judge_band_high: 1.01` is the sandbox workaround).
- Exios66/llm-mailroom#242: completeness judge verdicts rarely pass and don't track score.
- Exios66/llm-mailroom#243: `sliding_windows` can exceed the budget by the overlap.
- Exios66/llm-mailroom#244: policy-replay cutoff evidence includes chunk-loss attempts.
- Exios66/llm-mailroom#245: synthetic records allow an unbounded `test_fraction` and leave
  observations untyped.
- Exios66/llm-mailroom#246: a blank `content_sha256` passes manifest validation, then aborts the fetch.

## Next candidates (after E1–E3)

- Chunk-size sweep for contracts (12k / 18k / 25k), on the E1 documents, once E1 shows the direction.
- Judge calibration (#242), then re-run E2 to see whether the judge separates scores.
- Merger MAUD (0.13) needs its own investigation; chunking is not expected to fix it.
- Re-run r2 on the PR #299 vendor snapshot (llm-mailroom `5bcfe44`, Dojo v0.29.0) to
  isolate the upstream change before stacking ladder steps on it.

## Rebaseline on the 2026-11-16 pins (r3) and E2r

The vendor refresh to llm-mailroom `abb1ccf` and Dojo `13adc8e` changes date, MAUD,
decision-lane and Wilson-bound scores. r2 and E1 were scored on the old pins, so they no
longer compare like-for-like with new runs.

- `pipeline-qwen-flash-25-fit-r3`: r2's exact document draw, caps and model on the new
  pins, plus the settings every E2/E3 arm shares: blind routing, interim labels and the adopted
  condensed specialist prompts. It is the new baseline for every later step; compare new runs
  with r3, not r2. Run it before any further ladder step.
- `pipeline-qwen-flash-25-e2-corporate-rejudge` (E2r): the E2 control plus
  `corporate_record.judge_rejudge_retry: true`, paired with the control (see E2r above). On the
  judge arm the switch cannot change routing, so a judge-plus-rejudge arm would repeat the
  judge arm.

Human launch (paid), r3 first:

```bash
sandbox run preflight --config config/runs/pipeline-qwen-flash-25-fit-r3.yaml
sandbox run start --config config/runs/pipeline-qwen-flash-25-fit-r3.yaml --initials <XX>
```

## Results

| Step | Run id | contract | corporate | merger MAUD | insurance | correspondence | prompt tokens | est. USD |
|---|---|---|---|---|---|---|---|---|
| r2 | pipeline-qwen-flash-25-fit-r2 | 0.76 | 0.44 | 0.13 | 0.77 | 0.24 | 2.72M | ≤0.49 |
| E1 control / treatment | pipeline-qwen-flash-25-e1-contract-control / -chunk | 0.774 / 0.803 | n/a | n/a | n/a | n/a | 2.16M / 3.84M | ≈0.10 / ≈0.19 |
| r3 (blind routing, interim labels, condensed prompts) | pipeline-qwen-flash-25-fit-r3 | 0.771 | 0.654 (0.939 without templated) | 0.101 | 0.857 | 0.132 | 3.14M | — |
| E2 control / treatment | pipeline-qwen-flash-25-e2-corporate-control / -judge | n/a | 0.593 / 0.579 (0.862 / 0.807 without templated) | n/a | n/a | n/a | 0.70M / 1.38M | — |
| E2r rejudge | pipeline-qwen-flash-25-e2-corporate-rejudge | n/a | 0.584 (0.807 without templated) | n/a | n/a | n/a | 0.70M | — |
| E3 control / treatment | — | | | | | | | |

### E1 result (2026-11-16): recall up, precision down; not adopted as is

Both arms ran on the v0.30.0 snapshot (llm-mailroom `98c89b8`, Dojo `542a1c3`), so neither
is comparable to r2 (Dojo 0.30.0 changes scores). The 20 document ids were identical in both
arms. Cost is the key's billed total ($0.290 for both arms), split by token share.

| Measure | Control | Chunk (18k) | Bar | Met |
|---|---|---|---|---|
| Mean contract quality | 0.774 | 0.803 | ≥ control + 0.05 | **no** (+0.029; 95% CI −0.009 to +0.065) |
| CUAD missed clauses | 75 | 47 | fewer | **yes** (−28) |
| CUAD false clauses | 27 | 47 | ≤ +2 | **no** (+20) |
| Routed to review | 5 | 12 | — | — |
| Judge verdicts complete / partial / incomplete | 1 / 27 / 4 | 3 / 40 / 3 | — | — |
| Tokens (prompt + completion) | 2.27M | 4.14M | — | 1.82× |
| p50 latency per document | 63 s | 85 s | — | — |
| Parse errors / documents that lost every window | 0 / 0 | 0 / 0 | — | partial loss only: one document lost 1 of its 13 windows |

Split by whether chunking actually applied:

| Subset | n | Paired quality diff (95% CI) | Missed | False | Review |
|---|---|---|---|---|---|
| Chunked (2–13 windows) | 12 | **+0.048** (+0.007 to +0.091) | 58 → 34 | 15 → 32 | 2 → 8 |
| Single window (identical input in both arms) | 8 | +0.001 (−0.064 to +0.052), sd 0.092 | 17 → 13 | 12 → 15 | 3 → 4 |

Findings:

1. **Chunking restores recall.** On the chunked contracts, missed clauses fall from 58 to 34
   and quality rises by about 0.05. This confirms root cause 1: one whole-document call
   misses clauses that per-window reads find.
2. **The merge adds false clauses.** False clauses double on chunked contracts (15 → 32). The
   cross-window merge keeps clause claims from every window without a precision filter. That
   cost, plus 1.8× tokens and 2.4× review routing, keeps the treatment from passing.
3. **Noise floor.** The 8 single-window contracts received the same input in both arms, yet
   their per-document quality moved by a standard deviation of 0.09 (−0.19 to +0.07). At
   temperature 0.1, run-to-run variance is about the size of the effects this ladder looks
   for. If the treatment's paired differences have about the same per-document sd (0.09),
   a 20-document paired mean has a standard error near 0.09/√20 ≈ 0.02, so a mean within
   about ±0.04 (two standard errors) cannot be told from noise. Eight pairs give only a rough
   sd, so treat this as an order-of-magnitude bound, not a fixed threshold. Before
   scaling up: fix sampling (temperature 0 and a provider seed where supported), or repeat
   each arm and pool, and size samples against this variance.
4. **Judge.** It passed 3 of 46 calls (control 1 of 32). The arbiter loop then fires almost
   unconditionally (Exios66/llm-mailroom#242); it is the main token sink in both arms.

Next steps: the chunk-size sweep (25k, 32k) with a clause-precision check on the merge,
run as repeated arms or at temperature 0 so that it measures more than noise. Keep the
whole-document read until a size beats control on both the missed and the false bar.

### r3 result (2026-11-16): the new baseline

r3 is r2's draw on the #302 pins with blind routing, interim labels and the adopted condensed
specialist prompts. Its differences from r2 mix all three changes, and each run is scored against
its own labels, so they are not effect sizes. Most of the corporate rise (0.44 → 0.65) comes from
the interim labels. With n = 5 per class, only insurance (+0.10, CI +0.02 to +0.19) excludes zero.
Watch two things in E3, which has 10 correspondence documents:
- correspondence fell (0.24 → 0.13);
- contracts escalated more under blind routing: 0 → 2 sent to review, 4 → 9 judge calls, and one
  `judge_error`.

### E2 result (2026-11-16): judging every corporate extraction adds cost, not quality; not adopted

`python scripts/ladder_pair_report.py <control> <treatment>` on the shared 18 records. Quality is
on the lane without the templated `keywords` / `subject_matter`:

| Pair | Quality (control → treatment) | Diff (95% CI) | Review | Judge calls | Retries | Prompt tokens |
|---|---|---|---|---|---|---|
| E2: control → judge (`judge_band_high: 1.01`) | 0.862 → 0.807 | −0.056 (−0.17 to +0.06) | 0 → 6 | 0 → 32 | 1 → 16 | 0.71M → 1.39M |
| E2r: control → rejudge (`judge_rejudge_retry: true`) | 0.862 → 0.807 | −0.056 (−0.17 to +0.06) | 0 → 0 | 0 → 0 | 1 → 2 | 0.71M → 0.71M |

- **The rejudge arm is a noise control.** The switch never fired: every control-band extraction
  reported confidence ≥ 0.95, so no attempt was judged before a retry. Routing therefore matched
  the control. Its −0.056 comes from a single record whose first-pass `intent` flipped
  `investor_rights` → `other`, the same record and the same flip as in the judge arm.
- **So the judge arm's −0.056 is sampling noise.** The judge changed no document's score.
- **The judge does not catch bad extractions.** It marked both records scoring below 0.5
  `complete`. Its 20 `partial` verdicts sent 6 records to review; on the labelled fields, 5 of them
  score 1.00 and one 0.55. Some of its fix requests are wrong, for example moving an indenture's
  jurisdiction from the issuer's state of formation (Delaware) to its governing law (New York).
- **Caveat:** labels cover `intent` (heuristic) and up to six interim fields, so complaints about
  unlabelled fields are not scored.
- **Bar:** E2 needed paired quality above control and a judge that rejects most extractions
  scoring below 0.5. It met neither, at about 2× the tokens and with 6 records sent to review.
- **E2r:** the #241 switch cannot be tested on corporate records at the default band. Contracts
  are the next place to test it.
- **E3:** under the ladder rule, both the E1 treatment (contract chunking) and the E2 treatment
  (judge every corporate extraction) drop out of E3.

