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

## Hotfix IDs

IDs need not be consecutive. A range keeps its number when it lands; an open PR whose current ID
collides takes the one assigned here.

| Range | Owner | Status |
| --- | --- | --- |
| `HF-020`–`HF-022` | #425 (and #439, which carries it): corporate schema composition | open |
| `HF-023`–`HF-024` | Phase 3 subclass schemas (#438) | landed |
| `HF-025`–`HF-027` | Phase 4 correcting judge (`judge:`) | landed with the Phase 4 PR |
| `HF-028` | #437 specialist handoff check (registered there as `HF-021`; renumber on rebase) | open |

The next free vendor hotfix ID is `HF-029`. Scoring hotfixes have no open collision; the next free
ID is `SHF-017`.

## Critical-regressions rows

Rows must stay consecutive, so a row takes the next free number when its PR lands, not a number
reserved in advance. On `main` the last row is 22. Phase 4 adds no row (it names its guards on
existing rows). The open claims that collide today:

| Open PR | Rows it adds today | Topic |
| --- | --- | --- |
| #425 | 23, 24, 25 | corporate repair (reviewer identity, missing-field admission, applicability) |
| #439 | 24 (same text as #425's), 26 | merger admission, merger money evidence |
| #436 | 23 | an overlay field list keeps a label the policy still calls stale |
| #437 | 23, 24 | specialist handoff refusal; the mock echoing labels |

Landing #425 and #439 first keeps their 23–26. Whichever of #436 and #437 lands next renumbers its
rows to follow, and updates the rows it cites in its PR description and in any test or doc that
names them.

When a PR lands, mark its range landed here in the same change.
