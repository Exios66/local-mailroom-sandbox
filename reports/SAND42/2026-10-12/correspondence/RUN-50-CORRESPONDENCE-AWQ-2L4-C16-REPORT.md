# Run report — `sand42-50-correspondence-specialist-awq-2l4-c16`

Dated cell stem: `RUN-50-CORRESPONDENCE-AWQ-2L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-correspondence-specialist-awq-2l4-c16` |
| task / agent | `correspondence_specialist` |
| prompt | `correspondence_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **16** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `a779625fed641967db2d04a0ce2af370ea3a1bfb8ce4b4ebd0b82b38a096f020` |
| dataset fingerprint | `a00ba5dc0159` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.381584** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 39.894 |
| gpu_seconds | 40.198 |
| estimated GPU cost | 0.017866 |
| **GPU $/doc** | **0.00035732** |
| latency p50 / max (s) | 6.660609 / 11.915516 |
| prompt / completion tokens | 129444 / 7712 |
| concurrency speedup (Σlat/wall) | 9.06 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-3433644b29e318b3` | True | 0.496700 | 6.7 | 2311 | 122 | None |
| 2 | `DOC-3c85eb56a4145e0c` | True | 0.714300 | 6.7 | 2357 | 134 | None |
| 3 | `DOC-a21b03af9a6afc21` | True | 0.736800 | 6.7 | 2412 | 118 | None |
| 4 | `DOC-2a7acfac00e67bac` | True | 0.027800 | 8.5 | 2256 | 120 | None |
| 5 | `DOC-fc6108235411ca8e` | True | 0.060600 | 8.5 | 2465 | 198 | None |
| 6 | `DOC-bcc74152bde91996` | True | 0.809500 | 8.5 | 2211 | 121 | None |
| 7 | `DOC-c71d3ca0b727a0d4` | True | 0.333300 | 8.5 | 2310 | 128 | None |
| 8 | `DOC-fcab49d5955c76c0` | True | 0.060600 | 9.5 | 2332 | 146 | None |
| 9 | `DOC-275198e372250586` | True | 0.158700 | 9.5 | 2880 | 150 | None |
| 10 | `DOC-0dfd9710f2380220` | True | 0.205000 | 9.8 | 2367 | 158 | None |
| 11 | `DOC-8ca6802d3a0f5d1a` | True | 0.814800 | 10.1 | 3289 | 163 | None |
| 12 | `DOC-d9937f535b7c22f3` | True | 0.666700 | 10.5 | 2447 | 169 | None |
| 13 | `DOC-1de496e8c9350155` | True | 0.369600 | 10.7 | 2314 | 172 | None |
| 14 | `DOC-af2b2b54e31214cc` | True | 0.363600 | 10.8 | 2822 | 177 | None |
| 15 | `DOC-b7f699fd18d0f80c` | True | 0.518500 | 10.8 | 2731 | 178 | None |
| 16 | `DOC-3a21b2695c19d388` | True | 0.095200 | 11.9 | 2766 | 198 | None |
| 17 | `DOC-ede2172372d1f296` | True | 0.111100 | 5.5 | 2282 | 136 | None |
| 18 | `DOC-5cdfee2b0ef0a218` | True | 0.536200 | 6.6 | 2263 | 156 | None |
| 19 | `DOC-e7b6158bfb232964` | True | 0.500000 | 5.2 | 2246 | 115 | None |
| 20 | `DOC-6bdc0c7c153547b6` | True | 0.745100 | 7.2 | 2480 | 196 | None |
| 21 | `DOC-25958c023112a96e` | True | 0.333300 | 5.7 | 2242 | 126 | None |
| 22 | `DOC-8674660f9ccc8243` | True | 0.536200 | 5.3 | 2377 | 137 | None |
| 23 | `DOC-4ea9a8cde42f450b` | True | 0.466700 | 5.8 | 2309 | 147 | None |
| 24 | `DOC-38a7cb4be93dbecd` | True | 0.777800 | 6.7 | 2625 | 159 | None |
| 25 | `DOC-ba3217c0524a9577` | True | 0.333300 | 4.8 | 2368 | 124 | None |
| 26 | `DOC-4fa7aa63b169fea8` | True | 0.333300 | 5.9 | 2523 | 142 | None |
| 27 | `DOC-5cef7d1205cc37d5` | True | 0.472200 | 5.9 | 2581 | 137 | None |
| 28 | `DOC-b78953fa896bdeb9` | True | 0.575400 | 7.1 | 2441 | 174 | None |
| 29 | `DOC-9417d989cb45b287` | True | 0.055600 | 4.0 | 2212 | 89 | None |
| 30 | `DOC-3fd5fb2e4b505b04` | True | 0.764700 | 7.1 | 2584 | 177 | None |
| 31 | `DOC-80c4ee15e95f8cc6` | True | 0.049400 | 6.9 | 2631 | 168 | None |
| 32 | `DOC-bdf1d75db5874068` | True | 0.777800 | 10.6 | 2839 | 274 | None |
| 33 | `DOC-65c30d7452215c4b` | True | 0.133300 | 5.1 | 2272 | 131 | None |
| 34 | `DOC-315b7ca63910e311` | True | 0.193900 | 8.8 | 2607 | 231 | None |
| 35 | `DOC-a7e5e24fade86aae` | True | 0.454500 | 6.6 | 3230 | 150 | None |
| 36 | `DOC-fe0e62a4596a649b` | True | 0.060600 | 5.5 | 2255 | 132 | None |
| 37 | `DOC-8b2609c15d1d37af` | True | 0.428600 | 9.5 | 2604 | 204 | None |
| 38 | `DOC-44dd971367dd458a` | True | 0.588900 | 6.2 | 2298 | 111 | None |
| 39 | `DOC-537e1f953940c39c` | True | 0.233300 | 8.2 | 2600 | 172 | None |
| 40 | `DOC-20dc95a39ec83250` | True | 0.191100 | 6.4 | 2422 | 168 | None |
| 41 | `DOC-5feb4a34e13ce77a` | True | 0.100000 | 6.5 | 2415 | 176 | None |
| 42 | `DOC-f64e409a607594bb` | True | 0.176800 | 4.1 | 2264 | 115 | None |
| 43 | `DOC-aff14c55ba2c4d16` | True | 0.076900 | 7.3 | 3394 | 150 | None |
| 44 | `DOC-62d410af6bdd29f8` | True | 0.228600 | 5.1 | 2520 | 146 | None |
| 45 | `DOC-c4074ed5b08f097e` | True | 0.382700 | 5.5 | 2255 | 128 | None |
| 46 | `DOC-851611e86c9e36d0` | True | 0.514600 | 4.2 | 2806 | 131 | None |
| 47 | `DOC-90326221a1667d50` | True | 0.333300 | 7.0 | 3495 | 163 | None |
| 48 | `DOC-f8fb6b01de0fc173` | True | 0.527800 | 5.4 | 3169 | 142 | None |
| 49 | `DOC-e1e0cc74e784a403` | True | 0.321200 | 5.3 | 2677 | 191 | None |
| 50 | `DOC-6823b2f649cf1d0a` | True | 0.333300 | 6.4 | 4888 | 162 | None |
