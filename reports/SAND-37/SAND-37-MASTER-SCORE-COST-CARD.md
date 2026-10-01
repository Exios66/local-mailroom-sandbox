# SAND-37 / SAND-39 Specialist Grid: Results and Cost Summary

**Model:** Qwen/Qwen3-8B-AWQ on vLLM v0.29.0 · **GPU:** NVIDIA L4 at $0.80 per GPU-hour  
**Data:** public `Lucius-Morningstar/mailroom-dataset` ground_truth @ `ed7576b6`, seed 42; the n = 20 draw is nested in the n = 50 draw, and every n = 50 posture scores the identical documents.  
**Engine (SAND-37 / SAND-39):** AWQ-Marlin, fp8 KV cache, CUDA graphs, prefix caching, thinking disabled, 8,192-token output cap, frozen v1 prompts; temperature 0.7 for contracts and merger, 0.1 otherwise.  
**SAND-40:** one 32K deploy of the same 2×L4 engine at C32. Four specialists run n = 100 on unchanged settings (the n = 50 draw nested inside); merger runs the same 50 agreements as SAND-37 2×L4 with the optimized settings marked † (see *Merger † settings*).

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
| GPU cost per 1M tokens | $0.274 | $0.222 | $0.219 | pending |
| Busy-window GPU cost | $0.153 | $0.321 | $0.322 | pending |
| Busy wall time (sum of cells) | 687 s | 1,443 s | 724 s | pending |
| Tokens processed (prompt / completion) | 496,135 / 61,446 | 1,291,533 / 154,463 | 1,310,750 / 157,089 | pending |
| Length-capped finishes (vLLM) | 3 | 7 | 5 | pending |
| Preemptions (vLLM) | 0 | 0 | 0 | pending |

## Quality and cost by specialist

Columns within each cell follow the posture order above (1×L4 C8 n=20 · 1×L4 C8 n=50 · 2×L4 C32 n=50 · 2×L4 C32 n=100).

| Specialist | Metric | Score | ok / n | p50 latency (s) | $ per ok document |
| --- | --- | :---: | :---: | :---: | :---: |
| Insurance Claims | Field score | 0.684 · 0.684 · 0.686 · pending | 20/20 · 50/50 · 50/50 · pending | 13.2 · 14.0 · 19.6 · pending | 0.00042 · 0.00039 · 0.00032 · pending |
| Contracts | CUAD presence F1: labeled-document mean (micro) | 0.631 (0.597) · 0.602 (0.590) · 0.615 (0.605) · pending | 19/20 · 47/50 · 49/50 · pending | 65.8 · 68.2 · 103.3 · pending | 0.00350 · 0.00310 · 0.00284 · pending |
| Corporate Records | Field score | 0.459 · 0.449 · 0.452 · pending | 20/20 · 50/50 · 50/50 · pending | 14.4 · 13.2 · 24.1 · pending | 0.00026 · 0.00032 · 0.00019 · pending |
| Correspondence | Field score | 0.327 · 0.345 · 0.334 · pending | 20/20 · 50/50 · 50/50 · pending | 5.8 · 6.6 · 10.7 · pending | 0.00011 · 0.00018 · 0.00012 · pending |
| Merger Agreements | MAUD accuracy (coverage) | 0.014 (13%) · 0.048 (24%) · 0.035 (23%) · pending† | 18/20 · 46/50 · 46/50 · pending | 50.5 · 51.3 · 92.5 · pending | 0.00390 · 0.00284 · 0.00329 · pending |

Field scores (insurance claims, corporate records, correspondence) are the mean suite extraction score against ground truth over successful documents. Contracts ground truth is CUAD clause labels, so its score is the per-document CUAD clause-presence F1 averaged over the successful documents that carry CUAD labels (see *Clause scoring detail* for counts), with the pooled micro F1 in parentheses; the committed run reports count unlabeled documents as 0 and so read lower. Merger is micro-accuracy over labeled MAUD questions, with question coverage in parentheses, a different scale from the field scores. † marks the optimized merger cell (next section).

## Merger † settings

The SAND-40 merger cell keeps the engine, fleet and agreements of SAND-37 2×L4 and changes how each agreement is read and decoded. Changed settings are in bold.

| Setting | SAND-37 / SAND-39 merger | SAND-40 merger † |
| --- | --- | --- |
| Agreements | the same 50 (seed 42) | the same 50 (seed 42) |
| Serving window | 32,768 tokens on 2×L4 | 32,768 tokens on 2×L4 |
| **Input** | head + tail, 30,000 chars (rest of the agreement unread) | **whole agreement, chunked: 47,000-char windows + 6,500-char overlap (≤ 54,000 chars per call), merged** |
| **Prompt** | `merger_agreement_specialist_simplified` | **`merger_agreement_specialist_maud_v1`** |
| **Sampling** | temperature 0.7, other sampling at vLLM defaults | **temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.0** |
| **Output cap** | 8,192 tokens | **6,144 tokens** |
| **Re-sample on a length-capped output** | none | **1** |
| Result | MAUD accuracy 0.035, coverage 23%, 46/50 ok, $0.0033 per agreement | pending |

## Per-cell detail

One table per posture. Latency is per successful document; tokens per document is prompt plus completion over all documents; busy GPU $ is the cell's busy wall × GPUs × $0.80 per GPU-hour.

### SAND-37 1×L4 C8 n=20

| Specialist | ok / n | Errors | Schema-valid | Score (sd) | p50 / p95 latency (s) | Tokens per doc | Completion p95 / max | Wall (s) | Busy GPU $ | $ per ok doc | $ per 1M tokens | Tokens/s/GPU |
| --- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Insurance Claims | 20/20 | 0 | 0.30 | 0.684 (0.054) | 13.2 / 19.0 | 3,427 | 496 / 968 | 37.8 | $0.0084 | $0.00042 | $0.123 | 1,813 |
| Contracts | 19/20 | 1 (length 1) | 1.00 | 0.631 (0.143) | 65.8 / 104.9 | 8,161 | 2,442 / 4,860 | 299.3 | $0.0665 | $0.00350 | $0.429 | 518 |
| Corporate Records | 20/20 | 0 | 0.95 | 0.459 (0.245) | 14.4 / 20.5 | 5,040 | 239 / 247 | 23.4 | $0.0052 | $0.00026 | $0.052 | 4,315 |
| Correspondence | 20/20 | 0 | 1.00 | 0.327 (0.241) | 5.8 / 7.9 | 2,527 | 180 / 296 | 10.1 | $0.0022 | $0.00011 | $0.044 | 5,029 |
| Merger Agreements | 18/20 | 2 (length 2) | 1.00 | 0.014 (0.024) | 50.5 / 66.1 | 10,148 | 1,279 / 1,661 | 316.1 | $0.0703 | $0.00390 | $0.385 | 578 |

### SAND-39 1×L4 C8 n=50

| Specialist | ok / n | Errors | Schema-valid | Score (sd) | p50 / p95 latency (s) | Tokens per doc | Completion p95 / max | Wall (s) | Busy GPU $ | $ per ok doc | $ per 1M tokens | Tokens/s/GPU |
| --- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Insurance Claims | 50/50 | 0 | 0.20 | 0.684 (0.069) | 14.0 / 26.7 | 3,648 | 624 / 956 | 87.4 | $0.0194 | $0.00039 | $0.107 | 2,087 |
| Contracts | 47/50 | 3 (length 3) | 1.00 | 0.602 (0.118) | 68.2 / 108.9 | 8,868 | 2,829 / 3,391 | 655.2 | $0.1456 | $0.00310 | $0.349 | 636 |
| Corporate Records | 50/50 | 0 | 0.94 | 0.449 (0.249) | 13.2 / 19.8 | 4,630 | 237 / 247 | 71.2 | $0.0158 | $0.00032 | $0.068 | 3,254 |
| Correspondence | 50/50 | 0 | 1.00 | 0.345 (0.218) | 6.6 / 11.7 | 2,858 | 298 / 463 | 40.6 | $0.0090 | $0.00018 | $0.063 | 3,523 |
| Merger Agreements | 46/50 | 4 (length 4) | 1.00 | 0.048 (0.049) | 51.3 / 109.7 | 10,269 | 1,798 / 2,535 | 588.4 | $0.1308 | $0.00284 | $0.277 | 803 |

### SAND-37 2×L4 C32 n=50

| Specialist | ok / n | Errors | Schema-valid | Score (sd) | p50 / p95 latency (s) | Tokens per doc | Completion p95 / max | Wall (s) | Busy GPU $ | $ per ok doc | $ per 1M tokens | Tokens/s/GPU |
| --- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Insurance Claims | 50/50 | 0 | 0.24 | 0.686 (0.068) | 19.6 / 32.6 | 3,651 | 709 / 956 | 35.6 | $0.0158 | $0.00032 | $0.087 | 2,564 |
| Contracts | 49/50 | 1 (length 1) | 1.00 | 0.615 (0.127) | 103.3 / 156.6 | 8,917 | 2,688 / 2,915 | 312.8 | $0.1390 | $0.00284 | $0.318 | 699 |
| Corporate Records | 50/50 | 0 | 0.94 | 0.452 (0.235) | 24.1 / 34.6 | 4,630 | 233 / 247 | 21.2 | $0.0094 | $0.00019 | $0.041 | 5,467 |
| Correspondence | 50/50 | 0 | 1.00 | 0.334 (0.203) | 10.7 / 18.5 | 2,858 | 296 / 443 | 14.0 | $0.0062 | $0.00012 | $0.043 | 5,120 |
| Merger Agreements | 46/50 | 4 (length 4) | 1.00 | 0.035 (0.041) | 92.5 / 167.2 | 10,303 | 1,543 / 2,852 | 340.8 | $0.1515 | $0.00329 | $0.320 | 695 |

Merger score is MAUD micro-accuracy; its sd is over per-document scores.

## Clause scoring detail

| Posture | Contracts: CUAD-labeled docs | Precision | Recall | Micro F1 | Labeled-doc mean F1 | Value accuracy | Merger: MAUD questions | Answered (coverage) | Correct | Accuracy | Precision on answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SAND-37 1×L4 C8 n=20 | 16 of 19 ok | 0.657 | 0.548 | 0.597 | 0.631 | 32/44 (73%) | 289 | 39 (13%) | 4 | 0.014 | 0.103 |
| SAND-39 1×L4 C8 n=50 | 39 of 47 ok | 0.624 | 0.559 | 0.590 | 0.602 | 71/110 (65%) | 751 | 179 (24%) | 36 | 0.048 | 0.201 |
| SAND-37 2×L4 C32 n=50 | 40 of 49 ok | 0.703 | 0.531 | 0.605 | 0.615 | 77/113 (68%) | 747 | 174 (23%) | 26 | 0.035 | 0.149 |

Clause counts cover successful documents only, so two postures on the same draw can differ slightly in labeled documents and MAUD questions when different documents hit the output cap.

## Engine telemetry (vLLM /metrics, this run's delta)

Requests, length-capped finishes and preemptions are summed over replicas; prefix-cache hit rate and mean time to first token are request-weighted across replicas. A chunked or re-sampled document issues more than one request.

| Specialist | Requests | Length-capped finishes | Preemptions | Prefix-cache hit rate | Mean TTFT (s) |
| --- | :---: | :---: | :---: | :---: | :---: |
| Insurance Claims | 20 · 50 · 50 | 0 · 0 · 0 | 0 · 0 · 0 | 61% · 58% · 57% | 1.1 · 1.0 · 3.0 |
| Contracts | 20 · 50 · 50 | 1 · 3 · 1 | 0 · 0 · 0 | 43% · 44% · 43% | 3.1 · 1.8 · 6.9 |
| Corporate Records | 20 · 50 · 50 | 0 · 0 · 0 | 0 · 0 · 0 | 47% · 48% · 47% | 1.8 · 1.4 · 4.0 |
| Correspondence | 20 · 50 · 50 | 0 · 0 · 0 | 0 · 0 · 0 | 67% · 61% · 60% | 1.0 · 0.8 · 2.7 |
| Merger Agreements | 20 · 50 · 50 | 2 · 4 · 4 | 0 · 0 · 0 | 31% · 37% · 36% | 4.9 · 2.4 · 9.4 |

Columns follow the posture order (1×L4 C8 n=20 · 1×L4 C8 n=50 · 2×L4 C32 n=50).

## Run conditions by specialist

Identical across the postures above unless a cell lists more than one value.

| Specialist | Prompt | Input cap (chars) | Output cap (tokens) | Temperature | Retries |
| --- | --- | ---: | ---: | ---: | ---: |
| Insurance Claims | `insurance_claims_specialist_simplified` | 13,500 | 8,192 | 0.1 | 2 |
| Contracts | `contracts_specialist_v33_simplified` | 24,000 | 8,192 | 0.7 | 2 |
| Corporate Records | `corporate_records_specialist_simplified` | 15,000 | 8,192 | 0.1 | 2 |
| Correspondence | `correspondence_specialist_simplified` | 12,000 | 8,192 | 0.1 | 2 |
| Merger Agreements | `merger_agreement_specialist_simplified` | 30,000 | 8,192 | 0.7 | 2 |

## SAND-40 validation probes (n = 20, not pooled)

Before the scale run, two probes tested optimized long-document settings (64K YaRN window, 128,000-character input, chunked extraction, Qwen3 sampling, 6,144-token cap with one length re-sample; MAUD v1 prompt for merger) on the first 20 documents of the SAND-37 2×L4 n = 50 draw. They are not a posture column. The SAND-40 merger cell keeps the chunking, prompt and decode settings on the 32K window; the 64K window and 128,000-character input are not used. The matched columns compare per-document scores on the documents both runs scored, so sample composition cannot explain the difference.

| Specialist | Window | Input cap (chars) | ok / n | Score | Matched docs | Probe mean | SAND-37 2×L4 same docs | Δ (better / worse) | Prompt tokens per doc: probe vs SAND-37 | Wall (s) | Busy GPU $ | $ per ok doc |
| --- | ---: | ---: | :---: | ---: | :---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: |
| Contracts | 65,536 | 128,000 | 20/20 | 0.670 | 16 | 0.661 | 0.664 | -0.002 (8 / 7) | 7,144 vs 6,128 | 105.6 | $0.0469 | $0.00235 |
| Merger Agreements | 65,536 | 128,000 | 20/20 | 0.127 | 18 | 0.114 | 0.033 | +0.081 (14 / 3) | 96,478 vs 8,371 | 1,473.0 | $0.6547 | $0.03273 |

Score is the specialist's primary metric (contracts labeled-document CUAD F1, merger MAUD accuracy); the matched columns use per-document scores. Probe cards and run reports: `probes/<specialist>/`.

## Findings

1. **Scaling out to 2×L4 at C32 raises throughput by +99% at unchanged cost per document** (identical 250 documents, SAND-39 1×L4 C8 n=50 vs SAND-37 2×L4 C32 n=50). Moving from 1×L4 C8 n=50 to 2×L4 C32 n=50 changes cost per document by +0%, tokens per second per GPU by +1%, and pooled documents per minute by +99%, so capacity scales near-linearly with GPU count. Median per-document latency rises by a factor of 1.4–1.8×, reflecting per-replica queueing at the higher concurrency.
2. **Extraction quality is independent of serving posture.** Field scores differ by at most 0.029 across postures; CUAD F1 differs by 0.015, consistent with sampling variation rather than any change in model output.
3. **All 15 errors are output-cap truncations: the model reached the 8,192-token limit before closing the JSON** (contracts 1/20, 3/50, 1/50; merger agreements 2/20, 4/50, 4/50). No errors arose from infrastructure, authentication or JSON parsing.
4. **Merger agreements are the principal quality gap.** Source agreements far exceed the 30,000-character input window (head plus tail), so the model answers only 13%–24% of labeled MAUD questions, with 10%–20% precision on those answered. Closing the gap requires an input strategy such as chunked or retrieval-based clause extraction, not a change of serving posture.
5. **Correspondence field scores are low and dispersed** (mean 0.33–0.34, standard deviation 0.20–0.24). Stability across postures points to prompt or scorer alignment rather than serving; it is the next candidate for review.
6. **Schema conformance is incomplete for insurance claims** (schema-valid rate 0.20–0.30; corporate records 0.94–0.95; 1.00 for contracts, merger and correspondence). Its content scores well, but strict-schema consumers would reject most outputs; grammar-constrained decoding, as already used for contracts and merger, is the direct remedy.

## Figures: posture comparison

![Pooled serving efficiency by posture: GPU cost per 1,000 documents, tokens per second per GPU, and documents per minute.](figures/cmp-efficiency.png)

*Figure 1. Pooled serving efficiency by posture: GPU cost per 1,000 documents, tokens per second per GPU, and documents per minute.*

![Primary quality metric by specialist and posture; labels mark failed documents. Merger is MAUD accuracy, a different scale from the field scores.](figures/cmp-quality.png)

*Figure 2. Primary quality metric by specialist and posture; labels mark failed documents. Merger is MAUD accuracy, a different scale from the field scores.*

![Per-document latency (bar p50, whisker p95) and GPU cost per 1,000 successful documents, by specialist and posture.](figures/cmp-latency-cost.png)

*Figure 3. Per-document latency (bar p50, whisker p95) and GPU cost per 1,000 successful documents, by specialist and posture.*

![Matched-sample check: each point is one document scored under SAND-39 (1×L4 C8) and SAND-37 (2×L4 C32). Points on the diagonal mean the posture did not change the output's score.](figures/cmp-matched.png)

*Figure 4. Matched-sample check: each point is one document scored under SAND-39 (1×L4 C8) and SAND-37 (2×L4 C32). Points on the diagonal mean the posture did not change the output's score.*


## Cost accounting and run integrity

- **SAND-37 1×L4 C8 n=20:** busy-window GPU $0.15 across 100 documents.
- **SAND-39 1×L4 C8 n=50:** busy-window GPU $0.32 across 250 documents.
- **SAND-37 2×L4 C32 n=50:** busy-window GPU $0.32 across 250 documents.
- **SAND-37 metered Modal total:** $1.09 ($0.00 billed after credits). Covers both SAND-37 postures plus cold boots, pinned-warm idle between cells, the weight pre-warm, and one invalidated contracts attempt (client credential-precedence defect, SAND-038; excluded and rerun).
- **SAND-39 metered Modal total:** $0.49 ($0.00 billed after credits). One 1×L4 session: weight pre-warm, cold boot, the five cells pinned warm, and teardown. October month-to-date metering ($1.42) less the SAND-37 October hours ($0.93).
- **Teardown** is verified after each posture, with zero containers left warm.
- **Comparability:** SAND-39 and the SAND-37 2×L4 leg score identical n = 50 documents and differ only in GPU count and client concurrency; the SAND-37 1×L4 leg is a nested n = 20 subset.

**Source data:** per-cell score and cost cards, run reports and vLLM serving telemetry under `1L4/<specialist>/` and `2L4/<specialist>/`; posture suite cards `1L4/L4x1-SCORE-COST-CARD.md` and `2L4/L4x2-SCORE-COST-CARD.md`. Regenerate with `sandbox run card --master`.


## Appendix: posture dashboards

![SAND-37 1×L4 C8 n=20: per-document score and latency distributions, cost per 1,000 successful documents, and token mix by specialist.](1L4/figures/SAND-37-1xL4-C8-n20.png)

*Dashboard 1. SAND-37 1×L4 C8 n=20: per-document score and latency distributions, cost per 1,000 successful documents, and token mix by specialist.*

![SAND-39 1×L4 C8 n=50: per-document score and latency distributions, cost per 1,000 successful documents, and token mix by specialist.](1L4/figures/SAND-39-1xL4-C8-n50.png)

*Dashboard 2. SAND-39 1×L4 C8 n=50: per-document score and latency distributions, cost per 1,000 successful documents, and token mix by specialist.*

![SAND-37 2×L4 C32 n=50: per-document score and latency distributions, cost per 1,000 successful documents, and token mix by specialist.](2L4/figures/SAND-37-2xL4-C32-n50.png)

*Dashboard 3. SAND-37 2×L4 C32 n=50: per-document score and latency distributions, cost per 1,000 successful documents, and token mix by specialist.*
