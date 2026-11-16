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

All configs copy r2 exactly (dataset pin, seed 42, models, reviewer, caps) and differ only
in the lines marked `# E…`. Offline preflight passes except the API-key check, which needs
the OpenRouter key loaded into the shell.

| Step | Config | Change | Success bar |
|---|---|---|---|
| E1 | `config/runs/pipeline-qwen-flash-25-e1-contract-chunk.yaml` | `contracts_specialist.max_input_chars: 18000` → 15,750-char windows, ≤3 chunks; judge/arbiter keep full coverage (plan: `judge_coverage_min 1.0`) | contract ≥ 0.83 with prompt tokens < 774k |
| E2 | `config/runs/pipeline-qwen-flash-25-e2-corporate-judge.yaml` | `corporate_record.judge_band_high: 1.01` (judge every corporate extraction) | corporate > 0.44; judge verdicts separate the low scorers |
| E3 | `config/runs/pipeline-qwen-flash-25-e3-chunk-judge-all.yaml` | E1 + E2 + `contract.judge_band_high: 1.01` (retries get re-judged) | no class below r2; contract ≥ E1 |

Run order: E1 and E2 are independent (they touch different classes) and can run in
either order; E3 only after both. Launch (human-only, paid):

```bash
sandbox run preflight --config config/runs/<step>.yaml
sandbox run start --config config/runs/<step>.yaml --initials <XX>
```

Evaluate each step with `sandbox run routing --run-id <run_id>` and the per-class summary
(quality, CUAD FN/FP for contracts, judge verdict counts, prompt tokens, p50 latency,
estimated cost). Record the result in `reports/experiment_log.jsonl` and in the table
below before starting the next step.

## Next candidates (after E1–E3)

- Chunk-size sweep for contracts (12k / 18k / 25k) once E1 shows the direction.
- Judge leniency: 0/4 contract, 0/4 correspondence and 0/3 merger judge calls passed in r2.
  The judge prompt is upstream (`llm-mailroom`); change it there, then refresh `vendor/`.
- Merger MAUD (0.13) needs its own investigation; chunking is not expected to fix it.
- Re-run r2 on the PR #299 vendor snapshot (llm-mailroom `5bcfe44`, Dojo v0.29.0) to
  isolate the upstream change before stacking ladder steps on it.

## Results

| Step | Run id | contract | corporate | merger MAUD | insurance | correspondence | prompt tokens | est. USD |
|---|---|---|---|---|---|---|---|---|
| r2 | pipeline-qwen-flash-25-fit-r2 | 0.76 | 0.44 | 0.13 | 0.77 | 0.24 | 2.72M | ≤0.49 |
| E1 | — | | | | | | | |
| E2 | — | | | | | | | |
| E3 | — | | | | | | | |
