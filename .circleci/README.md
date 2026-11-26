# CI checks and runtime verification

[`config.yml`](config.yml) runs one workflow: `lint`
(`small`), `checks` (`small`), `test` (`medium`, 8 parallel containers),
`notebook-regressions` (`small`), `coverage` (`small`, runs after `test`) and `no-session-links` (`small`; fails
on claude.ai links, Claude-Session trailers or Claude Code footers in commits or
the PR description). The jobs use `cimg/python:3.11-node` except `no-session-links`,
which uses `cimg/python:3.11`. `lint`, `checks`, `test`, `notebook-regressions` and `no-session-links` start
together. This repository's CI configuration is CircleCI. GitHub branch
protection must require `ci/circleci: lint`, `ci/circleci: checks`,
`ci/circleci: test`, `ci/circleci: notebook-regressions`, `ci/circleci: coverage` and `ci/circleci: no-session-links`
to enforce every gate on `main`; configuration comments alone do not enable
branch protection.

## Gates and artifacts

| Job | Checks |
| --- | --- |
| `lint` | Ruff on source/tests/scripts/deploy/reports; Bandit medium-and-higher severity; YAMLlint; ShellCheck warning level; Markdownlint CLI2 0.18.1. Tool versions are pinned in [`lint-requirements.txt`](lint-requirements.txt); rule exclusions live in the repository config files (`pyproject.toml`, `.yamllint.yaml`, `.shellcheckrc`, `.markdownlint-cli2.yaml`). |
| `checks` | Committed generated files match their generators: the reports-hub snapshot (`build_hub.py --check`), the requirements mirrors (`sync_requirements.py --check`), the CLI reference (`check_cli_surface.py --check`) and the runbook catalog pins plus generated `docs/runbooks/` (`sandbox runbook check`), and the campaign report indexes (`sandbox report build --campaign rb1 --check`). Network-free; it needs the dev virtualenv but waits for no other job. |
| `notebook-regressions` | Dedicated offline execution and bootstrap checks in `tests/test_notebook.py`, `tests/test_notebooks.py` and `tests/test_prep.py`, with the notebook dependencies installed. This complements the full-suite and coverage gates. |
| `test` | Complete network-free pytest suite excluding `local_llm`, split by file across 8 containers (`parallelism: 8`) using recorded timings. Each container writes its own coverage data file. JUnit results are stored even when a shard fails, so the timing split keeps its data. |
| `coverage` | Combines the 8 coverage data files (fails unless all 8 are present), enforces `fail_under = 84` from `pyproject.toml` on the combined total and stores coverage XML. |

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

The one exception is `PER_TEST_XDIST_FILES` in `tests/conftest.py`. Its
`pytest_xdist_make_scheduler` hook returns a `LoadFileScheduling` subclass whose
`_split_scope` gives each test in those files its own scope, so their tests
spread over both workers. Every other file keeps one scope. The hook changes no
node IDs. (`--dist loadgroup` is not a substitute: with pytest 9.2 and
pytest-xdist 3.8 its `xdist_group` suffix is written to `_nodeid`, which pytest
no longer reads, so every test is scheduled singly.) The listed files are the
slowest ones, and their tests use only function-scoped fixtures. On one worker,
`tests/test_arbiter_termination.py` (260 tests, about 218 seconds) set the floor
for a whole container, so adding containers could not shorten the job. Add a
file only after checking that none of its tests reads state that another test
leaves behind.
`tests/test_regression_guards.py::test_loadfile_scheduler_splits_only_files_whose_tests_share_no_state`
fails if the routing matrix is listed or the split leaks to other files.

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
| `pip-lint-v3-{{ checksum ".circleci/lint-requirements.txt" }}` | Lint lane's `~/.cache/pip`. Ruff, Bandit, YAMLlint and `shellcheck-py` are pinned in `lint-requirements.txt`; changing a pin changes the key. Before a bump, run the new versions on the whole tree and fix new findings in the same change. |
| `venv-v1-{{ arch }}-{{ checksum ".ci-python-version" }}-{{ checksum "pyproject.toml" }}` | The installed dev virtualenv at `~/venv`, shared by `checks`, `test` and `coverage`, keyed on the exact interpreter version (the image tag floats) and `pyproject.toml`. A hit skips `pip install` entirely (a venv that cannot import the package is rebuilt); a dependency change in `pyproject.toml` builds a new one. The editable install is a plain `.pth` to this checkout's `src/`, so new modules need no reinstall. |
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
pytest -q tests/test_dataset_registry.py -n 0 --no-cov  # one worker, no coverage
python scripts/sync_requirements.py --check
python scripts/check_cli_surface.py --check
sandbox runbook check
npx --yes markdownlint-cli2@0.18.1
git diff --check
```

Choose only checks relevant to the changed surface. Investigate a hosted
failure with the smallest useful local reproduction, then let CI run the
complete gate again. Default tests must not load developer `.env` secrets or
make real LLM/Hub calls; live LLM tests remain opt-in via
`SANDBOX_LOCAL_LLM=1`. Merge only after required checks pass on the current
head, with review findings resolved and the stack's final diff inspected.
See [agent test policy](../AGENTS.md#tests).

## Diagnose failed jobs from the sandbox

Set `CIRCLE_TOKEN` to a CircleCI personal API token. `sandbox doctor --service circleci`
checks only whether it is present; add `--live` to authenticate with CircleCI. Fetch failed
step output with `sandbox circleci logs --job 123` or all failed jobs in a pipeline with
`sandbox circleci logs --pipeline <pipeline-uuid>`. Add `--all-steps` to include successful
steps, and `--project gh/owner/repo` for another GitHub project. The default is this repository.
The command uses CircleCI's v2 pipeline/workflow endpoints and v1.1 job step output; signed
output URLs are fetched without the API token. Logs can contain sensitive data: review them
before sharing. See [CircleCI's incident guide](https://circleci.com/docs/guides/orchestrate/analyze-pipelines-during-an-incident/).

## Notebook execution

The `notebook-regressions` job installs nbclient, nbformat, ipykernel, pandas and matplotlib
into its dev environment, then executes the four offline notebooks and their bootstrap/prep
regressions with one worker. This prevents the base dev suite from silently skipping notebook
runtime checks. The existing parallel full suite and combined 84% coverage gate remain required.
