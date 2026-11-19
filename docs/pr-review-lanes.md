# PR review lanes

How automated and subagent reviewers divide work on
`local-mailroom-sandbox`. Use this so bots do not duplicate threads and so
silent-failure classes still get a dedicated pass.

## Lane map

| Reviewer | Trigger | Owns | Does not own |
| --- | --- | --- | --- |
| **CodeRabbit** | Every PR (see [`.coderabbit.yaml`](../.coderabbit.yaml)) | Docs/link/consistency path instructions; markdownlint / yamllint / gitleaks surface; code↔doc sync | Silent score/draw/model/cost correctness; Dojo ownership; SHF/HF fingerprints |
| **CodeAnt** | External GitHub app (no in-repo config) | Generic code quality, security nits, API misuse | Domain regression checklist; spend-gate semantics |
| **CodeFactor** | External GitHub app (no in-repo config) | Maintainability / complexity / duplication grades | Blocking merge on grade alone; domain ownership |
| **`pr-domain-reviewer`** | On demand / Cursor Automation / Claude wrapper | Critical regressions 1–12, CP-\*, Dojo/vendor/SHF/HF ownership, spend gates, PR hygiene vs template | Restating CodeRabbit docs nits; CodeFactor grades; claim-existence audits |
| **`adversarial-reviewer`** | After an agent or human claims "done" | Cited files, tests, metrics and scope honesty | First-pass domain PR review |
| **`eval-judge`** | After scored eval/campaign evidence | Promote / hold / rollback from scores | Diff-time regression audit |
| **CircleCI** | Push / PR | Lint, pytest, coverage 84, generated-file checks | Narrative PR review |

## Companion rules

1. **`pr-domain-reviewer` opens with a Review lanes blurb** naming what it
   deferred to CodeRabbit / CodeAnt / CodeFactor and what it uniquely checked.
2. **No duplicate threads.** If another bot already filed an equivalent finding,
   reply "covered by \<bot\>" instead of opening a second comment.
3. **CodeRabbit stays on docs/consistency.** Domain pin, score-meaning and spend
   facts that CodeRabbit path instructions miss belong to `pr-domain-reviewer`.
4. **CodeAnt / CodeFactor stay generic.** Escalate to the domain bot only when
   a quality signal coincides with a removed guard (coverage floor, strata seal,
   hotfix fingerprint, spend validator).
5. **Canonical prompt:** [`.opencode/agents/pr-domain-reviewer.md`](../.opencode/agents/pr-domain-reviewer.md).
   Claude wrapper: [`.claude/agents/pr-domain-reviewer.md`](../.claude/agents/pr-domain-reviewer.md).
   Sync Cursor stubs with `sandbox subagents sync --harness project`.

## Policy pack the domain bot must apply

- [`critical-regressions.md`](critical-regressions.md)
- [`campaign-preparation-regressions.md`](campaign-preparation-regressions.md)
- [`scoring-hotfixes.md`](scoring-hotfixes.md)
- [`vendor-hotfixes.md`](vendor-hotfixes.md)
- [`dependency-snapshots.md`](dependency-snapshots.md)
- [`.github/PULL_REQUEST_TEMPLATE.md`](../.github/PULL_REQUEST_TEMPLATE.md)
