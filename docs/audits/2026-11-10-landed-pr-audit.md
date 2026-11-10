# Landed PR audit — 2026-11-10

## Scope and result

Audited main `0ca393ef785098123e52b9a0575274eddb72ce0e`, including merged
PRs #274, #275, #276, #277, #278, #280, #281, #282, #283, #286 and #287.
All eleven merge commits are ancestors of main, and required lint/test statuses
are successful on each PR's final head and on main. Review threads were checked
on every layer; none remains unresolved. Later layers contain the fixes for
threads raised against earlier layers. Closed/superseded #279 and #284 are
not additional landed implementations.

The requested features are present. This audit reproduced two gaps, patched
in the accompanying follow-up: partial workspace vendor writes on copy failure
and dotenv discovery during offline diagnostic bootstrap. The follow-up still
requires its own hosted checks; green results on the audited main do not certify
new changes.

## Feature verification

| Feature / PRs | Verification and limits |
| --- | --- |
| Live floor, private viewer digests, replay ownership and image layout — #274 | Focused floor tests pass, including isolated HTTP viewers, digest cleanup, replay refusal and relocated image assets. No new Docker image build or paid serving run. |
| Named datasets and task-GT identity — #274/#277 | Registry/selection/identity regressions pass. Source and prepared-subset hashes remain distinct; filtering affects request identity. No live Hub pull. |
| CI allocation and quality gates — #275/#286 | Medium test executor, two loadfile workers, lint caches, full hosted suite and coverage remain configured. The coverage floor is 84%. Historical matched jobs 609/620 establish the earlier allocation improvement; they do not promise a uniform runtime for later workloads. |
| Feature references and instruction contracts — #276/#278/#280/#281/#286/#287 | CLI reference, generated requirements, reports hub and project agent rendering checks pass. The task board's final test counts are corrected to the hosted main result below. |
| Execution identity and resource limits — #282/#283 | Preflight identifies the actual checkout/import source and rejects mismatches. Hook option parsing and offline environment regressions pass. Fresh-process tests added here expose and close bootstrap dotenv reads that handler-only tests missed. |
| Service readiness — #282 | Doctor regressions distinguish installed/configured/authenticated/reachable evidence. No live probes were used; configuration presence is not workflow certification. |
| Scoped sync and durable records — #283 | Project-only defaults, read-only previews/checks, content/framework drift, owned attempt history, locks, redaction and rejection cases pass. No global agent files or sibling checkouts were synchronized. |
| Vendor refresh hardening — #286 | Standalone Git refresh and sync_vendor script regressions pass. The preferred CLI workspace path still copied into the live tree incrementally; a second-file failure changed the first tracked file. The follow-up stages the complete workspace mirror and reuses the Git path's rollback/recovery promotion helper. No real vendor pin or snapshot changed. |

## Hosted evidence

The current main commit has passing
[lint job 701](https://circleci.com/gh/Exios66/local-mailroom-sandbox/701) and
[test job 700](https://circleci.com/gh/Exios66/local-mailroom-sandbox/700).
The test log reports **2,946 passed / 28 skipped**, **86.21% coverage**, and the
**84%** gate passing. Pytest reports 549.62 seconds; the CircleCI pytest action
is 552.525 seconds and the total test job is 613.483 seconds.

The prior handoff/board reported 2,948 passed / 27 skipped. Those counts were
not paired with this hosted commit/result and must not be presented as main's
CI result. Earlier local timings, including the approximately 109-second
figure in #286's description, do not establish current hosted runtime.

## Focused offline checks

These are overlapping scoped selections, not a full local-suite run:

- Audited main: 114 agent/environment/dispatch/sync/vendor tests passed.
- Audited main: 122 floor/registry/fetch-deps/service-doctor tests passed.
- Patched follow-up: 70 environment/default-profile/Dojo-source tests passed.
- Patched follow-up: 34 vendor-refresh/fetch-deps/sync_vendor tests passed.
- New regressions failed before the changes and passed afterward. Copy failure
  is covered for both workspace source layouts; existing promotion/rollback
  tests exercise the shared installation helper.
- A further 50 dispatch/sync/CLI-surface/doc-path checks passed after the patches.
- CLI reference and requirements mirrors are current. Reports hub check passes
  with 1,844 figures / 781 cross-checks. Project agent sync has no drift.
- Harness doctor: zero failures, one warning for installed Node 22.14.0 versus
  the optional eve doctor's Node >=24 requirement. No upgrade was performed.

All local test selections use one worker and no coverage. No full local suite,
benchmark, campaign, LLM request, deployment or live Hub pull was run.

## Issue #285: stable released snapshots

[Issue #285](https://github.com/Exios66/local-mailroom-sandbox/issues/285) remains
an open proposal (SAND-104), separate from the landed refresh hardening.
There is no `sandbox deps fetch` command, stable snapshot-cache resolver or new
pipeline release resolver in the audited tree.

Upstream release metadata was checked on 2026-11-10:

- [Dojo v0.28.1](https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.28.1)
  publishes a wheel, sdist, release-manifest.json and SHA256SUMS. Its manifest
  records commit `00a2a7f7b058a4ade06b027c2afbd8b03bea6a5f` and hashes/sizes for
  the two built artifacts; it is not a hash inventory of every source file.
- [Pipeline v0.9.3](https://github.com/Exios66/llm-mailroom/releases/tag/v0.9.3)
  has no attached assets. Both releases report `target_commitish: main`, which
  is a branch name, not immutable proof of the tag's commit.
- [Pipeline issue #225](https://github.com/Exios66/llm-mailroom/issues/225)
  separately tracks dependency/artifact fetching on the owning pipeline repo.

The proposal is feasible, with these acceptance details to settle before coding:

1. **Freeze selection explicitly.** Fetching a newer stable artifact must not
   silently change scoring or pipeline imports. Define the opt-in cache policy,
   exact component lock and resume behavior. Preserve the existing Dojo
   auto/installed/vendored modes and explicit source overrides.
2. **Verify the tag's peeled commit.** Compare manifest commit and downloaded
   content against an immutable tag commit. Do not compare a resolved archive
   commit to the mutable `target_commitish: main` value.
3. **Bridge wheel provenance.** Current auto selection expects installed VCS
   commit provenance; a release wheel normally supplies no VCS direct_url commit.
   Define how verified artifact provenance is carried into source selection and
   run locks instead of weakening the existing pin check to a version string.
4. **Separate offline checks from latest-release lookup.** Read-only means no
   filesystem writes, not necessarily no network. Define offline/cache-only
   checking and an explicit online latest-release check; preserve prior cache
   entries on every failure and verify cached integrity before reuse.
5. **Validate pipeline runtime contents.** The sandbox imports pipeline, graph,
   agents, llm and legalbench trees, and uses source-only helpers. An installed
   distribution's version or one successful import does not establish that all
   required runtime paths exist. Archive normalization, size limits, traversal,
   symlink/hardlink rejection and partial-download failures need fixture tests.

The proposal is not marked implemented or closed by this audit. It must retain
its own feature PR, publishing prerequisites and offline acceptance tests.

## Environment boundary

The audit ran from the dedicated main-based tooling worktree with its source
explicitly selected on PYTHONPATH. The separate root checkout remains on an
older feature branch; its editable environment points there. That checkout was
not switched or reset. Operators should verify checkout/import identity before
using the new commands from a different environment.

## Review clarification: vendor refresh requires quiescence

CodeAnt's review of `13ba9f9` identified that the promotion helper's two
renames briefly leave the destination absent. Staging and rollback protect
reviewed bytes from copy/install failures; they do not synchronize running
imports or prevent a process from mixing old and new modules. Vendor refresh
is a maintenance operation: stop every sandbox process using that checkout
before `sandbox fetch-deps` or `scripts/sync_vendor.py`, complete and review
the refresh, then restart the processes. This concurrency limitation is
explicit in the helper; an atomic directory swap alone would still permit
mixed-revision imports. The parser-default nit in that same review is
covered by `b3478a7`, which calls `build_parser()` for every offline action.

## Follow-up CI: prompt override isolation

[Test job 712](https://circleci.com/gh/Exios66/local-mailroom-sandbox/712), on
follow-up head `303e0ee`, exposed three order-dependent prompt-freeze failures
(2,956 other tests passed, 28 skipped; coverage passed at 86.24%). Generation
tests left their sentinel text in the process-wide pipeline prompt table. The
shared fixture cleared active selection but did not restore patched prompt
tables and imported lookup bindings. This was a test isolation defect, not a
change to the committed frozen prompts.

Running one generation test followed by the four freeze checks reproduced
three failures in 2.66 seconds. The shared fixture now deactivates runtime
overrides as well as clearing selection at both test boundaries. An ordered
selection covering generation, prompt versions, injection, registry, freeze and
condensed prompts passes: **221 passed / 2 skipped** in 20.56 seconds, one worker
without coverage. Frozen source hashes and assertions are unchanged. Full
current-head CI remains required; rerunning the previous failing revision alone
would not repair the leak.

## Final landing: audit fixes and issue #285

The earlier proposal assessment describes audited main `0ca393e`, before the
implementation. On 2026-11-10, both follow-ups landed in order:

| Work | Final tested head | Hosted evidence | Main merge |
| --- | --- | --- | --- |
| Audit/bootstrap/vendor fixes, #288 | `5d167e4861cc5c46063d2b1ce4f1fb009ede433a` | [Test 720](https://circleci.com/gh/Exios66/local-mailroom-sandbox/720): 2,959 passed / 28 skipped, 86.23% coverage, 542.12 s pytest; [lint 721](https://circleci.com/gh/Exios66/local-mailroom-sandbox/721) passed | `1e398dee7e8d81ae533672e767f864ed481b3ba0` |
| Stable dependency snapshots, #289 | `b9637bb3b2fa25bf2daa8cd0d1eebf148eb2ab9a` | [Test 723](https://circleci.com/gh/Exios66/local-mailroom-sandbox/723): 3,053 passed / 28 skipped, 86.25% coverage, 626.22 s pytest; [lint 722](https://circleci.com/gh/Exios66/local-mailroom-sandbox/722) passed | `cf1074039babd037245e486a0bbb21350f335fcd` |

Both lint/security gates passed and all inline review threads are resolved.
The unchanged coverage floor is 84%. Main `cf10740` contains both merges and
its tree is byte-identical to tested feature head `b9637bb`; issue #285 closed
automatically. The different test surfaces above are not a controlled runtime
comparison. The historical matched CI allocation evidence remains the basis
for the earlier speedup claim.

The feature now supplies `sandbox deps fetch`, verified offline caches,
explicit source selection, dependency tree fingerprints in new run locks and
matching cache/installed-source bundles for remote workers. The guide is
[dependency snapshots](../dependency-snapshots.md). Source fingerprinting fixes
and installed-worker export address the earlier review findings without
changing vendor pins or rewriting run locks. Pipeline archive digests remain
locally computed when releases publish no checksums; owner-published artifacts
remain upstream work. The remote adapter was tested with fresh offline worker
simulations; actual Modal deployment and paid serving were not exercised.
