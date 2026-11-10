# Agent environment, dispatch and recovery contract

This procedure applies to every coding agent and harness in this package.
Read [AGENTS.md](../AGENTS.md) and the
[instruction maintenance procedure](agent-instruction-maintenance.md) first.

## Establish execution identity

Before edits, verification or dispatch, record the repository root, branch,
HEAD, dirty state, intended base revision, interpreter, imported package path
and resolved CLI paths. Compare the package import location with the intended
checkout: an editable install can still import a sibling worktree. An older
branch may be intentional; establish that before proceeding. Do not switch,
reset, reinstall or clean someone else's checkout to make the check pass.

Use an explicit interpreter. Recreate environments at their intended location
rather than copying virtual environments between paths. Validate configured
machine paths before using them; examples under another operator's home are
hints, never proof that a service or checkout exists. Inspect only required
configuration keys and credential presence, never secret values.

## Dispatch contract

Before delegating, discover the current harness's provider/model catalog and
check the selected provider **instance**, authentication and worktree support.
A listed model or installed binary alone does not establish dispatch readiness.
Use connected purpose-built tools first. In T3, use app-owned delegation for
isolated worktrees or cross-provider work; native same-provider delegation is
appropriate only when it supports the chosen model and isolation. Use the
Hermes ACP bridge only for an explicitly requested Hermes workflow after
checking its local skill and handshake. Never infer one harness's availability
from another harness's similarly named provider.

Every delegated task must include:

- Objective and a bounded write scope (read-only is explicit).
- Checkout root, branch, starting SHA and intended PR base.
- Provider instance/model, applicable instructions and source ownership.
- Acceptance criteria, exact verification evidence and artifact locations.
- Resource limits: local workers, wall time, remote checks and spend authority.
- Stop conditions, blockers, known prior findings and unresolved objections.

Record the returned task ID immediately. Inspect its state before retrying an
ambiguous launch; a lost response does not prove the task was never started.
Use a stable request ID where supported. A delegated task is distinct from a
new top-level conversation: create a top-level thread only when the user asks.
Do not start parallel agents unless the current task/instructions authorize it.
Do not dispatch overlapping writers to the same checkout. Before accepting a
handoff, inspect the resulting diff and evidence against this contract.

## Classify failures before recovery

| Failure | Recovery and evidence |
| --- | --- |
| Transient infrastructure (mirror sync, 429, 502/503/504) | Preserve the failing step and revision. Honor Retry-After and use bounded retries. Prefer rerunning the same CI revision over unrelated code edits or no-content commits. |
| Authentication or authorization | Identify the blocked provider instance and capability. Do not retry indefinitely, change accounts silently or ask for secrets in chat. Use the harness's private secret-entry flow where available. |
| Invalid configuration, API contract or missing dependency | Inspect the current parser/schema, owning source and declared environment. Fix the cause before retrying; do not guess new flags or upgrade dependencies automatically. |
| CPU or memory exhaustion | Stop duplicate work, narrow local reproduction and offload expensive checks. Use allocated CPUs/memory, never the host CPU count, when choosing workers. Preserve quality gates. |
| Timeout or interrupted long run | Check task/process status and checkpoint ownership first. Resume the existing job when supported; do not duplicate paid work or delete a running checkpoint. |
| Missing/unreachable service | Distinguish configuration, authentication and reachability. Diagnose with bounded read-only checks; startup, deploy and live probes retain their existing authorization/spend gates. |
| Review quota notice | Suppress quota-only output and repeated notifications. Continue independent review and required CI; do not treat unavailable bot review as a passing review. |
| Product/test regression | Reproduce the smallest relevant failure, patch the owning source, and verify on the current head. Sweep related callers for the same failure pattern. |

A retry budget must be explicit. Stop retries when the failure is deterministic,
the budget is exhausted or task state is ambiguous; report the remaining blocker
with the next useful action. Recovery never authorizes destructive cleanup,
credential disclosure, paid work or weaker checks.

## Evidence and local resource policy

Accept hosted results only after checking the commit SHA, exact command/test
surface, outcome, coverage and artifacts. An agent does not have to rerun an
expensive suite locally to validate that evidence. Use focused single-worker,
no-coverage local regressions when needed. Full suites, coverage, campaigns and
benchmarks follow the [CI policy](../.circleci/README.md); dedicated campaign and
benchmark jobs must be arranged when absent. Mock results do not certify live
serving; configured credentials do not prove authentication; reachable services
do not prove a workflow succeeded.

## Synchronization scope

Preview synchronization and name its targets. For project-only changes use
`--harness opencode` and `--harness cursor` explicitly. `--harness all` currently
includes machine-global profiles: use it only when those targets are intended.
Sibling checkout propagation is a separate operation. Edit canonical prompts
in their home package, regenerate adapters, and inspect the diff. Check rendered
content and shared framework content, not merely the presence of a heading.
See [family synchronization](subagents-family-sync.md).

## Durable handoff

Keep a structured task record under the checkout's gitignored `data/runtime/`
(or a deliberately selected durable operator directory), not only `/tmp`.
Include a schema version, task/request IDs, contract, checkout/base/head SHAs,
provider/model, state, PR/base relationships, CI evidence, unresolved review IDs,
blockers and the next action. Preserve completed attempts when retrying.
Use atomic writes and refuse overwriting a different task's record. An active
record is not proof that its remote task is still running: reconcile with the
orchestrator before restart or dispatch.

Store credential-free artifact references. Remove URL userinfo, signed query
parameters and fragments; never persist raw capability/configuration dumps,
tokens, cookies or complete authenticated CI responses. Persistent reports
should distinguish measured, simulated, pending and unverified results.
