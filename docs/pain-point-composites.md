# Pain-point composites

Two penalty scores built around what a client's document-intelligence team said hurts most
in production: the number of documents a person has to review, errors, and misarchived
documents. Profile `amfam-v1` (the American Family Insurance pain points) sets the default
scale. Code: [`src/mailroom_sandbox/eval/pain_points.py`](../src/mailroom_sandbox/eval/pain_points.py);
tests: [`tests/test_pain_points.py`](../tests/test_pain_points.py).

Every pipeline run (`task: pipeline`) reports both composites. Each document earns
**penalty points** from 0 to 4, and **lower is better**:

- **0**: correct and complete, or sent to a person who really had to see it.
- **4**: sent to a person although the pipeline could have finished it. This is the worst
  outcome on both composites.

## Classification composite

When more than one reason applies, the worst one sets the points. The per-document
`Outcome.reasons` keeps every reason that applied, worst first. Persisted items and the run
summary record only the worst reason, so a zero `missed_review` count does not prove that no
review was missed on a document that was also archived under the wrong class.

| Points | Reason | When |
| --- | --- | --- |
| 4 | `unnecessary_review` | Routed to review, but the row's expected stage is `archived` |
| 4 | `pipeline_failure` | The document errored or did not finish in `archived` or `review` |
| 3 | `wrong_doc_type` | Archived under another class (a misarchive) |
| 2 | `missed_review` | Archived, but the row's expected stage is `review` |
| 1 | `wrong_subtype` | Archived under the right class with the wrong subclass |
| 0 | `necessary_review` | Routed to review, and the expected stage is `review` |
| 0 | `correct` | Archived under the right class (and the right subclass, when the row has one) |

A wrong subclass under the right class costs less than a wrong class. A document whose
extraction is missing because it went to the wrong class gets 3 points here, and its
extraction scores separately below.

## Entity extraction composite

This composite covers only documents whose row has field ground truth.

| Points | Reason | When |
| --- | --- | --- |
| 4 | `unnecessary_review` | As above: the extraction never had to reach a person |
| 4 | `pipeline_failure` | As above |
| 3 | `fabricated` | Values were stated, but none of them is supported by the truth |
| 2 | `low_recall` | Under a third of the targeted entities are correct, including an extraction that stated nothing |
| 1 | `partial` | Some targeted entities are right but not all, or extra values were invented beside them |
| 0 | `necessary_review` | As above: a person had to see it anyway |
| 0 | `complete` | Every targeted entity is right and nothing was invented |

So a partly valid extraction costs less than one with under a third right. That costs less
than a fully fabricated extraction, and a needless review costs the most.

### How each term is measured

- **Targeted entities** are the expected fields that have a value: the Dojo's `tp + fn`
  events. An entity is **correct** when the Dojo scores its field 1.0 (`tp`). The share is
  `tp / (tp + fn)`. Exactly one third is not "under a third".
- **Rows without event counts.** The detailed suite path (corporate records, and any row with a
  subclass) returns no `tp` / `fn`. For those rows the scorer's own per-field counts are used:
  `n_targeted` (targeted fields it scored) and `n_value_correct` (those scored 1.0). Without
  `fp`, the documented-absence hallucinations (`n_hallucinated`) count as values invented on
  empty truth.
- **Invented values** are the Dojo's false positives (`fp`) plus `n_value_wrong`. A false
  positive is a value on a field the truth leaves empty, including a documented absence
  under SHF-001, or an unmatched list item. `n_value_wrong` counts values stated on a
  targeted field that score under `scoring.FABRICATION_MAX_FIELD_SCORE` (0.5).
- A value that scores between 0.5 and 1.0 is a **near miss** (`n_value_partial`). It is wrong
  but not invented, so an extraction with near misses is never called `fabricated`.
- **Placeholders are blank.** A prediction of `null`, `none`, `n/a`, `nan`, `"[]"` or `"{}"` is a
  miss, not a stated value, as the Dojo scores it, so it never counts as invented.
- **Fabricated** means no correct entity, no near miss, and at least one invented value. An
  extraction with one correct entity among nine invented ones is `low_recall`, not
  `fabricated`. Its Dojo false positives (`fp`) still show in the run's `extraction_fp`; its
  `n_value_wrong` values do not, since the Dojo counts a wrong value on a targeted field as `fn`.
- **Contract (CUAD) and merger (MAUD) rows** are scored on clause labels, not fields. Their
  share is the row's `overall_extraction_score`, and they are never called `fabricated`. A row
  with neither event counts nor per-field counts uses the same share.

The scorer reports `n_targeted`, `n_value_correct`, `n_value_wrong` and `n_value_partial` on
each scored extraction row whose scorer returned per-field scores, raw and hotfixed, beside `tp`,
`fp` and `fn`.

## What "unnecessary review" relies on

The row's `expected_stage` (default `archived`) is the truth that the pipeline could have
finished the document. **A run whose rows carry no expected stage cannot tell a needed
review from a needless one, so every review counts as needless.** Before comparing two runs,
check that both use the same expected-stage labels and read the `necessary_review` count.

## Run-level output

A pipeline run's `scores` (in its experiment log record and run report) carry a `pain_points`
block and two flat headline keys:

```text
pain_points_classification_mean   mean points per scored document (0-4, lower is better)
pain_points_extraction_mean       same, extraction composite (None when no row has field truth)
pain_points:
  profile, scale                  the profile id and every point value used
  classification / extraction:
    n, excluded                   scored documents; rows left out (no class / no field truth)
    points, mean                  total and mean penalty points
    score                         1 - mean / 4 (0-1, higher is better)
    reasons                       documents per reason, every reason listed
    by_class                      {class: {n, points, mean}}
  raw_dojo                        the same two blocks on the vendored Dojo pin's scores
  scoring_hotfixes                the fixes the headline used
  scoring_hotfixes_changed        which composite a hotfix moved
```

Each document's `score` in `items.jsonl` carries `pain_points_classification_points` and
`pain_points_classification_reason`, and `pain_points_extraction_points` and
`pain_points_extraction_reason` when it has field truth. `sandbox rescore` recomputes them,
so a finished run can be scored on the composites without a model call.

Rows without an expected class are left out of both composites, and rows without field truth
are left out of the extraction composite. A missing label is never scored as correct
([critical regressions](critical-regressions.md) row 1). Always read `n` beside `mean`.

## Changing the scale

`PenaltyScale` holds every point value and the one-third bar. It refuses an order the client
did not ask for:

- a needless review must cost more than a wrong class, which must cost more than a wrong
  subclass;
- a needless review must cost more than fabrication, which must cost more than `low_recall`,
  which must cost more than `partial`;
- a wrong class must cost more than a missed review, which must cost more than nothing.

A new profile is a new `PenaltyScale` with its own id. Do not change the `amfam-v1` defaults
in place, or runs scored before and after the change stop being comparable.

## Scope and limits

- Only pipeline runs report the composites. Isolated sorter and reviewer runs report
  `routed_to_human_review`, but they have no archive stage to score.
- The composites are sandbox-local. If other repositories need them, they belong in
  `llm-dojo-scoring`, which owns every constellation-wide metric.
- Mock and replay runs report the composites like any other score. Never cite those numbers
  as model evidence ([critical regressions](critical-regressions.md) row 8).
