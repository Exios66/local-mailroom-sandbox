# Run report — `sand42-50-insurance-claims-specialist-awq-2l4-c16`

Dated cell stem: `RUN-50-INSURANCE-AWQ-2L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-insurance-claims-specialist-awq-2l4-c16` |
| task / agent | `insurance_claims_specialist` |
| prompt | `insurance_claims_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **16** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `6af67d4c005f741866ba6324beba4e6e5e033b1a40a61792337d5bef2b82da2c` |
| dataset fingerprint | `f4fdcee45e7f` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.668084** |
| schema_valid_rate | 0.240000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 85.994 |
| gpu_seconds | 86.307 |
| estimated GPU cost | 0.038359 |
| **GPU $/doc** | **0.00076718** |
| latency p50 / max (s) | 14.410444 / 40.279419 |
| prompt / completion tokens | 165315 / 20229 |
| concurrency speedup (Σlat/wall) | 9.11 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-968c9605eab0a87d` | True | 0.644200 | 13.8 | 2942 | 350 | None |
| 2 | `DOC-2aea7f6dc44b37e1` | True | 0.774100 | 13.8 | 2835 | 356 | None |
| 3 | `DOC-9ba0a3d4c680b976` | True | 0.639800 | 13.8 | 2982 | 334 | None |
| 4 | `DOC-2a33a6c34834e769` | True | 0.629800 | 13.8 | 2953 | 341 | None |
| 5 | `DOC-629fb5789dfd10ca` | True | 0.797900 | 13.8 | 2836 | 357 | None |
| 6 | `DOC-e7c196f508907c6f` | True | 0.783000 | 13.8 | 2834 | 362 | None |
| 7 | `DOC-2a55a2b5324659f8` | True | 0.809800 | 13.8 | 2865 | 347 | None |
| 8 | `DOC-997823d9605a4a59` | True | 0.644200 | 13.8 | 2973 | 359 | None |
| 9 | `DOC-158c0b74df673b81` | True | 0.644200 | 13.8 | 2939 | 367 | None |
| 10 | `DOC-991cb72cb83c7a6c` | True | 0.644200 | 13.8 | 2941 | 367 | None |
| 11 | `DOC-9a6f58879fcb3367` | True | 0.648700 | 14.1 | 2946 | 371 | None |
| 12 | `DOC-e2a58ed4c02470c0` | True | 0.795600 | 14.5 | 2835 | 373 | None |
| 13 | `DOC-ef79520b2f50217b` | True | 0.691500 | 14.9 | 3138 | 378 | None |
| 14 | `DOC-2435c398b95844bc` | True | 0.695600 | 15.1 | 3080 | 390 | None |
| 15 | `DOC-5c4e70db54374e72` | True | 0.687400 | 18.4 | 3151 | 403 | None |
| 16 | `DOC-728d06b610b25244` | True | 0.704300 | 8.5 | 2804 | 289 | None |
| 17 | `DOC-6f6fc9762418a70f` | True | 0.704800 | 8.4 | 2811 | 294 | None |
| 18 | `DOC-5b1e8e2aed95c089` | True | 0.682500 | 22.5 | 3123 | 541 | None |
| 19 | `DOC-2d7cc160b78a69c5` | True | 0.644200 | 11.1 | 2979 | 405 | None |
| 20 | `DOC-00d28a1df0e3f6ba` | True | 0.697100 | 12.3 | 2812 | 259 | None |
| 21 | `DOC-f5e6c0de5f1d8593` | True | 0.628300 | 13.3 | 2812 | 280 | None |
| 22 | `DOC-00ccdcb0154a8629` | True | 0.622800 | 13.4 | 2812 | 285 | None |
| 23 | `DOC-cbfcdb6f42cf2ae6` | True | 0.620500 | 13.6 | 2806 | 290 | None |
| 24 | `DOC-c34baab0b5fe378a` | True | 0.623200 | 13.7 | 2807 | 292 | None |
| 25 | `DOC-5060222215c75aa6` | True | 0.741200 | 13.7 | 2801 | 296 | None |
| 26 | `DOC-87c0c53132830a6c` | True | 0.613100 | 11.3 | 2993 | 372 | None |
| 27 | `DOC-9051d4cf8d7ab452` | True | 0.724800 | 16.1 | 3115 | 355 | None |
| 28 | `DOC-29e384939c31d44a` | True | 0.613100 | 16.7 | 3010 | 365 | None |
| 29 | `DOC-d8df43ed4d8faf89` | True | 0.713700 | 19.1 | 3107 | 395 | None |
| 30 | `DOC-e4b1466ee8d1ff19` | True | 0.703700 | 19.2 | 3113 | 401 | None |
| 31 | `DOC-364435343e0a2250` | True | 0.647400 | 13.9 | 3020 | 393 | None |
| 32 | `DOC-0cdb706a0cdbe3b6` | True | 0.613100 | 14.4 | 2981 | 315 | None |
| 33 | `DOC-4e21681f375a247d` | True | 0.618800 | 16.8 | 2985 | 368 | None |
| 34 | `DOC-27b23fd94cc70d9d` | True | 0.578500 | 15.1 | 2890 | 354 | None |
| 35 | `DOC-3ae2dc5d624e2120` | True | 0.599900 | 15.4 | 2871 | 347 | None |
| 36 | `DOC-44bcd388c4710b71` | True | 0.566300 | 14.2 | 2884 | 335 | None |
| 37 | `DOC-93c8d133c296d536` | True | 0.579600 | 15.0 | 2879 | 356 | None |
| 38 | `DOC-91da307f80433ae3` | True | 0.579600 | 15.9 | 2894 | 344 | None |
| 39 | `DOC-90338506fc792f32` | True | 0.579600 | 15.6 | 2882 | 342 | None |
| 40 | `DOC-164aa748f84cef54` | True | 0.581000 | 15.7 | 2911 | 394 | None |
| 41 | `DOC-7bd9dbc1b39ad41d` | True | 0.608100 | 28.2 | 3171 | 646 | None |
| 42 | `DOC-7f1f866b022cee63` | True | 0.730900 | 18.3 | 4985 | 508 | None |
| 43 | `DOC-ab18f15b7a51f1ab` | True | 0.742700 | 15.6 | 5538 | 423 | None |
| 44 | `DOC-73d64bbeb296bd95` | True | 0.619800 | 20.6 | 4524 | 542 | None |
| 45 | `DOC-384665a051d0fcd6` | True | 0.700000 | 17.5 | 5208 | 508 | None |
| 46 | `DOC-1076ac5b4b0df386` | True | 0.656900 | 14.1 | 4482 | 429 | None |
| 47 | `DOC-85314478b81710d9` | True | 0.699800 | 14.4 | 5285 | 438 | None |
| 48 | `DOC-6dcc0b9ba494c25b` | True | 0.756900 | 15.8 | 5114 | 555 | None |
| 49 | `DOC-5b97ae3f8558703c` | True | 0.691600 | 18.2 | 4565 | 654 | None |
| 50 | `DOC-02f77aa77391a8c2` | True | 0.686400 | 40.3 | 5091 | 1404 | None |
