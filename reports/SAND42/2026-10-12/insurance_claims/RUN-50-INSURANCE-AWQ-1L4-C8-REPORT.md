# Run report — `sand42-50-insurance-claims-specialist-awq-1l4-c8`

Dated cell stem: `RUN-50-INSURANCE-AWQ-1L4-C8`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-insurance-claims-specialist-awq-1l4-c8` |
| task / agent | `insurance_claims_specialist` |
| prompt | `insurance_claims_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **8** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `8f77e131022df5bb6cc49edf9d6e778d89e451b09b73fa9d7ca98b53d3647bb5` |
| dataset fingerprint | `f4fdcee45e7f` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.670864** |
| schema_valid_rate | 0.320000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 120.066 |
| gpu_seconds | 120.203 |
| estimated GPU cost | 0.026712 |
| **GPU $/doc** | **0.00053424** |
| latency p50 / max (s) | 13.401024 / 43.522901 |
| prompt / completion tokens | 165315 / 20586 |
| concurrency speedup (Σlat/wall) | 6.22 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-2a33a6c34834e769` | True | 0.629800 | 12.8 | 2953 | 337 | None |
| 2 | `DOC-2a55a2b5324659f8` | True | 0.809800 | 12.8 | 2865 | 346 | None |
| 3 | `DOC-629fb5789dfd10ca` | True | 0.794400 | 12.8 | 2836 | 345 | None |
| 4 | `DOC-158c0b74df673b81` | True | 0.644200 | 12.8 | 2939 | 350 | None |
| 5 | `DOC-e7c196f508907c6f` | True | 0.783000 | 14.0 | 2834 | 363 | None |
| 6 | `DOC-e2a58ed4c02470c0` | True | 0.785700 | 14.4 | 2835 | 366 | None |
| 7 | `DOC-991cb72cb83c7a6c` | True | 0.644200 | 15.4 | 2941 | 374 | None |
| 8 | `DOC-2aea7f6dc44b37e1` | True | 0.774100 | 16.1 | 2835 | 387 | None |
| 9 | `DOC-9ba0a3d4c680b976` | True | 0.639800 | 12.0 | 2982 | 334 | None |
| 10 | `DOC-997823d9605a4a59` | True | 0.639800 | 12.9 | 2973 | 355 | None |
| 11 | `DOC-968c9605eab0a87d` | True | 0.644200 | 13.1 | 2942 | 367 | None |
| 12 | `DOC-9a6f58879fcb3367` | True | 0.644200 | 14.0 | 2946 | 374 | None |
| 13 | `DOC-ef79520b2f50217b` | True | 0.689200 | 12.1 | 3138 | 382 | None |
| 14 | `DOC-2435c398b95844bc` | True | 0.687900 | 15.1 | 3080 | 469 | None |
| 15 | `DOC-5b1e8e2aed95c089` | True | 0.687600 | 18.0 | 3123 | 534 | None |
| 16 | `DOC-5c4e70db54374e72` | True | 0.676300 | 17.7 | 3151 | 535 | None |
| 17 | `DOC-00d28a1df0e3f6ba` | True | 0.697100 | 8.5 | 2812 | 259 | None |
| 18 | `DOC-9051d4cf8d7ab452` | True | 0.710000 | 12.3 | 3115 | 352 | None |
| 19 | `DOC-5060222215c75aa6` | True | 0.674500 | 9.7 | 2801 | 297 | None |
| 20 | `DOC-e4b1466ee8d1ff19` | True | 0.703700 | 13.8 | 3113 | 401 | None |
| 21 | `DOC-728d06b610b25244` | True | 0.704300 | 9.0 | 2804 | 273 | None |
| 22 | `DOC-00ccdcb0154a8629` | True | 0.622800 | 9.6 | 2812 | 281 | None |
| 23 | `DOC-f5e6c0de5f1d8593` | True | 0.716900 | 10.7 | 2812 | 307 | None |
| 24 | `DOC-d8df43ed4d8faf89` | True | 0.688800 | 18.4 | 3107 | 529 | None |
| 25 | `DOC-c34baab0b5fe378a` | True | 0.689900 | 10.6 | 2807 | 299 | None |
| 26 | `DOC-cbfcdb6f42cf2ae6` | True | 0.687200 | 10.0 | 2806 | 275 | None |
| 27 | `DOC-6f6fc9762418a70f` | True | 0.704800 | 10.4 | 2811 | 289 | None |
| 28 | `DOC-29e384939c31d44a` | True | 0.613100 | 10.9 | 3010 | 306 | None |
| 29 | `DOC-2d7cc160b78a69c5` | True | 0.644200 | 13.6 | 2979 | 396 | None |
| 30 | `DOC-0cdb706a0cdbe3b6` | True | 0.613100 | 10.3 | 2981 | 312 | None |
| 31 | `DOC-87c0c53132830a6c` | True | 0.626500 | 13.2 | 2993 | 397 | None |
| 32 | `DOC-4e21681f375a247d` | True | 0.642600 | 13.0 | 2985 | 400 | None |
| 33 | `DOC-27b23fd94cc70d9d` | True | 0.605200 | 11.4 | 2890 | 353 | None |
| 34 | `DOC-364435343e0a2250` | True | 0.647400 | 12.7 | 3020 | 393 | None |
| 35 | `DOC-3ae2dc5d624e2120` | True | 0.599900 | 11.6 | 2871 | 333 | None |
| 36 | `DOC-7bd9dbc1b39ad41d` | True | 0.603100 | 22.3 | 3171 | 625 | None |
| 37 | `DOC-93c8d133c296d536` | True | 0.566300 | 13.1 | 2879 | 325 | None |
| 38 | `DOC-91da307f80433ae3` | True | 0.579600 | 14.8 | 2894 | 358 | None |
| 39 | `DOC-44bcd388c4710b71` | True | 0.583700 | 16.2 | 2884 | 374 | None |
| 40 | `DOC-90338506fc792f32` | True | 0.582300 | 17.1 | 2882 | 372 | None |
| 41 | `DOC-164aa748f84cef54` | True | 0.589900 | 18.6 | 2911 | 403 | None |
| 42 | `DOC-73d64bbeb296bd95` | True | 0.619800 | 24.2 | 4524 | 544 | None |
| 43 | `DOC-7f1f866b022cee63` | True | 0.726100 | 22.1 | 4985 | 510 | None |
| 44 | `DOC-384665a051d0fcd6` | True | 0.679800 | 21.1 | 5208 | 501 | None |
| 45 | `DOC-85314478b81710d9` | True | 0.633200 | 17.2 | 5285 | 441 | None |
| 46 | `DOC-ab18f15b7a51f1ab` | True | 0.745900 | 21.0 | 5538 | 533 | None |
| 47 | `DOC-1076ac5b4b0df386` | True | 0.656900 | 15.6 | 4482 | 429 | None |
| 48 | `DOC-6dcc0b9ba494c25b` | True | 0.813300 | 17.8 | 5114 | 562 | None |
| 49 | `DOC-5b97ae3f8558703c` | True | 0.691200 | 16.0 | 4565 | 568 | None |
| 50 | `DOC-02f77aa77391a8c2` | True | 0.705900 | 43.5 | 5091 | 1371 | None |
