# Numbering reservations for open work

Hotfix IDs (`HF-*`, `SHF-*`) and [critical-regressions](critical-regressions.md) row numbers are
identities: run locks record hotfix IDs, and PRs cite rows by number. When two open PRs pick the
same number, the second one to land would overwrite the first in `apply_hotfixes()` and in every
lock's `vendor_hotfixes` (an ambiguous lock), or cite the wrong row. This page assigns the numbers
open work uses, so the PR that lands second knows its number before it rebases.

`tests/test_docs_drift.py` guards the result on every head:

- `test_every_hotfix_id_is_registered_once`: no `HF-*` or `SHF-*` ID is registered twice;
- `test_critical_regression_rows_are_numbered_once_in_order`: rows run 1..N, each number once;
- `test_the_reservations_page_lists_every_registered_hotfix_range_it_reserves`: a range below that
  is registered on the head is marked landed, and an open range is not registered.
- `test_the_next_free_hotfix_ids_follow_every_registered_and_reserved_id`: the next free `HF-*` and
  `SHF-*` IDs below are one past the highest registered or reserved ID.

## Hotfix IDs

IDs need not be consecutive. A range keeps its number when it lands; an open PR whose current ID
collides takes the one assigned here.

| Range | Owner | Status |
| --- | --- | --- |
| `HF-020`–`HF-022` | #425 (and #439, which carries it): corporate schema composition | landed on this branch |
| `HF-023`–`HF-024` | Phase 3 subclass schemas (#438) | landed |
| `HF-025`–`HF-027` | Phase 4 correcting judge (`judge:`) | landed with the Phase 4 PR |
| `HF-028` | #437 specialist handoff check (registered there as `HF-021`; renumber on rebase) | open |
| `HF-029` | Phase 5 part 1 evidence check (`job.evidence_check`) | landed with the Phase 5 part 1 PR |

The next free vendor hotfix ID is `HF-030`. Scoring hotfixes have no open collision; the next free
ID is `SHF-019`. A PR that registers or reserves an ID advances these in the same change
(`test_the_next_free_hotfix_ids_follow_every_registered_and_reserved_id` checks them).

## Critical-regressions rows

Rows must stay consecutive, so a row takes the next free number when its PR lands, not a number
reserved in advance. Phase 4 adds no row (it names its guards on existing rows).

| Row | Landed with | Topic |
| --- | --- | --- |
| 23 | #436 | an overlay field list keeps a label the policy still calls stale |

The current integrated branch retains main's rows 23 (stale overlays) and 24 (floor history),
and appends the corporate repair guards as rows 25–27. The merger follow-up #439 appends its
currency-evidence guard as row 28. Other open work takes the next free rows after its base:

| Open PR | Rows in the integrated stack | Topic |
| --- | --- | --- |
| #425 | 25, 26, 27 | corporate repair (reviewer identity, missing-field admission, applicability) |
| #439 | 26 (inherited), 28 | merger admission and merger money evidence |
| #437 | next free rows on its merge base | specialist handoff refusal; the mock echoing labels |

When another branch lands first, renumber only the unmerged rows and update their citations.
