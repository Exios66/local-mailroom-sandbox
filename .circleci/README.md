# CI checks and runtime verification

[`config.yml`](config.yml) runs one workflow on `cimg/python:3.11-node`: `lint`
(`small`), `test` (`medium`, 4 parallel containers), `coverage` (`small`,
runs after `test`) and `no-session-links` (`small`; fails on claude.ai links,
Claude-Session trailers or Claude Code footers in commits or the PR description). This repository's CI configuration is CircleCI. GitHub
branch protection must require `ci/circleci: lint`, `ci/circleci: test`,
`ci/circleci: coverage` and `ci/circleci: no-session-links` to enforce every gate on `main`; configuration
comments alone do not enable branch protection.

## Gates and artifacts

| Job | Checks |
| --- | --- |
| `lint` | Ruff on source/tests/scripts/deploy/reports; Bandit medium-and-higher severity; YAMLlint; ShellCheck warning level; Markdownlint. Repository config files define rule exclusions. |
| `test` | Complete network-free pytest suite excluding `local_llm`, split by file across 4 containers (`parallelism: 4`) using recorded timings. Each container writes its own coverage data file. |
| `coverage` | Combines the 4 coverage data files (fails unless all 4 are present), enforces `fail_under = 84` from `pyproject.toml` on the combined total, writes coverage XML, then checks the committed reports-hub snapshot and generated requirements mirrors. |

These are the configured jobs. There is no dedicated full-corpus campaign or
serial/parallel runtime-benchmark job; passing `lint` and `test` does not establish
those results. If a task requires one, arrange a separately scoped hosted job
and record its revision, workload and results. Until it runs, label that check
pending or unverified. Preserve live-call and spend gates for any campaign.

`circleci tests split --split-by=timings` gives each container a share of
the test files (by file name until timing data exists). Each container runs its
share with two pytest-xdist workers and `--dist loadfile`, writes JUnit to
`test-results/junit-<index>.xml` (`junit_family=legacy`, which carries the
`file` attribute the timing split needs) and the slowest 10 durations to the
job log. A single container covers only part of the code, so each passes
`--cov-fail-under=0`; the `coverage` job enforces the real 84% floor on the
combined data and stores `coverage/coverage.xml` as an artifact. Coverage is
scoped to `src/mailroom_sandbox` by `pyproject.toml`.
`tests/test_regression_guards.py::test_ci_parallel_test_shards_feed_a_combined_coverage_gate`
fails if the shards stop feeding a combined, floor-enforcing coverage job.

`loadfile` keeps each test file on one worker, and the timing split never
divides a file between containers. In particular,
`tests/test_pipeline_routing_matrix.py` accumulates a process-local `WALKED`
union and then checks aggregate graph-edge coverage. Splitting its scenarios
between workers invalidates that assertion. Preserve file scheduling unless
the test contract itself is deliberately redesigned.

Every worker independently collects the entire suite before scheduling, even
with `loadfile`. Keep parametrized case order and IDs deterministic: sort
unordered inputs, and give generated archives or other clock/random-dependent
bytes explicit descriptive `pytest.param(..., id="...")` labels. A collection
mismatch aborts before the tests run; the resulting partial coverage is not a
completed-suite measurement. Fix the unstable collection instead of reducing
workers or weakening coverage. `test_collection_ids_are_independent_of_archive_clock`
checks snapshot collection in two fresh, sequential single-worker interpreters
with different archive clocks and hash seeds; this reproduces the failure
without an expensive local suite or concurrent workers.

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
| `pip-lint-v2` | Lint lane's `~/.cache/pip`, restored and saved. Bump manually when changing the lint tool set. Ruff/YAMLlint/Bandit/`shellcheck-py` installs are unpinned. |
| `venv-v1-{{ arch }}-{{ checksum ".ci-python-version" }}-{{ checksum "pyproject.toml" }}` | The installed dev virtualenv at `~/venv`, shared by `test` and `coverage`, keyed on the exact interpreter version (the image tag floats) and `pyproject.toml`. A hit skips `pip install` entirely (a venv that cannot import the package is rebuilt); a dependency change in `pyproject.toml` builds a new one. The editable install is a plain `.pth` to this checkout's `src/`, so new modules need no reinstall. |
| `npm-v1` | `~/.npm` for Markdownlint CLI2 0.18.1; bump for a deliberate tool/cache refresh. |

The lint lane caches downloads and still installs its tools; ShellCheck comes
from the `shellcheck-py` wheel, so there is no `apt-get update`. `npx` may
consult the registry. A cache hit does not make setup network-free; the
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
seconds total; 958.421 seconds pytest). Their floor-feature test surface
differs from the CI prerequisite's, so use the matched-workload comparison
below for the allocation correction. Local timings cannot establish the
hosted improvement.

The completed #275 allocation comparison used the same 2,798 test-result
identities (2,770 passed, 28 skipped), including aggregate routing coverage,
with 81.80% coverage in both runs:

| Hosted test job | Allocation | Pytest step | Total job |
| --- | --- | --- | --- |
| [609](https://circleci.com/gh/Exios66/local-mailroom-sandbox/609), `06ae5d5` | small, two workers | 1032.962 s | 1103.057 s |
| [620](https://circleci.com/gh/Exios66/local-mailroom-sandbox/620), `9c9f81b` | medium, two workers | 503.073 s | 577.869 s |

That is a 51.3% pytest-step and 47.6% total-job reduction for these hosted
runs. It demonstrates wall-time improvement, not reduced credit consumption
or a guarantee for every push. Recheck the current feature stack's gates;
this prerequisite comparison does not certify later code changes.

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
