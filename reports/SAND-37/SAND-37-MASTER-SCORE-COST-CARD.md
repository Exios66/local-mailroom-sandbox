# SAND-37 / SAND-39 / SAND-40 Specialist Grid: Results and Cost Summary

## Key findings

1. **Scale-out is near-linear.** 2×L4 at C32 raises throughput +99% at +0.4% cost per document; median latency rises ×1.4–1.8 (identical 250 documents).
2. **Larger runs cost less per document.** Running n = 100 per specialist instead of n = 50 cuts GPU cost per document 19% on the four unchanged specialists; 1 of 400 failed (0.25%).
3. **Merger is the quality gap; the † settings narrow it.** They raise MAUD accuracy 0.035 → 0.140 and coverage 23% → 69% on the same 50 agreements, at 4.5× the GPU cost per agreement.

**Setup:** Qwen/Qwen3-8B-AWQ on vLLM v0.29.0, NVIDIA L4 at $0.80/GPU-hr; `Lucius-Morningstar/mailroom-dataset` @ `ed7576b6`, seed 42, smaller draws nested in larger ones. Frozen v1 prompts and an 8,192-token output cap except the † merger cell.

Method, detail tables and figures: [SAND-37-MASTER-APPENDIX.md](./SAND-37-MASTER-APPENDIX.md).

| Study | Posture | GPUs | Client concurrency | Documents per class | Status |
| --- | --- | ---: | ---: | ---: | --- |
| SAND-37 | 1×L4 C8 n=20 | 1 | 8 | 20 | 5 of 5 cells |
| SAND-39 | 1×L4 C8 n=50 | 1 | 8 | 50 | 5 of 5 cells |
| SAND-37 | 2×L4 C32 n=50 | 2 | 32 | 50 | 5 of 5 cells |
| SAND-40 | 2×L4 C32 n=100 | 2 | 32 | 100 (merger 50†) | 5 of 5 cells |

## Serving efficiency (pooled across the five specialists)

| Metric | SAND-37 1×L4 C8 n=20 | SAND-39 1×L4 C8 n=50 | SAND-37 2×L4 C32 n=50 | SAND-40 2×L4 C32 n=100 |
| --- | ---: | ---: | ---: | ---: |
| Error rate | 3.0% | 2.8% | 2.0% | 0.22% |
| Documents per minute | 8.74 | 10.40 | 20.71 | 11.86 |
| Tokens per second per GPU | 812 | 1,002 | 1,013 | 1,662 |
| GPU cost per document | $0.00153 | $0.00128 | $0.00129 | $0.00225 |

SAND-40 includes the † merger cell's whole-agreement reads; the like-for-like check is in the appendix.

## Quality and cost by specialist

Cell order: 1×L4 C8 n=20 · 1×L4 C8 n=50 · 2×L4 C32 n=50 · 2×L4 C32 n=100. Contracts: CUAD F1 (micro). Merger: MAUD accuracy (coverage), a different scale. † = optimized merger.

| Specialist | Score | ok / n | p50 latency (s) | $ per ok document |
| --- | :---: | :---: | :---: | :---: |
| Insurance Claims | 0.684 · 0.684 · 0.686 · 0.672 | 20/20 · 50/50 · 50/50 · 100/100 | 13.2 · 14.0 · 19.6 · 20.4 | 0.00042 · 0.00039 · 0.00032 · 0.00036 |
| Contracts | 0.631 (0.597) · 0.602 (0.590) · 0.615 (0.605) · 0.612 (0.608) | 19/20 · 47/50 · 49/50 · 99/100 | 65.8 · 68.2 · 103.3 · 96.1 | 0.00350 · 0.00310 · 0.00284 · 0.00207 |
| Corporate Records | 0.459 · 0.449 · 0.452 · 0.475 | 20/20 · 50/50 · 50/50 · 100/100 | 14.4 · 13.2 · 24.1 · 19.9 | 0.00026 · 0.00032 · 0.00019 · 0.00021 |
| Correspondence | 0.327 · 0.345 · 0.334 · 0.341 | 20/20 · 50/50 · 50/50 · 100/100 | 5.8 · 6.6 · 10.7 · 10.3 | 0.00011 · 0.00018 · 0.00012 · 0.00012 |
| Merger Agreements | 0.014 (13%) · 0.048 (24%) · 0.035 (23%) · 0.140 (69%)† | 18/20 · 46/50 · 46/50 · 50/50 | 50.5 · 51.3 · 92.5 · 1044.4 | 0.00390 · 0.00284 · 0.00329 · 0.01475 |

## Merger † settings

Same 50 agreements (seed 42) and 2×L4 engine as SAND-37; only the settings below change.

| Setting | SAND-37 / SAND-39 merger | SAND-40 merger † |
| --- | --- | --- |
| Input | head + tail, 30,000 chars (rest of the agreement unread) | whole agreement, chunked: 47,000-char windows + 6,500-char overlap (≤ 54,000 chars per call), merged |
| Prompt | `merger_agreement_specialist_simplified` | `merger_agreement_specialist_maud_v1` |
| Sampling | temperature 0.7, other sampling at vLLM defaults | temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.0 |
| Output cap | 8,192 tokens | 6,144 tokens |
| Re-sample on a length-capped output | none | 1 |
| Result | MAUD accuracy 0.035, coverage 23%, 46/50 ok, $0.0033 per agreement | MAUD accuracy 0.140, coverage 69%, 50/50 ok, $0.0147 per agreement |
| Matched agreements | — | +0.106 mean per-agreement score over 46 agreements (35 better / 1 worse) |

## Cost

- **SAND-37 metered Modal total:** $1.09 ($0.00 billed after credits).
- **SAND-39 metered Modal total:** $0.49 ($0.00 billed after credits).
- **SAND-40 metered Modal total:** $1.81 ($0.00 billed after credits).
- **Teardown** verified after each posture, zero containers left warm.
