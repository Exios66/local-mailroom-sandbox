# Run report — `grid-20-merger-specialist-awq-1l4`

Dated cell stem: `RUN-20-MERGER-AWQ-1L4-C8`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `grid-20-merger-specialist-awq-1l4` |
| task / agent | `merger_agreement_specialist` |
| prompt | `merger_agreement_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **8** |
| n | **20** |
| profile | `modal-vllm` |
| spec_hash | `afae1ed02471b9f35897017cf71876eb4a7b5574b9214c45833b0faaeb39aa8b` |
| dataset fingerprint | `53cb996f5b48` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **19 / 1 / 20** |
| **overall_extraction_score** | **0.028666** |
| schema_valid_rate | — |
| error_count | 1 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 939.179 |
| gpu_seconds | 939.456 |
| estimated GPU cost | 0.208768 |
| **GPU $/doc** | **0.010988** |
| latency p50 / max (s) | 358.711419 / 492.615825 |
| prompt / completion tokens | 200038 / 17412 |
| concurrency speedup (Σlat/wall) | 7.15 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-be8461dd68cfe458` | True | 0 | 110.0 | 10396 | 969 | None |
| 2 | `DOC-d01014aed8ad8824` | True | 0 | 144.3 | 10721 | 778 | None |
| 3 | `DOC-62456d43b50f73fa` | True | 0.062500 | 180.7 | 10915 | 830 | None |
| 4 | `DOC-cea6dc327188d9da` | True | 0 | 221.3 | 10670 | 928 | None |
| 5 | `DOC-d9157f4ad78024e5` | True | 0 | 268.3 | 10505 | 1075 | None |
| 6 | `DOC-d4b1a7a2b981fbf4` | True | 0 | 317.2 | 10600 | 1120 | None |
| 7 | `DOC-4f23b571c261a708` | True | 0 | 353.6 | 10296 | 816 | None |
| 8 | `DOC-4cab0ae6bfeaa370` | True | 0 | 386.4 | 10349 | 743 | None |
| 9 | `DOC-8a0bdfe3d16c33b2` | True | 0.058824 | 321.5 | 10570 | 978 | None |
| 10 | `DOC-158ec6b697211e14` | False | — | 468.4 | — | — | LengthFinishReasonError: Could not parse response content as the length limit was reached - CompletionUsage(completion_tokens=4096, prompt_tokens=10209, total_tokens=14305, completion_tokens_details=None, prompt_tokens_details=None) |
| 11 | `DOC-0534799ed39ca0db` | True | 0.055556 | 469.1 | 10414 | 763 | None |
| 12 | `DOC-297745a521cd1e8c` | True | 0.176471 | 490.6 | 10471 | 1335 | None |
| 13 | `DOC-4e57aa1ce9cc283b` | True | 0.058824 | 482.1 | 10437 | 798 | None |
| 14 | `DOC-f9870e3b8fd141b0` | True | 0 | 470.4 | 10697 | 776 | None |
| 15 | `DOC-9d34581755c603a3` | True | 0 | 474.3 | 10033 | 845 | None |
| 16 | `DOC-169bbcdc5d9e609c` | True | 0.076923 | 479.5 | 11214 | 777 | None |
| 17 | `DOC-5d30efc302f3c431` | True | 0 | 492.6 | 10490 | 1241 | None |
| 18 | `DOC-ff3ceb691481f1bd` | True | 0 | 358.7 | 10527 | 994 | None |
| 19 | `DOC-681bc6115b882191` | True | 0 | 359.9 | 10509 | 807 | None |
| 20 | `DOC-7128ff7c2ed51cd6` | True | 0.055556 | 337.3 | 10224 | 839 | None |
