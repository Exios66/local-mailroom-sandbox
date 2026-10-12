# Corporate Records — 1× L4 · C8 · n=5

**Run:** `sand42-check-5-corporate-records-awq-1l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

## Conditions

| Condition | Value |
| --- | --- |
| Task | corporate_records_specialist |
| Prompt | corporate_records_specialist_simplified |
| Temperature | 0.1 (vendored call site) |
| Output cap (max_tokens) | 8,192 |
| Input cap (max_input_chars) | 15,000 |
| Job retries | 2 |
| Dataset | Lucius-Morningstar/mailroom-dataset ground_truth @ ed7576b6, split=all, seed 42 |
| Draw | 5 docs (fingerprint 34c1303db918) |
| Engine | awq_marlin · fp8 KV · CUDA graphs [1, 2, 4, 8, 16] · prefix caching on · thinking off |
| Admission | max_model_len 32768 · max_num_seqs 16 per replica · max_inputs 32 |

## Score & cost card

| Metric | Value |
| --- | ---: |
| **Run** |  |
| Run ID | `sand42-check-5-corporate-records-awq-1l4-c8` |
| GPUs / replicas | 1 |
| Concurrency | 8 (8 per replica) |
| Documents | 5 |
| Spec hash | 53132be4… |
| **Time** |  |
| Wall (busy) | 0.43 s |
| GPU seconds | 0.77 s |
| Cold boot | 0.34 s |
| **Cost** |  |
| Busy-window GPU $ | $0.000095 |
| Billed GPU $ (incl. boot) | $0.000172 |
| Idle $ | not captured |
| Cost per document | $0.000019 |
| Cost per ok document | $0.000019 |
| Cost per 1M tokens | $0.0045 |
| **Tokens** |  |
| Prompt tokens | 20,069 |
| Completion tokens | 847 (4.0%) |
| Total tokens | 20,916 |
| Tokens per document | 4,183 |
| Per document: instructions + template | 2,214 (52.9%) |
| Per document: document text | 1,799 (43.0%) |
| Per document: output | 169 (4.0%) |
| Instruction tokens per model call | 2,214 over 5 calls |
| Token split basis | document chars ÷ 4.5 chars/token; instructions are the remainder |
| Completion p95 / max (ok docs) | 234 / 234 |
| **Throughput** |  |
| Tokens / second | 48,869.2 |
| Tokens / second per L4 | 48,869.2 |
| Documents / minute | 700.93 |
| **Latency (per document, ok rows)** |  |
| Mean | 11.28 s |
| p50 | 11.02 s |
| p95 | 12.34 s |
| Max | 12.34 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 131.80× of 8 |
| Slot occupancy | 1647.5% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 5 |
| Mean TTFT per replica | 4.493 s |
| Prefix-cache hit per replica | 31.9% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 0 |
| **GPU hardware (nvidia-smi)** | 4 samples · serving-replica nvidia-smi |
| GPU utilization | 49.0 % mean (min 0.0 / peak 100.0) |
| GPU power draw | 52.4 W (min 31.9 / max 72.9) |
| GPU temperature | 69.8 C (min 66.0 / max 72.0) |
| GPU memory used | 20,938 MiB (min 20,764 / max 20,996) |
| **Quality** |  |
| Overall extraction score | 0.5625 (sd 0.164) |
| Score min / max | 0.4103 / 0.8205 |
| Scoring method | `suite` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 5 |

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-f134b9491efc5c57` | yes | 0.4615 | 11.0 | 2865 | 151 | — |
| 2 | `DOC-0a8eb16fff7e67ca` | yes | 0.6923 | 11.0 | 5246 | 150 | — |
| 3 | `DOC-e478fa89043a29e3` | yes | 0.8205 | 11.0 | 2910 | 151 | — |
| 4 | `DOC-37152a33cfb70d37` | yes | 0.4103 | 11.0 | 2902 | 161 | — |
| 5 | `DOC-a973ebf005e0e785` | yes | 0.4278 | 12.3 | 6146 | 234 | — |

_Generated 2026-10-12T01:06:30+00:00 by `sandbox run card`. Machine-readable twin: `sand42-check-5-corporate-records-awq-1l4-c8.card.json`._
