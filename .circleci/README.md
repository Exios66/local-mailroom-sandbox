# CI checks and runtime verification

[`config.yml`](config.yml) runs one workflow with independent `lint` and `test`
jobs on `cimg/python:3.11-node`: lint uses `small` and test uses `medium`.
This repository's CI
configuration is CircleCI. GitHub branch protection must require
`ci/circleci: lint` and `ci/circleci: test` to enforce both gates on `main`;
configuration comments alone do not enable branch protection.

## Gates and artifacts

| Job | Checks |
| --- | --- |
| `lint` | Ruff on source/tests/scripts/deploy/reports; Bandit medium-and-higher severity; YAMLlint; ShellCheck warning level; Markdownlint. Repository config files define rule exclusions. |
| `test` | Complete network-free pytest suite excluding `local_llm`, merged coverage, committed reports-hub snapshot, and generated requirements mirrors. |

The test command uses two pytest-xdist workers with `--dist loadfile` and
retains JUnit at `test-results/junit.xml`, coverage XML at
`coverage/coverage.xml`, and the slowest 20 test durations in the job log.
CircleCI ingests the JUnit results and stores the coverage directory as an
artifact. Coverage is scoped to `src/mailroom_sandbox` by `pyproject.toml`;
the configured 77% failure threshold remains in force.

`loadfile` keeps each test file on one worker. In particular,
`tests/test_pipeline_routing_matrix.py` accumulates a process-local `WALKED`
union and then checks aggregate graph-edge coverage. Splitting its scenarios
between workers invalidates that assertion. Preserve file scheduling unless
the test contract itself is deliberately redesigned.

The default is `SANDBOX_XDIST=2`, matching the test job's two allocated CPUs
and 4 GB RAM. CircleCI's Docker `small` allocation is one CPU and 2 GB;
two workers on that allocation did not speed up hosted job 609 (1032.962
seconds pytest, 1103.057 seconds total). See the
[official resource table](https://circleci.com/docs/guides/execute/using-docker/).
The test job therefore overrides the shared executor's small default with
`medium`; lint stays small. The resource change affects credits per minute,
so measure credit usage separately from wall time.

Set an explicit worker count in CircleCI to override it. Do not use `auto`:
Docker can expose the host CPU count and start many workers, exhausting memory before imports
finish. Changing worker count does not change test selection or waive gates.

## Caches and dependencies

| Cache key | Contents and invalidation |
| --- | --- |
| `pip-lint-v1` | Lint lane's `~/.cache/pip`, restored and saved. Bump manually when changing the lint tool set. Ruff/YAMLlint/Bandit installs are unpinned. |
| `pip-v1-{{ checksum "pyproject.toml" }}` | Test lane's pip download cache; changes to the project dependency definition generate a new key. |
| `npm-v1` | `~/.npm` for Markdownlint CLI2 0.18.1; bump for a deliberate tool/cache refresh. |

Caches retain downloaded packages, not a preinstalled environment. Each job
still installs its tools. `npx` may consult the registry, and ShellCheck's apt
installation is uncached. A cache hit does not make setup network-free; the
pytest workload itself is network-free. `pytest-xdist` is part of the dev
extra and its generated requirements mirrors. Change dependencies in
`pyproject.toml` and regenerate with `scripts/sync_requirements.py`.

## Proving a runtime improvement

Use completed passing hosted runs. Record the commit SHA, worker settings,
executor, cache hit/miss state, total job duration and pytest step duration.
Compare the same test surface and coverage settings; account for added tests,
queue/setup time and cold caches. Keep failures separate from speed claims.
Inspect the slow-test log, JUnit results (including the aggregate routing
check) and coverage artifact to ensure a shorter run still performs the work.

Pre-change passing hosted reference runs for the PR 274 stack were test job
602 (988.576 seconds total; 935.179 seconds pytest) and job 604 (1022.392
seconds total; 958.421 seconds pytest). They are baselines, not proof of the
new configuration's hosted gain. Compare completed current-head runs before
reporting a percentage reduction. Local timing measurements cannot establish
the hosted improvement.

## Local verification policy

Keep expensive full suites, coverage sweeps, large mock campaigns and timing
benchmarks on hosted CI. Locally, inspect diffs and use lint, configuration
validation, generated-file checks and narrow fixture regressions. For example:

```bash
pytest -q tests/test_dataset_registry.py  # one worker, no coverage
python scripts/sync_requirements.py --check
python scripts/check_cli_surface.py --check
git diff --check
```

Choose only checks relevant to the changed surface. Investigate a hosted
failure with the smallest useful local reproduction, then let CI run the
complete gate again. Default tests must not load developer `.env` secrets or
make real LLM/Hub calls; live LLM tests remain opt-in via
`SANDBOX_LOCAL_LLM=1`. Merge only after required checks pass on the current
head, with review findings resolved and the stack's final diff inspected.
See [agent test policy](../AGENTS.md#tests).
