# SAND-042 master score & cost card — paired concurrency × fleet grid

**Conditions measured:** 1 of 4 · **Documents per condition:** 250 (5 specialists × n=50, one shared subclass-stratified draw) · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr · **Prompts:** v1 `*_simplified` only.

Four conditions — {1×L4, 2×L4} × {client concurrency 8, 16} — on the SAND-037 aligned spec. Every condition scores the **identical 250 documents**, so every delta is paired.
Design, metric contract and acceptance rules: [`docs/SAND42-EXPERIMENT-DESIGN.md`](../../docs/SAND42-EXPERIMENT-DESIGN.md).

## Conditions

| Condition | Runbook | GPUs | Client concurrency | Per replica | min=max |
| --- | --- | ---: | ---: | ---: | --- |
| `1l4-c8` | `sandbox runbook show sand42-1l4-c8` | 1 | 8 | 8 | 1 |
| `1l4-c16` | `sandbox runbook show sand42-1l4-c16` | 1 | 16 | 16 | 1 |
| `2l4-c8` | `sandbox runbook show sand42-2l4-c8` | 2 | 8 | 4 | 2 |
| `2l4-c16` | `sandbox runbook show sand42-2l4-c16` | 2 | 16 | 8 | 2 |

**Matched per-replica-load pair:** `1l4-c8` vs `2l4-c16` (8 per replica each) isolates replica count. `1l4-c8` vs `1l4-c16` isolates concurrency at fixed GPUs. The 2×L4 cells are *not* a load twin of the 1×L4 cells.

## Quality (mean field score; contracts CUAD presence F1, merger MAUD accuracy)

| Metric | 1×L4 C8 | 1×L4 C16 | 2×L4 C8 | 2×L4 C16 |
| --- | ---: | ---: | ---: | ---: |
| Correspondence | 0.384 | 0.381 | not run | not run |
| Insurance Claims | 0.670 | 0.665 | not run | not run |
| Corporate Records | 0.497 | 0.484 | not run | not run |
| Contracts | 0.579 | 0.603 | not run | not run |
| Merger Agreements | 0.021 | not run | not run | not run |

## Serving efficiency (per condition, per specialist)

| Metric | 1×L4 C8 | 1×L4 C16 | 2×L4 C8 | 2×L4 C16 |
| --- | ---: | ---: | ---: | ---: |
| Correspondence · documents/min/GPU | not captured | not captured | not run | not run |
| Correspondence · goodput docs/min/GPU | 49.41 | 130.35 | not run | not run |
| Correspondence · tokens/s/GPU | 2,258 | 5,967 | not run | not run |
| Correspondence · GPU util % (mean) | 73.8 | 44.4 | not run | not run |
| Correspondence · GPU mem used | 20,994 MiB (91.1% of 23,034) | 21,002 MiB (91.2% of 23,034) | not run | not run |
| Correspondence · GPU mem bandwidth | not captured | 38.9% mean | not run | not run |
| Correspondence · $/1k ok | $0.266880 | $0.279800 | not run | not run |
| Correspondence · $/1k schema-valid | $0.266880 | $0.279800 | not run | not run |
| Insurance Claims · documents/min/GPU | not captured | not captured | not run | not run |
| Insurance Claims · goodput docs/min/GPU | 23.14 | 472.22 | not run | not run |
| Insurance Claims · tokens/s/GPU | 1,439 | 29,288 | not run | not run |
| Insurance Claims · GPU util % (mean) | 92.8 | 74.6 | not run | not run |
| Insurance Claims · GPU mem used | 21,023 MiB (91.3% of 23,034) | 21,025 MiB (91.3% of 23,034) | not run | not run |
| Insurance Claims · GPU mem bandwidth | not captured | 66.9% mean | not run | not run |
| Insurance Claims · $/1k ok | $0.574880 | $0.536440 | not run | not run |
| Insurance Claims · $/1k schema-valid | $1.916267 | $1.915857 | not run | not run |
| Corporate Records · documents/min/GPU | not captured | not captured | not run | not run |
| Corporate Records · goodput docs/min/GPU | 34.64 | 71.96 | not run | not run |
| Corporate Records · tokens/s/GPU | 2,372 | 4,925 | not run | not run |
| Corporate Records · GPU util % (mean) | 77.6 | 67.8 | not run | not run |
| Corporate Records · GPU mem used | 21,023 MiB (91.3% of 23,034) | 21,026 MiB (91.3% of 23,034) | not run | not run |
| Corporate Records · GPU mem bandwidth | not captured | 47.2% mean | not run | not run |
| Corporate Records · $/1k ok | $0.387920 | $0.412340 | not run | not run |
| Corporate Records · $/1k schema-valid | $0.404083 | $0.429521 | not run | not run |
| Contracts · documents/min/GPU | not captured | not captured | not run | not run |
| Contracts · goodput docs/min/GPU | 0.00 | 0.00 | not run | not run |
| Contracts · tokens/s/GPU | 1,010 | 921 | not run | not run |
| Contracts · GPU util % (mean) | 97.6 | 94.5 | not run | not run |
| Contracts · GPU mem used | 21,026 MiB (91.3% of 23,034) | 21,024 MiB (91.3% of 23,034) | not run | not run |
| Contracts · GPU mem bandwidth | not captured | 84.7% mean | not run | not run |
| Contracts · $/1k ok | $4.091500 | $5.082960 | not run | not run |
| Contracts · $/1k schema-valid | $4.091500 | $5.082960 | not run | not run |
| Merger Agreements · documents/min/GPU | not captured | not run | not run | not run |
| Merger Agreements · goodput docs/min/GPU | 0.64 | not run | not run | not run |
| Merger Agreements · tokens/s/GPU | 1,113 | not run | not run | not run |
| Merger Agreements · GPU util % (mean) | 98.3 | not run | not run | not run |
| Merger Agreements · GPU mem used | 21,027 MiB (91.3% of 23,034) | not run | not run | not run |
| Merger Agreements · GPU mem bandwidth | not captured | not run | not run | not run |
| Merger Agreements · $/1k ok | $20.712260 | not run | not run | not run |
| Merger Agreements · $/1k schema-valid | $20.712260 | not run | not run | not run |

## Paired deltas vs `1l4-c8`

Intervals are 95% percentile bootstrap over documents; a CI containing 0 is inside the noise floor. Full table: [`SAND42-CELL-COMPARISON.md`](SAND42-CELL-COMPARISON.md).

* `1l4-c16` vs `1l4-c8` · contracts_specialist: Δ +0.024 ([-0.006, 0.055], n=45, 24/15 better/worse)
* `1l4-c16` vs `1l4-c8` · corporate_records_specialist: Δ -0.013 ([-0.035, 0.003], n=50, 3/3 better/worse)
* `1l4-c16` vs `1l4-c8` · correspondence_specialist: Δ -0.003 ([-0.022, 0.017], n=50, 2/5 better/worse)
* `1l4-c16` vs `1l4-c8` · insurance_claims_specialist: Δ -0.005 ([-0.013, 0.002], n=50, 11/14 better/worse)

## Findings

* Not measured yet — condition cards report 1l4-c8 5/5, 1l4-c16 4/5, 2l4-c8 0/5, 2l4-c16 0/5. No cross-cell claim is made until all four conditions are complete.

## Cost

| Session | Metered USD | Billed USD |
| --- | ---: | ---: |
| SAND-42 | 0.0 | 0.0 |

Per-condition detail and engine/GPU telemetry: [`SAND42-MASTER-REPORT.md`](SAND42-MASTER-REPORT.md).

_Generated 2026-10-12T06:10:36+00:00 by `sandbox run card --runbook sand42`._
