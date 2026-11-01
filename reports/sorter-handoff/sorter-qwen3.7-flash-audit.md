# Audit: Qwen3.7 Flash sorter answers on the full train split (2,979 documents)

Saved pass: `data/handoff/sorter-qwen3.7-flash/{train,test}.jsonl` + `manifest.json`
(written by `scripts/export_sorter_handoff.py`; no document text, labels included).
Runs: `sorter-handoff-qwen-train` (2,942; stopped by its API cap, which priced tokens at the
profile's DeepSeek route, $0.05/$0.25) + `sorter-handoff-qwen-train-rest` (37). List cost at
$0.03/$0.13 per 1M: train $1.20, test $0.13. Reviewer runs read it with
`reviewer.handoff_run: data/handoff/sorter-qwen3.7-flash/train.jsonl`; there is no need to re-run the sorter.

## Is the sorter output fit to be training material?

As the *input* (the handoff the reviewer checks): yes, its errors are the cases the reviewer
must learn to catch. As the *target*: no. Targets must be the dataset labels, corrected where
a label is wrong.

| | Train (2,979) | Test (323) |
| --- | ---: | ---: |
| Class correct | 2,852 (95.7%) | 309 (95.7%) |
| Subclass correct (contract names mapped to taxonomy keys) | 2,102 (70.6%) | 223 (69.0%) |
| Routed to human review, sorter alone (unknown class or below the class high band) | 964 (32.4%) | 115 (35.6%) |

**The sorter's confidence tells us nothing.** Its 127 wrong classes have a median confidence
of 0.95, the same as its right answers, and 122 of the 127 are at 0.95 or above. No cutoff on
the sorter's confidence can separate them; the reviewer's probabilities must.

The 127 class errors are systematic, not noise:

| Label | Sorter | Count | Pattern |
| --- | --- | ---: | --- |
| corporate_record / indenture | contract | 49 | indentures read as agreements |
| corporate_record / rights_instrument | contract | 40 | registration-rights agreements, joinders, unit purchase options |
| correspondence / email | unknown | 30 | bare URLs, attachment stubs, one-line jokes (corpus: all mailbox text is correspondence) |
| other | | 8 | 3 email → contract, 3 contract → correspondence, 1 demand → unknown, 1 articles → contract |

The Decisions-model reviewer had already answered 33 of these 127 (from the 735-document v1/v2
train draw), and it agreed with the label on all 33. These are sorter errors, not label errors.
The other 94 have no reviewer evidence yet; they are the same patterns.

## Patched targets (applied)

`scripts/patch_sorter_handoff.py` writes `data/handoff/sorter-qwen3.7-flash/{train,test}.targets.jsonl`
and `{split}.corrections.json`. The raw sorter answers in `{split}.jsonl` are unchanged: they are the
reviewer's input. Each targets row has `target_doc_class` / `target_subclass`, `target_status`,
`target_evidence`, `use_for_class` / `use_for_subclass`, and the sorter's correctness against the target.

| Status | Train | Test | Meaning |
| --- | ---: | ---: | --- |
| label | 2,359 | 252 | label kept |
| label_normalized | 538 | 59 | contract CUAD folder name mapped to the taxonomy key |
| corrected | 28 | 4 | the title line and the Decisions reviewer (p >= 0.9) both contradict the label |
| unannotated | 49 | 8 | merger `other` with no MAUD Type of Consideration: class used, subclass not scored |
| ambiguous | 5 | 0 | sorter and reviewer both dispute a label no rule confirms: an example only, not a target |

The corrections are the known label noise:
- 14 Certificates of Amendment labelled board_resolution → charter_amendment;
- 6 bylaws labelled articles_of_incorporation;
- 2 bylaws labelled powers_of_attorney;
- 2 restated charters labelled charter_amendment;
- one each of other → articles, board_resolution → officer_certificate, articles → charter_amendment, and articles → rights_instrument;
- in test, the LIMITED POWER OF ATTORNEY labelled contract/Service → corporate_record/powers_of_attorney.

To settle the 19 rows where only one source disputed the label, and the sorter errors no rule
confirmed, `reviewer-verify-sorter-handoff-train` ran the Decisions model (question set 3.1.0)
on 46 documents: 535,592 input tokens, $0.054 at list price.

**Sorter against the patched targets.**

| | Train | Test |
| --- | ---: | ---: |
| Class correct | 2,852 / 2,974 (95.9%) | 310 / 323 (96.0%) |
| Subclass correct | 2,122 / 2,925 (72.5%) | 226 / 315 (71.7%) |
| Class errors with the label confirmed | 121 of 122 | 13 of 13 |

A label is confirmed by the Enron maildir rule, a title rule, or the Decisions reviewer.

## Next agent

1. Score reviewer and sorter runs against `target_*` with `use_for_*`, not the raw labels.
   `calibrate_reviewer.py` still reads the raw labels; switch it to the targets file.
2. Fix the sorter prompt for indentures and rights instruments (corporate_record) and for mailbox
   fragments (correspondence). Those are 119 of its 122 class errors.
3. Upstream the 32 label corrections and the merger `unannotated` subclass to the dataset
   (Lucius-Morningstar/mailroom-dataset), citing `{split}.corrections.json`.
