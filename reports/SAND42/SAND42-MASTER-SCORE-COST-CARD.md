# SAND-042 master score & cost card — paired concurrency × fleet grid

**Conditions measured:** 0 of 4 · **Documents per condition:** 250 (5 specialists × n=50, one shared subclass-stratified draw) · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr · **Prompts:** v1 `*_simplified` only.

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
| Correspondence | not run | not run | not run | not run |
| Insurance Claims | not run | not run | not run | not run |
| Corporate Records | not run | not run | not run | not run |
| Contracts | not run | not run | not run | not run |
| Merger Agreements | not run | not run | not run | not run |

## Serving efficiency (per condition, per specialist)

| Metric | 1×L4 C8 | 1×L4 C16 | 2×L4 C8 | 2×L4 C16 |
| --- | ---: | ---: | ---: | ---: |
| Correspondence · documents/min/GPU | not run | not run | not run | not run |
| Correspondence · goodput docs/min/GPU | not run | not run | not run | not run |
| Correspondence · tokens/s/GPU | not run | not run | not run | not run |
| Correspondence · GPU util % (mean) | not run | not run | not run | not run |
| Correspondence · $/1k ok | not run | not run | not run | not run |
| Correspondence · $/1k schema-valid | not run | not run | not run | not run |
| Insurance Claims · documents/min/GPU | not run | not run | not run | not run |
| Insurance Claims · goodput docs/min/GPU | not run | not run | not run | not run |
| Insurance Claims · tokens/s/GPU | not run | not run | not run | not run |
| Insurance Claims · GPU util % (mean) | not run | not run | not run | not run |
| Insurance Claims · $/1k ok | not run | not run | not run | not run |
| Insurance Claims · $/1k schema-valid | not run | not run | not run | not run |
| Corporate Records · documents/min/GPU | not run | not run | not run | not run |
| Corporate Records · goodput docs/min/GPU | not run | not run | not run | not run |
| Corporate Records · tokens/s/GPU | not run | not run | not run | not run |
| Corporate Records · GPU util % (mean) | not run | not run | not run | not run |
| Corporate Records · $/1k ok | not run | not run | not run | not run |
| Corporate Records · $/1k schema-valid | not run | not run | not run | not run |
| Contracts · documents/min/GPU | not run | not run | not run | not run |
| Contracts · goodput docs/min/GPU | not run | not run | not run | not run |
| Contracts · tokens/s/GPU | not run | not run | not run | not run |
| Contracts · GPU util % (mean) | not run | not run | not run | not run |
| Contracts · $/1k ok | not run | not run | not run | not run |
| Contracts · $/1k schema-valid | not run | not run | not run | not run |
| Merger Agreements · documents/min/GPU | not run | not run | not run | not run |
| Merger Agreements · goodput docs/min/GPU | not run | not run | not run | not run |
| Merger Agreements · tokens/s/GPU | not run | not run | not run | not run |
| Merger Agreements · GPU util % (mean) | not run | not run | not run | not run |
| Merger Agreements · $/1k ok | not run | not run | not run | not run |
| Merger Agreements · $/1k schema-valid | not run | not run | not run | not run |

## Paired deltas vs `1l4-c8`

Intervals are 95% percentile bootstrap over documents; a CI containing 0 is inside the noise floor. Full table: [`SAND42-CELL-COMPARISON.md`](SAND42-CELL-COMPARISON.md).

*_Not measured yet._*

## Findings

* Not measured yet — condition cards report 1l4-c8 0/5, 1l4-c16 0/5, 2l4-c8 0/5, 2l4-c16 0/5. No cross-cell claim is made until all four conditions are complete.

## Cost

_No teardown spend recorded yet_ (`sandbox run card --record-metered SAND-42 <metered> <billed>`).

Per-condition detail and engine/GPU telemetry: [`SAND42-MASTER-REPORT.md`](SAND42-MASTER-REPORT.md).

_Generated 2026-10-12T00:11:20+00:00 by `sandbox run card --runbook sand42`._
