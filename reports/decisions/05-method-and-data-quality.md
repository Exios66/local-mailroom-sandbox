# Method, data quality and open measurements

## How the numbers were made

- **Nothing was re-run.** No model was called and no spend was incurred. Every figure comes from files tracked in this
  repository, rebuilt by `python reports/decisions/build_decisions_report.py` (stdlib only). `--check` exits 1 if a
  figure, CSV, `summary.json` or the dashboard is stale.
- **Computed from data:** the Qwen agent's cost (per-document tokens priced against the tiered OpenRouter sheet), its
  latency and class accuracy, the per-class breakdowns, cutoffs, routing rates and every extraction-gate number.
- **Taken from prose reports:** class and subclass accuracy and the run costs of the chat and Decisions reviewer runs.
  Each sits in `RECORDED` / `RUNS` in the script with its source file. The recorded inputs are echoed under
  `recorded_inputs` in `data/summary.json`.
- **Modelled:** the "1x Qwen reviewer". It is one more Qwen call over the same document, at the same cost as the agent
  call. See below.

## Colour and accessibility

Colour follows the entity in every figure: **blue** is the Qwen agent, **orange** the chat (traditional LLM) reviewer,
**aqua** the Decisions model, grey the baseline or comparison. The three slots come from the dataviz reference palette
and were run through the validator in light and dark, on adjacent and all-pairs lists:
[`data/palette-validation.txt`](data/palette-validation.txt). All checks pass. One WARN remains (light aqua at 2.74:1
against the surface); its relief is a visible value on every mark or a table view. Heatmaps use one blue ramp, with the
anchor flipped in dark mode. Every figure has a `<title>` hover on each mark, keyboard focus, and a CSV twin in
[`data/`](data/); the [dashboard](decisions-dashboard.html) adds tooltips and a table view under each chart.

## Data-quality notes

These are source inconsistencies found while assembling the report. None changes a conclusion, and none was edited at the source.

| # | Where | What | How the report handles it |
| --- | --- | --- | --- |
| 1 | Qwen handoff manifest vs price sheet | `list_cost_usd` ($0.1298 test, $1.2007 train) prices every call at the lowest tier ($0.03 / $0.13). The price sheet in `config/api_prices.yaml` bills 3.3x per token from 32k prompt tokens. | Uses the sheet: $0.2513 test, $2.3119 train. Shows the flat figure as a sensitivity. |
| 2 | `reviewer-calibration-luna-decisions.md` vs `LINEAGE.yaml` | Decisions v2 test subclass accuracy: the report says 83.3%; the lineage compares v3.0.0's 263 of 323 against v2's 265 of 323 (82.0%). | Subclass accuracy is not charted across versions; the lineage figure is quoted for v2 vs v3.0.0. |
| 3 | Same report | Train v2 cost read $0.69 and was corrected to $0.86 (8.55M tokens). | Uses $0.86. |
| 4 | Chat test arms | The default and `decision_v1` test runs used 317 documents with task ground truth; the v3 and Decisions test runs used all 323. | Cost per document uses each run's own n. |
| 5 | Chat v3 test | Only the 98.8% accuracy and the misroute count are recorded; no cost or document-level result. | Shown as "as reported" in the accuracy chart; left out of the cost chart. |
| 6 | `extraction-gate-luna-v1.1.0-r2.yaml` | The cost comment repeats the 220-document estimate (about 2.4M tokens, $0.24) for 690 documents. | Gate cost is not used anywhere. |
| 7 | Latency | Qwen: 323 test documents, whole-document calls. Chat and Decisions: 735 train documents at concurrency 16. | Presented as direction only; the figure says so. |
| 8 | Cutoffs | With no wrong answers in a class, the cutoff is the lowest right-answer confidence, so it tracks sample size. | Called out in the figure subtitle and in [03](03-classification-reviewer.md#4-cutoffs). |
| 9 | Routing counts | Per-class routing counts use the reviewer's class (59 / 48 / 83 / 114 / 17 plus `unknown`), not the true class (60 / 47 / 85 / 114 / 17). | Each table is labelled with its own basis. |

## Limits of the cost comparison

1. **The 1x reviewer is modelled.** A Qwen reviewer prompt that differs in length from the sorter prompt shifts the
   2.00x line. A shorter prompt (the sorter-condensed lineage renders 3,681 characters against V15's 25,074) would lower it.
2. **The chat reviewer is a different model.** Its price ($0.10 / $0.50 per 1M) is not Qwen's, and the chat arm is
   superseded in this repo. It is included because it is the only measured traditional LLM reviewer.
3. **Run costs are rounded to the cent** in the source reports ($0.24, $0.122).
4. **No human cost is assumed.** The break-even figures ($0.0022 per review) say what a review has to be worth, not
   what it is worth.
5. **The reviewer ran on every document in these experiments.** In the pipeline today the LLM reviewer runs only on
   medium-confidence sorter results, while a `decision_only` class reaches its reviewer at any confidence. The 2.00x
   line therefore overstates the traditional pipeline's reviewer share, and the saving against it is an upper bound.
6. **Held-out means 323 documents.** One misroute is 0.3%; the intervals around any single rate are wide.

## What to measure next

| # | Measurement | Why | Rough cost |
| --- | --- | --- | --- |
| 1 | Run the `sorter_reviewer` task on **Qwen 3.7 Flash** over the 323 test documents | Replaces the modelled 1x reviewer with a measured one: cost, accuracy, confidence | about $0.25 |
| 2 | `reviewer-calibration-luna-decisions-v3.1.0-train`: the full 2,979-document train split with the sorter handoff | Settles whether the confidence advantage holds at scale; fixes the cutoffs | about $2.05 (cap $2.60) |
| 3 | Validate sorter prompt V15 with `config/runs/sorter-v15-qwen-train-errors.yaml` | Lowers the 1x agent's error rate before the reviewer sees it | about $0.49 |
| 4 | Question set 4.0.0: derive the verdict in code | Removes the 5x human-review penalty of 3.0.0 | none new |
| 5 | A per-field extraction gate scored against field-level truth | The gate's one signal is at field level | open |

Each paid run needs a signed `sandbox run start --initials XX`; nothing here has been started.
