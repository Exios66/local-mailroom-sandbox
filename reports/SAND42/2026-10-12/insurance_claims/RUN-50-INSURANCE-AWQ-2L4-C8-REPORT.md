# Run report — `sand42-50-insurance-claims-specialist-awq-2l4-c8`

Dated cell stem: `RUN-50-INSURANCE-AWQ-2L4-C8`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-insurance-claims-specialist-awq-2l4-c8` |
| task / agent | `insurance_claims_specialist` |
| prompt | `insurance_claims_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **8** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `9c87cb29fa61abbfab9d2fe5201b5101fd7498b483d22219cb9ffbfd1eda4177` |
| dataset fingerprint | `f4fdcee45e7f` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.670326** |
| schema_valid_rate | 0.300000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 119.725 |
| gpu_seconds | 120.063 |
| estimated GPU cost | 0.053361 |
| **GPU $/doc** | **0.00106722** |
| latency p50 / max (s) | 11.397067 / 49.897795 |
| prompt / completion tokens | 165315 / 20870 |
| concurrency speedup (Σlat/wall) | 5.38 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-2aea7f6dc44b37e1` | True | 0.774100 | 11.2 | 2835 | 357 | None |
| 2 | `DOC-2a55a2b5324659f8` | True | 0.809800 | 11.2 | 2865 | 352 | None |
| 3 | `DOC-158c0b74df673b81` | True | 0.644200 | 11.2 | 2939 | 369 | None |
| 4 | `DOC-2a33a6c34834e769` | True | 0.629800 | 11.6 | 2953 | 337 | None |
| 5 | `DOC-629fb5789dfd10ca` | True | 0.797900 | 12.5 | 2836 | 348 | None |
| 6 | `DOC-e2a58ed4c02470c0` | True | 0.781200 | 13.4 | 2835 | 365 | None |
| 7 | `DOC-e7c196f508907c6f` | True | 0.783000 | 13.4 | 2834 | 363 | None |
| 8 | `DOC-991cb72cb83c7a6c` | True | 0.644200 | 13.5 | 2941 | 372 | None |
| 9 | `DOC-9ba0a3d4c680b976` | True | 0.639800 | 10.0 | 2982 | 334 | None |
| 10 | `DOC-9a6f58879fcb3367` | True | 0.644200 | 10.3 | 2946 | 359 | None |
| 11 | `DOC-968c9605eab0a87d` | True | 0.644200 | 11.0 | 2942 | 350 | None |
| 12 | `DOC-997823d9605a4a59` | True | 0.644200 | 11.3 | 2973 | 362 | None |
| 13 | `DOC-ef79520b2f50217b` | True | 0.689200 | 11.0 | 3138 | 382 | None |
| 14 | `DOC-5c4e70db54374e72` | True | 0.687400 | 11.5 | 3151 | 399 | None |
| 15 | `DOC-2435c398b95844bc` | True | 0.687900 | 13.7 | 3080 | 478 | None |
| 16 | `DOC-5b1e8e2aed95c089` | True | 0.682500 | 15.9 | 3123 | 543 | None |
| 17 | `DOC-00d28a1df0e3f6ba` | True | 0.697100 | 7.5 | 2812 | 259 | None |
| 18 | `DOC-9051d4cf8d7ab452` | True | 0.710000 | 10.8 | 3115 | 352 | None |
| 19 | `DOC-728d06b610b25244` | True | 0.704300 | 7.5 | 2804 | 273 | None |
| 20 | `DOC-e4b1466ee8d1ff19` | True | 0.703700 | 11.5 | 3113 | 399 | None |
| 21 | `DOC-5060222215c75aa6` | True | 0.674500 | 8.9 | 2801 | 297 | None |
| 22 | `DOC-00ccdcb0154a8629` | True | 0.622800 | 8.6 | 2812 | 281 | None |
| 23 | `DOC-f5e6c0de5f1d8593` | True | 0.648700 | 9.2 | 2812 | 309 | None |
| 24 | `DOC-d8df43ed4d8faf89` | True | 0.688800 | 15.4 | 3107 | 529 | None |
| 25 | `DOC-c34baab0b5fe378a` | True | 0.689900 | 8.7 | 2807 | 280 | None |
| 26 | `DOC-cbfcdb6f42cf2ae6` | True | 0.687200 | 8.6 | 2806 | 275 | None |
| 27 | `DOC-6f6fc9762418a70f` | True | 0.704800 | 9.2 | 2811 | 294 | None |
| 28 | `DOC-29e384939c31d44a` | True | 0.613100 | 9.4 | 3010 | 306 | None |
| 29 | `DOC-2d7cc160b78a69c5` | True | 0.644200 | 11.0 | 2979 | 378 | None |
| 30 | `DOC-0cdb706a0cdbe3b6` | True | 0.626500 | 10.8 | 2981 | 386 | None |
| 31 | `DOC-87c0c53132830a6c` | True | 0.626500 | 11.3 | 2993 | 397 | None |
| 32 | `DOC-4e21681f375a247d` | True | 0.642600 | 11.4 | 2985 | 400 | None |
| 33 | `DOC-27b23fd94cc70d9d` | True | 0.605200 | 9.9 | 2890 | 353 | None |
| 34 | `DOC-364435343e0a2250` | True | 0.647400 | 11.4 | 3020 | 393 | None |
| 35 | `DOC-93c8d133c296d536` | True | 0.566300 | 9.1 | 2879 | 325 | None |
| 36 | `DOC-3ae2dc5d624e2120` | True | 0.599900 | 10.8 | 2871 | 347 | None |
| 37 | `DOC-7bd9dbc1b39ad41d` | True | 0.603100 | 19.9 | 3171 | 626 | None |
| 38 | `DOC-91da307f80433ae3` | True | 0.579600 | 12.1 | 2894 | 358 | None |
| 39 | `DOC-44bcd388c4710b71` | True | 0.566300 | 11.6 | 2884 | 346 | None |
| 40 | `DOC-90338506fc792f32` | True | 0.582300 | 13.5 | 2882 | 372 | None |
| 41 | `DOC-164aa748f84cef54` | True | 0.581000 | 13.6 | 2911 | 382 | None |
| 42 | `DOC-73d64bbeb296bd95` | True | 0.619800 | 18.6 | 4524 | 542 | None |
| 43 | `DOC-7f1f866b022cee63` | True | 0.787300 | 18.1 | 4985 | 510 | None |
| 44 | `DOC-384665a051d0fcd6` | True | 0.679800 | 17.6 | 5208 | 532 | None |
| 45 | `DOC-85314478b81710d9` | True | 0.628700 | 13.9 | 5285 | 426 | None |
| 46 | `DOC-ab18f15b7a51f1ab` | True | 0.749000 | 15.6 | 5538 | 459 | None |
| 47 | `DOC-1076ac5b4b0df386` | True | 0.656900 | 13.6 | 4482 | 429 | None |
| 48 | `DOC-6dcc0b9ba494c25b` | True | 0.817800 | 15.9 | 5114 | 570 | None |
| 49 | `DOC-5b97ae3f8558703c` | True | 0.691200 | 16.4 | 4565 | 599 | None |
| 50 | `DOC-02f77aa77391a8c2` | True | 0.686400 | 49.9 | 5091 | 1816 | None |
