---
name: experiment-figures
description: >-
  How this repository makes figures for experiments: per-run figures for LLM-sorter and
  decision-model runs, the sorter-vs-decision (H5) comparison (total run time, latency, quality
  against non-inferiority margins, routing, cost), form-floor and threshold calibration, and any
  new experiment comparison. Covers the fixed colour roles, the type scale, finding-as-title text
  rules, uncertainty, provenance, the figure-text linter and the render-and-look review. Use it
  whenever you create, change, review or explain a chart, plot, figure, SVG or visual in this repo,
  add a figure to a report or campaign, compare runs or arms visually, or are asked to make
  results "presentable", "publication quality" or "professional", even if the word figure is
  never used. It extends the general dataviz skill; read this one for anything in this repo.
---

# Experiment figures

A figure here is evidence in a decision (adopt a question set, accept a sorter arm, set a
threshold). It must say what it shows, be right about it, and look like every other figure in the
repo so readers compare runs at a glance. The general `dataviz` method still applies (form first,
colour by job, validated palette, thin marks, one axis, table view, render and look). This skill
adds what experiments need on top of it.

## The implementation already exists: use it

| Module | What it gives you |
| --- | --- |
| `src/mailroom_sandbox/figure_style.py` | Colour roles, type scale, `Fig` (deterministic SVG), `heading`, `axis_labels`, `legend_below`, `value_axis`, `wilson`, `humanize`, `lint_svg`, and the `lint` command |
| `src/mailroom_sandbox/decision_figures.py` | Per-run figures for any sorter or decision run (`build`), the paired question-set figure (`paired_svg`) |
| `src/mailroom_sandbox/comparison_figures.py` | Sorter-arm comparison figures from a `sorter_arms` report (`build`) |

Commands:

```bash
# per-run figures: written with every run report
sandbox report build --campaign rb1
# H5 comparison figures (total run time, latency, quality, routing, cost, list pricing)
python scripts/compare_sorter_arms.py --a <llm run> --b <decision run> [--b <another>] --figures <dir>
python scripts/compare_sorter_arms.py ... --experiment-key rb1-r13b --write   # into the campaign tree
# check any figure against the text and typography rules
python -m mailroom_sandbox.figure_style lint <file.svg | directory>
```

Add a new figure to one of these modules, built from the same helpers, rather than writing a
one-off matplotlib script. A figure outside them drifts: its own colours, fonts and wording.

## Procedure

1. **Name the decision.** Write down the question the figure answers and the decision it feeds
   ("is the decision model fast enough to replace the sorter?"). If you cannot, you do not need a
   figure yet. See `references/figure-catalog.md` for the questions each experiment asks and the
   figure that answers each.
2. **Pick the form** from the catalog or the dataviz form heuristic. One measure per axis, never
   two scales; two measures that matter together get a scatter (cost against accuracy) or two
   panels.
3. **Assign colour by role**, from `references/colour-and-type.md`. The system decides the
   colour (decision model blue, LLM sorter orange), never the arm's position; outcome states
   use status colours with a text label; a reference arm or question set is neutral grey.
4. **Show uncertainty and n.** Rates come with a 95% interval (Wilson for a proportion; the
   report's paired bootstrap for a difference) or with n beside them. Below about five errors, a
   ranking metric (AUROC) is shown but flagged as too few to judge. A difference is shown against
   its pre-registered margin.
5. **Write the text** under `references/text-rules.md`: the title states the finding for this
   data, computed from it, in one grammatical sentence; the subtitle says what is measured, on
   what population, with n; axis labels are sentence-case nouns with units; run ids go in the
   source line only. State a cost's basis (billed or estimated from the price sheet).
6. **Render, lint and look.** Run the lint command, then render to PNG and look at every figure:
   label collisions, clipped text, empty panels, a title that no longer matches the data. The
   linter checks text; only looking catches layout.
7. **Test it.** A new figure gets a focused test that builds it from a small fixture, asserts the
   computed title and `lint_svg(svg) == []`, and checks determinism (two builds are identical).

## Rules that are easy to get wrong

- **Every claim in a title must survive the data.** Compute titles from the numbers; recheck
  them whenever inputs change.
- **No cost direction without a clean comparison.** Never say one arm costs more or less, or is
  cheaper, unless every arm's cost is billed and at least 1,000 paired documents were compared
  (`COST_CLAIM_MIN_DOCS`). Per-document cost depends on the document-length mix, and the LLM
  sorter's cost is priced from the sheet, not billed. Below that, the title says why cost is not
  yet comparable ("Cost is not yet comparable: n = 20 and LLM sorter cost estimated"), and the
  ground truth shown is the list pricing itself (`pricing` figure from `config/api_prices.yaml`,
  with its checked date). This holds in notes, summaries and chat too, not only in titles.
- **Compare like with like.** Same documents (paired), same concurrency for run time, same
  pricing basis for cost, same question set unless the question set is the variable. If any
  differs, the subtitle says so, or the figure is not made.
- **Total run time is wall-clock for the same documents.** Report it with documents/min and hours
  per 100k documents; latency per document is a separate figure (a distribution, log scale).
- **Deterministic output.** Figures are committed and diffed. `Fig` pins the hash salt, strips
  dates, jitters by document-id hash and measures text with DejaVu Sans (shipped with
  matplotlib), so macOS and CI produce the same bytes. Do not change the measurement font.
- **No snake_case on a figure.** Class names, park reasons and groups go through `humanize` or
  a label map (`reason_label`, `GROUP_LABELS`).
- **One table view per figure set.** Per-run figures write `analysis/<stem>.figure-data.csv`; the
  comparison figures read `comparison.json`. Every number on a figure is in one of those.

## Review checklist (run before you hand a figure over)

- Title: a finding, true for this data, sentence case, no full stop, 80 characters or fewer.
- Subtitle: measure, population, n, interval method; 120 characters or fewer.
- Axes: units in parentheses, log scale named, percent axes capped at 100%, zero baseline on bars.
- Colour: system and status roles as listed; legend for two or more series; no colour-only meaning.
- Uncertainty: interval or n on every rate; margin line on every non-inferiority difference.
- Provenance: source line names the run or comparison; cost basis stated.
- `python -m mailroom_sandbox.figure_style lint` passes; the rendered PNG has no collisions.

## Reference files

- `references/figure-catalog.md`: experiments, the questions they ask, and the figure for each.
- `references/text-rules.md`: titles, subtitles, labels, legends and source lines, with examples.
- `references/colour-and-type.md`: colour roles, type scale and layout, with the reasons.
