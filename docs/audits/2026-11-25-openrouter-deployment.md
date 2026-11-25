# OpenRouter deployment and recent-main integration audit

Audit date: 2026-11-25. Source range: `09bd00ec` through
`dcfa2744052af2ad65e404cbcf76077a238d700c`. The latter includes #411,
which landed while the audit was running. The original checkout's existing
experiment files were preserved; repairs were prepared in an isolated worktree.

## Findings and repairs

| Finding | Reproduction | Repair and guard |
| --- | --- | --- |
| A Decisions backend can retry after the absolute run deadline. | With an already expired pipeline deadline, `_post_decision` still made three fake HTTP attempts. It ignored `Retry-After` and slept after the final failure. Five new tests failed before the repair. | [#413](https://github.com/Exios66/local-mailroom-sandbox/pull/413): one transport deadline across requests and backoff, per-attempt run checks, remaining-time HTTP timeouts, bounded Retry-After handling and no final sleep. Invalid attempt counts/timeouts are refused before HTTP. `tests/test_decision_transport.py`. |
| Reviewer schema and runtime window calculations disagree after #405/#410. | Real `ReviewerSpec` rejected Jev's 1,032,576-character runtime estimate at 437,145 characters, and Liquid's 246,144-character estimate at zero. Three initial real-schema cases failed. Earlier window tests used synthetic spec objects. | [#414](https://github.com/Exios66/local-mailroom-sandbox/pull/414): share Decisions model-window arithmetic. Schema uses the default question reserve, preflight reserves actual questions, execution also reserves the handoff. Real-schema/variant/large-question tests in `tests/test_decision_windows.py`; above-window overrides remain refused. Schema validation does not reload frozen question files. |
| The newest floor viewer displays the wrong graph for a selected confusion cell in DEBUG. | With class `contract` isolated, DEBUG enabled and cell `letter → contract` selected, the document table identified `d3` but the graph kept the contract debug path and showed two classify documents. Endpoint counting declined the cell isolate. The new JavaScript execution test failed. | The floor follow-up gives a confusion pair precedence over DEBUG and uses the same pair for repeat badges. The browser then showed one classify document, zero human-review documents and one START document. `test_confusion_pair_controls_graph_counts_even_with_debug_class_and_mode_filters` executes actual viewer functions and verifies clearing restores DEBUG. |

The confirmed latest-main viewer defect is repaired locally without reverting
the other #411 functionality. No broad rollback is justified by these findings.
The API defects likewise have targeted repairs; reverting #410 would also remove
its context and routing safeguards. Repairs remain proposals until reviewed,
merged and deployed.

## Recent landing reconciliation

| Landing | Source and integration checks |
| --- | --- |
| `b1061f9e` | Only removes identifying wording from the `cost_compare.json` fixture note. Numeric fixture data is unchanged. |
| #407 `d8d4bcc1` | Rescore execution refusal is present in local lifecycle, remote dispatch and deployed worker paths. Focused remote/generation checks pass. |
| #406 `cc9f961b` | Dojo snapshot is updated; SHF-014 is retired. Current hotfix check reports SHF-001–013 current. No vendor files were edited during this audit. Scoring engine ownership remains with Dojo. |
| #408 `1b7e9dde` | Reviewed intent labels are distinguished in gate causes; focused `test_gate_causes.py` passes. |
| #405 `afa1f48a` | Paired comparison, price/usage propagation and reviewer override code are present. Comparison checks pass; the schema/transport integration gap is repaired in #414. |
| #410 `2886fd03` | HF-011/HF-012, fitted output caps, mandatory applicable-reader input checks, legacy retry thresholds and per-model Decisions sizing are present. Focused compiled routing, context, hotfix and window checks pass. Validating real model swaps exposed the #414 gap. |
| #404 `d02bfa17` | Braintrust declared range is `>=0.42,<0.53`; generated requirements agree. This does not establish that an installed or deployed environment was upgraded. |
| #403 `c8175a78` | Declared pins are FastAPI 0.165.0, python-multipart 0.0.34 and pydantic-ai-slim[typesafe] 2.71.0. Requirements mirror checks pass. Exact installed local versions differ, as recorded below; hosted main gates supply the declared-install evidence. |
| #409 `f3887b68` | Floor builder, failure-mode explanations and replay isolation are present; focused digest/app checks pass. Replay evidence remains synthetic. |
| #411 `dcfa2744` | Cross-run document/mode tracking, decision filtering, confusion selection and note copying are present. Prior review fixes for keyboard activation, clipboard fallback, run-wide cell selection and endpoints are in current source. Browser keyboard copying reached the injected clipboard stub without toggling the mode. The additional DEBUG/cell precedence defect is repaired in the floor follow-up. |

Earlier OpenRouter fixes were checked in current code and full discussion
replies: #377 (single Decisions charge), #388 (4.2 routing identity), #389
(judge/high-confidence and window records), #395 (expanded inputs and resume),
and #397 (whole-document API guards) and #398 (integration repairs).
The checks preserve their documented scope: API specialist/sorter/intake
guards do not guarantee arbitrary-length judge or arbiter coverage.

## Verification evidence

All local pytest invocations use one worker and no coverage. Commands below
use the existing checkout's explicit virtualenv interpreter, with
`PYTHONPATH=$PWD/src`; both imported package and resolved root were verified
to be this worktree. Counts overlap and must not be summed as unique tests.

- Starting main `f3887b68` and updated main `dcfa2744` each have successful
  CircleCI statuses for lint, generated checks, full tests, notebook regressions,
  coverage and no-session-links. Updated-main workflow:
  [4f308ca5-69c7-4471-bc49-08e1a2f4dae7](https://app.circleci.com/workflow/4f308ca5-69c7-4471-bc49-08e1a2f4dae7).
  These are commit-matched status records, not downloaded JUnit or coverage
  artifacts; no numerical coverage result is inferred.
- Starting main: `test_pipeline_routing_matrix.py`, `test_context_fit.py`,
  `test_decision_windows.py`, `test_call_guard.py`: **90 passed**.
- Starting main: `test_floor_digest.py`, `test_floor_app.py`,
  `test_requirements.py`, `test_job_remote.py`, `test_job_generation_residuals.py`,
  `test_sorter_arms.py`, `test_gate_causes.py`: **268 passed**.
- Transport repair: `test_decision_transport.py`, `test_call_guard.py`,
  `test_decisions_backend.py`, `test_pipeline_routing_matrix.py`,
  `test_decision_slots.py`: **176 passed, 1 optional skip**.
- Transport review repair `8c0e8cc7`: `test_decision_transport.py`,
  `test_call_guard.py`, `test_decisions_backend.py`: **119 passed**.
  This adds invalid-attempt/timeout refusal and qualifies the timer's start.
- Updated-main floor plus initial schema repair: `test_decision_windows.py`,
  `test_decisions_backend.py`, `test_job_spec.py`, `test_floor_digest.py`,
  `test_floor_app.py`: **214 passed**.
- Integration sweep: `test_context_plan.py`, `test_provider_credentials.py`,
  `test_provider_pins.py`, `test_vendor_hotfixes.py`, `test_routing_calibration.py`,
  `test_decision_transport.py`: **172 passed**.
- Final schema repair `4bf3a87b`: `test_decision_windows.py`,
  `test_decisions_backend.py`, `test_job_spec.py`, `test_autoresearch_levers.py`:
  **232 passed**.
- Final floor repair: `test_floor_app.py`, `test_floor_digest.py`:
  **90 passed**, including the JavaScript execution regression.
- After rebasing the review repair through the stack: `test_decision_windows.py`,
  `test_decision_transport.py`, `test_floor_app.py`, `test_floor_digest.py`:
  **138 passed**. Markdown lint checked 200 files with zero errors.
- `scripts/sync_requirements.py --check`: every requirements mirror matches.
  `scripts/check_hotfixes.py`: HF-001–012 applied; SHF-001–013 current.
- Ruff 0.17.5 and markdownlint-cli2 0.18.1 passed on the repair surfaces.
  Final floor-repair results and tested head are recorded in its PR.

The browser used a throwaway digest produced by the committed floor selftest
fixture and current builder, served over loopback. These are UI regression
checks with simulated documents, never model-quality or serving measurements.

## Environment and deployment limits

The local interpreter is Python 3.14.5 with sandbox distribution metadata
0.3.0, OpenAI 3.14.1, langchain-openai 1.6.2 and HTTPX 0.28.1.
Its installed FastAPI 0.162.0, python-multipart 0.0.32 and pydantic-ai-slim
2.63.0 predate current declarations. Braintrust and Modal are absent.
No environment was silently upgraded. Local checks do not certify the new
dependency pins; matching hosted main gates are separate evidence.

`deploy/modal_job.py` bundles source/config/vendor snapshots at deployment
time. A merge into main does not update an existing worker image. Its source
selection, generation checks, OpenRouter credential scoping and hotfix checks
were inspected, but no deployed app identity was queried or changed. Deployment
from the final reviewed revision and matching locked provenance remain operator
acceptance. No paid or live model calls, deployment, dataset pull, experiment
re-lock or held-out access occurred.

Remaining known risks from #410 are still open: Decisions context metadata is
read from a mutable catalog on resume; non-Luna tokenizers have no measured fit
for the shared 0.25 tokens/character estimate; a swapped model inherits
Luna-calibrated cutoffs; and in-pipeline reviewer answers omit the truncation flag.
Chat transport retries, SDK retries and graph retries are different layers;
bounded graph self-loops do not prove a per-HTTP-attempt ceiling. Already
in-flight requests can finish after client timeout. The transport timer starts
after backend preparation; it does not receive the caller's earlier node
deadline, so that caller can expire first. The current overlay's configured
call allowance is 600 seconds; with an absolute run deadline active, the
transport uses the smaller of its explicit timeout and that allowance.
These need separately scoped provenance, calibration and live acceptance work.

Instruction validation checked AGENTS, CLAUDE, the dispatch and maintenance
procedures, tool router and selected serving skill against the recorded
revisions. Dependency declarations, installed versions, vendor ownership and
CI job configuration were distinguished. Critical-regression rows 5, 6, 9,
13, 17–20 and campaign CP-09, CP-11, CP-14 apply to the repairs. Offline
evidence does not close live or human campaign gates.
