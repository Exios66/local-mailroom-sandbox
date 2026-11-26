"""Meta regression guards — fail closed when shipped capabilities go missing.

These tests complement the behavioral suites (watch web, agents, vendor, eval)
by asserting wiring that PR #63–#65 (unified themed logging + watch --web +
sandbox dev) and HUB-015 (reduced profile) depend on, and that CI actually
runs the network-free pytest suite.
"""

from __future__ import annotations

import importlib
import re

import pytest
import yaml

from mailroom_sandbox.eval import agents
from mailroom_sandbox.paths import repo_root

ROOT = repo_root()
CI_CONFIG = ROOT / ".circleci" / "config.yml"

# Files that must exist — deleting them should fail CI, not silently drop coverage.
REGRESSION_TEST_MODULES = (
    "tests/test_vendor.py",
    "tests/test_vendor_drift.py",
    "tests/test_agents.py",
    "tests/test_eval.py",
    "tests/test_watch.py",
    "tests/test_watch_web.py",
    "tests/test_watch_demo.py",
    "tests/test_mailroom_session.py",
    "tests/test_board.py",
    "tests/test_eval_environment_lineage.py",
    "tests/test_job_preflight.py",
    "tests/test_serving_parity.py",
    "tests/test_requirements.py",
    "tests/test_subagents.py",
    "tests/test_governance_sand.py",
)


@pytest.mark.parametrize("rel", REGRESSION_TEST_MODULES)
def test_regression_guard_module_exists(rel):
    path = ROOT / rel
    assert path.is_file(), f"missing regression module {rel}"


def test_ci_workflow_runs_network_free_pytest():
    """The sandbox CI must not be a no-op stub (regression of DMR-057 guardrails)."""
    assert CI_CONFIG.is_file()
    config = yaml.safe_load(CI_CONFIG.read_text(encoding="utf-8"))
    steps = config["jobs"]["test"]["steps"]
    joined = "\n".join(
        step["run"]["command"] for step in steps
        if isinstance(step, dict) and isinstance(step.get("run"), dict)
    )
    assert "pytest" in joined
    assert "local_llm" in joined
    assert "echo ok" not in joined
    assert "test" in config["workflows"]["ci"]["jobs"]


def test_ci_parallel_test_shards_feed_a_combined_coverage_gate():
    """A split test job only measures part of the suite per container, so the
    84% floor must be enforced on the combined data, after every shard ran."""
    config = yaml.safe_load(CI_CONFIG.read_text(encoding="utf-8"))
    test_job = config["jobs"]["test"]
    shards = test_job.get("parallelism", 1)
    test_cmds = "\n".join(
        step["run"]["command"] for step in test_job["steps"]
        if isinstance(step, dict) and isinstance(step.get("run"), dict)
    )
    assert "--dist loadfile" in test_cmds  # WALKED union stays on one worker
    if shards == 1:
        return
    assert "circleci tests split" in test_cmds
    assert "--cov-fail-under=0" in test_cmds  # per-shard partials must not gate
    assert any(
        isinstance(step, dict) and "coverage-data" in str(step.get("persist_to_workspace", ""))
        for step in test_job["steps"]
    )
    cov_cmds = "\n".join(
        step["run"]["command"] for step in config["jobs"]["coverage"]["steps"]
        if isinstance(step, dict) and isinstance(step.get("run"), dict)
    )
    assert "coverage combine" in cov_cmds
    assert "coverage report" in cov_cmds and "--fail-under" not in cov_cmds  # pyproject's floor
    assert f"-eq {shards}" in cov_cmds  # every shard's data file is present
    workflow = {
        (next(iter(j)) if isinstance(j, dict) else j): (j[next(iter(j))] if isinstance(j, dict) else {})
        for j in config["workflows"]["ci"]["jobs"]
    }
    assert "test" in workflow["coverage"].get("requires", [])
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "fail_under = 84" in pyproject


def test_loadfile_scheduler_splits_only_files_whose_tests_share_no_state():
    """CI's `--dist loadfile` keeps each file on one worker, so process-local unions such as
    test_pipeline_routing_matrix.WALKED stay whole. conftest's scheduler hands out single tests
    only for PER_TEST_XDIST_FILES, whose tests share no state; on one worker the slowest of them
    set the floor for a whole CI container."""
    import conftest

    # _split_scope reads no scheduler state; __init__ would need a live worker spec.
    sched = object.__new__(conftest.PerTestLoadFileScheduling)
    routing = "tests/test_pipeline_routing_matrix.py::test_every_edge_is_walked[a]"
    arbiter = "tests/test_arbiter_termination.py::test_every_judge_and_arbiter_path_terminates[x]"
    assert sched._split_scope(routing) == "tests/test_pipeline_routing_matrix.py"
    assert sched._split_scope(arbiter) == arbiter
    assert "tests/test_pipeline_routing_matrix.py" not in conftest.PER_TEST_XDIST_FILES
    for rel in conftest.PER_TEST_XDIST_FILES:
        assert (ROOT / rel).is_file(), rel


class _DistConfig:
    def __init__(self, dist):
        self.dist = dist

    def getvalue(self, name):
        return {"dist": self.dist, "tx": ["2*popen"]}.get(name)


def test_ci_s_loadfile_mode_gets_the_per_test_scheduler():
    """Without this, a hook that stopped answering for `loadfile` would silently bring back the
    one-worker floor while every other guard still passed."""
    import conftest

    sched = conftest.pytest_xdist_make_scheduler(config=_DistConfig("loadfile"), log=None)
    assert isinstance(sched, conftest.PerTestLoadFileScheduling)
    assert sched.numnodes == 2


@pytest.mark.parametrize("dist", ["load", "loadgroup", "no"])
def test_other_dist_modes_keep_xdist_s_own_scheduler(dist):
    import conftest

    assert conftest.pytest_xdist_make_scheduler(config=_DistConfig(dist), log=None) is None


def test_ci_checks_job_gates_every_committed_generated_file():
    """Stale generated files (critical-regressions: CLI reference, runbooks, hub,
    requirements) fail in their own job, which waits for nothing."""
    config = yaml.safe_load(CI_CONFIG.read_text(encoding="utf-8"))
    cmds = "\n".join(
        step["run"]["command"] for step in config["jobs"]["checks"]["steps"]
        if isinstance(step, dict) and isinstance(step.get("run"), dict)
    )
    for check in (
        "reports/dashboard/build_hub.py --check",
        "scripts/sync_requirements.py --check",
        "scripts/check_cli_surface.py --check",
        "sandbox runbook check",
    ):
        assert check in cmds, check
    assert "checks" in config["workflows"]["ci"]["jobs"]  # a bare entry: no `requires`
    lint = "\n".join(
        str(step) for step in config["jobs"]["lint"]["steps"] if isinstance(step, dict)
    )
    assert "-r .circleci/lint-requirements.txt" in lint
    assert 'checksum ".circleci/lint-requirements.txt"' in lint
    pins = (ROOT / ".circleci" / "lint-requirements.txt").read_text(encoding="utf-8")
    tools = [ln for ln in pins.splitlines() if ln.strip() and not ln.startswith("#")]
    assert tools and all("==" in ln for ln in tools), tools


def test_cli_parser_builds_without_importing_floor_app(monkeypatch):
    """`sandbox <cmd>` on native Windows must not trip the floor app's unix-only imports.

    floor_app reaches job.checkpoint -> fcntl; the floor parser gets its port from
    ports.py, so building ANY parser would only import floor_app through a floor run.
    """
    import sys

    import mailroom_sandbox
    from mailroom_sandbox import cli

    # Keep the interpreter's real module mapping and clear the package attribute
    # too: ``from mailroom_sandbox import tui`` must not reuse a cached package.
    for name in list(sys.modules):
        if name == "mailroom_sandbox.tui" or name.startswith("mailroom_sandbox.tui."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.delattr(mailroom_sandbox, "tui", raising=False)
    cli.build_parser()
    assert "mailroom_sandbox.tui.floor_app" not in sys.modules


def test_reduced_profile_reporter_retired_in_components():
    from mailroom_sandbox.components import is_enabled

    text = (ROOT / "config" / "components.yaml").read_text(encoding="utf-8")
    assert "reporter" in text
    assert "retired_agents" in text
    assert not is_enabled("agents", "reporter")
    assert is_enabled("nodes", "compile_report")
    assert "reporter" not in agents.SPECS


def test_five_live_specialists_stay_enabled():
    """HUB-015 / AGENTS.md: one specialist agent per live doc class."""
    from mailroom_sandbox.components import is_enabled

    live = (
        "contracts_specialist",
        "merger_agreement_specialist",
        "corporate_records_specialist",
        "correspondence_specialist",
        "insurance_claims_specialist",
    )
    for name in live:
        assert is_enabled("agents", name), name
    overlay = yaml.safe_load((ROOT / "config" / "taxonomy.overlay.yaml").read_text(encoding="utf-8"))
    for name in live:
        assert name in (overlay.get("agents") or {}), f"{name} missing from taxonomy overlay"


def test_unified_mailroom_logging_surface():
    """PR #63/#65: pretty_log palette drives browser theme; dev == watch --web --demo."""
    web = importlib.import_module("mailroom_sandbox.tui.web")
    pl = importlib.import_module("mailroom_sandbox.tui.pretty_log")
    assert callable(getattr(web, "serve_watch_web", None))
    assert callable(getattr(web, "_html_page", None))
    page = web._html_page().decode()
    assert "THE MAILROOM" in page
    assert web.THEME["blue"] == "#%02x%02x%02x" % pl.BLUE
    cli_src = (ROOT / "src" / "mailroom_sandbox" / "cli.py").read_text(encoding="utf-8")
    assert re.search(r'add_parser\s*\(\s*["\']dev["\']', cli_src)
    assert "--web" in cli_src and "--demo" in cli_src


@pytest.mark.parametrize(
    "task",
    ["sorter", "judge", "pipeline", "local_vs_api", "compile_report"],
)
def test_mock_eval_tasks_remain_registered(task):
    if task == "compile_report":
        assert task in agents.SPECS
    else:
        assert task in agents.EVAL_TASKS
