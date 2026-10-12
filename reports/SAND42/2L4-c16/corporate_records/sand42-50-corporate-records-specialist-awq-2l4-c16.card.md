# Corporate Records — 2× L4 · C16 · n=50

**Run:** `sand42-50-corporate-records-specialist-awq-2l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm-b` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-corporate-records-specialist-awq-2l4-c16` |
| GPUs / replicas | 2 |
| Concurrency | 16 (8 per replica) |
| Documents | 50 |
| Spec hash | aca0ec6a… |
| **Time** |  |
| Wall (busy) | 53.71 s |
| GPU seconds | 54.20 s |
| Cold boot | 0.30 s |
| **Cost** |  |
| Busy-window GPU $ | $0.023870 |
| Billed GPU $ | $0.024090 |
| Billed seconds | 54.20 s |
| Idle $ | $0.007396 (16.64 s) |
| Cost per document | $0.000482 |
| Cost per ok document | $0.000482 |
| Cost per 1M tokens | $0.1172 |
| **Tokens** |  |
| Prompt tokens | 197,319 |
| Completion tokens | 8,278 (4.0%) |
| Total tokens | 205,597 |
| Tokens per document | 4,112 |
| Per document: instructions + template | 2,090 (50.8%) |
| Per document: document text | 1,856 (45.1%) |
| Per document: output | 166 (4.0%) |
| Instruction tokens per model call | 2,090 over 50 calls |
| Token split basis | fit across documents, 4.21 chars/token |
| Completion p95 / max (ok docs) | 213 / 234 |
| **Throughput** |  |
| Tokens / second | 3,828.1 |
| Tokens / second per L4 | 1,914.0 |
| Documents / minute | 55.86 |
| **Latency (per document, ok rows)** |  |
| Mean | 11.86 s |
| p50 | 11.19 s |
| p95 | 19.07 s |
| Max | 21.20 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 11.04× of 16 |
| Slot occupancy | 69.0% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 26 / 24 |
| Mean TTFT per replica | 1.652 s / 1.447 s |
| Prefix-cache hit per replica | 48.5% / 51.4% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 18 samples · serving-replica nvidia-smi |
| GPU utilization | 65.4 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 65.6 % — **below the 90% gate (issue #128)** |
| GPU power draw | 59.8 W (min 31.4 / max 72.8) of 72 W cap |
| GPU memory bandwidth | 52.3 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,499 MHz (min 975 / max 2,040) |
| GPU temperature | 74.4 C (min 62.0 / max 80.0) |
| GPU memory used | 19,994 MiB (min 19,992 / max 19,996) |
| **Quality** |  |
| Overall extraction score | 0.4980 (sd 0.247) |
| Score min / max | 0.0635 / 0.8889 |
| Scoring method | `suite` |
| Schema-valid rate | 0.98 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Corporate Records run dashboard](sand42-50-corporate-records-specialist-awq-2l4-c16.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-6790430ae2a6c724` | yes | 0.1846 | 11.0 | 4477 | 143 | — |
| 2 | `DOC-a040ac19abb88fec` | yes | 0.4097 | 11.0 | 2206 | 141 | — |
| 3 | `DOC-0a262afc80c73247` | yes | 0.1136 | 11.0 | 3124 | 153 | — |
| 4 | `DOC-81ae205a3b0bf16f` | yes | 0.2480 | 11.2 | 2515 | 158 | — |
| 5 | `DOC-12a6d4cd092cf66d` | yes | 0.5026 | 11.2 | 7710 | 158 | — |
| 6 | `DOC-0f56fe8db6df01bd` | yes | 0.0635 | 11.3 | 5368 | 161 | — |
| 7 | `DOC-020d77c0107d273d` | yes | 0.4722 | 13.5 | 2302 | 203 | — |
| 8 | `DOC-c4c9c37a96291975` | yes | 0.0813 | 16.1 | 2424 | 136 | — |
| 9 | `DOC-91f89b9c0d285ac7` | yes | 0.6667 | 16.1 | 6902 | 129 | — |
| 10 | `DOC-9ca44c7926a47ede` | yes | 0.5024 | 16.1 | 2292 | 140 | — |
| 11 | `DOC-fbcdd16e24f143ac` | yes | 0.1582 | 16.5 | 2456 | 155 | — |
| 12 | `DOC-e545bbd5f5ea61b6` | yes | 0.3636 | 16.6 | 2788 | 158 | — |
| 13 | `DOC-e077f1f7e80e1e04` | yes | 0.1624 | 7.4 | 4043 | 153 | — |
| 14 | `DOC-f134b9491efc5c57` | yes | 0.7949 | 7.3 | 2865 | 158 | — |
| 15 | `DOC-732b812b7d9d9653` | yes | 0.8889 | 18.8 | 5572 | 165 | — |
| 16 | `DOC-01054efd0980066b` | yes | 0.8222 | 19.1 | 5122 | 159 | — |
| 17 | `DOC-b3ad98e5530dfeaf` | yes | 0.2820 | 9.4 | 2521 | 182 | — |
| 18 | `DOC-2819b889b134ea01` | yes | 0.7500 | 20.9 | 5344 | 175 | — |
| 19 | `DOC-68d5a8753fcc3675` | yes | 0.4405 | 21.2 | 5671 | 189 | — |
| 20 | `DOC-9376c6bfa6779d5e` | yes | 0.4822 | 11.4 | 2200 | 150 | — |
| 21 | `DOC-fc9f56d999bd7566` | yes | 0.6667 | 9.2 | 2509 | 184 | — |
| 22 | `DOC-2f19002c84083aa8` | yes | 0.4363 | 11.5 | 5200 | 157 | — |
| 23 | `DOC-474a0002b4c03be1` | yes | 0.8205 | 9.4 | 2938 | 150 | — |
| 24 | `DOC-d015968793450753` | yes | 0.8056 | 10.2 | 5082 | 166 | — |
| 25 | `DOC-1e8e3ce47882ae71` | yes | 0.1485 | 15.6 | 3063 | 200 | — |
| 26 | `DOC-b832b5eaa2b4848c` | yes | 0.1068 | 8.4 | 2762 | 157 | — |
| 27 | `DOC-bfa92eb6c72569ee` | yes | 0.4518 | 7.8 | 3771 | 160 | — |
| 28 | `DOC-37152a33cfb70d37` | yes | 0.4103 | 7.3 | 2902 | 170 | — |
| 29 | `DOC-e478fa89043a29e3` | yes | 0.8205 | 13.6 | 2910 | 151 | — |
| 30 | `DOC-0a8eb16fff7e67ca` | yes | 0.6923 | 7.2 | 5246 | 150 | — |
| 31 | `DOC-41b53ea487b84955` | yes | 0.7500 | 11.8 | 4617 | 233 | — |
| 32 | `DOC-a5fd7fe18b094f20` | yes | 0.8485 | 13.8 | 5919 | 149 | — |
| 33 | `DOC-204c3c7c0ba021cd` | yes | 0.4746 | 14.2 | 2226 | 152 | — |
| 34 | `DOC-9467462d9bb34f8e` | yes | 0.5417 | 15.1 | 5345 | 161 | — |
| 35 | `DOC-4dc719baa790a79c` | yes | 0.6667 | 18.5 | 2669 | 190 | — |
| 36 | `DOC-f21f3dadebb121e3` | yes | 0.7843 | 9.2 | 3308 | 180 | — |
| 37 | `DOC-78f2456f571403a9` | yes | 0.1809 | 8.3 | 2345 | 165 | — |
| 38 | `DOC-00193d0c070747e6` | yes | 0.7143 | 14.5 | 3225 | 177 | — |
| 39 | `DOC-ffb48271e0a5e812` | yes | 0.6667 | 12.8 | 5344 | 145 | — |
| 40 | `DOC-2338d194d5250def` | yes | 0.4867 | 6.5 | 5258 | 128 | — |
| 41 | `DOC-d4dfbfe8049d41f9` | yes | 0.4907 | 8.4 | 3856 | 179 | — |
| 42 | `DOC-842215e36884da89` | yes | 0.2467 | 7.0 | 5226 | 164 | — |
| 43 | `DOC-e6906e59f9bd74ca` | yes | 0.6200 | 10.3 | 2978 | 162 | — |
| 44 | `DOC-d0aebe650be3e512` | yes | 0.4976 | 4.7 | 2405 | 163 | — |
| 45 | `DOC-a973ebf005e0e785` | yes | 0.4278 | 15.7 | 6146 | 234 | — |
| 46 | `DOC-606242f2919653a4` | yes | 0.2332 | 8.4 | 5253 | 159 | — |
| 47 | `DOC-866139125545b36a` | yes | 0.7733 | 10.3 | 5397 | 180 | — |
| 48 | `DOC-dfe42f3747f299e6` | yes | 0.7500 | 8.4 | 5870 | 164 | — |
| 49 | `DOC-80e90a37bb750a3c` | yes | 0.1654 | 12.2 | 2776 | 213 | — |
| 50 | `DOC-27bbad54b6fd107e` | yes | 0.8333 | 5.8 | 2871 | 169 | — |

_Generated 2026-10-12T06:53:30+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-corporate-records-specialist-awq-2l4-c16.card.json`._
