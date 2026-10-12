# SAND-042 master score & cost card — paired concurrency × fleet grid

**Conditions measured:** 5 of 5 · **Documents per condition:** 250 (5 specialists × n=50, one shared subclass-stratified draw) · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr · **Prompts:** v1 `*_simplified` only.

**Metric coverage:** verbatim /metrics 6/26 · GPU memory bandwidth 21/26 · mid-run KV/queue 6/26 · cold boot 3/5 cells. Every blank states its reason (no substitute values); the full matrix is in the master report.

5 conditions — {1×L4, 2×L4} × {client concurrency 8, 16} plus the 2×L4 C32 saturation point (16 per replica, the engine's `max_num_seqs` admission ceiling) — on the SAND-037 aligned spec.

**The cells do NOT all score the same documents.** `sand42-50-contracts`: ['2l4-c16', '2l4-c32', '2l4-c8'] (50 docs) vs ['1l4-c8'] (50 docs). Any delta between cells on different draws is **not paired** — the per-document difference is undefined across a draw change, so those columns compare different documents and must not be read as a comparison until every cell re-runs on one draw. Everything else in this table (cost, throughput, engine telemetry) is unaffected.
Design, metric contract and acceptance rules: [`docs/SAND42-EXPERIMENT-DESIGN.md`](../../docs/SAND42-EXPERIMENT-DESIGN.md).

## Conditions

| Condition | Runbook | GPUs | Client concurrency | Per replica | min=max |
| --- | --- | ---: | ---: | ---: | --- |
| `1l4-c8` | `sandbox runbook show sand42-1l4-c8` | 1 | 8 | 8 | 1 |
| `1l4-c16` | `sandbox runbook show sand42-1l4-c16` | 1 | 16 | 16 | 1 |
| `2l4-c8` | `sandbox runbook show sand42-2l4-c8` | 2 | 8 | 4 | 2 |
| `2l4-c16` | `sandbox runbook show sand42-2l4-c16` | 2 | 16 | 8 | 2 |
| `2l4-c32` | `sandbox runbook show sand42-2l4-c32` | 2 | 32 | 16 | 2 |

**Matched per-replica-load pair:** `1l4-c8` vs `2l4-c16` (8 per replica each) isolates replica count. `1l4-c8` vs `1l4-c16` isolates concurrency at fixed GPUs. The 2×L4 cells are *not* a load twin of the 1×L4 cells.

## Quality (mean field score; contracts CUAD presence F1, merger MAUD accuracy)

| Metric | 1×L4 C8 | 1×L4 C16 | 2×L4 C8 | 2×L4 C16 | 2×L4 C32 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correspondence | 0.388 | 0.381 | 0.379 | 0.382 | 0.378 |
| Insurance Claims | 0.671 | 0.665 | 0.670 | 0.668 | 0.670 |
| Corporate Records | 0.482 | 0.484 | 0.481 | 0.498 | 0.485 |
| Contracts | 0.599 | 0.603 | 0.622 | 0.606 | 0.593 |
| Merger Agreements | 0.027 | 0.029 | 0.031 | 0.024 | 0.024 |

## Serving efficiency (per condition, per specialist)

| Metric | 1×L4 C8 | 1×L4 C16 | 2×L4 C8 | 2×L4 C16 | 2×L4 C32 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correspondence · documents/min/GPU | 49.41 | 63.47 | 29.63 | 37.60 | 38.41 |
| Correspondence · goodput docs/min/GPU | 49.41 | 63.47 | 29.63 | 37.60 | 38.41 |
| Correspondence · tokens/s/GPU | 2,262 | 2,905 | 1,356 | 1,719 | 1,756 |
| Correspondence · GPU util % (mean) | 87.2 | 44.4 | 69.1 | 63.7 | 62.3 |
| Correspondence · GPU mem used | 21,027 MiB (91.3% of 23,034) | 21,002 MiB (91.2% of 23,034) | 20,983 MiB (91.1% of 23,034) | 19,973 MiB (86.7% of 23,034) | 20,981 MiB (91.1% of 23,034) |
| Correspondence · GPU mem bandwidth | 59.0% mean | 38.9% mean | 56.4% mean | 57.8% mean | 54.5% mean |
| Correspondence · $/1k ok | $0.245320 | $0.279800 | $0.461040 | $0.359540 | $0.352680 |
| Correspondence · $/1k schema-valid | $0.245320 | $0.279800 | $0.461040 | $0.359540 | $0.352680 |
| Insurance Claims · documents/min/GPU | 20.31 | 28.41 | 12.53 | 17.44 | 20.12 |
| Insurance Claims · goodput docs/min/GPU | 20.31 | 28.41 | 12.53 | 17.44 | 20.12 |
| Insurance Claims · tokens/s/GPU | 1,258 | 1,762 | 778 | 1,079 | 1,246 |
| Insurance Claims · GPU util % (mean) | 93.2 | 74.6 | 75.3 | 76.3 | 75.6 |
| Insurance Claims · GPU mem used | 21,028 MiB (91.3% of 23,034) | 21,025 MiB (91.3% of 23,034) | 20,997 MiB (91.2% of 23,034) | 19,993 MiB (86.8% of 23,034) | 21,023 MiB (91.3% of 23,034) |
| Insurance Claims · GPU mem bandwidth | 82.6% mean | 66.9% mean | 73.0% mean | 69.0% mean | 70.3% mean |
| Insurance Claims · $/1k ok | $0.536240 | $0.536440 | $1.072720 | $0.769340 | $0.669460 |
| Insurance Claims · $/1k schema-valid | $1.675750 | $1.915857 | $3.575733 | $3.205583 | $2.231533 |
| Corporate Records · documents/min/GPU | 33.94 | 39.67 | 23.10 | 27.93 | 30.57 |
| Corporate Records · goodput docs/min/GPU | 33.94 | 39.67 | 23.10 | 27.93 | 30.57 |
| Corporate Records · tokens/s/GPU | 2,324 | 2,715 | 1,581 | 1,914 | 2,092 |
| Corporate Records · GPU util % (mean) | 84.6 | 67.8 | 79.6 | 65.4 | 68.6 |
| Corporate Records · GPU mem used | 21,028 MiB (91.3% of 23,034) | 21,026 MiB (91.3% of 23,034) | 20,997 MiB (91.2% of 23,034) | 19,994 MiB (86.8% of 23,034) | 21,023 MiB (91.3% of 23,034) |
| Corporate Records · GPU mem bandwidth | 69.6% mean | 47.2% mean | 64.5% mean | 52.3% mean | 49.4% mean |
| Corporate Records · $/1k ok | $0.370180 | $0.412340 | $0.588180 | $0.481800 | $0.442320 |
| Corporate Records · $/1k schema-valid | $0.385604 | $0.429521 | $0.612688 | $0.491633 | $0.460750 |
| Contracts · documents/min/GPU | 2.18 | 2.67 | 1.53 | 1.41 | 1.46 |
| Contracts · goodput docs/min/GPU | 0.00 | 0.00 | 1.53 | 0.00 | 0.00 |
| Contracts · tokens/s/GPU | 688 | 829 | 446 | 422 | 437 |
| Contracts · GPU util % (mean) | 97.4 | 94.5 | 84.2 | 79.9 | 83.1 |
| Contracts · GPU mem used | 21,028 MiB (91.3% of 23,034) | 21,024 MiB (91.3% of 23,034) | 21,000 MiB (91.2% of 23,034) | 19,994 MiB (86.8% of 23,034) | 21,027 MiB (91.3% of 23,034) |
| Contracts · GPU mem bandwidth | 90.1% mean | 84.7% mean | 80.0% mean | 76.8% mean | 79.8% mean |
| Contracts · $/1k ok | $6.137540 | $5.082960 | $8.912980 | $9.653776 | $9.125560 |
| Contracts · $/1k schema-valid | $6.137540 | $5.082960 | $8.734720 | $9.460700 | $9.125560 |
| Merger Agreements · documents/min/GPU | 0.64 | 0.73 | 0.47 | 0.52 | 0.76 |
| Merger Agreements · goodput docs/min/GPU | 0.64 | 0.00 | 0.47 | 0.52 | 0.76 |
| Merger Agreements · tokens/s/GPU | 1,113 | 1,262 | 811 | 901 | 1,313 |
| Merger Agreements · GPU util % (mean) | 88.7 | 98.2 | 80.6 | 82.2 | 94.8 |
| Merger Agreements · GPU mem used | 21,028 MiB (91.3% of 23,034) | 21,027 MiB (91.3% of 23,034) | 21,002 MiB (91.2% of 23,034) | 19,996 MiB (86.8% of 23,034) | 21,027 MiB (91.3% of 23,034) |
| Merger Agreements · GPU mem bandwidth | 70.8% mean | 78.2% mean | 68.5% mean | 69.0% mean | 74.8% mean |
| Merger Agreements · $/1k ok | $19.927040 | $18.219480 | $28.326080 | $25.497100 | $17.534160 |
| Merger Agreements · $/1k schema-valid | $19.927040 | $18.219480 | $28.326080 | $25.497100 | $17.534160 |

## Paired deltas vs `1l4-c8`

Intervals are 95% percentile bootstrap over documents; a CI containing 0 is inside the noise floor. Full table: [`SAND42-CELL-COMPARISON.md`](SAND42-CELL-COMPARISON.md).

* `1l4-c16` vs `1l4-c8` · contracts_specialist: Δ -0.003 ([-0.047, 0.039], n=39, 15/17 better/worse)
* `1l4-c16` vs `1l4-c8` · corporate_records_specialist: Δ +0.002 ([-0.018, 0.021], n=50, 5/2 better/worse)
* `1l4-c16` vs `1l4-c8` · correspondence_specialist: Δ -0.007 ([-0.028, 0.013], n=50, 1/4 better/worse)
* `1l4-c16` vs `1l4-c8` · insurance_claims_specialist: Δ -0.006 ([-0.014, 0.001], n=50, 9/11 better/worse)
* `1l4-c16` vs `1l4-c8` · merger_agreement_specialist: Δ +0.002 ([-0.010, 0.013], n=50, 6/6 better/worse)
* `2l4-c8` vs `1l4-c8` · contracts_specialist: Δ +0.018 ([-0.023, 0.060], n=38, 18/12 better/worse)
* `2l4-c8` vs `1l4-c8` · corporate_records_specialist: Δ -0.002 ([-0.018, 0.010], n=50, 4/3 better/worse)
* `2l4-c8` vs `1l4-c8` · correspondence_specialist: Δ -0.009 ([-0.025, 0.001], n=50, 1/3 better/worse)
* `2l4-c8` vs `1l4-c8` · insurance_claims_specialist: Δ -0.001 ([-0.005, 0.003], n=50, 7/7 better/worse)
* `2l4-c8` vs `1l4-c8` · merger_agreement_specialist: Δ +0.004 ([-0.006, 0.013], n=50, 8/4 better/worse)
* `2l4-c16` vs `1l4-c8` · contracts_specialist: Δ -0.001 ([-0.044, 0.044], n=39, 17/17 better/worse)
* `2l4-c16` vs `1l4-c8` · corporate_records_specialist: Δ +0.016 ([0.001, 0.036], n=50, 5/2 better/worse)
* `2l4-c16` vs `1l4-c8` · correspondence_specialist: Δ -0.006 ([-0.033, 0.019], n=50, 2/6 better/worse)
* `2l4-c16` vs `1l4-c8` · insurance_claims_specialist: Δ -0.003 ([-0.010, 0.004], n=50, 16/13 better/worse)
* `2l4-c16` vs `1l4-c8` · merger_agreement_specialist: Δ -0.004 ([-0.018, 0.009], n=50, 7/8 better/worse)
* `2l4-c32` vs `1l4-c8` · contracts_specialist: Δ -0.005 ([-0.046, 0.036], n=39, 16/15 better/worse)
* `2l4-c32` vs `1l4-c8` · corporate_records_specialist: Δ +0.003 ([-0.017, 0.022], n=50, 3/1 better/worse)
* `2l4-c32` vs `1l4-c8` · correspondence_specialist: Δ -0.010 ([-0.028, 0.001], n=50, 2/5 better/worse)
* `2l4-c32` vs `1l4-c8` · insurance_claims_specialist: Δ -0.001 ([-0.006, 0.004], n=50, 8/7 better/worse)
* `2l4-c32` vs `1l4-c8` · merger_agreement_specialist: Δ -0.003 ([-0.015, 0.006], n=50, 4/3 better/worse)

## Findings

* 1l4-c16 vs 1l4-c8 · correspondence_specialist: +28% documents/min/GPU
* 1l4-c16 vs 1l4-c8 · insurance_claims_specialist: +40% documents/min/GPU
* 1l4-c16 vs 1l4-c8 · corporate_records_specialist: +17% documents/min/GPU
* 1l4-c16 vs 1l4-c8 · contracts_specialist: +23% documents/min/GPU
* 1l4-c16 vs 1l4-c8 · merger_agreement_specialist: +14% documents/min/GPU
* 2l4-c8 vs 1l4-c8 · correspondence_specialist: -40% documents/min/GPU
* 2l4-c8 vs 1l4-c8 · insurance_claims_specialist: -38% documents/min/GPU
* 2l4-c8 vs 1l4-c8 · corporate_records_specialist: -32% documents/min/GPU
* 2l4-c8 vs 1l4-c8 · contracts_specialist: -30% documents/min/GPU
* 2l4-c8 vs 1l4-c8 · merger_agreement_specialist: -27% documents/min/GPU
* 2l4-c16 vs 1l4-c8 · correspondence_specialist: -24% documents/min/GPU
* 2l4-c16 vs 1l4-c8 · insurance_claims_specialist: -14% documents/min/GPU
* 2l4-c16 vs 1l4-c8 · corporate_records_specialist: -18% documents/min/GPU
* 2l4-c16 vs 1l4-c8 · contracts_specialist: -35% documents/min/GPU
* 2l4-c16 vs 1l4-c8 · merger_agreement_specialist: -19% documents/min/GPU
* 2l4-c32 vs 1l4-c8 · correspondence_specialist: -22% documents/min/GPU
* 2l4-c32 vs 1l4-c8 · insurance_claims_specialist: -1% documents/min/GPU
* 2l4-c32 vs 1l4-c8 · corporate_records_specialist: -10% documents/min/GPU
* 2l4-c32 vs 1l4-c8 · contracts_specialist: -33% documents/min/GPU
* 2l4-c32 vs 1l4-c8 · merger_agreement_specialist: +18% documents/min/GPU

## Cost

| Session | Metered USD | Billed USD |
| --- | ---: | ---: |
| SAND-42 | 0.0 | 0.0 |

Per-condition detail and engine/GPU telemetry: [`SAND42-MASTER-REPORT.md`](SAND42-MASTER-REPORT.md).

_Generated 2026-10-12T20:14:27+00:00 by `sandbox run card --runbook sand42`._
