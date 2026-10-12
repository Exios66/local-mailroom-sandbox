# Run report — `sand42-50-contracts-specialist-awq-2l4-c32`

Dated cell stem: `RUN-50-CONTRACTS-AWQ-2L4-C32`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-contracts-specialist-awq-2l4-c32` |
| task / agent | `contracts_specialist` |
| prompt | `contracts_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **32** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `f11ad4ea08f3c19664adb26dea60a556982d0f6d74fe38a61b565224f56d7c18` |
| dataset fingerprint | `83eb6b1f2c7e` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.533642** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 1026.392 |
| gpu_seconds | 1026.601 |
| estimated GPU cost | 0.456267 |
| **GPU $/doc** | **0.00912534** |
| latency p50 / max (s) | 172.152698 / 1011.810562 |
| prompt / completion tokens | 765208 / 130896 |
| concurrency speedup (Σlat/wall) | 10.59 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-e4272758b561f8cd` | True | 0.642900 | 66.0 | 6987 | 933 | None |
| 2 | `DOC-fc9671ccde642e8d` | True | — | 68.0 | 7936 | 988 | None |
| 3 | `DOC-6b4cc54c8c4d796f` | True | — | 75.5 | 4015 | 724 | None |
| 4 | `DOC-f5a54932794ef16e` | True | 0.666700 | 78.3 | 5302 | 1140 | None |
| 5 | `DOC-385a86c69f8e562c` | True | 0.666700 | 79.1 | 6560 | 1156 | None |
| 6 | `DOC-70f90b46b2c4f1a6` | True | 0.750000 | 25.1 | 3154 | 505 | None |
| 7 | `DOC-a9850db362f57916` | True | — | 103.9 | 6764 | 1078 | None |
| 8 | `DOC-6671a684f52f82a9` | True | 0.640000 | 106.4 | 11320 | 1102 | None |
| 9 | `DOC-1e22a2d4068b8650` | True | 0.769200 | 110.3 | 7587 | 1104 | None |
| 10 | `DOC-f8b0d4bcbac60ca2` | True | 0.600000 | 116.0 | 3824 | 1204 | None |
| 11 | `DOC-035731e655e67aab` | True | 0.500000 | 121.3 | 5207 | 2027 | None |
| 12 | `DOC-03529267ee75444d` | True | 0.580600 | 131.6 | 10583 | 1370 | None |
| 13 | `DOC-e998c563b82122b9` | True | 0.526300 | 140.3 | 10006 | 1493 | None |
| 14 | `DOC-27b649fe2f6fae8e` | True | 0.666700 | 151.6 | 5464 | 1566 | None |
| 15 | `DOC-186145066ab191fa` | True | 0.363600 | 50.6 | 3718 | 867 | None |
| 16 | `DOC-0812d9d3e2b1baa0` | True | 0.470600 | 162.2 | 18679 | 2282 | None |
| 17 | `DOC-81c4ce12d907380c` | True | 0.720000 | 164.0 | 7047 | 1774 | None |
| 18 | `DOC-e0d31c39359cb803` | True | 0.666700 | 35.6 | 6879 | 495 | None |
| 19 | `DOC-3c07c9ccd9a01d6e` | True | 0.736800 | 173.7 | 7428 | 2894 | None |
| 20 | `DOC-fe06800cc62e5e19` | True | 0.509100 | 81.5 | 8619 | 1416 | None |
| 21 | `DOC-b1aba7df0380a1b2` | True | — | 189.9 | 5032 | 958 | None |
| 22 | `DOC-593f2c6de770b84c` | True | 0.666700 | 199.4 | 9228 | 1106 | None |
| 23 | `DOC-4b57f485708ab60b` | True | 0.600000 | 66.0 | 6639 | 1260 | None |
| 24 | `DOC-01849fa3020a5ac1` | True | 0.500000 | 39.4 | 4173 | 923 | None |
| 25 | `DOC-f45b328fd8a54c8b` | True | 0.588200 | 93.5 | 4608 | 1786 | None |
| 26 | `DOC-e235bc9735f96335` | True | 0.722200 | 222.4 | 10699 | 2510 | None |
| 27 | `DOC-812192e392d8d410` | True | 0.600000 | 237.1 | 5551 | 2607 | None |
| 28 | `DOC-62b300182901e850` | True | 0.428600 | 170.6 | 33346 | 3483 | None |
| 29 | `DOC-1ddc9333769d27e4` | True | 0.533300 | 163.6 | 4450 | 1051 | None |
| 30 | `DOC-8f737e9fec8f24f0` | True | 0.500000 | 166.9 | 35815 | 3480 | None |
| 31 | `DOC-9a36838df2878b37` | True | 0.666700 | 249.9 | 8142 | 2715 | None |
| 32 | `DOC-b83763aeff114369` | True | 0.642900 | 263.8 | 7446 | 2096 | None |
| 33 | `DOC-9cee2e10b449a71c` | True | 0.709700 | 288.6 | 21752 | 2640 | None |
| 34 | `DOC-472f423cdf0819ef` | True | 0.571400 | 195.1 | 4656 | 1191 | None |
| 35 | `DOC-c9d4c4f8ff433527` | True | 0.521700 | 189.6 | 7730 | 1118 | None |
| 36 | `DOC-b87880882e5fe354` | True | — | 314.8 | 19278 | 3613 | None |
| 37 | `DOC-dfb4e69a3ab10dc9` | True | 0.400000 | 224.2 | 7378 | 1735 | None |
| 38 | `DOC-4fb6419e37bff201` | True | 0.689700 | 325.7 | 22234 | 3380 | None |
| 39 | `DOC-8993ad1085e08bd0` | True | 0.777800 | 277.6 | 22402 | 2341 | None |
| 40 | `DOC-2b510409d3b9a4a6` | True | 0.645200 | 358.9 | 21668 | 4113 | None |
| 41 | `DOC-0752e0811f5f5eb7` | True | 0.421100 | 378.2 | 41619 | 4610 | None |
| 42 | `DOC-1266801f2faad19f` | True | 0.500000 | 379.0 | 33383 | 4191 | None |
| 43 | `DOC-dbe52fd78e44b0ef` | True | 0.818200 | 224.8 | 18750 | 2316 | None |
| 44 | `DOC-73055dbb1e9f5f2f` | True | 0.370400 | 393.7 | 49409 | 4488 | None |
| 45 | `DOC-be1eccde5bae9c82` | True | 0.476200 | 272.0 | 9330 | 3632 | None |
| 46 | `DOC-e218d39bb2f3c5ef` | True | 0.538500 | 305.6 | 19923 | 4400 | None |
| 47 | `DOC-dfd20f94bb76b6e4` | True | 0.720000 | 334.6 | 11041 | 1807 | None |
| 48 | `DOC-712c3f92a0a56b77` | True | 0.551700 | 502.4 | 56227 | 7326 | None |
| 49 | `DOC-e29140d2e8e989be` | True | 0.258100 | 786.0 | 21229 | 1974 | None |
| 50 | `DOC-53e364f030a30b5c` | True | 0.787900 | 1011.8 | 94991 | 25928 | None |
