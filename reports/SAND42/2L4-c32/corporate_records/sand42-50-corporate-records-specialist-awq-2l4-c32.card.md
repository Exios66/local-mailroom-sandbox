# Corporate Records — 2× L4 · C32 · n=50

**Run:** `sand42-50-corporate-records-specialist-awq-2l4-c32` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-corporate-records-specialist-awq-2l4-c32` |
| GPUs / replicas | 2 |
| Concurrency | 32 (16 per replica) |
| Documents | 50 |
| Spec hash | 4c3e1631… |
| **Time** |  |
| Wall (busy) | 49.07 s |
| GPU seconds | 49.76 s |
| Cold boot | 0.33 s |
| **Cost** |  |
| Busy-window GPU $ | $0.021808 |
| Billed GPU $ | $0.022116 |
| Billed seconds | 49.76 s |
| Idle $ | $0.008148 (18.33 s) |
| Cost per document | $0.000442 |
| Cost per ok document | $0.000442 |
| Cost per 1M tokens | $0.1077 |
| **Tokens** |  |
| Prompt tokens | 197,319 |
| Completion tokens | 7,970 (3.9%) |
| Total tokens | 205,289 |
| Tokens per document | 4,106 |
| Per document: instructions + template | 2,090 (50.9%) |
| Per document: document text | 1,856 (45.2%) |
| Per document: output | 159 (3.9%) |
| Instruction tokens per model call | 2,090 over 50 calls |
| Token split basis | fit across documents, 4.21 chars/token |
| Completion p95 / max (ok docs) | 198 / 234 |
| **Throughput** |  |
| Tokens / second | 4,183.7 |
| Tokens / second per L4 | 2,091.8 |
| Documents / minute | 61.14 |
| **Latency (per document, ok rows)** |  |
| Mean | 19.67 s |
| p50 | 19.11 s |
| p95 | 33.32 s |
| Max | 33.99 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 20.04× of 32 |
| Slot occupancy | 62.6% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 30 / 20 |
| Mean TTFT per replica | 9.055 s / 2.226 s |
| Prefix-cache hit per replica | 52.5% / 44.0% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 13 samples · serving-replica nvidia-smi |
| GPU utilization | 68.6 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 86.2 % — **below the 90% gate (issue #128)** |
| GPU power draw | 60.0 W (min 32.3 / max 72.5) of 72 W cap |
| GPU memory bandwidth | 49.4 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,416 MHz (min 960 / max 2,040) |
| GPU temperature | 76.4 C (min 69.0 / max 81.0) |
| GPU memory used | 21,023 MiB (min 21,022 / max 21,024) |
| **Quality** |  |
| Overall extraction score | 0.4851 (sd 0.253) |
| Score min / max | 0.0635 / 0.8889 |
| Scoring method | `suite` |
| Schema-valid rate | 0.96 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Corporate Records run dashboard](sand42-50-corporate-records-specialist-awq-2l4-c32.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-f134b9491efc5c57` | yes | 0.7949 | 14.1 | 2865 | 140 | — |
| 2 | `DOC-e077f1f7e80e1e04` | yes | 0.1624 | 14.1 | 4043 | 151 | — |
| 3 | `DOC-474a0002b4c03be1` | yes | 0.8205 | 14.2 | 2938 | 150 | — |
| 4 | `DOC-b832b5eaa2b4848c` | yes | 0.1068 | 14.3 | 2762 | 157 | — |
| 5 | `DOC-01054efd0980066b` | yes | 0.8222 | 14.5 | 5122 | 159 | — |
| 6 | `DOC-fbcdd16e24f143ac` | yes | 0.1582 | 14.5 | 2456 | 155 | — |
| 7 | `DOC-0f56fe8db6df01bd` | yes | 0.0635 | 14.5 | 5368 | 161 | — |
| 8 | `DOC-e545bbd5f5ea61b6` | yes | 0.3636 | 14.7 | 2788 | 159 | — |
| 9 | `DOC-020d77c0107d273d` | yes | 0.4746 | 17.6 | 2302 | 113 | — |
| 10 | `DOC-9376c6bfa6779d5e` | yes | 0.4822 | 17.8 | 2200 | 131 | — |
| 11 | `DOC-2f19002c84083aa8` | yes | 0.4951 | 19.1 | 5200 | 170 | — |
| 12 | `DOC-68d5a8753fcc3675` | yes | 0.4405 | 19.1 | 5671 | 177 | — |
| 13 | `DOC-c4c9c37a96291975` | yes | 0.0813 | 19.4 | 2424 | 136 | — |
| 14 | `DOC-9ca44c7926a47ede` | yes | 0.5024 | 19.7 | 2292 | 131 | — |
| 15 | `DOC-b3ad98e5530dfeaf` | yes | 0.2820 | 19.5 | 2521 | 189 | — |
| 16 | `DOC-a5fd7fe18b094f20` | yes | 0.8485 | 21.4 | 5919 | 145 | — |
| 17 | `DOC-6790430ae2a6c724` | yes | 0.1846 | 22.5 | 4477 | 142 | — |
| 18 | `DOC-12a6d4cd092cf66d` | yes | 0.5026 | 23.1 | 7710 | 158 | — |
| 19 | `DOC-81ae205a3b0bf16f` | yes | 0.2480 | 23.5 | 2515 | 158 | — |
| 20 | `DOC-9467462d9bb34f8e` | yes | 0.5417 | 23.3 | 5345 | 158 | — |
| 21 | `DOC-0a262afc80c73247` | yes | 0.1136 | 25.4 | 3124 | 156 | — |
| 22 | `DOC-732b812b7d9d9653` | yes | 0.8889 | 25.4 | 5572 | 165 | — |
| 23 | `DOC-d015968793450753` | yes | 0.8056 | 27.0 | 5082 | 166 | — |
| 24 | `DOC-bfa92eb6c72569ee` | yes | 0.1184 | 13.5 | 3771 | 158 | — |
| 25 | `DOC-4dc719baa790a79c` | yes | 0.6667 | 27.7 | 2669 | 167 | — |
| 26 | `DOC-0a8eb16fff7e67ca` | yes | 0.3590 | 13.4 | 5246 | 159 | — |
| 27 | `DOC-e6906e59f9bd74ca` | yes | 0.6200 | 10.0 | 2978 | 160 | — |
| 28 | `DOC-80e90a37bb750a3c` | yes | 0.1495 | 13.5 | 2776 | 167 | — |
| 29 | `DOC-606242f2919653a4` | yes | 0.2332 | 9.0 | 5253 | 160 | — |
| 30 | `DOC-dfe42f3747f299e6` | yes | 0.7500 | 7.3 | 5870 | 158 | — |
| 31 | `DOC-d4dfbfe8049d41f9` | yes | 0.4934 | 9.7 | 3856 | 175 | — |
| 32 | `DOC-27bbad54b6fd107e` | yes | 0.8333 | 6.5 | 2871 | 182 | — |
| 33 | `DOC-a973ebf005e0e785` | yes | 0.4278 | 15.4 | 6146 | 234 | — |
| 34 | `DOC-fc9f56d999bd7566` | yes | 0.6667 | 30.1 | 2509 | 184 | — |
| 35 | `DOC-1e8e3ce47882ae71` | yes | 0.1485 | 30.8 | 3063 | 198 | — |
| 36 | `DOC-41b53ea487b84955` | yes | 0.7500 | 32.1 | 4617 | 228 | — |
| 37 | `DOC-a040ac19abb88fec` | yes | 0.4097 | 33.0 | 2206 | 141 | — |
| 38 | `DOC-91f89b9c0d285ac7` | yes | 0.6667 | 33.3 | 6902 | 126 | — |
| 39 | `DOC-204c3c7c0ba021cd` | yes | 0.4746 | 33.2 | 2226 | 133 | — |
| 40 | `DOC-2819b889b134ea01` | yes | 0.7500 | 33.6 | 5344 | 149 | — |
| 41 | `DOC-e478fa89043a29e3` | yes | 0.8205 | 34.0 | 2910 | 151 | — |
| 42 | `DOC-2338d194d5250def` | yes | 0.4867 | 15.0 | 5258 | 126 | — |
| 43 | `DOC-ffb48271e0a5e812` | yes | 0.6667 | 20.0 | 5344 | 144 | — |
| 44 | `DOC-78f2456f571403a9` | yes | 0.1531 | 17.1 | 2345 | 144 | — |
| 45 | `DOC-37152a33cfb70d37` | yes | 0.4103 | 20.4 | 2902 | 161 | — |
| 46 | `DOC-00193d0c070747e6` | yes | 0.7143 | 20.7 | 3225 | 173 | — |
| 47 | `DOC-866139125545b36a` | yes | 0.7733 | 15.9 | 5397 | 161 | — |
| 48 | `DOC-842215e36884da89` | yes | 0.2467 | 15.6 | 5226 | 161 | — |
| 49 | `DOC-f21f3dadebb121e3` | yes | 0.7843 | 20.8 | 3308 | 180 | — |
| 50 | `DOC-d0aebe650be3e512` | yes | 0.4976 | 13.3 | 2405 | 163 | — |

_Generated 2026-10-12T16:25:55+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-corporate-records-specialist-awq-2l4-c32.card.json`._
