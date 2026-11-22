# Recent main landing integrity audit

The audit covers the nine most recent main landings: #384 and #390–#397,
through `1f1c3a4b72e8eeca671261912d9e13a7c41956e0` on 2026-11-22.
It checks shipped behavior, review replies and unresolved requests, source
ownership, artifact integrity, and matching hosted gate evidence.

## Findings and corrections

| Area | Correction | Guard |
| --- | --- | --- |
| Pain-point report truth | Hash the exact prepared dataset bytes parsed; refuse missing/mismatched hashes and duplicate truth IDs. Shared truth loading rejects duplicates before indexing local or rebuilt Hub truth, protecting rescore too. Explicit replacement truth keeps its own provenance. | `tests/test_pain_points_report.py`, `tests/test_corpus.py`, `tests/test_rescore.py` |
| Report completeness | Refuse prepared, running, paused and foreign checkpoints; verify legacy rescore ancestry, refusing missing/foreign/cyclic source links, and write derived identities for new rescores. Display terminal state and locked row count; a bundle without a checkpoint is visibly unverified. | `tests/test_pain_points_report.py`, `tests/test_rescore.py` |
| Suite teardown | Mock, offline and dry-run execution never reaches live cleanup. Apply the effective `--local` override to cleanup targets; disclose when none are live. A failed cleanup returns its error and no longer prints success. | `tests/test_run_suite.py` |
| Notebook state | Scope warning filters and restore the prior logging-disable level on success and failure. | `test_quiet_pipeline_logs_restores_kernel_state` |
| Portable demos | Sanitize published output paths, including the selected kernel interpreter, resolved symlinks and both macOS temporary-path aliases. Skip binary MIME payloads. Recorded mock results and embedded PNGs remain unchanged. | `tests/test_render_notebook_demos.py` |
| Visualizer refresh | Retain the replaced checkout after the final clean check, preserving later writes through existing file descriptors. Print the recovery path for manual inspection. | `test_visualizer_retains_writes_through_an_old_open_descriptor` |
| Label-cache publication | Export and overlay staging share a stable sibling lock from initial read through publication. Refuse foreign directories and unmanaged deletions; prepare the replacement before swapping, restore interrupted moves and retain recoverable bytes if rollback fails. | `tests/test_export_mailroom_cache.py`, `tests/test_stage_label_overlay.py` |
| Operator guidance | Narrow whole-document refusal to the protected readers; distinguish isolated item errors from pipeline review. Document manual teardown after both concurrent calibration runs. Correct remaining refusal, fleet-capacity and label-admission wording. | Focused source comparison, CLI-reference generator and Markdown lint |

## Review reconciliation

- PR #398 implements the repairs. Its 15 review threads were verified and resolved,
  including the subsequent multi-step legacy rescore objection.
- #384's two open notebook findings are covered by the notebook and demo fixes.
- #395's disabled-fit route findings already have their fix on main:
  `apply_context_fit` records explicit routes before the disabled-fit return.
  `test_disabled_fit_still_records_an_openrouter_route` verifies refusal.
- #395's run-ID resume finding already has its fix on main: `run_job`
  checks `context_fit_resume_detail` before activation and document execution.
  Matching stamps and legacy locks remain accepted; the focused runner tests
  cover mismatch and legacy compatibility.
- #390's final recovery objection is covered by retaining the old visualizer
  checkout. Its refusal docstrings now describe the actual precedence and
  replay checks.
- #391's transport fixes include the Docker bridge bind and environment-enabled
  Compose profile guard. Its remaining capacity explanation now describes
  unused sequence slots rather than unused machines.
- #392's remaining admission wording distinguishes generated dates from
  Hub-backed and reviewed cells; only populated corrections require a quote.
- #396's concurrent r2 instructions now omit automatic suite teardown and name
  the exact follow-up configuration. #397's guide distinguishes intake's soft
  failure and the judge/arbiter excerpt limits.

Domain review: scoring algorithms remain Dojo-owned. The pain-point scoring
copy, all SHF/HF targets, vendor snapshots, model/provider pins, dataset pins,
split assignments and immutable run artifacts are unchanged. The repairs are
sandbox reporting, lifecycle, publication and documentation changes.
Critical-regression rows 1, 2, 6–11, 15 and 16 apply; CP-01, CP-04, CP-08,
CP-14 and CP-16 identify the related campaign boundaries. No guard was loosened.

## Verification evidence

- Repair code revision `25f5d5d1c1df887ffc7c7e7b36377920e41ad957` passed all six
  CircleCI gates in workflow `6793d073-c38b-4f04-aef1-b8131f2ffb43` on 2026-11-22:
  lint, generated files, no-session-links, full tests, notebook execution and coverage.
  Job #3109's four shards total 5,288 passed and 42 skipped; notebook job #3107
  passed 101 tests, including the actual demo-renderer kernel integration.
  Coverage job #3110 reports 89% (rounded display), above the unchanged 84% floor.
  This closeout documentation still requires the final PR head's hosted gates.
- All six CircleCI gates passed on the nine merged PR heads and on the starting
  main revision. These are prior hosted results, not certification of the new
  repair commit; its own hosted gates remain required before merge.
- The first focused repair checks passed 55 tests. Related context-fit,
  experiments, context-plan, production-slice, fleet/Compose, staged-overlay,
  builder and export checks passed 217 tests with three optional skips.
- Subsequent focused repair checks passed 66 tests; maintenance/fleet checks
  passed 46 tests. These overlapping invocations are reported separately and
  must not be summed as unique tests. Final-head results belong in the PR.
- Review repairs passed 204 focused tests; the NotebookNode fix passed 9 renderer
  tests, and legacy-chain verification passed 54 report/rescore tests. The first
  hosted renderer regression exposed a dict-subclass conversion defect; preserving
  output node types fixed it, confirmed by the hosted notebook result above.
- The hotfix checker reports HF-001–010 applied and SHF-001–014 current.
- Three committed label-release output digests match their summary. The release
  has 3,302 unique document IDs and 48,688 unique document/field provenance cells.
  This checks byte and structural integrity, not semantic truth for every label.
- The local interpreter imports this checkout. Focused tests use one worker and
  no coverage; the full suite, notebook execution and unchanged 84% coverage
  floor remain hosted gates.

Instruction validation compared `AGENTS.md`, `CLAUDE.md`, the dispatch contract,
the sandbox router and dataset skill, current source, CI configuration and run
pins. The campaign checklist's stale prepared status for #368/#369 is corrected
to their verified 2026-11-19 merges. No dependency or pin upgrade was selected.

## Remaining acceptance

This audit does not authorize or certify paid runs, deployed-worker parity,
new model-quality measurements, held-out access or human label adjudication.
G0 and the live/human gates in the campaign contract remain separate acceptance
work. Existing measurements and experiment locks retain their original basis.
Visualizer recovery directories deliberately consume disk until an operator
has closed old writers and inspected them; they are not deleted automatically.

## Follow-up: PR 399

PR 399 (`987145da18c7d26778bcdb73998aa0ebcd8ea3d1`, 2026-11-22 18:41 UTC) landed
after this audit closed. It was verified separately, with the same standard:

- All six CircleCI gates passed on the PR head (`84aca2b5`, workflow
  `67922a02-87bf-47a6-94cf-1832a26f1f00`), plus CodeFactor, GitGuardian and the
  Cursor approval agent. CodeRabbit's check is neutral.
- The merge tree is byte-identical to the tested head, and local `main` matches
  `origin/main` cleanly at the merge commit.
- Its only review thread (CodeAnt: colliding dated-report stems for rerun arms)
  is resolved and verified in `0b8c443d` and `51e51b28`, squashed into the
  merge; the PR body describes both fixes.
- Focused single-worker, no-coverage local reruns pass: dated reports, #214
  window configs, scoring hotfixes and routing calibration, 180 passed.
- The shipped artifacts are on main: `reports/SAND-214/2026-11-21/`,
  `reports/serving/SAND-214/`, the run-ledger start rows, both new window-arm
  configs, the 150-document confidence-cutoff config and the exclude lists.
- No paid work was launched by this audit. The window-length suite and the
  confidence-cutoff run remain unexecuted and gated on the owner's go-ahead;
  merger quality (0.091) is an open extraction problem before either result is
  usable.
