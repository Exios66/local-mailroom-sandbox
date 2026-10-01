# SAND-37 / SAND-39 Specialist Grid: Results and Cost Summary

Full detail, figures and method notes live in [SAND-37-MASTER-APPENDIX.md](./SAND-37-MASTER-APPENDIX.md).

**Model:** Qwen/Qwen3-8B-AWQ (vLLM v0.29.0) · **GPU:** NVIDIA L4 at $0.80/GPU-hr · **Data:** `Lucius-Morningstar/mailroom-dataset` ground_truth @ `ed7576b6`, seed 42 (n = 20 nested in n = 50; every n = 50 posture scores identical documents).  
**Engine:** AWQ-Marlin, fp8 KV, CUDA graphs, prefix caching, thinking off, 8,192-token cap, frozen v1 prompts (T 0.7 contracts/merger, 0.1 elsewhere). SAND-40 † merger settings in the appendix.

| Study | Posture | GPUs | Client concurrency | Documents per class | Status |
| --- | --- | ---: | ---: | ---: | --- |
| SAND-37 | 1×L4 C8 n=20 | 1 | 8 | 20 | 5 of 5 cells |
| SAND-39 | 1×L4 C8 n=50 | 1 | 8 | 50 | 5 of 5 cells |
| SAND-37 | 2×L4 C32 n=50 | 2 | 32 | 50 | 5 of 5 cells |
| SAND-40 | 2×L4 C32 n=100 | 2 | 32 | 100 (merger 50†) | pending |

## Serving efficiency (pooled across the five specialists)

| Metric | SAND-37 1×L4 C8 n=20 | SAND-39 1×L4 C8 n=50 | SAND-37 2×L4 C32 n=50 | SAND-40 2×L4 C32 n=100 |
| --- | ---: | ---: | ---: | ---: |
| Documents ok / total | 97 / 100 | 243 / 250 | 245 / 250 | pending |
| Error rate | 3.0% | 2.8% | 2.0% | pending |
| Throughput (documents per minute) | 8.74 | 10.40 | 20.71 | pending |
| Throughput (tokens per second per GPU) | 812 | 1,002 | 1,013 | pending |
| GPU cost per document | $0.00153 | $0.00128 | $0.00129 | pending |
| Busy-window GPU cost | $0.153 | $0.321 | $0.322 | pending |

## Quality and cost by specialist

Cell order: 1×L4 C8 n=20 · 1×L4 C8 n=50 · 2×L4 C32 n=50 · 2×L4 C32 n=100. Contracts = CUAD F1 (micro in parentheses); merger = MAUD accuracy (coverage in parentheses) — different scales from the field scores.

| Specialist | Score | ok / n | p50 latency (s) | $ per ok document |
| --- | :---: | :---: | :---: | :---: |
| Insurance Claims | 0.684 · 0.684 · 0.686 · pending | 20/20 · 50/50 · 50/50 · pending | 13.2 · 14.0 · 19.6 · pending | 0.00042 · 0.00039 · 0.00032 · pending |
| Contracts | 0.631 (0.597) · 0.602 (0.590) · 0.615 (0.605) · pending | 19/20 · 47/50 · 49/50 · pending | 65.8 · 68.2 · 103.3 · pending | 0.00350 · 0.00310 · 0.00284 · pending |
| Corporate Records | 0.459 · 0.449 · 0.452 · pending | 20/20 · 50/50 · 50/50 · pending | 14.4 · 13.2 · 24.1 · pending | 0.00026 · 0.00032 · 0.00019 · pending |
| Correspondence | 0.327 · 0.345 · 0.334 · pending | 20/20 · 50/50 · 50/50 · pending | 5.8 · 6.6 · 10.7 · pending | 0.00011 · 0.00018 · 0.00012 · pending |
| Merger Agreements | 0.014 (13%) · 0.048 (24%) · 0.035 (23%) · pending† | 18/20 · 46/50 · 46/50 · pending | 50.5 · 51.3 · 92.5 · pending | 0.00390 · 0.00284 · 0.00329 · pending |

## Key findings

1. **Scale-out is near-linear:** 2×L4 at C32 raises throughput by +99% at +0% cost per document (identical 250 documents; median latency ×1.4–1.8).
2. **Quality is posture-independent:** field scores within 0.029 across postures; all 15 errors are 8,192-token output-cap truncations (contracts/merger only).
3. **Merger is the quality gap:** MAUD coverage 13%–24% — agreements exceed the 30,000-char window, so chunked extraction (not more GPUs) is the fix. See the appendix for probes, correspondence and schema notes.

## Cost and integrity

- **SAND-37 metered Modal total:** $1.09 ($0.00 billed after credits). Covers both SAND-37 postures plus cold boots, pinned-warm idle between cells, the weight pre-warm, and one invalidated contracts attempt (client credential-precedence defect, SAND-038; excluded and rerun).
- **SAND-39 metered Modal total:** $0.49 ($0.00 billed after credits). One 1×L4 session: weight pre-warm, cold boot, the five cells pinned warm, and teardown. October month-to-date metering ($1.42) less the SAND-37 October hours ($0.93).
- **Teardown** verified after each posture, zero containers left warm.

**Source data:** per-cell cards under `1L4/<specialist>/` and `2L4/<specialist>/`; suite cards `1L4/L4x1-SCORE-COST-CARD.md`, `2L4/L4x2-SCORE-COST-CARD.md`. Detail, method and figures: [./SAND-37-MASTER-APPENDIX.md](./SAND-37-MASTER-APPENDIX.md). Regenerate with `sandbox run card --master`.
