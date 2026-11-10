# CLAUDE.md — local-mailroom-sandbox

Local-first experiment harness around the Mailroom family: it runs prompt loops,
evals and calibration against a **vendored** copy of `llm-mailroom` and
`llm-dojo-scoring`, with Modal/vLLM as the default serving path and Langfuse as the
default trace sink. It does **not** reimplement the pipeline. Python 3.11+.

Open [`AGENTS.md`](AGENTS.md) at task start; it is the full command reference and
is **not** auto-loaded. Follow its
[routine instruction validation](AGENTS.md#instruction-validation-routine):
validate relevant facts in this file, `AGENTS.md`, scoped rules and skills against
current evidence, including after long experiments, feature/configuration updates
and before handoff or merge. Correct stale guidance and record unresolved facts;
see the [maintenance procedure](docs/agent-instruction-maintenance.md).
For any provider, tracing,
dataset or deploy task, read `.cursor/skills/sandbox-tool-router/SKILL.md` first,
then exactly one specialty skill in `.cursor/skills/`. For a full docs/README
staleness sweep, follow `.cursor/skills/docs-audit-tool-router/SKILL.md`.

PR and issue descriptions use an executive summary, never a transcript: no
direct quotes from the requester, names, handles or credentials, and no
`User description` section. Paraphrase the intent and use the PR template.

## Setup and checks (all network-free)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q tests/test_job_spec.py -n 0 --no-cov  # focused local check
ruff check src tests scripts deploy reports                 # correctness gate, config in pyproject
python scripts/sync_requirements.py --check                 # requirements/*.txt mirror pyproject
python reports/dashboard/build_hub.py --check               # committed reports-hub snapshot
sandbox pilot --mock                                        # no LLM, no spend
sandbox doctor                                              # offline status of external CLIs
```

- `[dev]` already pulls the `[pipeline]` extra (langchain/langgraph/sqlalchemy) —
  the default suite imports the vendored graph, so a bare base install is not enough.
- Coverage floor is `fail_under = 84`: **never lower it to land a change.**
- Full-suite, coverage, campaign and runtime benchmarking checks belong in hosted
  CI. Use focused single-worker checks without coverage locally; require passing
  current-head hosted gates before merging. CircleCI currently runs lint, pytest,
  coverage, reports-snapshot and requirements checks; it has no dedicated campaign
  or runtime-benchmark jobs. If those are needed, arrange scoped hosted verification
  and keep the result unverified until it runs. See [CI guidance](.circleci/README.md).
- Live-LLM tests need `SANDBOX_LOCAL_LLM=1`; real Modal/HF contract checks need
  `SANDBOX_SERVICE_SMOKE=1`. Leave both unset.

## Spend and safety — read before running anything

- **Never launch paid or live work unprompted:** `sandbox run start`,
  `sandbox experiment launch`, `sandbox modal deploy|prewarm`, `modal deploy|run`,
  anything with `--real`, or `--live`. Settings deny or ask for these on purpose.
- The spend gate is `sandbox run preflight --config <file>` then
  `sandbox run start --config <file> --initials <XX>` (2–6 capital letters).
  Initials belong to a human — never invent them.
- Every paid run needs `job.max_wall_seconds`; GPU runs need `job.cost_cap_usd`;
  OpenRouter runs need `job.api_cost_cap_usd` plus a price in `config/api_prices.yaml`.
- Default serving is Modal vLLM; Ollama is an offline fallback; OpenRouter is opt-in.
  Do not use Phoenix or Braintrust as the The-Mailroom sink.

## Do not hand-edit (a hook blocks these)

- `vendor/**` — tracked snapshots guarded by `tests/test_vendor_drift.py`
  (byte-identity). Change the owning repo first (`llm-mailroom` for pipeline,
  `llm-dojo-scoring` for scoring), then refresh with `python scripts/sync_vendor.py`
  or `sandbox fetch-deps`. Pins live in `_VENDOR_PINS` in `src/mailroom_sandbox/cli.py`.
- `requirements/*.txt` — generated: edit `pyproject.toml`, then
  `python scripts/sync_requirements.py`. The one exception is
  `requirements/dojo-release.txt` (DMR-057, kept out of `pyproject.toml`): it is moved
  with `_VENDOR_PINS` on a Dojo vendor refresh, and `tests/test_dojo_source.py` checks it.
- `uv.lock` (use `uv lock`), `.env` / `config/.env` (secrets), `data/runtime/` and
  `data/cache/` (gitignored runtime state).

## Ownership rules that bite

- This repo owns the offline/Modal harness. **Commit sandbox fixes here first**,
  then they are imported into Digital-Mailroom. Never export hub edits back into the
  standalone repos, and never patch scoring or pipeline logic in `vendor/`.
- `sandbox` flags such as `--profile`, `--model`, `--prompt` work before or after the
  subcommand; a flag after the subcommand wins.
- The reporter agent is retired here: `compile_report` is the deterministic
  procedural reporter (no LLM). Reviewers (`sorter_reviewer`) stay enabled.
- Experiment log is `reports/experiment_log.jsonl` (sandbox-local). Reports under
  `reports/` are large; search narrowly instead of grepping the whole tree.

## Environment and dispatch

Follow [the shared dispatch/recovery contract](docs/agent-dispatch.md). Check the
actual checkout and import paths, discover current provider-instance readiness,
record task IDs and reconcile timeouts before retrying. Preserve credential-free
durable handoffs. Use explicit project-only synchronization targets unless global
or sibling updates are intended.

## Coding subagents

The roster and canonical prompts are in `.opencode/agents/`. Two are registered as Claude
Code subagents in `.claude/agents/` as thin read-only wrappers that load the canonical
prompt (no duplicated text to drift): `adversarial-reviewer` and `eval-judge`. For any
other persona (`harness-doctor`, `trace-auditor`, …) read its file in `.opencode/agents/`.

## Skills

- `/vendor-sync` (`.claude/skills/vendor-sync/`) — the sanctioned way to refresh
  `vendor/`. User-invoked only.
