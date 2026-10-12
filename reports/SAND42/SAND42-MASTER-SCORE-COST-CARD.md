# SAND-042 master score & cost card — paired concurrency × fleet grid

**Conditions measured:** 2 of 4 · **Documents per condition:** 250 (5 specialists × n=50, one shared subclass-stratified draw) · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr · **Prompts:** v1 `*_simplified` only.

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
| Correspondence | 0.384 | 0.381 | 0.379 | 0.382 |
| Insurance Claims | 0.670 | 0.665 | 0.670 | 0.668 |
| Corporate Records | 0.497 | 0.484 | 0.481 | 0.498 |
| Contracts | 0.579 | 0.603 | 0.622 | not run |
| Merger Agreements | 0.021 | 0.029 | not run | not run |

## Serving efficiency (per condition, per specialist)

| Metric | 1×L4 C8 | 1×L4 C16 | 2×L4 C8 | 2×L4 C16 |
| --- | ---: | ---: | ---: | ---: |
| Correspondence · documents/min/GPU | not captured | not captured | not captured | not captured |
| Correspondence · goodput docs/min/GPU | 49.41 | 130.35 | 29.63 | 37.60 |
| Correspondence · tokens/s/GPU | 2,258 | 5,967 | 1,356 | 1,719 |
| Correspondence · GPU util % (mean) | 73.8 | 44.4 | 69.1 | 63.7 |
| Correspondence · GPU mem used | 20,994 MiB (91.1% of 23,034) | 21,002 MiB (91.2% of 23,034) | 20,983 MiB (91.1% of 23,034) | 19,973 MiB (86.7% of 23,034) |
| Correspondence · GPU mem bandwidth | not captured | 38.9% mean | 56.4% mean | 57.8% mean |
| Correspondence · $/1k ok | $0.266880 | $0.279800 | $0.461040 | $0.359540 |
| Correspondence · $/1k schema-valid | $0.266880 | $0.279800 | $0.461040 | $0.359540 |
| Insurance Claims · documents/min/GPU | not captured | not captured | not captured | not captured |
| Insurance Claims · goodput docs/min/GPU | 23.14 | 472.22 | 12.53 | 17.44 |
| Insurance Claims · tokens/s/GPU | 1,439 | 29,288 | 778 | 1,079 |
| Insurance Claims · GPU util % (mean) | 92.8 | 74.6 | 75.3 | 76.3 |
| Insurance Claims · GPU mem used | 21,023 MiB (91.3% of 23,034) | 21,025 MiB (91.3% of 23,034) | 20,997 MiB (91.2% of 23,034) | 19,993 MiB (86.8% of 23,034) |
| Insurance Claims · GPU mem bandwidth | not captured | 66.9% mean | 73.0% mean | 69.0% mean |
| Insurance Claims · $/1k ok | $0.574880 | $0.536440 | $1.072720 | $0.769340 |
| Insurance Claims · $/1k schema-valid | $1.916267 | $1.915857 | $3.575733 | $3.205583 |
| Corporate Records · documents/min/GPU | not captured | not captured | not captured | not captured |
| Corporate Records · goodput docs/min/GPU | 34.64 | 71.96 | 23.10 | 27.93 |
| Corporate Records · tokens/s/GPU | 2,372 | 4,925 | 1,581 | 1,914 |
| Corporate Records · GPU util % (mean) | 77.6 | 67.8 | 79.6 | 65.4 |
| Corporate Records · GPU mem used | 21,023 MiB (91.3% of 23,034) | 21,026 MiB (91.3% of 23,034) | 20,997 MiB (91.2% of 23,034) | 19,994 MiB (86.8% of 23,034) |
| Corporate Records · GPU mem bandwidth | not captured | 47.2% mean | 64.5% mean | 52.3% mean |
| Corporate Records · $/1k ok | $0.387920 | $0.412340 | $0.588180 | $0.481800 |
| Corporate Records · $/1k schema-valid | $0.404083 | $0.429521 | $0.612688 | $0.491633 |
| Contracts · documents/min/GPU | not captured | not captured | not captured | not run |
| Contracts · goodput docs/min/GPU | 0.00 | 0.00 | 1.53 | not run |
| Contracts · tokens/s/GPU | 1,010 | 921 | 446 | not run |
| Contracts · GPU util % (mean) | 97.6 | 94.5 | 84.2 | not run |
| Contracts · GPU mem used | 21,026 MiB (91.3% of 23,034) | 21,024 MiB (91.3% of 23,034) | 21,000 MiB (91.2% of 23,034) | not run |
| Contracts · GPU mem bandwidth | not captured | 84.7% mean | 80.0% mean | not run |
| Contracts · $/1k ok | $4.091500 | $5.082960 | $8.912980 | not run |
| Contracts · $/1k schema-valid | $4.091500 | $5.082960 | $8.734720 | not run |
| Merger Agreements · documents/min/GPU | not captured | not captured | not run | not run |
| Merger Agreements · goodput docs/min/GPU | 0.64 | 0.00 | not run | not run |
| Merger Agreements · tokens/s/GPU | 1,113 | 1,262 | not run | not run |
| Merger Agreements · GPU util % (mean) | 98.3 | 98.2 | not run | not run |
| Merger Agreements · GPU mem used | 21,027 MiB (91.3% of 23,034) | 21,027 MiB (91.3% of 23,034) | not run | not run |
| Merger Agreements · GPU mem bandwidth | not captured | 78.2% mean | not run | not run |
| Merger Agreements · $/1k ok | $20.712260 | $18.219480 | not run | not run |
| Merger Agreements · $/1k schema-valid | $20.712260 | $18.219480 | not run | not run |

## Paired deltas vs `1l4-c8`

Intervals are 95% percentile bootstrap over documents; a CI containing 0 is inside the noise floor. Full table: [`SAND42-CELL-COMPARISON.md`](SAND42-CELL-COMPARISON.md).

* `1l4-c16` vs `1l4-c8` · contracts_specialist: Δ +0.024 ([-0.006, 0.055], n=45, 24/15 better/worse)
* `1l4-c16` vs `1l4-c8` · corporate_records_specialist: Δ -0.013 ([-0.035, 0.003], n=50, 3/3 better/worse)
* `1l4-c16` vs `1l4-c8` · correspondence_specialist: Δ -0.003 ([-0.022, 0.017], n=50, 2/5 better/worse)
* `1l4-c16` vs `1l4-c8` · insurance_claims_specialist: Δ -0.005 ([-0.013, 0.002], n=50, 11/14 better/worse)
* `1l4-c16` vs `1l4-c8` · merger_agreement_specialist: Δ +0.008 ([-0.002, 0.020], n=50, 9/5 better/worse)
* `2l4-c8` vs `1l4-c8` · contracts_specialist: Δ +0.042 ([0.002, 0.081], n=44, 26/11 better/worse)
* `2l4-c8` vs `1l4-c8` · corporate_records_specialist: Δ -0.016 ([-0.038, 0.001], n=50, 2/6 better/worse)
* `2l4-c8` vs `1l4-c8` · correspondence_specialist: Δ -0.005 ([-0.019, 0.005], n=50, 1/3 better/worse)
* `2l4-c8` vs `1l4-c8` · insurance_claims_specialist: Δ +0.001 ([-0.005, 0.007], n=50, 10/10 better/worse)
* `2l4-c16` vs `1l4-c8` · corporate_records_specialist: Δ +0.001 ([-0.018, 0.021], n=50, 4/4 better/worse)
* `2l4-c16` vs `1l4-c8` · correspondence_specialist: Δ -0.003 ([-0.029, 0.021], n=50, 3/5 better/worse)
* `2l4-c16` vs `1l4-c8` · insurance_claims_specialist: Δ -0.001 ([-0.007, 0.003], n=50, 14/11 better/worse)

## Findings


## Cost

| Session | Metered USD | Billed USD |
| --- | ---: | ---: |
| SAND-42 | 0.0 | 0.0 |

Per-condition detail and engine/GPU telemetry: [`SAND42-MASTER-REPORT.md`](SAND42-MASTER-REPORT.md).

_Generated 2026-10-12T07:01:20+00:00 by `sandbox run card --runbook sand42`._
