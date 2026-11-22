# Campaign preparation regressions

Reviewers and collaborating agents must read this checklist with
[critical regressions](critical-regressions.md) and the
[current campaign contract](EXPERIMENT-CAMPAIGN-CONTRACT.md). In a campaign PR or
handoff, cite the applicable `CP-*` and critical-regression row numbers, the tested
commit, expected behavior, evidence and remaining acceptance. A passing unit test
is not live quality evidence. Do not resolve a review or close an issue from a
prepared patch alone.

The [master tracking discussion](https://github.com/Exios66/local-mailroom-sandbox/discussions/343)
is the progress record. This checklist records behavior to preserve. Patch status
below is a snapshot taken on 2026-11-19; check the linked PR before relying on a
pending fix. Tests named for an unmerged patch live in that PR.

## Campaign state

- Landed in this closeout: [#359](https://github.com/Exios66/local-mailroom-sandbox/pull/359),
  [#361](https://github.com/Exios66/local-mailroom-sandbox/pull/361),
  [#360](https://github.com/Exios66/local-mailroom-sandbox/pull/360),
  [#362](https://github.com/Exios66/local-mailroom-sandbox/pull/362) and
  [#345](https://github.com/Exios66/local-mailroom-sandbox/pull/345).
- Landed in this closeout (continued): [#354](https://github.com/Exios66/local-mailroom-sandbox/pull/354)
  (notebooks), [#365](https://github.com/Exios66/local-mailroom-sandbox/pull/365)
  (CircleCI helper and consolidated design), and
  [#367](https://github.com/Exios66/local-mailroom-sandbox/pull/367)
  (confidence, patch readiness, cost and campaign contract). Full hosted tests and
  the unchanged 84% coverage gate passed on each merged head.
- Landed on 2026-11-19: [#368](https://github.com/Exios66/local-mailroom-sandbox/pull/368)
  (offline hotfix-wiring audit and three guard corrections) and
  [#369](https://github.com/Exios66/local-mailroom-sandbox/pull/369)
  (spend/reproducibility hardening stacked on it).
- New generations use dataset v9.3, immutable tag commit
  `ff4ca546d4346991628c2616ae014afc15e9fe04`, data parent
  `7fd99b406ab1b627f43602dd6a3af5fb5b7a3ac5`, and `runbook-v2`.
  Historical v9.1/runbook-v1 locks, measured calibration draw 1 and reports stay immutable.
- G0 remains open. In the isolated offline checkout, split, schema and hotfix
  checks passed; six R01 ledgers and six R03 adjudication sheets were absent and
  R02 human sign-off did not pass. Missing local artifacts do not erase historical
  smoke evidence. No new paid campaign run or held-out unsealing was performed.

## Regression checklist

| ID | Behavior that must remain fixed | Patch state | Evidence and guard |
| --- | --- | --- | --- |
| CP-01 | Blind routing never reads evaluation truth; API routes use fitted whole-document reads where supported. | Landed campaign safeguards | `tests/test_production_slices.py`, `tests/test_context_plan.py`, R01 per-path/expected-agent ledger checks. Oracle handoff is a separately labelled condition. |
| CP-02 | A prepared draw preserves IDs, exclusions and control labels. Bundles have no scored class/subclass; fragments retain their source class. | Landed #361/#360 | `tests/test_rb1_form_floor.py`, `tests/test_experiment_splits.py`; question-set 4.0.2 and both unrun draw-2 arms use the same fresh source draw and constructed defects. |
| CP-03 | No spent tuning/calibration component enters held-out. | Landed #362 | All 50 spent draw-1 IDs join the 483-ID exposure list; one leaked into the initially proposed held-out set and was removed. `sandbox splits audit --name runbook-v2` rebuilds the split and checks complements/components. Never rebuild a used split. |
| CP-04 | Label revision, split and field registry agree; v9.1/v9.3 scores are separate measurements. | Landed #362 | `tests/test_experiment_splits.py`, `tests/test_gold_audit.py`, `tests/test_sorter_arms.py`; `sandbox schemas build --check`. |
| CP-05 | Truth labels have admissible evidence and provenance; conflicting values are visible. | Landed #359/#362 | `label_overlay_grounding`, `merged_truth`, `tests/test_notebook.py`. Full v9.3 audit: 7,852 labels, zero unsupported admissions/precedence violations; 30 unsettled Hub conflicts remain. Grounding is not complete semantic review. |
| CP-06 | Reviewed near-gold supersedes eligible conflicting gate fills; original-header values retain their distinct precedence/provenance. | Landed SHF-010 | `tests/test_scoring_hotfixes.py`, `tests/test_near_gold_overlay.py`, `tests/test_label_review_decisions.py`. Header values may be absent from model input; near-gold is reviewed machine truth, not human gold. |
| CP-07 | Documented absences count false positives; partial names, currency differences and identifier punctuation score correctly. | Landed SHF-001–004 | `tests/test_scoring_hotfixes.py`, `tests/test_scoring_golden.py`; preserve raw Dojo values beside corrected scores. |
| CP-08 | Failed documents stay in scored denominators; missing truth stays explicitly unscored; abstentions and parse errors are counted. | Landed SHF-005–008/011 | `tests/test_scoring_hotfixes.py`, `tests/test_job_lifecycle_regressions.py`; never invent judge/arbiter/boss truth or credit failed paired items for partial output. |
| CP-09 | Decision form, abstention and truncation keys govern routing; subclass scoring is joint with class and retains raw Hub truth. | Landed SHF-009/012/013 | `tests/test_scoring_hotfixes.py`, `tests/test_scoring_hotfixes_shf013.py`, `tests/test_rb1_form_floor.py`. Reviewed subclass corrections remain fingerprinted. |
| CP-10 | Corporate type derives from registered subclasses; judge parse failures route as errors; intake cleaning cannot discard source content. | Landed HF-001–003 | `tests/test_vendor_hotfixes.py`, `tests/test_scoring_hotfixes.py`; frozen extraction guidance remains authoritative. |
| CP-11 | Instrumented returned calls record usage promptly and stop later calls at armed ceilings. | Landed HF-004 and call guards. A Decisions response is priced once, in the transport; the usage wrapper does not price it again. Isolated `sorter_reviewer` and `extraction_gate` rows take the per-document ceiling | `tests/test_call_guard.py`, `tests/test_provider_pins.py`. Do not generalize this to uninstrumented transports, early-bound aliases, missing usage or already in-flight calls; audit every paid path and scope separately. |
| CP-12 | Saturated filesystem bins hold files without dropping them; waits/uploads are bounded. | Landed HF-005/#358 | `tests/test_backpressure.py`. Watcher imports need observability dependencies; verify `scripts/check_hotfixes.py --require-watcher` before relying on watcher readiness. |
| CP-13 | Explicit numeric zero confidence remains zero in single and chunked specialist output. | Landed HF-006 in #367 | `tests/test_vendor_hotfixes.py`; missing confidence still uses the fallback, and a zero-confidence chunk cannot disappear behind a higher chunk. Frozen corporate-prompt policy remains #216. |
| CP-14 | Missing/stale required hotfixes refuse preflight and execution; run locks name patch/source identity. | Landed #367 (identity guards already landed); the resume audit of started legacy locks is #368's scope | `tests/test_vendor_hotfixes.py`, `tests/test_check_g0.py`, `tests/test_job_preflight.py`, `tests/test_job_runner.py`; offline hotfix checker and G0 gate. Treat started legacy locks without a basis as a separate worker/resume audit, not automatically safe. |
| CP-15 | Input-cost estimates count confidence retries, arbiter retries and completeness plus conditional correctness per judge pass. | Landed #367; measured comparison open #330 | `tests/test_context_plan.py`, `tests/test_routing_calibration.py`, including the graph's actual two-call judge sequence. Rejudge changes its named scenario; a one-pass cap has no retry scenario. `keep_best_attempt` adds no calls. Output, intake, classification and transport retries remain outside this estimate. |
| CP-16 | Offline notebooks suppress dotenv reads and tracing, isolate artifacts/activation state, report the actual relocated taxonomy path, validate every probe URL and avoid cloud timeout diagnostics. | Landed #354 | `tests/test_notebook.py`, `tests/test_notebooks.py`, health/probe tests; dedicated hosted notebook execution passed, but it does not replace the full-suite gate. The relocated-directory regression restores the real resolver inside its worker-unique temporary directory, preserving default xdist isolation. |
| CP-17 | CircleCI project aliases canonicalize correctly; API tokens never reach log-download hosts; offline doctor does not authenticate. | Landed #365 | `tests/test_circleci.py`, doctor/CLI tests. Authenticated log retrieval remains unverified; GitHub status metadata alone does not provide a test traceback. |
| CP-18 | Serving dependency guards agree with declared versions; historical runs retain their recorded versions. | Landed #345 | Modal 1.6.4 / FastAPI 0.163.1, exact-version and CLI contract tests. No deployment or live parity claim follows from a dependency update. |

## Review and retirement

Apply the [pipeline hotfix](vendor-hotfixes.md) and
[scoring hotfix](scoring-hotfixes.md) catalogs with their fingerprints and raw/fixed
reporting. Keep `vendor/` unchanged; a new upstream version requires source review,
refresh through the sanctioned workflow, and revalidation or retirement of each
workaround. Existing locks cannot silently inherit a new patch generation.

Before approving a campaign change, reviewers must:

1. Cite applicable `CP-*` IDs and critical-regression rows with source commit and focused evidence.
2. Verify current-head hosted gates, split/truth identity and executed worker identity.
3. Keep prepared patches, offline/mock checks, historical measurements and fresh live evidence distinct.
4. Leave acceptance open for long-document reading/window records (#213/#214), confidence bands and frozen-prompt policy (#215/#216), Modal parity and re-smokes (#217/#308/#212), measured cost (#330), label adjudication/labeler methodology (#328/#363), and the distributed Modal race (#154).
5. Keep held-out sealed and preserve budget/initials gates. This checklist authorizes no paid run.
