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

## Before using it as a training target (next agent)

1. For each row the target is `expected_doc_class` / `expected_subclass`; `sorter_*` is the input.
2. Known label noise to fix or exclude first: merger `other` = no MAUD annotation (57 rows, not
   a consideration type); 9+ charter amendments labelled board_resolution; bylaws labelled
   articles_of_incorporation; the LIMITED POWER OF ATTORNEY labelled contract/Service
   (see `reports/reviewer-calibration/reviewer-calibration-luna-decisions.md`).
3. The 94 sorter class errors with no reviewer evidence: check them with the Decisions
   reviewer (about $0.0006 per document measured on test, so about $0.06) or by hand.
4. Fix the sorter prompt for indentures/rights instruments (corporate_record) and mailbox
   fragments (correspondence). Those 119 errors are 94% of its class errors.
