# Run report — `sand42-50-correspondence-specialist-awq-2l4-c32`

Dated cell stem: `RUN-50-CORRESPONDENCE-AWQ-2L4-C32`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-correspondence-specialist-awq-2l4-c32` |
| task / agent | `correspondence_specialist` |
| prompt | `correspondence_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **32** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `6309643e22df187b496a257b0042a8e592ac73b485b57b53480b986af4503580` |
| dataset fingerprint | `a00ba5dc0159` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.377546** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 39.053 |
| gpu_seconds | 39.294 |
| estimated GPU cost | 0.017464 |
| **GPU $/doc** | **0.00034928** |
| latency p50 / max (s) | 12.860047 / 23.522625 |
| prompt / completion tokens | 129444 / 7747 |
| concurrency speedup (Σlat/wall) | 16.80 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-c71d3ca0b727a0d4` | True | 0.333300 | 6.3 | 2310 | 128 | None |
| 2 | `DOC-25958c023112a96e` | True | 0.666700 | 6.7 | 2242 | 170 | None |
| 3 | `DOC-e7b6158bfb232964` | True | 0.500000 | 8.6 | 2246 | 115 | None |
| 4 | `DOC-1de496e8c9350155` | True | 0.369600 | 8.7 | 2314 | 115 | None |
| 5 | `DOC-2a7acfac00e67bac` | True | 0.027800 | 8.9 | 2256 | 120 | None |
| 6 | `DOC-bcc74152bde91996` | True | 0.809500 | 9.3 | 2211 | 121 | None |
| 7 | `DOC-ba3217c0524a9577` | True | 0.333300 | 9.9 | 2368 | 124 | None |
| 8 | `DOC-3433644b29e318b3` | True | 0.496700 | 10.0 | 2311 | 123 | None |
| 9 | `DOC-3c85eb56a4145e0c` | True | 0.714300 | 10.9 | 2357 | 134 | None |
| 10 | `DOC-5cef7d1205cc37d5` | True | 0.234100 | 11.0 | 2581 | 137 | None |
| 11 | `DOC-8674660f9ccc8243` | True | 0.536200 | 11.5 | 2377 | 142 | None |
| 12 | `DOC-80c4ee15e95f8cc6` | True | 0.049400 | 5.7 | 2631 | 166 | None |
| 13 | `DOC-8ca6802d3a0f5d1a` | True | 0.814800 | 12.2 | 3289 | 153 | None |
| 14 | `DOC-5cdfee2b0ef0a218` | True | 0.536200 | 12.2 | 2263 | 156 | None |
| 15 | `DOC-0dfd9710f2380220` | True | 0.205000 | 12.8 | 2367 | 156 | None |
| 16 | `DOC-d9937f535b7c22f3` | True | 0.333300 | 13.4 | 2447 | 171 | None |
| 17 | `DOC-65c30d7452215c4b` | True | 0.133300 | 4.8 | 2272 | 131 | None |
| 18 | `DOC-b7f699fd18d0f80c` | True | 0.518500 | 14.2 | 2731 | 189 | None |
| 19 | `DOC-44dd971367dd458a` | True | 0.622200 | 4.3 | 2298 | 113 | None |
| 20 | `DOC-a7e5e24fade86aae` | True | 0.454500 | 5.9 | 3230 | 152 | None |
| 21 | `DOC-3a21b2695c19d388` | True | 0.121200 | 14.8 | 2766 | 200 | None |
| 22 | `DOC-315b7ca63910e311` | True | 0.193900 | 15.4 | 2607 | 223 | None |
| 23 | `DOC-f64e409a607594bb` | True | 0.176800 | 4.3 | 2264 | 125 | None |
| 24 | `DOC-fcab49d5955c76c0` | True | 0.060600 | 16.9 | 2332 | 136 | None |
| 25 | `DOC-5feb4a34e13ce77a` | True | 0.100000 | 6.1 | 2415 | 180 | None |
| 26 | `DOC-275198e372250586` | True | 0.158700 | 17.7 | 2880 | 150 | None |
| 27 | `DOC-62d410af6bdd29f8` | True | 0.228600 | 5.9 | 2520 | 182 | None |
| 28 | `DOC-851611e86c9e36d0` | True | 0.497100 | 4.5 | 2806 | 142 | None |
| 29 | `DOC-a21b03af9a6afc21` | True | 0.824600 | 18.4 | 2412 | 130 | None |
| 30 | `DOC-b78953fa896bdeb9` | True | 0.575400 | 18.7 | 2441 | 171 | None |
| 31 | `DOC-e1e0cc74e784a403` | True | 0.321200 | 5.1 | 2677 | 186 | None |
| 32 | `DOC-bdf1d75db5874068` | True | 0.777800 | 19.7 | 2839 | 167 | None |
| 33 | `DOC-4ea9a8cde42f450b` | True | 0.466700 | 19.8 | 2309 | 152 | None |
| 34 | `DOC-3fd5fb2e4b505b04` | True | 0.764700 | 20.9 | 2584 | 184 | None |
| 35 | `DOC-9417d989cb45b287` | True | 0.055600 | 12.9 | 2212 | 89 | None |
| 36 | `DOC-ede2172372d1f296` | True | 0.111100 | 21.6 | 2282 | 140 | None |
| 37 | `DOC-fc6108235411ca8e` | True | 0.060600 | 21.7 | 2465 | 198 | None |
| 38 | `DOC-af2b2b54e31214cc` | True | 0.363600 | 21.8 | 2822 | 177 | None |
| 39 | `DOC-8b2609c15d1d37af` | True | 0.428600 | 21.7 | 2604 | 204 | None |
| 40 | `DOC-4fa7aa63b169fea8` | True | 0.333300 | 22.3 | 2523 | 142 | None |
| 41 | `DOC-38a7cb4be93dbecd` | True | 0.740700 | 23.3 | 2625 | 231 | None |
| 42 | `DOC-6bdc0c7c153547b6` | True | 0.614700 | 23.5 | 2480 | 224 | None |
| 43 | `DOC-537e1f953940c39c` | True | 0.233300 | 17.0 | 2600 | 181 | None |
| 44 | `DOC-fe0e62a4596a649b` | True | 0.060600 | 14.1 | 2255 | 132 | None |
| 45 | `DOC-aff14c55ba2c4d16` | True | 0.076900 | 15.2 | 3394 | 150 | None |
| 46 | `DOC-c4074ed5b08f097e` | True | 0.382700 | 12.9 | 2255 | 132 | None |
| 47 | `DOC-90326221a1667d50` | True | 0.333300 | 13.7 | 3495 | 153 | None |
| 48 | `DOC-6823b2f649cf1d0a` | True | 0.407400 | 12.5 | 4888 | 141 | None |
| 49 | `DOC-f8fb6b01de0fc173` | True | 0.527800 | 11.7 | 3169 | 142 | None |
| 50 | `DOC-20dc95a39ec83250` | True | 0.191100 | 14.6 | 2422 | 167 | None |
