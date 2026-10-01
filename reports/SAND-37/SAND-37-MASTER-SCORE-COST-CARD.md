# SAND-37 / SAND-39 Specialist Grid: Results and Cost Summary

**Model:** Qwen/Qwen3-8B-AWQ on vLLM v0.29.0 · **GPU:** NVIDIA L4 at $0.80 per GPU-hour  
**Data:** public `Lucius-Morningstar/mailroom-dataset` ground_truth @ `ed7576b6`, seed 42; the n = 20 draw is nested in the n = 50 draw, and every n = 50 posture scores the identical documents.  
**Engine (all postures):** AWQ-Marlin, fp8 KV cache, CUDA graphs, prefix caching, thinking disabled, 8,192-token output cap, frozen v1 prompts; temperature 0.7 for contracts and merger, 0.1 otherwise.

| Study | Posture | GPUs | Client concurrency | Documents per class | Status |
| --- | --- | ---: | ---: | ---: | --- |
| SAND-37 | 1×L4 C8 n=20 | 1 | 8 | 20 | 5 of 5 cells |
| SAND-39 | 1×L4 C8 n=50 | 1 | 8 | 50 | pending |
| SAND-37 | 2×L4 C32 n=50 | 2 | 32 | 50 | 5 of 5 cells |

## Serving efficiency (pooled across the five specialists)

| Metric | SAND-37 1×L4 C8 n=20 | SAND-39 1×L4 C8 n=50 | SAND-37 2×L4 C32 n=50 |
| --- | ---: | ---: | ---: |
| Documents ok / total | 97 / 100 | pending | 245 / 250 |
| Error rate | 3.0% | pending | 2.0% |
| Throughput (documents per minute) | 8.74 | pending | 20.71 |
| Throughput (tokens per second per GPU) | 812 | pending | 1,013 |
| GPU cost per document | $0.00153 | pending | $0.00129 |
| GPU cost per 1M tokens | $0.274 | pending | $0.219 |
| Busy-window GPU cost | $0.153 | pending | $0.322 |

## Quality and cost by specialist

Columns within each cell follow the posture order above (1×L4 C8 n=20 · 1×L4 C8 n=50 · 2×L4 C32 n=50).

| Specialist | Metric | Score | ok / n | p50 latency (s) | $ per ok document |
| --- | --- | :---: | :---: | :---: | :---: |
| Insurance Claims | Field score | 0.684 · pending · 0.686 | 20/20 · pending · 50/50 | 13.2 · pending · 19.6 | 0.00042 · pending · 0.00032 |
| Contracts | Field score (CUAD F1) | 0.631 (0.597) · pending · 0.615 (0.605) | 19/20 · pending · 49/50 | 65.8 · pending · 103.3 | 0.00350 · pending · 0.00284 |
| Corporate Records | Field score | 0.459 · pending · 0.452 | 20/20 · pending · 50/50 | 14.4 · pending · 24.1 | 0.00026 · pending · 0.00019 |
| Correspondence | Field score | 0.327 · pending · 0.334 | 20/20 · pending · 50/50 | 5.8 · pending · 10.7 | 0.00011 · pending · 0.00012 |
| Merger Agreements | MAUD accuracy (coverage) | 0.014 (13%) · pending · 0.035 (23%) | 18/20 · pending · 46/50 | 50.5 · pending · 92.5 | 0.00390 · pending · 0.00329 |

Field scores are the mean suite extraction score against ground truth; contracts adds CUAD clause scoring. Merger is scored by micro-accuracy over labeled MAUD questions, a different scale from the field scores.

## Findings

1. **2×L4 at C32 is the more cost-efficient posture** (1×L4 C8 n=20 vs 2×L4 C32 n=50; sample sizes differ, SAND-39 pending). Moving from 1×L4 C8 n=20 to 2×L4 C32 n=50 changes cost per document by −16%, tokens per second per GPU by +25%, and pooled documents per minute by +137%. Median per-document latency changes by a factor of 1.5–1.9×, reflecting per-replica queueing at the higher concurrency.
2. **Extraction quality is independent of serving posture.** Field scores differ by at most 0.016 across postures; CUAD F1 differs by 0.008, consistent with sampling variation rather than any change in model output.
3. **All 8 errors are output-cap truncations: the model reached the 8,192-token limit before closing the JSON** (contracts 1/20, 1/50; merger agreements 2/20, 4/50). No errors arose from infrastructure, authentication or JSON parsing.
4. **Merger agreements are the principal quality gap.** Source agreements far exceed the 30,000-character input window (head plus tail), so the model answers only 13%–23% of labeled MAUD questions, with 10%–15% precision on those answered. Closing the gap requires an input strategy such as chunked or retrieval-based clause extraction, not a change of serving posture.
5. **Correspondence field scores are low and dispersed** (mean 0.33, standard deviation 0.20–0.24). Stability across postures points to prompt or scorer alignment rather than serving; it is the next candidate for review.
6. **Schema conformance is incomplete for insurance claims** (schema-valid rate 0.24–0.30; corporate records 0.94–0.95; 1.00 for contracts, merger and correspondence). Its content scores well, but strict-schema consumers would reject most outputs; grammar-constrained decoding, as already used for contracts and merger, is the direct remedy.

## Cost accounting and run integrity

- **SAND-37 1×L4 C8 n=20:** busy-window GPU $0.15 across 100 documents.
- **SAND-37 2×L4 C32 n=50:** busy-window GPU $0.32 across 250 documents.
- **SAND-37 metered Modal total:** $1.09 ($0.00 billed after credits). Covers both SAND-37 postures plus cold boots, pinned-warm idle between cells, the weight pre-warm, and one invalidated contracts attempt (client credential-precedence defect, SAND-038; excluded and rerun).
- **Teardown** is verified after each posture, with zero containers left warm.
- **Comparability:** SAND-39 and the SAND-37 2×L4 leg score identical n = 50 documents and differ only in GPU count and client concurrency; the SAND-37 1×L4 leg is a nested n = 20 subset.

**Source data:** per-cell score and cost cards, run reports and vLLM serving telemetry under `1L4/<specialist>/` and `2L4/<specialist>/`; posture suite cards `1L4/L4x1-SCORE-COST-CARD.md` and `2L4/L4x2-SCORE-COST-CARD.md`. Regenerate with `sandbox run card --master`.
