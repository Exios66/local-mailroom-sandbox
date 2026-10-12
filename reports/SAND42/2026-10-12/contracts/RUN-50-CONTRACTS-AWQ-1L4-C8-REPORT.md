# Run report — `sand42-50-contracts-specialist-awq-1l4-c8`

Dated cell stem: `RUN-50-CONTRACTS-AWQ-1L4-C8`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-contracts-specialist-awq-1l4-c8` |
| task / agent | `contracts_specialist` |
| prompt | `contracts_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **8** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `b01173a2eacc23710ab86350a616c0277f8f2f59ac2c44c8a7e0ac367d82a885` |
| dataset fingerprint | `5344b28a3033` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.598814** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 1377.987 |
| gpu_seconds | 1378.143 |
| estimated GPU cost | 0.306254 |
| **GPU $/doc** | **0.00612508** |
| latency p50 / max (s) | 114.243562 / 1001.056539 |
| prompt / completion tokens | 816380 / 132358 |
| concurrency speedup (Σlat/wall) | 7.18 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-e235bc9735f96335` | True | 0.666700 | 55.3 | 10699 | 940 | None |
| 2 | `DOC-3c07c9ccd9a01d6e` | True | 0.800000 | 83.2 | 7428 | 1471 | None |
| 3 | `DOC-f5a54932794ef16e` | True | 0.750000 | 90.2 | 5302 | 1596 | None |
| 4 | `DOC-593f2c6de770b84c` | True | 0.666700 | 94.4 | 9228 | 1659 | None |
| 5 | `DOC-385a86c69f8e562c` | True | 0.666700 | 113.9 | 6560 | 1953 | None |
| 6 | `DOC-268df6c8fabb385a` | True | 0.666700 | 82.6 | 5201 | 1445 | None |
| 7 | `DOC-a7ea445212692b88` | True | 0.620700 | 114.6 | 9369 | 2001 | None |
| 8 | `DOC-eaa14fe106140524` | True | 0.416700 | 43.0 | 7001 | 948 | None |
| 9 | `DOC-4fb6419e37bff201` | True | 0.666700 | 246.2 | 22234 | 4485 | None |
| 10 | `DOC-e4272758b561f8cd` | True | 0.555600 | 73.6 | 6987 | 1442 | None |
| 11 | `DOC-0752e0811f5f5eb7` | True | 0.367300 | 287.1 | 41619 | 5347 | None |
| 12 | `DOC-cbc1f0d62edbb23e` | True | 0.545500 | 45.7 | 4155 | 944 | None |
| 13 | `DOC-2c3a9c3168cd0e3a` | True | 0.666700 | 37.1 | 3385 | 799 | None |
| 14 | `DOC-73055dbb1e9f5f2f` | True | 0.685700 | 233.1 | 49409 | 4517 | None |
| 15 | `DOC-f8b0d4bcbac60ca2` | True | 0.545500 | 47.9 | 3824 | 994 | None |
| 16 | `DOC-1843cfdaf5db1840` | True | 0.272700 | 117.6 | 7407 | 2446 | None |
| 17 | `DOC-81c4ce12d907380c` | True | 0.571400 | 110.9 | 7047 | 2040 | None |
| 18 | `DOC-812192e392d8d410` | True | 0.600000 | 105.0 | 5551 | 1974 | None |
| 19 | `DOC-9cee2e10b449a71c` | True | 0.687500 | 133.7 | 21752 | 2382 | None |
| 20 | `DOC-b83763aeff114369` | True | 0.642900 | 111.1 | 7446 | 1904 | None |
| 21 | `DOC-2b510409d3b9a4a6` | True | 0.333300 | 508.0 | 9632 | 1117 | None |
| 22 | `DOC-9a36838df2878b37` | True | 0.400000 | 159.9 | 8142 | 2454 | None |
| 23 | `DOC-035731e655e67aab` | True | 0.555600 | 164.3 | 5207 | 2773 | None |
| 24 | `DOC-e998c563b82122b9` | True | 0.526300 | 79.2 | 10006 | 1401 | None |
| 25 | `DOC-1e22a2d4068b8650` | True | 0.857100 | 71.9 | 7587 | 1478 | None |
| 26 | `DOC-e29140d2e8e989be` | True | 0.640000 | 671.4 | 33913 | 3993 | None |
| 27 | `DOC-70f90b46b2c4f1a6` | True | 0.666700 | 34.2 | 3154 | 623 | None |
| 28 | `DOC-27b649fe2f6fae8e` | True | 0.777800 | 75.6 | 5464 | 1345 | None |
| 29 | `DOC-712c3f92a0a56b77` | True | 0.628600 | 267.1 | 56227 | 4552 | None |
| 30 | `DOC-8993ad1085e08bd0` | True | 0.620700 | 95.6 | 22402 | 1710 | None |
| 31 | `DOC-1ddc9333769d27e4` | True | 0.615400 | 50.6 | 4450 | 946 | None |
| 32 | `DOC-dfb4e69a3ab10dc9` | True | 0.318200 | 61.3 | 7378 | 1303 | None |
| 33 | `DOC-1266801f2faad19f` | True | 0.588200 | 354.8 | 33383 | 6299 | None |
| 34 | `DOC-fe06800cc62e5e19` | True | 0.620700 | 82.8 | 8619 | 1742 | None |
| 35 | `DOC-472f423cdf0819ef` | True | 0.666700 | 212.2 | 4656 | 1037 | None |
| 36 | `DOC-53e364f030a30b5c` | True | 0.754100 | 728.5 | 94991 | 10611 | None |
| 37 | `DOC-c9d4c4f8ff433527` | True | 0.521700 | 158.4 | 7730 | 1301 | None |
| 38 | `DOC-62b300182901e850` | True | 0.666700 | 385.6 | 33346 | 2024 | None |
| 39 | `DOC-e0d31c39359cb803` | True | 0.588200 | 98.7 | 6879 | 835 | None |
| 40 | `DOC-d6b6b418dd211b76` | True | 0.620700 | 281.6 | 7293 | 3222 | None |
| 41 | `DOC-3f4003eb02433292` | True | 0.545500 | 136.8 | 4421 | 1952 | None |
| 42 | `DOC-a6f559e4010fc8d1` | True | 0.529400 | 1001.1 | 32594 | 3134 | None |
| 43 | `DOC-4b57f485708ab60b` | True | 0.600000 | 167.8 | 6639 | 2777 | None |
| 44 | `DOC-dbe52fd78e44b0ef` | True | 0.800000 | 109.9 | 18750 | 1896 | None |
| 45 | `DOC-01849fa3020a5ac1` | True | 0.500000 | 72.8 | 4173 | 1307 | None |
| 46 | `DOC-8f737e9fec8f24f0` | True | 0.545500 | 513.2 | 35815 | 6087 | None |
| 47 | `DOC-aca7df716d7eef00` | True | 0.666700 | 434.6 | 36448 | 5997 | None |
| 48 | `DOC-e218d39bb2f3c5ef` | True | 0.560000 | 220.8 | 19923 | 5096 | None |
| 49 | `DOC-dfd20f94bb76b6e4` | True | 0.536600 | 215.9 | 21000 | 4957 | None |
| 50 | `DOC-6b67382dcf833c5b` | True | 0.628600 | 259.5 | 24554 | 7102 | None |
