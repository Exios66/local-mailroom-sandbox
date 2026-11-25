# Qwen 3.7 Flash vs Luna Decisions on 500 documents

2026-11-24. Both arms classified the same 500 documents. Every document finished,
none was truncated, and every document reported a provider charge. The numbers
below are the slideshow table. The machine-readable copy is
[qwen3.7-flash-vs-luna-decisions.json](qwen3.7-flash-vs-luna-decisions.json).

## Headline

| | Qwen 3.7 Flash | Luna Decisions |
| --- | ---: | ---: |
| Model | `qwen/qwen3.7-flash` | `openai/gpt-6-luna-decisions` |
| Class accuracy | **99.4%** (497/500) | **98.2%** (491/500) |
| Macro F1 | **99.6%** | **99.1%** |
| Macro false-positive rate | **0.046%** | **0.046%** |
| Macro false-negative rate | **0.48%** | **1.44%** |
| Subclass accuracy | 79.8% (399/500) | **83.4%** (417/500) |
| Unit accuracy | 80.2% (401/500) | **83.4%** (417/500) |
| Wall time | 2 min 46 s (165.9 s) | **40.5 s** |
| Latency, median / 95th | 2.10 s / 6.50 s | **0.57 s / 1.14 s** |
| Provider cost | **$0.3425** | **$0.5267** |
| Cost per document | $0.000685 | $0.001053 |

Qwen is ahead on class accuracy. The decisions model is ahead on subclass and
unit accuracy, and it finishes in about a quarter of the wall time. The paired
difference (decisions minus Qwen), with a 95% bootstrap interval:

| Comparison | Estimate | 95% interval |
| --- | ---: | --- |
| Class accuracy | −1.2 points | −2.2 to −0.4 |
| Macro F1 | −0.49 points | −0.97 to −0.13 |
| Unit accuracy | +3.2 points | 0.0 to +6.6 |

Six documents are right only for Qwen and none are right only for the decisions
model (McNemar p = 0.031). The unit-accuracy interval includes zero
(McNemar p = 0.085). Both arms predicted the same class on 494 of 500 documents:
491 both correct, 3 both wrong.

## Per class

Strata: contract 91, corporate record 68, correspondence 151, insurance claim
167, merger agreement 23. False-positive and false-negative rates are
one-versus-rest.

| Class | n | Qwen F1 | Qwen FNR | Decisions F1 | Decisions FNR |
| --- | ---: | ---: | ---: | ---: | ---: |
| Contract | 91 | 99.4% | 1.1% (1) | 99.4% | 1.1% (1) |
| Corporate record | 68 | 99.3% | 0 | 98.5% | 1.5% (1) |
| Correspondence | 151 | 99.3% | 1.3% (2) | 97.6% | 4.6% (7) |
| Insurance claim | 167 | 100% | 0 | 100% | 0 |
| Merger agreement | 23 | 100% | 0 | 100% | 0 |

The only false positive on either arm is the same contract called a corporate
record (corporate-record false-positive rate 0.23%, one of 432 documents that
are not corporate records). Macro false-positive rate is that one error
averaged across the five classes.

Qwen's three class misses: two correspondence documents called `unknown`, and
that one contract. The decisions model's nine class misses: seven correspondence
documents and one corporate record called `unknown`, plus the same contract.

## Time, tokens and cost

Concurrency was 8 on both arms. Timing is the evaluator's execution window.

| | Qwen 3.7 Flash | Luna Decisions |
| --- | ---: | ---: |
| Wall time | 165.9 s | 40.5 s |
| Active time | 165.6 s | 40.2 s |
| Documents per minute | 181 | 746 |
| Input tokens | 5,194,340 | 5,267,251 |
| Output tokens | 51,082 | 0 |
| Provider cost | $0.3425 | $0.5267 |
| Cache-aware list price | $0.3457 | $0.5267 |
| Cost basis | provider, 500/500 | provider, 500/500 |

The decisions charge matches $0.10 per million input tokens
(5,267,251 × $0.10 / 1,000,000 = $0.5267). Qwen's provider bill is $0.0031
under its cache-aware list price. A cost-direction claim needs 1,000 documents
(`COST_CLAIM_MIN_DOCS`). These totals are the measured bills on 500 documents.

## What each arm would send on

The two "parked" counts use different rules. Qwen parks a lone sorter answer
that is an unknown class or sits under that class's high confidence band.
The decisions arm parks by its question set (`abstained` / `route_to_human`).

| | Qwen 3.7 Flash | Luna Decisions |
| --- | ---: | ---: |
| Parked | 122 (24.4%) | 27 (5.4%) |
| Sent on | 378 | 473 |
| Class accuracy of documents sent on | 99.7% (377/378) | 99.8% (472/473) |
| Class accuracy of parked documents | 98.4% (120/122) | 70.4% (19/27) |

Qwen's 122 parked documents are 120 below the high band and 2 unknown-class
answers. A parked decisions document can carry more than one reason. Across
the 27 parked documents the reason counts are document form 23, unknown max 9,
doc type 8, subclass gate 8, and margin 1.

Calibration on the forced class answer: Qwen ECE 0.019, Brier 0.007; decisions
ECE 0.045, Brier 0.022.

## How the two arms were run

Both arms used one ranked draw: Hugging Face
`Lucius-Morningstar/mailroom-dataset`, config `ground_truth`, split `all`,
revision `ff4ca546d4346991628c2616ae014afc15e9fe04`, seed 3302, staged labels
`9.3.1-rc.9`, exclusion list `config/production/excluded-ids.txt`. Prepared
dataset sha256 `a49f7285d8dabb305786e6bdb5ed66746a804f26949a6fedc5befcf99cc6c38d`.
Trace sink was `none`. Both runs started at 2026-11-24T01:09:59Z and reached
`done`.

| | Qwen | Decisions |
| --- | --- | --- |
| Run | `sorter-vs-decision-500-llm-qwen3.7-flash` | `sorter-vs-decision-500-decision-luna` |
| Config | `config/runs/sorter-vs-decision-500-llm-qwen3.7-flash.yaml` | `config/runs/sorter-vs-decision-500-decision-luna.yaml` |
| Spec hash prefix | `aed6bd904510` | `911495e1db93` |
| Task | `isolated` | `sorter_reviewer` |
| Question set | code-default sorter prompt | `reviewer_decisions_v4.1.0` (no sorter handoff) |
| Classify window | context fit, 2,375,884 characters | `reviewer.max_input_chars` 2,328,000 |
| API cap | $6 | $5 |

The longest document in the draw is 787,688 characters, under both windows.
Provider was OpenRouter. Qwen is pinned to Alibaba. The decisions model is
pinned by its canonical slug in `config/decision_models.yaml`.

Scores come from `mailroom_sandbox.sorter_arms` (`arm_summary` and
`compare_pair`) on the finished local items. `pair()` was not called.
168 of the 500 documents are also in the sealed held-out set
(`config/splits/runbook-v2`), so `scripts/compare_sorter_arms.py` refuses this
draw unless `--confirmatory` is passed. That flag was not used. This report is
the full 500-document draw, not a sealed confirmatory read.
