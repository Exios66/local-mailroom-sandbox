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
| E3 | `-e3-mix-control` → `-e3-chunk-judge-all` | **45 held-out documents**: 10 each of contract, corporate, correspondence, insurance and 5 mergers (untouched by the changes; 5 limits cost); seed 2026. No overlap with E1/E2 and 1 shared with r2. | E1 + E2 + `contract.judge_band_high: 1.01` (retries re-judged) | no class more than 0.03 below control; contract and corporate improve |

Why these sizes: the r2 class samples (n = 5) cannot show a 0.05–0.07 change. A paired
n of 18–20 over distinct subtypes can, at a few cents per arm. E1 and E2 tune on seed
1115. E3 confirms on seed 2026, which the tuning never saw, so a change that only fits
the tuning draw is caught there.

Estimated API spend, from r2 per-document costs: E1 about $0.15 control + $0.30 treatment;
E2 about $0.05 + $0.10; E3 about $0.70 per arm. Each config's `api_cost_cap_usd` is about 2× its
estimate (E1 0.60, E2 0.40, E3 1.75).

Run order: E1 and E2 are independent (different classes) and can run in either order.
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

## Results

| Step | Run id | contract | corporate | merger MAUD | insurance | correspondence | prompt tokens | est. USD |
|---|---|---|---|---|---|---|---|---|
| r2 | pipeline-qwen-flash-25-fit-r2 | 0.76 | 0.44 | 0.13 | 0.77 | 0.24 | 2.72M | ≤0.49 |
| E1 control / treatment | — | | n/a | n/a | n/a | n/a | | |
| E2 control / treatment | — | n/a | | n/a | n/a | n/a | | |
| E3 control / treatment | — | | | | | | | |
