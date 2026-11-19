# Figure text rules

Text is the part of a figure people quote. These rules keep it accurate, short and consistent,
and `python -m mailroom_sandbox.figure_style lint` checks the mechanical ones.

## Title: the finding, for this data

- One grammatical sentence that states what the figure shows for these numbers, computed from
  them. A reader who sees only the title should learn the result.
- Sentence case, no full stop, numerals for numbers, `×` for ratios, an en dash for ranges
  (`3.7–6.3×`), 80 characters or fewer.
- Subjects agree with numbers: "1 class error", "3 class errors", "1 of 50 was". Never "(s)".
- Name systems, never run ids: "the decision model", "decision model runs", "the LLM sorter".
- Only claim what the data supports. Say "not shown at n = 20" rather than implying equivalence;
  "too few to judge" under five errors. Never state a cost direction ("costs more", "cheaper")
  unless every arm is billed and at least 1,000 paired documents were compared; otherwise say
  "Cost is not yet comparable" and why, and point to the list prices.
- When a computed title would run over 80 characters, fall back to a plain description of the
  measure, and put the numbers in the subtitle.

| Weak | Better |
| --- | --- |
| Where each document went | 9 of 67 constructed defects reached extraction |
| Total run time | Decision model runs finished 3.7–6.3× faster than the LLM sorter |
| Cost vs quality (20 documents, one arm estimated) | Cost is not yet comparable: n = 20 and LLM sorter cost estimated |
| Only 1 class error(s) | Only 1 class error: too few to judge the ranking |
| Latency for rb1-r13b-smoke20c | Median latency was 0.63 s per document |

## Subtitle: what, on whom, how many, how uncertain

Measure, population and n, then method notes, separated by ` · `. 120 characters or fewer. It
also carries the caveat a reader needs before acting: estimated costs, differing concurrency,
the interval method, "lower is better".

> Wall-clock run time on the same 20 documents at concurrency 8
> Each arm minus the LLM sorter · 95% paired bootstrap · dashed red: margin

## Axis labels

Sentence-case noun phrase with the unit in parentheses: `Total run time (s)`, `Cost per 1,000
documents (USD)`, `Latency (s, log scale)`. Name a log scale. Percent axes use `%` tick labels and
stop at 100%. No snake_case, no abbreviations a reader must decode (write "documents", not
"docs").

## Category labels, legends, annotations

- Humanize identifiers: `corporate_record` → `Corporate record`; park rules through
  `reason_label` (`margin` → `Class margin too small`).
- Legend entries are short sentence-case nouns: `Archived, correct`, `Parked for review`.
- Direct labels sit beside the mark in secondary ink, never in the series colour.
- Value labels: counts as integers, rates as `35/43` or `81%`, differences as signed points
  `+5.0 [+0.0, +15.0]`.

## Source line

Bottom-left, muted, 7.5 pt: `Source: run <run id> · <system>` or `Source: <key> sorter-arm
comparison · <set> · reference <run id>`. This is where ids belong, so a figure separated from
its report can still be traced.
