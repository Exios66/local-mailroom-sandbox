# Colour roles, type and layout

Values live in `src/mailroom_sandbox/figure_style.py`; this file says why.

## Colour follows the role

| Role | Colour | Where |
| --- | --- | --- |
| Decision model | blue `#2a78d6` (categorical slot 1) | its bars, dots, lines, and every single-series mark on its run figures |
| LLM sorter | orange `#eb6834` (slot 2) | same, for LLM-sorter runs and arms |
| Third system | aqua `#1baf7a` (slot 3) | any other model in a comparison |
| Reference (base question set, baseline arm of the same system) | neutral `#b4b2a9` | the "before" in a paired figure |
| Archived, correct | good `#0ca30c` | routing states |
| Parked for review | warning `#fab219` | routing states and parked dots |
| Misarchived | critical `#d03b3b` | routing states; non-inferiority margins |
| No truth class | neutral | routing states |
| Failed, no answer | slate `#52514e` | routing states; never shown as archived |
| Passed (not parked) dots | slate `#52514e` | strip plots |

Why these:

- Slots 1–3 are the three categorical colours that pass the dataviz validator for **all pairs**
  (not only neighbours), so they stay distinct on scatters and strips where any two can touch.
  A fourth system folds into "Other" or gets its own panel.
- The system colour is fixed across every figure, so a reader who has learned "orange is the LLM
  sorter" never relearns it, and a filter or a missing arm never repaints the others.
- "Parked" is amber everywhere, bars and dots alike, so the same state never has two colours.
  Amber and the other status colours always come with a text label (legend or direct label),
  because amber is under 3:1 against the surface.
- Two runs of the same system share its colour and are told apart by label, not by a new hue.

## Type

Measured with DejaVu Sans (ships with matplotlib, so layout is identical on every machine);
the SVG declares `system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Helvetica, Arial,
"DejaVu Sans", sans-serif`, which renders narrower, so text never overflows its measured box.

| Element | Size (pt) | Weight, colour |
| --- | --- | --- |
| Title | 12 | bold, primary ink `#0b0b0b` |
| Subtitle | 9.5 | regular, secondary ink `#52514e` |
| Axis label | 9 | secondary ink |
| Tick label | 8.5 | secondary ink |
| Legend | 9 | primary ink |
| Annotation, value label | 8.5 | secondary ink (white or black inside a filled bar) |
| Source line | 7.5 | muted `#898781` |

Nothing smaller than 7.5 pt; the linter rejects it.

## Layout

- Width 6.4 in (one report column). Height grows with the number of rows, about 0.4–0.55 in each.
- Title and subtitle flush with the figure's left edge (the y tick labels), not the plot's,
  placed by `fs.heading` after layout so spacing is fixed in points.
- Legend centred under the x-axis label (`fs.legend_below`), never over data.
- Gridlines on the value axis only, hairline `#e1e0d9`, behind marks; no tick marks on the
  category axis; top and right spines off.
- Horizontal bars for categories with long names; bars start at zero; a 1.5 px surface gap
  between stacked segments.
- Log scales use plain 1–2–5 tick labels (`0.5`, `1`, `2`, `5k`), never powers of ten.
