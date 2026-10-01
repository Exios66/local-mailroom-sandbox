# SAND-37 — specialist grid score & cost cards

Every run of the aligned Qwen3-8B-AWQ specialist grid (`docs/SPECIALIST-GRID-PLAN.md`) writes its
score & cost card here, organized by fleet shape and then by specialist:

```
reports/SAND-37/
├── 1L4/                                   # 1× L4 · C8 — runbook grid-1l4
│   ├── L4x1-SCORE-COST-CARD.md            # finalized 1× L4 suite card (+ .json)
│   ├── correspondence/<run_id>.card.md    # one card per run (+ .card.json)
│   ├── insurance_claims/
│   ├── corporate_records/
│   ├── contracts/
│   └── merger_agreement/
└── 2L4/                                   # 2× L4 · C32 — runbook grid-2l4
    ├── L4x2-SCORE-COST-CARD.md
    └── <same five specialist folders>
```

## What writes them

| Artifact | Written by |
| --- | --- |
| `<specialist>/<run_id>.card.md` + `.card.json` | `sandbox run start` (runner hook, at the end of every grid run), then re-rendered by `sandbox run card --config <cfg>` once the after-run `/metrics` scrape exists |
| `L4x1-SCORE-COST-CARD.md` + `.json` | `sandbox run card --runbook grid-1l4` (the runbook's last step) |
| `L4x2-SCORE-COST-CARD.md` + `.json` | `sandbox run card --runbook grid-2l4` |

The runbooks bracket every `sandbox run start` with `sandbox run scrape-metrics --label before|after`,
so each card carries the run's own per-replica vLLM telemetry (requests, TTFT, prefix-cache hit,
preemptions, length-capped finishes).

## What a run card holds

- **Conditions:** task, prompt, temperature (and whether it came from the posture knob or the vendored
  call site), output and input caps, retries, dataset pin and draw fingerprint, engine and admission.
- **Score & cost card:** Run · Time (wall, GPU seconds, cold boot) · Cost (busy-window and billed GPU $,
  idle $, $ per document and per ok document, $ per 1M tokens) · Tokens (prompt, completion and share,
  per document, completion p95/max) · Throughput (tok/s, per L4, docs/min) · Latency (mean, p50, p95,
  max) · Engine (parallelism, slot occupancy, per-replica telemetry) · Quality (score mean/sd/min/max,
  scoring method, schema-valid rate, parse errors, errors) · CUAD or MAUD clause scoring for contracts
  and merger.
- **Errors** by kind, and **per-document results** (score, latency, tokens, error).

Values are measured from the run store; a field the run did not capture says "not captured". The
suite cards are rebuilt from the committed `*.card.json`, so commit this whole tree after each runbook.
