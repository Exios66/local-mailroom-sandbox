# Experiment figures

Every finished sorter or decision-model run gets a set of figures in one house style, and
the H5 comparison (LLM sorter against the decision model acting as the sorter) gets its own
set. Everything here is offline: the commands read finished run directories and make no model
call and no spend.

- Figure code: `src/mailroom_sandbox/figure_style.py` (style and linter),
  `decision_figures.py` (per-run), `comparison_figures.py` (H5).
- Agent procedure and the full catalogue: [`.claude/skills/experiment-figures/`](../.claude/skills/experiment-figures/SKILL.md).
- Report tree layout: [`reports/campaigns/README.md`](../reports/campaigns/README.md).

## Quick start

```bash
# 1. Per-run figures: rebuild one run's report tree, then the campaign indexes
sandbox report build --run rb1-r13b-smoke20-decision-sorter-luna
sandbox report build --campaign rb1

# 2. H5 comparison: text digest plus six figures into a folder of your choice
python scripts/compare_sorter_arms.py \
    --a rb1-r13b-smoke20-llm-sorter-qwen3.7-flash \
    --b rb1-r13b-smoke20-decision-sorter-luna \
    --figures /tmp/h5-figures

# 3. Check any figures against the house rules
python -m mailroom_sandbox.figure_style lint /tmp/h5-figures
```

`--campaign rb1` only refreshes the READMEs and `index.jsonl`. It does not redraw a run's
figures. Use `--run <run id>` for that.

## What changed on the command line

| Command | Change | Effect for the reader |
| --- | --- | --- |
| `sandbox report build --run <id>` | Writes the full per-run figure set (below) in a fixed order with alt text, not only `latency.svg` | Report trees built before this change carry only `latency.svg`. Rebuild them to get the rest |
| `scripts/compare_sorter_arms.py --figures DIR` | New. Writes the H5 figures as `<key>-sorter-arms.<figure>.svg` | Look at the comparison without writing anything under `reports/` |
| `scripts/compare_sorter_arms.py --write` | Also writes the H5 figures to `reports/campaigns/rb1/<key>-sorter-vs-decision/figures/` | The campaign tree holds the figures next to the comparison JSON and digest |
| `scripts/compare_sorter_arms.py --allow-mock` | Every figure carries "SIMULATED: mock runs, not evidence" and the subtitle starts "Simulated, not evidence" | A figure from mock runs cannot be mistaken for evidence once it is copied elsewhere. `--write` still refuses mock runs |
| `scripts/compare_sorter_arms.py` (no `--split-dir`) | Pairs the arms on the split their run locks drew from | The r13b runs (runbook-v1) compare without naming a split |
| `scripts/compare_sorter_arms.py` digest | New line under each cost difference and the frontier: `not a cost comparison yet (...)` | Cost numbers are shown, but nothing is called cheaper or dearer until the comparison is clean (see [Cost](#cost)) |
| `python -m mailroom_sandbox.figure_style lint PATH...` | New linter. Takes SVG files or folders | Exit 0 clean, 1 problems found, 2 usage error, missing path or no SVG found |

### Reading the new digest line

Under each candidate's cost difference, and under the frontier header, the digest now says why
the numbers are not yet a cost comparison:

```text
  list-price cost per 1k docs $… [$…, $…], lower-cost p=…
  not a cost comparison yet (n = 20, under 1,000 paired documents; no billed cost for: <run id>)
```

The line goes away only when every arm has a billed total for every compared document and at
least 1,000 documents are paired, and the list-price and billed costs agree on which arm costs more.

## Per-run figures

Written under `<run tree>/figures/<run_id>-<iNN>.<figure>.svg` by `sandbox report build --run`.
A figure is drawn only when the run has the data for it.

| Figure | Question it answers | How to read it |
| --- | --- | --- |
| `routing` | Where did each document go? | One bar per class: archived right, archived wrong, sent to a person, failed (no answer). Counts sit inside the segments and n at the bar end |
| `confidence` | Does the class probability rank right answers above wrong ones? | Dots for right and wrong answers. The title reads the AUROC: above 0.5 ranks right above wrong, below 0.5 ranks wrong above right, 0.5 does not separate. With under 5 errors the title says there are too few to judge |
| `risk-coverage` | What error rate does a probability floor buy at each coverage? | Step line. The black point is where the run actually routed. Drawn only when there is at least one error |
| `form-mass` | Does the document-form probability separate defects from intact documents? | Dots per group with the 0.5 park line |
| `park-reasons` | Which rule parked documents? | Bars per rule. A document can trigger several rules, so the bars can sum to more than the parked count |
| `subclass` | How accurate is the subclass among archived documents, per class? | Bars with Wilson 95% whiskers and k/n labels. Wide whiskers mean a small n, not a confident result |
| `latency` | How does latency grow with document size? | Log-log scatter. Median in the title; p95, throughput and cost per 1,000 in the subtitle |

## H5 comparison figures

Written by `compare_sorter_arms.py --figures DIR` or `--write`. Arm A is the reference (the LLM
sorter); each `--b` is compared with it.

| Figure | Question it answers | How to read it |
| --- | --- | --- |
| `runtime` | How long does each arm take for the same documents? | Bars of total time, labelled with documents/min and hours per 100k documents. Every arm uses one basis, stated in the subtitle: wall-clock run time when each run held exactly the compared documents, otherwise active time from first request to last answer. When another document of a run ran inside that window, or the timing is incomplete (a request or another item has no end time), the subset has no run time of its own: the figure is left out and the digest prints no speed-up. Run time is only comparable at the same concurrency, and the figure says when it differs |
| `latency` | How long does one document take? | One dot per document on a log axis, with the median marked. The median is the digest's p50 (nearest rank over every latency), so figure and digest agree |
| `quality` | Is the decision model non-inferior? | Forest plot of candidate minus reference with the 95% paired bootstrap interval. Dashed red lines are the margins (2 pts macro-F1, 4 pts subclass unit); the black tick is the exact one-sided test bound |
| `routing` | How many documents does each arm send to a person, and how many does it archive wrongly? | Stacked bars in status colours |
| `cost-quality` | What does each arm cost for its accuracy at this sample's document-length mix? | Cost per 1,000 documents against subclass-unit accuracy. The axis label and subtitle state the cost basis (see [Cost](#cost)) |
| `pricing` | What does each model charge, by prompt size? | List input price per 1M tokens against prompt size (log axis), from `config/api_prices.yaml` with its checked date. Tick rows show each compared call's prompt size, so you can see which price tier each one falls in. Output tokens are billed separately |

A multi-call document puts one tick per call in the `pricing` figure, at that call's size (from
`call_usage` when recorded, otherwise the document's prompt total split evenly over its calls).
Cost is priced the same way.

## Cost

Cost is the easiest number to misread, so the figures and digest follow one rule:

- `per_1k_docs_usd` is **list price × tokens** for every arm, from `config/api_prices.yaml` and
  `config/decision_models.yaml`. It is an estimate, not a charge.
- A billed total (`provider_reported_usd`) is used only when it covers every compared document.
  The figure plots billed totals only when every arm has one; otherwise it plots list-price cost
  for all arms and names the unbilled arms.
- No figure title or digest line says one arm is cheaper or dearer until every arm is billed
  **and** at least 1,000 paired documents are compared (`sorter_arms.COST_CLAIM_MIN_DOCS`).
  Before then the title reads, for example, "Cost is not yet comparable: n = 20 and LLM sorter
  cost estimated".
- The digest's cost lines are list price × tokens ("list-price cost per 1k docs"). Even on a
  clean billed sample, they stand for the billed direction only when both agree; otherwise the
  digest says `list-price and billed costs disagree on direction for <arm> and <arm>`. Every pair
  of arms is checked, so a reversed ranking between two candidates also blocks the claim.
- H5's lower-cost leg is a cost claim too. An arm whose three tests pass on list-price cost is
  reported as `undecided`, not `SUPPORTED`, until every arm in the comparison is billed, priced
  and in agreement. The digest re-checks this for reports saved before the gate existed.
- Per-document cost depends on the length mix: qwen3.7-flash is tiered by prompt size and
  charges for output, while the decision model charges a flat input-only rate. The `pricing`
  figure shows both schedules. Check the sheet with `python scripts/refresh_api_prices.py --check`
  before quoting a price.

## Colours

Colour follows the system, never its rank, and is the same in every figure:

| Role | Colour |
| --- | --- |
| Decision model | blue `#2a78d6` |
| LLM sorter | orange `#eb6834` |
| A third system | aqua `#1baf7a` |
| Reference or neutral | grey `#b4b2a9` |
| Failed, no answer | slate `#52514e` |

Status colours (good, warning, critical) appear only where colour means an outcome, as in
`routing`, and always with a text label.

## The linter

```bash
python -m mailroom_sandbox.figure_style lint reports/campaigns/rb1/<experiment>/<run>/i01/figures
```

It checks each figure's title, subtitle, axis labels, legend and source line against the house
text rules:

- every figure has a title, and no text runs over its length limit;
- sentence case, and no full stop at the end of a title or axis label;
- no code identifiers (`snake_case`) and no run or document ids in a title;
- no hedged plurals such as "error(s)", and no repeated words;
- no text below the minimum type size, and the SVG declares the system font stack.

It prints one line per problem and a summary such as `6 figure(s) checked, 0 with problems`.

| Exit | Meaning |
| --- | --- |
| 0 | Every figure is clean |
| 1 | At least one figure has a problem (listed above the summary) |
| 2 | Usage error, a path that does not exist, or no SVG found: an empty check never passes |

## When something goes wrong

- **`compare_sorter_arms: ... unpaired` (exit 2).** The runs do not cover the same documents.
  Restrict both to a split set with `--set`, or compare runs drawn from the same set.
- **`--write stores evidence; mock runs are not evidence` (exit 2).** Drop `--write` and use
  `--figures DIR` to look at mock output; it will be labelled simulated.
- **Refusal naming a split.** The runs' locks name different splits, or `--split-dir` differs
  from theirs. Leave `--split-dir` unset unless you know the runs drew from that split.
- **A report tree has only `latency.svg`.** It was built before the full figure set. Rebuild it
  with `sandbox report build --run <run id>`, then `--campaign rb1`.
