# Run report — `sand42-50-contracts-specialist-awq-2l4-c16`

Dated cell stem: `RUN-50-CONTRACTS-AWQ-2L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-contracts-specialist-awq-2l4-c16` |
| task / agent | `contracts_specialist` |
| prompt | `contracts_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **16** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `d78405fe6d28cd8b6dd97fa6d690aa8f8a2eaddb10a7aceafaa278d0b5d033f1` |
| dataset fingerprint | `83eb6b1f2c7e` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **49 / 1 / 50** |
| **overall_extraction_score** | **0.543951** |
| schema_valid_rate | 1.000000 |
| error_count | 1 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 1063.387 |
| gpu_seconds | 1063.696 |
| estimated GPU cost | 0.472754 |
| **GPU $/doc** | **0.00964804** |
| latency p50 / max (s) | 104.763310 / 973.089059 |
| prompt / completion tokens | 753520 / 144543 |
| concurrency speedup (Σlat/wall) | 7.78 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-6b4cc54c8c4d796f` | True | — | 49.7 | 4015 | 973 | None |
| 2 | `DOC-f5a54932794ef16e` | True | 0.631600 | 57.4 | 5302 | 1091 | None |
| 3 | `DOC-03529267ee75444d` | True | 0.533300 | 70.9 | 10583 | 1457 | None |
| 4 | `DOC-a9850db362f57916` | True | — | 75.4 | 6764 | 1025 | None |
| 5 | `DOC-b1aba7df0380a1b2` | True | — | 84.3 | 5032 | 1133 | None |
| 6 | `DOC-6671a684f52f82a9` | True | 0.642900 | 96.4 | 11320 | 1355 | None |
| 7 | `DOC-593f2c6de770b84c` | True | 0.833300 | 102.4 | 9228 | 1462 | None |
| 8 | `DOC-385a86c69f8e562c` | True | 0.666700 | 104.8 | 6560 | 1513 | None |
| 9 | `DOC-fc9671ccde642e8d` | True | — | 122.1 | 7936 | 1762 | None |
| 10 | `DOC-f8b0d4bcbac60ca2` | True | 0.666700 | 58.5 | 3824 | 1103 | None |
| 11 | `DOC-3c07c9ccd9a01d6e` | True | 0.777800 | 146.6 | 7428 | 2317 | None |
| 12 | `DOC-4fb6419e37bff201` | True | 0.758600 | 156.2 | 22234 | 3153 | None |
| 13 | `DOC-e4272758b561f8cd` | True | 0.666700 | 89.3 | 6987 | 1747 | None |
| 14 | `DOC-e235bc9735f96335` | True | 0.685700 | 175.3 | 10699 | 2802 | None |
| 15 | `DOC-0812d9d3e2b1baa0` | True | 0.434800 | 201.5 | 18679 | 3143 | None |
| 16 | `DOC-81c4ce12d907380c` | True | 0.571400 | 109.9 | 7047 | 1856 | None |
| 17 | `DOC-b83763aeff114369` | True | 0.615400 | 96.9 | 7446 | 1806 | None |
| 18 | `DOC-73055dbb1e9f5f2f` | True | 0.600000 | 187.6 | 49409 | 3342 | None |
| 19 | `DOC-812192e392d8d410` | True | 0.600000 | 157.8 | 5551 | 2644 | None |
| 20 | `DOC-e998c563b82122b9` | True | 0.555600 | 89.6 | 10006 | 1377 | None |
| 21 | `DOC-9a36838df2878b37` | True | 0.538500 | 132.3 | 8142 | 2130 | None |
| 22 | `DOC-0752e0811f5f5eb7` | True | 0.390200 | 279.8 | 41619 | 5826 | None |
| 23 | `DOC-70f90b46b2c4f1a6` | True | 0.666700 | 35.8 | 3154 | 632 | None |
| 24 | `DOC-27b649fe2f6fae8e` | True | 0.636400 | 94.9 | 5464 | 1567 | None |
| 25 | `DOC-035731e655e67aab` | True | 0.421100 | 147.1 | 5207 | 3299 | None |
| 26 | `DOC-1ddc9333769d27e4` | True | 0.571400 | 43.3 | 4450 | 1006 | None |
| 27 | `DOC-8993ad1085e08bd0` | True | 0.764700 | 101.9 | 22402 | 2397 | None |
| 28 | `DOC-9cee2e10b449a71c` | True | 0.810800 | 222.4 | 21752 | 3841 | None |
| 29 | `DOC-dfb4e69a3ab10dc9` | True | 0.666700 | 58.3 | 7378 | 881 | None |
| 30 | `DOC-2b510409d3b9a4a6` | True | 0.711100 | 290.2 | 21668 | 5421 | None |
| 31 | `DOC-1e22a2d4068b8650` | True | 0.714300 | 142.3 | 7587 | 2263 | None |
| 32 | `DOC-c9d4c4f8ff433527` | True | 0.555600 | 40.9 | 7730 | 916 | None |
| 33 | `DOC-472f423cdf0819ef` | True | 0.571400 | 51.9 | 4656 | 1223 | None |
| 34 | `DOC-4b57f485708ab60b` | True | 0.600000 | 36.6 | 6639 | 812 | None |
| 35 | `DOC-186145066ab191fa` | True | 0.461500 | 70.6 | 3718 | 1130 | None |
| 36 | `DOC-fe06800cc62e5e19` | True | 0.642900 | 92.2 | 8619 | 1505 | None |
| 37 | `DOC-f45b328fd8a54c8b` | True | 0.842100 | 74.5 | 4608 | 1282 | None |
| 38 | `DOC-e0d31c39359cb803` | True | 0.714300 | 72.5 | 6879 | 1684 | None |
| 39 | `DOC-b87880882e5fe354` | True | — | 416.5 | 19278 | 8382 | None |
| 40 | `DOC-01849fa3020a5ac1` | True | 0.363600 | 45.9 | 4173 | 1140 | None |
| 41 | `DOC-1266801f2faad19f` | True | 0.571400 | 277.2 | 33383 | 4811 | None |
| 42 | `DOC-dfd20f94bb76b6e4` | True | 0.625000 | 104.8 | 21000 | 2294 | None |
| 43 | `DOC-e218d39bb2f3c5ef` | True | 0.352900 | 190.3 | 19923 | 4230 | None |
| 44 | `DOC-62b300182901e850` | True | 0.350000 | 319.7 | 33346 | 6661 | None |
| 45 | `DOC-dbe52fd78e44b0ef` | True | 0.647100 | 234.0 | 18750 | 6172 | None |
| 46 | `DOC-712c3f92a0a56b77` | True | 0.684200 | 431.5 | 56227 | 9655 | None |
| 47 | `DOC-e29140d2e8e989be` | True | 0.411800 | 639.3 | 32801 | 4308 | None |
| 48 | `DOC-be1eccde5bae9c82` | False | — | 304.8 | — | — | LengthFinishReasonError: Could not parse response content as the length limit was reached - CompletionUsage(completion_tokens=8192, prompt_tokens=9330, total_tokens=17522, completion_tokens_details=None, prompt_tokens_details=None) |
| 49 | `DOC-8f737e9fec8f24f0` | True | 0.476200 | 424.5 | 23930 | 3438 | None |
| 50 | `DOC-53e364f030a30b5c` | True | 0.651200 | 973.1 | 82987 | 18576 | None |
