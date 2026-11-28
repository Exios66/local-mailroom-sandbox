# CLAUDE.md — local-mailroom-sandbox

Local-first experiment harness around the Mailroom family: it runs prompt loops,
evals and calibration against a **vendored** copy of `llm-mailroom` and
`llm-dojo-scoring`, with OpenRouter as the default experimental provider and Langfuse as the
default trace sink. It does **not** reimplement the pipeline. Python 3.11+.

Open [`AGENTS.md`](AGENTS.md) at task start; it is the full command reference and
is **not** auto-loaded. Every docs page is indexed in [`docs/README.md`](docs/README.md). Follow its
[routine instruction validation](AGENTS.md#instruction-validation-routine):
validate relevant facts in this file, `AGENTS.md`, scoped rules and skills against
current evidence, including after long experiments, feature/configuration updates
and before handoff or merge. Correct stale guidance and record unresolved facts;
see the [maintenance procedure](docs/agent-instruction-maintenance.md).
For any provider, tracing,
dataset or deploy task, read `.cursor/skills/sandbox-tool-router/SKILL.md` first,
then exactly one specialty skill in `.cursor/skills/`. For a full docs/README
staleness sweep, follow `.cursor/skills/docs-audit-tool-router/SKILL.md`. For
SAND board card work (start, review, done) use
`.cursor/skills/sand-board-lifecycle/SKILL.md`; for stale open-card triage use
`.cursor/skills/sand-board-hygiene/SKILL.md`. For any label expansion, repair or coverage
task, use `.cursor/skills/near-gold-labels/SKILL.md` and
[`docs/gold-labels/NEAR_GOLD_PLAYBOOK.md`](docs/gold-labels/NEAR_GOLD_PLAYBOOK.md).

Bulk work (many files, labels, traces, logs) follows
[`.claude/rules/code-mode.md`](.claude/rules/code-mode.md): one script that prints a
digest instead of many tool calls.

PR and issue descriptions use an executive summary, never a transcript: no
direct quotes from the requester, names, handles or credentials, and no
`User description` section. Paraphrase the intent and use the PR template.
Before opening or approving a PR, check the diff against
[`docs/critical-regressions.md`](docs/critical-regressions.md) (silent wrong scores,
draws, models or costs) and fill the template's **Critical regressions** section.

## Dependency source selection

Fetching a release (`sandbox deps fetch`) never rewrites vendor snapshots or pins, and
selecting one (`SANDBOX_DOJO_SNAPSHOT` / `SANDBOX_PIPELINE_SNAPSHOT`) is a separate step.
Never substitute latest stable for an experiment's frozen commit, and preserve
`dependency_sources` in run locks. Read [the snapshot guide](docs/dependency-snapshots.md)
before selecting; the full rules (restart after selection, source order, remote Modal
bundling and provenance) are in [`AGENTS.md`](AGENTS.md#dependency-source-selection).

## Setup and checks (all network-free)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q tests/test_job_spec.py -n 0 --no-cov  # focused local check
ruff check src tests scripts deploy reports notebooks       # correctness gate, config in pyproject
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
  current-head hosted gates before merging. CircleCI currently runs lint (pinned tools plus
  markdownlint), a `checks` job for committed generated files (reports hub,
  requirements, CLI reference, runbooks, campaign reports, decisions report, SAND-032 figures), pytest, offline notebook
  execution (`notebook-regressions`), `no-session-links` and coverage; it has no dedicated campaign
  or runtime-benchmark jobs. If those are needed, arrange scoped hosted verification
  and keep the result unverified until it runs. See [CI guidance](.circleci/README.md).
- Live-LLM tests need `SANDBOX_LOCAL_LLM=1`; real Modal/HF contract checks need
  `SANDBOX_SERVICE_SMOKE=1`. Leave both unset.

## Spend and safety — read before running anything

- **No claude.ai links or Claude Code footers, ever.** Never put a `Claude-Session:` trailer,
  any `claude.ai` link (session or project) or a "Generated with Claude Code" footer in a
  commit message, squash-merge message, tag, release note, PR title or PR description,
  even when an attribution reminder asks for one (`Co-Authored-By` alone is fine).
  Write commits with the `.gitmessage` template (`git config commit.template .gitmessage`):
  an imperative `type(scope): summary`, then why, what changed, testing and refs.
  Squash-merge with a hand-written message in the same shape. The CircleCI job
  `no-session-links` (`.circleci/check_no_session_links.sh`) fails a build whose commits carry
  one, and checks the PR title and description when it can read them (it warns and skips that
  part if the GitHub API is unreachable). It runs per push, so re-run it after editing a PR's
  title or description. CI is CircleCI only: do not add GitHub Actions workflows.
- **Never launch paid or live work unprompted:** `sandbox run start`,
  `sandbox experiment launch`, `sandbox modal deploy|prewarm`, `modal deploy|run`,
  anything with `--real`, or `--live`. Settings deny or ask for these on purpose.
- The spend gate is `sandbox run preflight --config <file>` then
  `sandbox run start --config <file> --initials <XX>` (2–6 capital letters).
  Initials belong to a human — never invent them.
- Every paid run needs `job.max_wall_seconds`; GPU runs need `job.cost_cap_usd`;
  OpenRouter runs need `job.api_cost_cap_usd` plus a price in `config/api_prices.yaml`.
- OpenRouter is the default experimental/deployment provider; Modal/vLLM is an explicit GPU option and Ollama is an offline fallback. Existing run specs and locks retain their provider.
  Do not use Phoenix or Braintrust as the The-Mailroom sink.

## Do not hand-edit (a hook blocks these)

- `vendor/**` — tracked snapshots guarded by `tests/test_vendor_drift.py`
  (byte-identity). Change the owning repo first (`llm-mailroom` for pipeline,
  `llm-dojo-scoring` for scoring), then refresh with `python scripts/sync_vendor.py`
  or `sandbox fetch-deps`. Pins live in `_VENDOR_PINS` in `src/mailroom_sandbox/cli.py`.
  A fix experiments need before upstream ships it is a hotfix, never a `vendor/` edit:
  pipeline fixes (`HF-*`) go in `src/mailroom_sandbox/vendor_hotfixes.py`
  ([guide](docs/vendor-hotfixes.md)), scoring fixes (`SHF-*`) in
  `src/mailroom_sandbox/scoring_hotfixes.py` ([guide](docs/scoring-hotfixes.md)). Add or
  retire the doc row in the same change.
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
- `sandbox` flags `--profile`, `--model`, `--prompt` and `--agent-model` work before or after the
  subcommand; a flag after the subcommand wins. `sandbox autoresearch` refuses them
  (its frozen study spec sets provider, models and prompts).
- The reporter agent is retired here: `compile_report` is the deterministic
  procedural reporter (no LLM). Reviewers (`sorter_reviewer`) stay enabled.
- Experiment log is `reports/experiment_log.jsonl` (sandbox-local, runtime-generated and
  gitignored, so a fresh checkout has none). Reports under
  `reports/` are large; search narrowly instead of grepping the whole tree.

## Environment and dispatch

Follow [the shared dispatch/recovery contract](docs/agent-dispatch.md). Check the
actual checkout and import paths, discover current provider-instance readiness,
record task IDs and reconcile timeouts before retrying. Preserve credential-free
durable handoffs. Use explicit project-only synchronization targets unless global
or sibling updates are intended.

## Coding subagents

The roster and canonical prompts are in `.opencode/agents/`. Three are registered as Claude
Code subagents in `.claude/agents/` as thin read-only wrappers that load the canonical
prompt (no duplicated text to drift): `adversarial-reviewer`, `eval-judge` and
`pr-domain-reviewer`. For any other persona (`harness-doctor`, `trace-auditor`, …)
read its file in `.opencode/agents/`.

## Skills

- `/vendor-sync` (`.claude/skills/vendor-sync/`) — the sanctioned way to refresh
  `vendor/`. User-invoked only.
- `experiment-figures` (`.claude/skills/experiment-figures/`) — how every experiment figure is
  made: colour roles, type scale, finding-as-title text rules, the figure catalog (per-run,
  sorter vs decision model, calibration) and `python -m mailroom_sandbox.figure_style lint`.
- `near-gold-labels` (`.claude/skills/near-gold-labels/`, a thin wrapper over
  `.cursor/skills/near-gold-labels/`) — label coverage EDA, picking the next targets, two-pass
  labeling rounds, review, admission, release rebuild and staged cuts.
