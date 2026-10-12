# Corporate Records — 1× L4 · C16 · n=50

**Run:** `sand42-50-corporate-records-specialist-awq-1l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Draw | 50 docs (fingerprint 76b083c7c46d) |
| Engine | awq_marlin · fp8 KV · CUDA graphs [1, 2, 4, 8, 16] · prefix caching on · thinking off |
| Admission | max_model_len 32768 · max_num_seqs 16 per replica · max_inputs 32 |

## Score & cost card

| Metric | Value |
| --- | ---: |
| **Run** |  |
| Run ID | `sand42-50-corporate-records-specialist-awq-1l4-c16` |
| GPUs / replicas | 1 |
| Concurrency | 16 (16 per replica) |
| Documents | 50 |
| Spec hash | 94320a5e… |
| **Time** |  |
| Wall (busy) | 75.63 s |
| GPU seconds | 92.78 s |
| Cold boot | 0.32 s |
| **Cost** |  |
| Busy-window GPU $ | $0.016807 |
| Billed GPU $ | $0.020617 |
| Billed seconds | 92.78 s |
| Idle $ | $0.003872 (17.42 s) |
| Cost per document | $0.000412 |
| Cost per ok document | $0.000412 |
| Cost per 1M tokens | $0.1004 |
| **Tokens** |  |
| Prompt tokens | 197,319 |
| Completion tokens | 8,000 (3.9%) |
| Total tokens | 205,319 |
| Tokens per document | 4,106 |
| Per document: instructions + template | 2,090 (50.9%) |
| Per document: document text | 1,856 (45.2%) |
| Per document: output | 160 (3.9%) |
| Instruction tokens per model call | 2,090 over 50 calls |
| Token split basis | fit across documents, 4.21 chars/token |
| Completion p95 / max (ok docs) | 198 / 234 |
| **Throughput** |  |
| Tokens / second | 2,714.7 |
| Tokens / second per L4 | 2,714.7 |
| Documents / minute | 39.67 |
| **Latency (per document, ok rows)** |  |
| Mean | 18.63 s |
| p50 | 19.58 s |
| p95 | 24.28 s |
| Max | 31.46 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 12.31× of 16 |
| Slot occupancy | 77.0% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 50 |
| Mean TTFT per replica | 2.562 s |
| Prefix-cache hit per replica | 50.9% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 0 |
| **GPU hardware (nvidia-smi)** | 16 samples · serving-replica nvidia-smi |
| GPU utilization | 67.8 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 59.2 W (min 31.1 / max 72.5) of 72 W cap |
| GPU memory bandwidth | 47.2 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,489 MHz (min 1,020 / max 2,040) |
| GPU temperature | 75.1 C (min 67.0 / max 82.0) |
| GPU memory used | 21,026 MiB (min 21,026 / max 21,026) |
| **Quality** |  |
| Overall extraction score | 0.4840 (sd 0.251) |
| Score min / max | 0.0635 / 0.8889 |
| Scoring method | `suite` |
| Schema-valid rate | 0.96 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Corporate Records run dashboard](sand42-50-corporate-records-specialist-awq-1l4-c16.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-91f89b9c0d285ac7` | yes | 0.6667 | 19.6 | 6902 | 128 | — |
| 2 | `DOC-9ca44c7926a47ede` | yes | 0.5024 | 19.6 | 2292 | 130 | — |
| 3 | `DOC-020d77c0107d273d` | yes | 0.4746 | 19.6 | 2302 | 116 | — |
| 4 | `DOC-c4c9c37a96291975` | yes | 0.0813 | 20.7 | 2424 | 136 | — |
| 5 | `DOC-a040ac19abb88fec` | yes | 0.4121 | 21.3 | 2206 | 141 | — |
| 6 | `DOC-6790430ae2a6c724` | yes | 0.1846 | 22.6 | 4477 | 142 | — |
| 7 | `DOC-e545bbd5f5ea61b6` | yes | 0.3636 | 23.8 | 2788 | 154 | — |
| 8 | `DOC-12a6d4cd092cf66d` | yes | 0.5026 | 23.8 | 7710 | 158 | — |
| 9 | `DOC-0a262afc80c73247` | yes | 0.1136 | 23.9 | 3124 | 153 | — |
| 10 | `DOC-81ae205a3b0bf16f` | yes | 0.2480 | 23.9 | 2515 | 158 | — |
| 11 | `DOC-01054efd0980066b` | yes | 0.8222 | 23.9 | 5122 | 160 | — |
| 12 | `DOC-fbcdd16e24f143ac` | yes | 0.1582 | 23.9 | 2456 | 155 | — |
| 13 | `DOC-2819b889b134ea01` | yes | 0.7500 | 24.2 | 5344 | 169 | — |
| 14 | `DOC-732b812b7d9d9653` | yes | 0.8889 | 24.2 | 5572 | 165 | — |
| 15 | `DOC-0f56fe8db6df01bd` | yes | 0.0635 | 24.2 | 5368 | 161 | — |
| 16 | `DOC-68d5a8753fcc3675` | yes | 0.4405 | 31.5 | 5671 | 177 | — |
| 17 | `DOC-b832b5eaa2b4848c` | yes | 0.1068 | 10.6 | 2762 | 95 | — |
| 18 | `DOC-9376c6bfa6779d5e` | yes | 0.4822 | 15.2 | 2200 | 131 | — |
| 19 | `DOC-f134b9491efc5c57` | yes | 0.7949 | 13.8 | 2865 | 140 | — |
| 20 | `DOC-e077f1f7e80e1e04` | yes | 0.1624 | 17.4 | 4043 | 151 | — |
| 21 | `DOC-2f19002c84083aa8` | yes | 0.4978 | 16.9 | 5200 | 165 | — |
| 22 | `DOC-a5fd7fe18b094f20` | yes | 0.7576 | 16.6 | 5919 | 143 | — |
| 23 | `DOC-474a0002b4c03be1` | yes | 0.8205 | 16.7 | 2938 | 149 | — |
| 24 | `DOC-e478fa89043a29e3` | yes | 0.8205 | 16.9 | 2910 | 151 | — |
| 25 | `DOC-b3ad98e5530dfeaf` | yes | 0.2820 | 21.2 | 2521 | 182 | — |
| 26 | `DOC-9467462d9bb34f8e` | yes | 0.5417 | 19.5 | 5345 | 158 | — |
| 27 | `DOC-d015968793450753` | yes | 0.8056 | 19.8 | 5082 | 166 | — |
| 28 | `DOC-1e8e3ce47882ae71` | yes | 0.1485 | 21.3 | 3063 | 198 | — |
| 29 | `DOC-204c3c7c0ba021cd` | yes | 0.4746 | 13.8 | 2226 | 152 | — |
| 30 | `DOC-4dc719baa790a79c` | yes | 0.6667 | 24.2 | 2669 | 193 | — |
| 31 | `DOC-fc9f56d999bd7566` | yes | 0.6667 | 24.3 | 2509 | 196 | — |
| 32 | `DOC-41b53ea487b84955` | yes | 0.7500 | 27.8 | 4617 | 228 | — |
| 33 | `DOC-bfa92eb6c72569ee` | yes | 0.1184 | 20.1 | 3771 | 158 | — |
| 34 | `DOC-37152a33cfb70d37` | yes | 0.4103 | 20.0 | 2902 | 161 | — |
| 35 | `DOC-00193d0c070747e6` | yes | 0.7143 | 21.6 | 3225 | 181 | — |
| 36 | `DOC-ffb48271e0a5e812` | yes | 0.6667 | 15.9 | 5344 | 141 | — |
| 37 | `DOC-0a8eb16fff7e67ca` | yes | 0.3590 | 19.0 | 5246 | 159 | — |
| 38 | `DOC-78f2456f571403a9` | yes | 0.1531 | 15.9 | 2345 | 144 | — |
| 39 | `DOC-2338d194d5250def` | yes | 0.5170 | 12.0 | 5258 | 138 | — |
| 40 | `DOC-80e90a37bb750a3c` | yes | 0.1495 | 16.7 | 2776 | 167 | — |
| 41 | `DOC-f21f3dadebb121e3` | yes | 0.7843 | 17.2 | 3308 | 180 | — |
| 42 | `DOC-e6906e59f9bd74ca` | yes | 0.6200 | 14.2 | 2978 | 160 | — |
| 43 | `DOC-d4dfbfe8049d41f9` | yes | 0.4934 | 14.7 | 3856 | 175 | — |
| 44 | `DOC-866139125545b36a` | yes | 0.7733 | 14.7 | 5397 | 179 | — |
| 45 | `DOC-842215e36884da89` | yes | 0.2467 | 10.5 | 5226 | 158 | — |
| 46 | `DOC-606242f2919653a4` | yes | 0.2332 | 10.7 | 5253 | 161 | — |
| 47 | `DOC-a973ebf005e0e785` | yes | 0.4278 | 22.0 | 6146 | 234 | — |
| 48 | `DOC-dfe42f3747f299e6` | yes | 0.7500 | 7.7 | 5870 | 158 | — |
| 49 | `DOC-d0aebe650be3e512` | yes | 0.4976 | 5.7 | 2405 | 163 | — |
| 50 | `DOC-27bbad54b6fd107e` | yes | 0.8333 | 6.2 | 2871 | 182 | — |

_Generated 2026-10-12T17:17:04+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-corporate-records-specialist-awq-1l4-c16.card.json`._
