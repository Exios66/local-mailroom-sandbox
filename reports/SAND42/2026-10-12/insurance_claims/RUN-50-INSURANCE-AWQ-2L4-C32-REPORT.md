# Run report — `sand42-50-insurance-claims-specialist-awq-2l4-c32`

Dated cell stem: `RUN-50-INSURANCE-AWQ-2L4-C32`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-insurance-claims-specialist-awq-2l4-c32` |
| task / agent | `insurance_claims_specialist` |
| prompt | `insurance_claims_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **32** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `676fd83f131d1e934335e7cf50d430c187ff134877993d5c13d4936caef819df` |
| dataset fingerprint | `f4fdcee45e7f` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.670142** |
| schema_valid_rate | 0.300000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 74.555 |
| gpu_seconds | 74.819 |
| estimated GPU cost | 0.033253 |
| **GPU $/doc** | **0.00066506** |
| latency p50 / max (s) | 28.757662 / 44.675364 |
| prompt / completion tokens | 165315 / 20534 |
| concurrency speedup (Σlat/wall) | 17.75 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-e7c196f508907c6f` | True | 0.783000 | 10.9 | 2834 | 362 | None |
| 2 | `DOC-2a55a2b5324659f8` | True | 0.809800 | 10.9 | 2865 | 345 | None |
| 3 | `DOC-d8df43ed4d8faf89` | True | 0.688800 | 14.9 | 3107 | 522 | None |
| 4 | `DOC-cbfcdb6f42cf2ae6` | True | 0.694600 | 15.7 | 2806 | 286 | None |
| 5 | `DOC-c34baab0b5fe378a` | True | 0.689900 | 15.7 | 2807 | 285 | None |
| 6 | `DOC-00ccdcb0154a8629` | True | 0.622800 | 16.2 | 2812 | 281 | None |
| 7 | `DOC-5060222215c75aa6` | True | 0.741200 | 17.1 | 2801 | 296 | None |
| 8 | `DOC-29e384939c31d44a` | True | 0.613100 | 17.7 | 3010 | 306 | None |
| 9 | `DOC-2a33a6c34834e769` | True | 0.629800 | 19.5 | 2953 | 338 | None |
| 10 | `DOC-629fb5789dfd10ca` | True | 0.797900 | 20.0 | 2836 | 349 | None |
| 11 | `DOC-968c9605eab0a87d` | True | 0.644200 | 20.9 | 2942 | 367 | None |
| 12 | `DOC-e2a58ed4c02470c0` | True | 0.785700 | 21.2 | 2835 | 366 | None |
| 13 | `DOC-9a6f58879fcb3367` | True | 0.644200 | 21.8 | 2946 | 374 | None |
| 14 | `DOC-ef79520b2f50217b` | True | 0.689200 | 22.7 | 3138 | 382 | None |
| 15 | `DOC-2aea7f6dc44b37e1` | True | 0.774100 | 23.0 | 2835 | 387 | None |
| 16 | `DOC-2d7cc160b78a69c5` | True | 0.644200 | 23.5 | 2979 | 396 | None |
| 17 | `DOC-4e21681f375a247d` | True | 0.618800 | 14.6 | 2985 | 371 | None |
| 18 | `DOC-5b1e8e2aed95c089` | True | 0.689600 | 29.0 | 3123 | 547 | None |
| 19 | `DOC-728d06b610b25244` | True | 0.704300 | 30.0 | 2804 | 273 | None |
| 20 | `DOC-5c4e70db54374e72` | True | 0.676300 | 31.0 | 3151 | 590 | None |
| 21 | `DOC-3ae2dc5d624e2120` | True | 0.599900 | 15.2 | 2871 | 338 | None |
| 22 | `DOC-7bd9dbc1b39ad41d` | True | 0.603100 | 31.2 | 3171 | 588 | None |
| 23 | `DOC-f5e6c0de5f1d8593` | True | 0.648700 | 31.6 | 2812 | 309 | None |
| 24 | `DOC-91da307f80433ae3` | True | 0.579600 | 15.7 | 2894 | 367 | None |
| 25 | `DOC-00d28a1df0e3f6ba` | True | 0.697100 | 32.4 | 2812 | 260 | None |
| 26 | `DOC-90338506fc792f32` | True | 0.595600 | 15.6 | 2882 | 367 | None |
| 27 | `DOC-9ba0a3d4c680b976` | True | 0.639800 | 34.0 | 2982 | 334 | None |
| 28 | `DOC-9051d4cf8d7ab452` | True | 0.710000 | 35.6 | 3115 | 352 | None |
| 29 | `DOC-6f6fc9762418a70f` | True | 0.704800 | 37.3 | 2811 | 291 | None |
| 30 | `DOC-158c0b74df673b81` | True | 0.644200 | 38.2 | 2939 | 362 | None |
| 31 | `DOC-1076ac5b4b0df386` | True | 0.656900 | 14.6 | 4482 | 428 | None |
| 32 | `DOC-ab18f15b7a51f1ab` | True | 0.741400 | 17.0 | 5538 | 486 | None |
| 33 | `DOC-73d64bbeb296bd95` | True | 0.624500 | 20.2 | 4524 | 531 | None |
| 34 | `DOC-991cb72cb83c7a6c` | True | 0.644200 | 40.6 | 2941 | 374 | None |
| 35 | `DOC-997823d9605a4a59` | True | 0.644200 | 42.1 | 2973 | 363 | None |
| 36 | `DOC-0cdb706a0cdbe3b6` | True | 0.613100 | 42.1 | 2981 | 379 | None |
| 37 | `DOC-e4b1466ee8d1ff19` | True | 0.703700 | 42.4 | 3113 | 403 | None |
| 38 | `DOC-87c0c53132830a6c` | True | 0.626500 | 42.6 | 2993 | 410 | None |
| 39 | `DOC-5b97ae3f8558703c` | True | 0.691200 | 14.4 | 4565 | 484 | None |
| 40 | `DOC-2435c398b95844bc` | True | 0.687900 | 44.7 | 3080 | 453 | None |
| 41 | `DOC-93c8d133c296d536` | True | 0.566300 | 31.0 | 2879 | 325 | None |
| 42 | `DOC-27b23fd94cc70d9d` | True | 0.605200 | 32.7 | 2890 | 362 | None |
| 43 | `DOC-44bcd388c4710b71` | True | 0.566300 | 30.3 | 2884 | 346 | None |
| 44 | `DOC-364435343e0a2250` | True | 0.647400 | 36.8 | 3020 | 393 | None |
| 45 | `DOC-164aa748f84cef54` | True | 0.589900 | 29.5 | 2911 | 393 | None |
| 46 | `DOC-85314478b81710d9` | True | 0.618900 | 28.5 | 5285 | 445 | None |
| 47 | `DOC-7f1f866b022cee63` | True | 0.787300 | 31.5 | 4985 | 509 | None |
| 48 | `DOC-384665a051d0fcd6` | True | 0.679800 | 30.7 | 5208 | 504 | None |
| 49 | `DOC-6dcc0b9ba494c25b` | True | 0.756900 | 29.0 | 5114 | 546 | None |
| 50 | `DOC-02f77aa77391a8c2` | True | 0.691200 | 40.2 | 5091 | 1409 | None |
