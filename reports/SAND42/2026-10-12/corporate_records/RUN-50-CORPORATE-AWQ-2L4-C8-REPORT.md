# Run report — `sand42-50-corporate-records-specialist-awq-2l4-c8`

Dated cell stem: `RUN-50-CORPORATE-AWQ-2L4-C8`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-corporate-records-specialist-awq-2l4-c8` |
| task / agent | `corporate_records_specialist` |
| prompt | `corporate_records_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **8** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `b13d7fb4ce48dc6f606f6ee6eb644d9b8ad2d9e430d6c49a5b92fbd6622ff807` |
| dataset fingerprint | `76b083c7c46d` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.480586** |
| schema_valid_rate | 0.960000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 64.926 |
| gpu_seconds | 65.229 |
| estimated GPU cost | 0.028991 |
| **GPU $/doc** | **0.00057982** |
| latency p50 / max (s) | 7.726200 / 12.269298 |
| prompt / completion tokens | 197319 / 8006 |
| concurrency speedup (Σlat/wall) | 5.96 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-9ca44c7926a47ede` | True | 0.502400 | 5.8 | 2292 | 130 | None |
| 2 | `DOC-020d77c0107d273d` | True | 0.474600 | 5.8 | 2302 | 116 | None |
| 3 | `DOC-fbcdd16e24f143ac` | True | 0.158200 | 8.2 | 2456 | 155 | None |
| 4 | `DOC-e545bbd5f5ea61b6` | True | 0.363600 | 8.2 | 2788 | 156 | None |
| 5 | `DOC-81ae205a3b0bf16f` | True | 0.248000 | 8.3 | 2515 | 163 | None |
| 6 | `DOC-6790430ae2a6c724` | True | 0.184600 | 11.0 | 4477 | 142 | None |
| 7 | `DOC-12a6d4cd092cf66d` | True | 0.502600 | 11.5 | 7710 | 158 | None |
| 8 | `DOC-01054efd0980066b` | True | 0.822200 | 11.5 | 5122 | 159 | None |
| 9 | `DOC-c4c9c37a96291975` | True | 0.081300 | 5.6 | 2424 | 136 | None |
| 10 | `DOC-91f89b9c0d285ac7` | True | 0.666700 | 6.8 | 6902 | 128 | None |
| 11 | `DOC-a040ac19abb88fec` | True | 0.409700 | 7.3 | 2206 | 141 | None |
| 12 | `DOC-0a262afc80c73247` | True | 0.113600 | 7.7 | 3124 | 153 | None |
| 13 | `DOC-0f56fe8db6df01bd` | True | 0.063500 | 9.9 | 5368 | 161 | None |
| 14 | `DOC-732b812b7d9d9653` | True | 0.888900 | 7.7 | 5572 | 156 | None |
| 15 | `DOC-68d5a8753fcc3675` | True | 0.440500 | 8.3 | 5671 | 177 | None |
| 16 | `DOC-e077f1f7e80e1e04` | True | 0.162400 | 8.7 | 4043 | 160 | None |
| 17 | `DOC-9376c6bfa6779d5e` | True | 0.451900 | 4.6 | 2200 | 134 | None |
| 18 | `DOC-2819b889b134ea01` | True | 0.750000 | 9.5 | 5344 | 175 | None |
| 19 | `DOC-b3ad98e5530dfeaf` | True | 0.282000 | 9.0 | 2521 | 190 | None |
| 20 | `DOC-2f19002c84083aa8` | True | 0.495100 | 7.3 | 5200 | 170 | None |
| 21 | `DOC-f134b9491efc5c57` | True | 0.794900 | 6.0 | 2865 | 140 | None |
| 22 | `DOC-474a0002b4c03be1` | True | 0.820500 | 6.1 | 2938 | 152 | None |
| 23 | `DOC-4dc719baa790a79c` | True | 0.666700 | 6.7 | 2669 | 163 | None |
| 24 | `DOC-e478fa89043a29e3` | True | 0.820500 | 6.7 | 2910 | 151 | None |
| 25 | `DOC-fc9f56d999bd7566` | True | 0.666700 | 8.4 | 2509 | 196 | None |
| 26 | `DOC-1e8e3ce47882ae71` | True | 0.148500 | 9.5 | 3063 | 198 | None |
| 27 | `DOC-d015968793450753` | True | 0.805600 | 7.9 | 5082 | 167 | None |
| 28 | `DOC-a5fd7fe18b094f20` | True | 0.848500 | 7.6 | 5919 | 145 | None |
| 29 | `DOC-b832b5eaa2b4848c` | True | 0.106800 | 4.2 | 2762 | 95 | None |
| 30 | `DOC-204c3c7c0ba021cd` | True | 0.474600 | 7.1 | 2226 | 133 | None |
| 31 | `DOC-41b53ea487b84955` | True | 0.750000 | 10.0 | 4617 | 233 | None |
| 32 | `DOC-bfa92eb6c72569ee` | True | 0.118400 | 7.3 | 3771 | 158 | None |
| 33 | `DOC-9467462d9bb34f8e` | True | 0.541700 | 9.3 | 5345 | 160 | None |
| 34 | `DOC-37152a33cfb70d37` | True | 0.410300 | 6.6 | 2902 | 161 | None |
| 35 | `DOC-0a8eb16fff7e67ca` | True | 0.359000 | 6.5 | 5246 | 159 | None |
| 36 | `DOC-00193d0c070747e6` | True | 0.714300 | 9.0 | 3225 | 173 | None |
| 37 | `DOC-f21f3dadebb121e3` | True | 0.784300 | 6.3 | 3308 | 180 | None |
| 38 | `DOC-78f2456f571403a9` | True | 0.153100 | 5.0 | 2345 | 151 | None |
| 39 | `DOC-ffb48271e0a5e812` | True | 0.666700 | 8.8 | 5344 | 141 | None |
| 40 | `DOC-a973ebf005e0e785` | True | 0.427800 | 12.3 | 6146 | 211 | None |
| 41 | `DOC-e6906e59f9bd74ca` | True | 0.620000 | 9.1 | 2978 | 160 | None |
| 42 | `DOC-d4dfbfe8049d41f9` | True | 0.490700 | 7.9 | 3856 | 179 | None |
| 43 | `DOC-80e90a37bb750a3c` | True | 0.165400 | 10.4 | 2776 | 201 | None |
| 44 | `DOC-2338d194d5250def` | True | 0.486700 | 6.4 | 5258 | 128 | None |
| 45 | `DOC-866139125545b36a` | True | 0.773300 | 9.5 | 5397 | 180 | None |
| 46 | `DOC-842215e36884da89` | True | 0.246700 | 5.7 | 5226 | 158 | None |
| 47 | `DOC-606242f2919653a4` | True | 0.233200 | 7.8 | 5253 | 165 | None |
| 48 | `DOC-dfe42f3747f299e6` | True | 0.750000 | 6.5 | 5870 | 166 | None |
| 49 | `DOC-d0aebe650be3e512` | True | 0.497600 | 4.5 | 2405 | 163 | None |
| 50 | `DOC-27bbad54b6fd107e` | True | 0.625000 | 5.2 | 2871 | 179 | None |
