## Summary

<!--
Executive summary, in your own words: what changed and why.
Do not paste the requester's prompt, direct quotes, names, handles or credentials,
and do not use a "User description" section.
-->

## Changes

-

## Validation

<!-- Commands, tests, hosted checks, and what remains unverified. -->

-

## Critical regressions

<!--
Check the diff against docs/critical-regressions.md. For each row it touches, name the
guard that covers it and its output from this head, or say why it does not apply.
-->

- [ ] Ground truth is present and scored n is reported (1)
- [ ] Document selection matches spec and lock; no silent drift (2)
- [ ] No tuning/evaluation leakage; in-sample numbers labeled (3)
- [ ] Served model and provider match the pins; no alias substitution (4)
- [ ] Spend caps and prices intact; nothing paid launched by an agent (5)
- [ ] Locked code and vendor revisions ran; `vendor/` unedited (6)
- [ ] Credentials routed correctly; no secrets or requester details in text (7)
- [ ] No mock or replay output cited as evidence (8)
- [ ] Resume/retry cannot reuse or corrupt a measurement (9)
- [ ] Offline paths stay offline; the suite stays network-free (10)
- [ ] No quality gate loosened (coverage 84, lint, snapshots, CLI reference) (11)
- [ ] Explicit numeric confidence of zero stays zero (12)
- [ ] A Decisions response is charged once (13)

## Docs

<!--
tests/test_docs_drift.py fails when one of these is missing; tick what this PR touched.
-->

- [ ] A new or moved page is linked from `docs/README.md` (old paths added to `_STALE_DOC_PATHS`)
- [ ] A new or retired hotfix has its row in `docs/vendor-hotfixes.md` or `docs/scoring-hotfixes.md`
- [ ] A new top-level `sandbox` command is in the README CLI block
- [ ] A new top-level directory is in the `docs/setting-up/LAYOUT.md` table

## Risks / follow-ups

<!-- Known limitations, follow-up issues/PRs, and rollback notes. -->

-
