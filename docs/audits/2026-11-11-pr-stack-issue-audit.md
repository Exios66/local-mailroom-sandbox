# PR stack landing and open-issue audit — 2026-11-11

## Boundary and evidence

Inspected sandbox main `87645990da145e55365007c1fff917d0ba661510`, the
20 open issue bodies and comments, current review/check state, source/config
files cited below, and the owning upstream issue/PR status through GitHub.
This is a scoped acceptance audit, not a live deployment or full code audit.
No paid calls, GPU boots, vendor refreshes, local full suites or benchmarks ran.

The final layers landed in order:

| PR | Merge | Verification |
| --- | --- | --- |
| [#291](https://github.com/Exios66/local-mailroom-sandbox/pull/291) | `d824fc6` | Snapshot collection stability; hosted test #730: 3,054 passed / 28 skipped, 86.25% coverage |
| [#290](https://github.com/Exios66/local-mailroom-sandbox/pull/290) | `56a1edf` | Documentation closeout; hosted test #733: 3,054 passed / 28 skipped, 86.25% coverage |
| [#292](https://github.com/Exios66/local-mailroom-sandbox/pull/292) | `8764599` | Head `98101d5`: hosted test #749, 3,138 passed / 28 skipped, 86.33% coverage; lint #748 and security passed; no unresolved inline threads |

The coverage floor stays **84%**. #292 includes provider-neutral native-artifact
replay, view-only replay execution boundaries, remote node-log transfer,
frozen dataset identity, readiness evidence and resource-guard corrections.
Review resolution covered inline, outside-diff and general findings; an old
review's position alone was not taken as proof of a remaining defect.

## CI timing

The medium test executor and explicit two workers remain configured in
[CircleCI](../../.circleci/config.yml). The completed matched-workload comparison
in [CI guidance](../../.circleci/README.md) used the same 2,798 result identities:

| Hosted test job | Pytest action | Total job |
| --- | --- | --- |
| [609](https://circleci.com/gh/Exios66/local-mailroom-sandbox/609), `06ae5d5`, small | 1,032.962 s | 1,103.057 s |
| [620](https://circleci.com/gh/Exios66/local-mailroom-sandbox/620), `9c9f81b`, medium | 503.073 s | 577.869 s |
| [749](https://circleci.com/gh/Exios66/local-mailroom-sandbox/749), `98101d5`, medium | 547.789 s | 671.425 s |

The matched 609→620 reduction is **51.3%** for the pytest action and **47.6%**
for the total job. Job 749 has 3,166 results and a higher coverage floor than
that historical comparison; its pytest summary reports 545.02 s inside the
547.789 s action. Its runtime is current evidence, not a new matched benchmark
or a claim of equivalent credit consumption. Public CircleCI job metadata was
rechecked on 2026-11-11; signed log URLs were not recorded.

## All open issues

All 20 remain open with an individual evidence comment. None meets its entire
acceptance contract. Previously completed sandbox children #266/#267/#268 and
snapshot issue #285 are already closed; they are not reopened by this audit.

| Issue | Current boundary / remaining acceptance |
| --- | --- |
| [#31](https://github.com/Exios66/local-mailroom-sandbox/issues/31) | Modal judge/specialist already use Qwen3.5-9B. Judge posture, paired thinking measurement and judge-specific GEPA baseline remain. |
| [#154](https://github.com/Exios66/local-mailroom-sandbox/issues/154) | Same-generation distributed dispatch race remains; generation validation is not an atomic claim. |
| [#185](https://github.com/Exios66/local-mailroom-sandbox/issues/185) | New offline failure-path tests help; complete command/handler/precedence/no-side-effect matrix remains. |
| [#186](https://github.com/Exios66/local-mailroom-sandbox/issues/186) | PTY/browser tests exist; complete reconnect/restart, responsive and accessibility evidence remains. |
| [#187](https://github.com/Exios66/local-mailroom-sandbox/issues/187) | Current hosted offline gates are recorded above; release-readiness and outstanding roadmap evidence remain. |
| [#188](https://github.com/Exios66/local-mailroom-sandbox/issues/188) | Readiness tooling improved; credential rotation, authenticated pairing, staged smoke and teardown evidence remain unverified. |
| [#189](https://github.com/Exios66/local-mailroom-sandbox/issues/189) | Real PTY coverage exists; operator acceptance and authenticated browser action boundary remain. |
| [#190](https://github.com/Exios66/local-mailroom-sandbox/issues/190) | Cost-accounting fixes and provider-neutral node artifacts landed; campaign/fleet/mixed-route/spend acceptance remains. |
| [#212](https://github.com/Exios66/local-mailroom-sandbox/issues/212) | Use the calibrated Decisions smoke; complete per-document route/token/parking, report/card and cost audit remains. |
| [#213](https://github.com/Exios66/local-mailroom-sandbox/issues/213) | Current vendored judge/arbiter caps remain 16,000 characters; whole-document validation and measured long-document evidence remain. |
| [#214](https://github.com/Exios66/local-mailroom-sandbox/issues/214) | Chunk confidence still uses max(); measured replacement and source-owned implementation remain. |
| [#215](https://github.com/Exios66/local-mailroom-sandbox/issues/215) | Extraction judge confidence band remains; reviewer calibration does not establish above-band extraction accuracy. |
| [#216](https://github.com/Exios66/local-mailroom-sandbox/issues/216) | Frozen corporate prompt/schema confidence mismatch and zero-as-missing remain; versioned policy fix required. |
| [#217](https://github.com/Exios66/local-mailroom-sandbox/issues/217) | #29 is closed; full topology, row/kernel verification, race handling and measurements remain. |
| [#219](https://github.com/Exios66/local-mailroom-sandbox/issues/219) | Calibration/concurrency prerequisites improved; paired arm reports, classifier bundle and reviewed spend design remain. |
| [#221](https://github.com/Exios66/local-mailroom-sandbox/issues/221) | #289 supplies release-cache/provenance progress. Upstream mirror and original acquisition/fallback contract reconciliation remain. |
| [#259](https://github.com/Exios66/local-mailroom-sandbox/issues/259) | #258/#179 merged; production is v5. Issue narrowed to held-out confirmation, label decisions and corpus keyword proposal. |
| [#262](https://github.com/Exios66/local-mailroom-sandbox/issues/262) | Native kernel installation/boot and performance evidence unverified; base-image absence was not asserted without probing it. |
| [#263](https://github.com/Exios66/local-mailroom-sandbox/issues/263) | Three serving-row health/VRAM/KV/context checks still required; no new GPU boot performed. |
| [#269](https://github.com/Exios66/local-mailroom-sandbox/issues/269) | Sandbox children closed. Dojo #132/#133 and pipeline #188/#189/#190 all remain open; governed consumption and oracle gate remain. |

Issue bodies #31/#217/#219/#221/#259 were corrected, not just annotated with
comments that contradict the original instructions. Historical dataset pins
and experimental prompt bytes were preserved. No issue was closed merely for
age or because related tooling shipped.

## Owning sources and historical correction

Runtime conclusions came from `job/remote.py`, `job/runner.py`,
`tui/floor_replay.py`, `services/doctor.py`, the current vendored
`agents/judge.py`, `agents/arbiter.py`, `graph/routing.py`,
`langchain_agents/specialist_agents.py`, profile/model files, frozen corporate
prompt, PTY/browser tests and `VENDOR.md` records. Current pins remain Dojo
`v0.28.1` / `00a2a7f` and pipeline `19203eac`; fetched snapshots do not change them.

The two committed prime-sample reports under `reports/sorter-handoff/` record:

| Metric | Condensed v1 | V15 |
| --- | --- | --- |
| Class fixed | 108 | 100 |
| Class broken | 0 | 0 |
| Class still wrong | 12 | 20 |
| Class right after | 263 | 255 |

The previous changelog/lineage figures **96 versus 80** incorrectly subtracted
still-wrong answers from fixed answers. This follow-up corrects them to
**108 versus 100**, without changing the reports, prompt bytes or adoption
policy. Production v5's changed bylaw rule does not inherit v1's measured
train-split results. Old commit messages cannot be rewritten as part of an
evidence correction.

The historical rounded list-cost figures ($0.30 / $0.36) imply about **0.83×**,
not 0.9×. The earlier estimates ($0.34 / $0.41) also round to 0.83×. The
changelog ratio is corrected; these rounded amounts do not establish an exact
billed-spend ratio.
