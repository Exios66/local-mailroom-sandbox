# Run report — `sand42-50-contracts-specialist-awq-2l4-c8`

Dated cell stem: `RUN-50-CONTRACTS-AWQ-2L4-C8`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-contracts-specialist-awq-2l4-c8` |
| task / agent | `contracts_specialist` |
| prompt | `contracts_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **8** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `c1b846e76dbc48058acd686ffe6e284fbc73af4ead4cc0cc0dc45c7d600024e5` |
| dataset fingerprint | `83eb6b1f2c7e` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **49 / 1 / 50** |
| **overall_extraction_score** | **0.558441** |
| schema_valid_rate | 1.000000 |
| error_count | 1 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 981.453 |
| gpu_seconds | 981.807 |
| estimated GPU cost | 0.436359 |
| **GPU $/doc** | **0.00890529** |
| latency p50 / max (s) | 76.472742 / 802.849225 |
| prompt / completion tokens | 755259 / 119420 |
| concurrency speedup (Σlat/wall) | 5.60 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-a9850db362f57916` | True | — | 28.9 | 6764 | 897 | None |
| 2 | `DOC-6b4cc54c8c4d796f` | True | — | 29.9 | 4015 | 918 | None |
| 3 | `DOC-3c07c9ccd9a01d6e` | True | 0.705900 | 34.1 | 7428 | 994 | None |
| 4 | `DOC-f5a54932794ef16e` | True | 0.666700 | 49.4 | 5302 | 1146 | None |
| 5 | `DOC-b1aba7df0380a1b2` | True | — | 78.9 | 5032 | 1945 | None |
| 6 | `DOC-fc9671ccde642e8d` | True | — | 86.5 | 7936 | 2087 | None |
| 7 | `DOC-6671a684f52f82a9` | True | 0.689700 | 59.3 | 11320 | 1579 | None |
| 8 | `DOC-03529267ee75444d` | True | 0.588200 | 72.0 | 10583 | 1824 | None |
| 9 | `DOC-385a86c69f8e562c` | True | 0.666700 | 88.5 | 6560 | 2261 | None |
| 10 | `DOC-0812d9d3e2b1baa0` | True | 0.615400 | 81.6 | 18679 | 2091 | None |
| 11 | `DOC-593f2c6de770b84c` | True | 0.666700 | 51.0 | 9228 | 1227 | None |
| 12 | `DOC-b87880882e5fe354` | True | — | 163.1 | 19278 | 4037 | None |
| 13 | `DOC-0752e0811f5f5eb7` | True | 0.333300 | 181.4 | 41619 | 4486 | None |
| 14 | `DOC-4fb6419e37bff201` | True | 0.769200 | 118.5 | 22234 | 2931 | None |
| 15 | `DOC-e235bc9735f96335` | True | 0.600000 | 144.1 | 10699 | 3684 | None |
| 16 | `DOC-f8b0d4bcbac60ca2` | True | 0.666700 | 46.9 | 3824 | 1120 | None |
| 17 | `DOC-9cee2e10b449a71c` | True | 0.687500 | 79.2 | 21752 | 2095 | None |
| 18 | `DOC-81c4ce12d907380c` | True | 0.571400 | 97.5 | 7047 | 2632 | None |
| 19 | `DOC-812192e392d8d410` | True | 0.500000 | 95.7 | 5551 | 2620 | None |
| 20 | `DOC-b83763aeff114369` | True | 0.758600 | 63.9 | 7446 | 1746 | None |
| 21 | `DOC-e29140d2e8e989be` | True | 0.666700 | 279.9 | 45485 | 7389 | None |
| 22 | `DOC-9a36838df2878b37` | True | 0.538500 | 74.4 | 8142 | 1924 | None |
| 23 | `DOC-73055dbb1e9f5f2f` | True | 0.545500 | 293.0 | 49409 | 7630 | None |
| 24 | `DOC-035731e655e67aab` | True | 0.631600 | 60.4 | 5207 | 1446 | None |
| 25 | `DOC-e4272758b561f8cd` | False | — | 304.3 | — | — | LengthFinishReasonError: Could not parse response content as the length limit was reached - CompletionUsage(completion_tokens=8192, prompt_tokens=6987, total_tokens=15179, completion_tokens_details=None, prompt_tokens_details=None) |
| 26 | `DOC-e998c563b82122b9` | True | 0.526300 | 53.0 | 10006 | 1272 | None |
| 27 | `DOC-27b649fe2f6fae8e` | True | 0.875000 | 51.0 | 5464 | 1219 | None |
| 28 | `DOC-1e22a2d4068b8650` | True | 0.714300 | 67.1 | 7587 | 1671 | None |
| 29 | `DOC-1266801f2faad19f` | True | 0.708300 | 167.8 | 33383 | 4156 | None |
| 30 | `DOC-70f90b46b2c4f1a6` | True | 0.857100 | 15.1 | 3154 | 392 | None |
| 31 | `DOC-2b510409d3b9a4a6` | True | 0.413800 | 395.8 | 9632 | 2055 | None |
| 32 | `DOC-dfb4e69a3ab10dc9` | True | 0.769200 | 31.7 | 7378 | 801 | None |
| 33 | `DOC-1ddc9333769d27e4` | True | 0.500000 | 41.0 | 4450 | 984 | None |
| 34 | `DOC-8993ad1085e08bd0` | True | 0.700000 | 91.3 | 22402 | 2184 | None |
| 35 | `DOC-fe06800cc62e5e19` | True | 0.647100 | 38.8 | 8619 | 1158 | None |
| 36 | `DOC-186145066ab191fa` | True | 0.333300 | 27.0 | 3718 | 886 | None |
| 37 | `DOC-62b300182901e850` | True | 0.297900 | 119.8 | 33346 | 3153 | None |
| 38 | `DOC-472f423cdf0819ef` | True | 0.750000 | 58.2 | 4656 | 1297 | None |
| 39 | `DOC-4b57f485708ab60b` | True | 0.600000 | 34.4 | 6639 | 1372 | None |
| 40 | `DOC-e0d31c39359cb803` | True | 0.631600 | 44.5 | 6879 | 947 | None |
| 41 | `DOC-f45b328fd8a54c8b` | True | 0.761900 | 63.1 | 4608 | 1340 | None |
| 42 | `DOC-712c3f92a0a56b77` | True | 0.571400 | 267.9 | 56227 | 6330 | None |
| 43 | `DOC-c9d4c4f8ff433527` | True | 0.705900 | 127.5 | 7730 | 2856 | None |
| 44 | `DOC-01849fa3020a5ac1` | True | 0.500000 | 35.1 | 4173 | 1043 | None |
| 45 | `DOC-be1eccde5bae9c82` | True | 0.500000 | 76.5 | 9330 | 2221 | None |
| 46 | `DOC-e218d39bb2f3c5ef` | True | 0.533300 | 103.6 | 19923 | 2583 | None |
| 47 | `DOC-dfd20f94bb76b6e4` | True | 0.545500 | 92.5 | 21000 | 2800 | None |
| 48 | `DOC-dbe52fd78e44b0ef` | True | 0.869600 | 87.4 | 18750 | 2434 | None |
| 49 | `DOC-8f737e9fec8f24f0` | True | 0.545500 | 246.4 | 35815 | 6494 | None |
| 50 | `DOC-53e364f030a30b5c` | True | 0.638300 | 802.8 | 69850 | 7063 | None |
