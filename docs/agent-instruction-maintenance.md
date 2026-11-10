# Agent instruction maintenance

Repository instruction files contain both operating rules and factual claims.
Follow the applicable instruction hierarchy, including the user's current
direction, while checking factual claims against evidence. A committed
`AGENTS.md`, `CLAUDE.md`, skill or canonical agent prompt can contain stale facts.

## When to check

Make this a routine part of work, with a scope proportional to the task:

- At task start and every resumed session, read the applicable instruction files
  in the checkout and any scoped rules for the paths being changed. Validate the
  facts the task depends on before acting on them.
- During long-horizon experiments or feature work, recheck at meaningful
  milestones and when resuming after a pause or context handoff. Compare with the
  starting revision so intervening changes are visible.
- After an experiment finishes or a feature, configuration, dependency, vendor
  snapshot or release changes, revisit the instructions describing that behavior.
- After switching branches, rebasing or changing a PR stack's base, reread the
  affected guidance from that checkout. Before handoff or merge, check it against
  the final diff and current-head verification results.

This is an evidence check, not an instruction to perform a full repository audit
or rerun an expensive experiment at every checkpoint. Expand the search when a
stale claim reveals the same problem in related instructions.

## What to validate

| Claim | Evidence to inspect |
| --- | --- |
| Package or tool version | `pyproject.toml`, generated `requirements/`, lockfiles, image pins and the relevant environment's installed version; report declared and installed values separately |
| Published release or tag | The owning repository's release/tag and resolved commit; a changelog heading or development version alone does not prove publication |
| Vendor or dataset revision | `_VENDOR_PINS` in `src/mailroom_sandbox/cli.py`, vendor `VENDOR.md`, dataset configuration and the experiment's own locks; preserve explicit revisions |
| Command, option, default or configuration field | Current parser/schema/implementation, configuration and cheap `--help`, offline mocks or focused tests where needed |
| File, link, ownership or source reference | The target file/anchor in the current checkout, canonical package and pinned source revision; use official upstream documentation for external behavior |
| Experiment result, calibration or completion status | Run ID, source commit, dataset/prompt/spec locks and actual report artifacts; distinguish planned, running, completed, simulated and superseded evidence |
| Quality gate or runtime claim | Current CI configuration and current-head hosted results; compare matching workloads and retain coverage/test gates |

Use local source and immutable artifacts first. When a task depends on a mutable
external fact such as a release, model availability, service API or price, verify
it through the owning service or official documentation and record the check
date. If offline or unable to verify it, label the claim unverified and explain
the consequence; do not invent a current value. Ask for missing information only
when the uncertainty blocks the authorized next action.

Historical releases and measured results remain valid as dated history. Label
them with their revision/run and superseding reference rather than replacing
them with an unrelated latest value. A newer upstream release does not authorize
an upgrade, pin change, vendor refresh, paid run or rewrite of a locked experiment.

## Correct and carry the evidence forward

1. Identify the stale claim and its canonical source. Search related instruction
   files, selected skills, runbooks and examples for the same failure pattern.
2. Correct the owning documentation and affected entry points. Keep fixes within
   the current PR's scope; use a linked documentation follow-up for separately
   scoped work. Preserve historical evidence and explain what superseded it.
3. For generated agent adapters, change the canonical prompt in its home package
   and follow the [roster sync workflow](subagents-family-sync.md). Do not patch
   generated stubs or silently propagate edits to unrelated checkouts.
4. Verify changed links, examples and Markdown with cheap local checks. Use
   focused, single-worker tests without coverage if behavior needs verification;
   leave full suites, coverage, campaigns and benchmarks to hosted CI under the
   [test policy](../AGENTS.md#tests). Check which jobs actually exist: current
   CircleCI has no dedicated campaign or runtime-benchmark job. Arrange scoped
   hosted verification when needed, preserving live/spend gates, and record
   absent results as pending or unverified.
5. In the existing PR description, experiment report or handoff, record the
   checked scope, checkout/source revision, external check date when applicable,
   corrections and unresolved facts. Do not claim a complete audit when only a
   scoped check was performed.

A compact handoff entry can read:

> Instruction check: compared `AGENTS.md`, `CLAUDE.md` and the selected skill with
> the final source revision and run locks. Corrected the stale command example;
> validated the changed links and CLI help. The external release claim remains
> unverified while offline and is not used to justify an upgrade.
