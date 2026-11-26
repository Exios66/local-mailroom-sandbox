# Post-merge integration review

Reviewed 2026-11-25 against main
`f1b7ce5e44862abfb52a32cc14f6e8831cf2a1ca`, after #413, #414 and #415 merged.
Remote main had no additional commits at inventory time. GitHub connector
`search_prs` and `gh pr list --state open` both returned zero open PRs.
The scope therefore revisits the integrated fixes and their adjacent callers;
it does not imply that later landings or live deployment were reviewed.

## Findings

| Finding | Before repair | Guard and expected behavior |
| --- | --- | --- |
| Confusion-pair node clicks still highlight class neighbors. | The actual render prefix chooses neighbors from run/class counters while displayed graph counts use the pair. The regression fails because the pair's archive neighbor is absent and an unrelated human-review neighbor remains. | Graph count helpers now supply node counts, edge counts, neighbor traffic and the selected-node count. The existing JavaScript execution regression covers clicked-node neighbors; clearing the pair restores previous behavior. Critical row 20. |
| Shared snapshots inherit filters from their receiving viewer. | Export omits document filters and the tab; import leaves the receiving cell, searches, outcome and miss toggle unchanged. The new export/import regression fails with foreign filters still selected. | Focus carries filters and tab; import resets filters before restoring validated values. Legacy exports use defaults, malformed fields are ignored. `test_shared_floor_digest_restores_its_filters_and_clears_foreign_filters`. Critical row 21. |

Browser checks used the committed floor selftest's synthetic run fixture and
the actual current builder, with original and repaired templates served over
loopback. Before repair, selecting `letter → contract` under DEBUG and class
`contract`, then selecting classify, showed `2 (class)` and highlighted intake,
extract and human_review. After repair it shows `1 (pair)` and only intake as
a neighbor. The arrival diagnosis continues to identify document d3 in both.
Export/import before repair retained the receiver's foreign cell and searches;
after repair it restores the sender's pair, searches and DOCUMENTS tab. An older
export clears those filters. These are simulated UI checks, not model evidence.

## OpenRouter reconciliation

- #413 remains present with invalid attempt/timeout refusal, one transport budget,
  Retry-After handling, per-attempt absolute run checks and single usage charging.
  Backend preparation still starts before the transport timer; the earlier caller
  node deadline remains unpropagated, as documented in the original audit.
- #414 remains present with shared Decisions model-window arithmetic. Real
  reviewer schemas, model variants and frozen question-file behavior are covered
  by the focused checks. Tokenizer fit for non-Luna models remains unverified.
- #415 remains present with pair precedence for graph counts, repeat badges and
  node arrival/repeat/archive diagnostics. This review extends that scope to
  clicked-node neighbors and shared-view persistence.
- Full PR discussion replies were reread for all three landings. The prior
  attempt validation, timer-scope and node-diagnostic findings are addressed in
  current code. Quota notices supply no review evidence.

## Validation and limits

- Main `f1b7ce5e` has six successful CircleCI statuses: lint, generated checks,
  full tests, coverage, notebook regressions and no-session-links. Workflow:
  [0ecfa412-bc3f-4ecd-a385-a5f213b272e9](https://app.circleci.com/workflow/0ecfa412-bc3f-4ecd-a385-a5f213b272e9).
- Before repair, both added/extended JavaScript regressions fail on current main.
- After repair: `tests/test_floor_app.py`, `tests/test_floor_digest.py`,
  `tests/test_decision_transport.py`, `tests/test_decision_windows.py` and
  `tests/test_call_guard.py`: **149 passed**, one worker, no coverage.
  The command uses the original checkout's explicit Python 3.14.5 interpreter
  with `PYTHONPATH=$PWD/src`; the imported package resolves to this worktree.
- The worktree is isolated from the original checkout's experiment files.
  No vendor, provider, dataset, prompt, lock or dependency changes are included.
- Instructions were checked against current source ownership, CI configuration,
  Modal 1.6.4/vLLM v0.29.0 declarations and the unchanged 84% coverage floor.
  This does not assert an installed or deployed dependency upgrade.
- Final repair head and hosted gates are recorded in the follow-up PR. The full
  suite and coverage remain CI work; local checks do not replace them.

No live model calls, deployment, environment upgrades or experiment relocking
occurred. Deployment identity and the original audit's remaining Decisions
catalog provenance, non-Luna tokenizer/calibration, truncation reporting and
caller-node deadline issues remain separate acceptance or follow-up work.
