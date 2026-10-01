# SAND-37 Specialist Grid: Results and Cost Summary

**Scope:** five document-type extraction specialists, each evaluated on two Modal serving postures.
**Date:** 2026-09-30 · **Model:** Qwen3-8B-AWQ on vLLM v0.29.0 · **GPU:** NVIDIA L4 at $0.80 per GPU-hour
**Data:** public `Lucius-Morningstar/mailroom-dataset` ground truth @ `ed7576b6`, seed 42. The n = 20 draw is nested inside the n = 50 draw.

| Posture | GPUs | Client concurrency | Documents per class | Cells |
| --- | ---: | ---: | ---: | ---: |
| **1×L4** | 1 | 8 | 20 | 5 |
| **2×L4** | 2 (data-parallel replicas) | 32 | 50 | 5 |

Both postures use the same engine configuration: AWQ-Marlin, fp8 KV cache, CUDA graphs, prefix caching, thinking disabled, 8,192-token output cap, and frozen v1 prompts. Temperature is 0.7 for contracts and merger and 0.1 for the other classes.

## Serving efficiency (pooled across the five specialists)

| Metric | 1×L4 | 2×L4 | Change |
| --- | ---: | ---: | ---: |
| Documents ok / total | 97 / 100 | 245 / 250 | — |
| Error rate | 3.0% | 2.0% | −1.0 pt |
| Throughput (documents per minute) | 8.74 | 20.71 | +137% |
| Throughput (tokens per second per GPU) | 812 | 1,013 | +25% |
| GPU cost per document | $0.00153 | $0.00129 | −16% |
| GPU cost per 1M tokens | $0.274 | $0.219 | −20% |
| Busy-window GPU cost | $0.153 | $0.322 | — |

## Quality and cost by specialist

| Specialist | Metric | 1×L4 score | 2×L4 score | ok / n (1×L4 · 2×L4) | p50 latency (s) | $ per ok document (1×L4 · 2×L4) |
| --- | --- | ---: | ---: | :---: | :---: | :---: |
| Insurance claims | Field score | 0.684 | 0.686 | 20/20 · 50/50 | 13.2 · 19.6 | 0.00042 · 0.00032 |
| Contracts | Field score (CUAD F1) | 0.631 (0.597) | 0.615 (0.605) | 19/20 · 49/50 | 65.8 · 103.3 | 0.00350 · 0.00284 |
| Corporate records | Field score | 0.459 | 0.452 | 20/20 · 50/50 | 14.4 · 24.1 | 0.00026 · 0.00019 |
| Correspondence | Field score | 0.327 | 0.334 | 20/20 · 50/50 | 5.8 · 10.7 | 0.00011 · 0.00012 |
| Merger agreements | MAUD accuracy (coverage) | 0.014 (13%) | 0.035 (23%) | 18/20 · 46/50 | 50.5 · 92.5 | 0.00390 · 0.00329 |

Field scores are the mean suite extraction score against ground truth. The contracts score also includes CUAD clause scoring. Merger is scored by micro-accuracy over labeled MAUD questions, which is a different scale from the field scores.

## Findings

1. **2×L4 at concurrency 32 is the more cost-efficient posture.** It costs 16% less per document and delivers 25% more tokens per second per GPU. Pooled document throughput rises by a factor of 2.4. Median latency per document rises by 1.5–1.8×, because the higher concurrency adds queueing at each replica. 1×L4 at concurrency 8 therefore remains preferable where per-document latency matters more than throughput.
2. **Extraction quality does not depend on serving posture.** On the three classes scored by field score alone, scores differ by at most 0.007 between postures. On contracts, the field score differs by 0.016 and CUAD F1 by 0.008. These differences are consistent with the larger sample (n = 50 versus 20), not with any change in model output.
3. **All 8 errors are output-cap truncations in the two grammar-constrained classes.** The model reached the 8,192-token limit and the output could not be parsed: contracts 1/20 and 1/50, merger 2/20 and 4/50. No errors came from infrastructure or authentication, and no response failed to parse as JSON.
4. **Merger agreements are the main quality gap.** Source agreements run to 260k–404k characters, and the input window is 30k characters (head plus tail). The model therefore sees about 7–12% of each document and answers only 13–23% of labeled MAUD questions, with 10–15% precision on the questions it does answer. Closing this gap requires a different input strategy, such as chunked or retrieval-based clause extraction, not a change to the serving posture.
5. **Correspondence shows low and variable field scores** (mean 0.33, standard deviation 0.20–0.24). Its scores are stable across postures, which points to the prompt or scorer alignment rather than serving. It is the next candidate for prompt or scorer review.
6. **Schema conformance is incomplete for insurance claims.** The schema-valid rate is 0.30 on 1×L4 and 0.24 on 2×L4, compared with 0.94–0.95 for corporate records and 1.00 for the other three classes. Insurance claims has the highest field score of the five, so its outputs score well on content but often do not strictly conform to the target schema. Downstream consumers that require strict schema validation would reject most of these outputs. Enforcing the schema through grammar-constrained decoding, as is already done for contracts and merger, is the direct remedy.

## Cost accounting and run integrity

- **Busy-window GPU cost:** $0.47 across all 10 cells (350 documents).
- **Total metered Modal cost for the session:** $1.09, fully covered by credits ($0.00 billed). The difference from the busy-window cost is cold boots, pinned-warm idle time between cells, the weight pre-warm, and one invalidated launch.
- **Invalidated contracts attempt:** the first 1×L4 contracts attempt failed authentication. The cause was a client credential-precedence defect in the LangChain-based specialists. The attempt was excluded and the cell rerun with corrected credentials. All results above come from the rerun.
- **Teardown:** verified after each posture, with zero containers left warm.
- **Comparability:** the postures differ in GPU count, client concurrency and sample size by design. The comparison is between complete serving postures, not GPU count alone.

**Source data:** per-cell score and cost cards, run reports and vLLM serving telemetry are in `1L4/<specialist>/` and `2L4/<specialist>/`. Posture-level suite cards are `1L4/L4x1-SCORE-COST-CARD.md` and `2L4/L4x2-SCORE-COST-CARD.md`.
