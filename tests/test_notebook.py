"""Notebook bootstrap helpers and gold-field grounding (``mailroom_sandbox.notebook``), network-free."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mailroom_sandbox import notebook
from mailroom_sandbox.eval import experiment_log
from mailroom_sandbox.notebook import (
    CATEGORICAL,
    GROUNDED,
    NON_TEXT,
    UNGROUNDED,
    gold_field_grounding,
    ungrounded,
)
from mailroom_sandbox.paths import repo_root
from mailroom_sandbox.prep import prepare_offline_datasets


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Undo every variable ``bootstrap`` sets, and keep data writes under tmp_path."""
    for var in (
        "SANDBOX_RUN_MODE",
        "OBSERVABILITY_PROVIDER",
        "LOG_LEVEL",
        "PHOENIX_TRACING",
        "SANDBOX_PROFILE",
        notebook.LOG_ENV,
        notebook.OBSERVABILITY_ENV,
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path / "data"))
    return tmp_path


def test_find_repo_root_walks_up_from_notebooks_dir(monkeypatch):
    root = repo_root()
    monkeypatch.delenv("SANDBOX_ROOT", raising=False)
    assert notebook.find_repo_root(root / "notebooks") == root
    monkeypatch.chdir(root / "notebooks")
    assert notebook.find_repo_root() == root


def test_find_repo_root_ignores_invalid_env_and_falls_back(tmp_path, monkeypatch):
    root = repo_root()
    monkeypatch.setenv("SANDBOX_ROOT", str(tmp_path))  # not a checkout
    assert notebook.find_repo_root(root / "notebooks") == root
    # Outside any checkout: fall back to the installed package's root.
    assert notebook.find_repo_root(tmp_path) == notebook.paths.repo_root()


def test_bootstrap_pins_absolute_base_dir_and_offline_defaults(isolated_env, monkeypatch):
    root = repo_root()
    monkeypatch.chdir(root / "notebooks")
    monkeypatch.setenv("MAILROOM_BASE_DIR", "./data")  # the relative .env default
    ctx = notebook.bootstrap(create_dotenv=False, activate_profile=False)

    assert ctx.root == root
    assert ctx.data_dir == root / "data"
    assert notebook.os.environ["MAILROOM_BASE_DIR"] == str(root / "data")
    assert ctx.profile == notebook.OFFLINE_PROFILE
    assert ctx.mock and notebook.os.environ["SANDBOX_RUN_MODE"] == "mock"
    assert ctx.observability == "none" == notebook.os.environ["OBSERVABILITY_PROVIDER"]
    assert notebook.os.environ["LOG_LEVEL"] == "WARNING"
    assert ctx.prepared_dir == root / "data" / "runtime" / "prepared"
    shown = ctx.as_dict()
    assert shown["data_dir"] == "data"
    assert shown["experiment_log"] == "data/runtime/notebooks/experiment_log.jsonl"


def test_bootstrap_respects_kernel_profile_and_sink(isolated_env, monkeypatch):
    monkeypatch.setenv("SANDBOX_PROFILE", "llamacpp")
    monkeypatch.setenv(notebook.OBSERVABILITY_ENV, "langfuse")
    ctx = notebook.bootstrap(mock=False, create_dotenv=False, activate_profile=False)
    assert ctx.profile == "llamacpp"
    assert ctx.observability == "langfuse"
    assert not ctx.mock
    assert notebook.os.environ.get("SANDBOX_RUN_MODE") != "mock"
    # Outside the checkout, as_dict shows the absolute path.
    assert ctx.as_dict()["data_dir"] == str(isolated_env / "data")


def test_bootstrap_activates_profile(isolated_env, monkeypatch):
    calls = []
    monkeypatch.setattr(notebook, "_configure_pipeline_logging", lambda: calls.append(True))
    ctx = notebook.bootstrap(create_dotenv=False)
    assert ctx.profile == "ollama"
    assert calls == [True]
    assert notebook.os.environ["MAILROOM_BASE_DIR"] == str(isolated_env / "data")
    assert notebook.os.environ["OBSERVABILITY_PROVIDER"] == "none"


def test_bootstrap_creates_dotenv_only_when_asked(isolated_env, monkeypatch):
    import mailroom_sandbox.prep as prep

    created = []
    monkeypatch.setattr(prep, "ensure_dotenv_from_example", lambda: created.append(True))
    notebook.bootstrap(activate_profile=False)
    assert created == [True]


def test_configure_pipeline_logging_uses_vendored_setup(monkeypatch):
    import pipeline.logging as plog

    seen = []
    monkeypatch.setattr(plog, "setup_logging", lambda level=None: seen.append(level))
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert notebook._configure_pipeline_logging() is True
    assert seen == ["ERROR"]


def test_configure_pipeline_logging_without_pipeline(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pipeline.logging":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert notebook._configure_pipeline_logging() is False


def test_notebook_log_path_variants(isolated_env, monkeypatch):
    root = repo_root()
    default = notebook.notebook_log_path(root)
    assert default == isolated_env / "data" / "runtime" / "notebooks" / "experiment_log.jsonl"
    monkeypatch.setenv(notebook.LOG_ENV, "reports")
    assert notebook.notebook_log_path(root) == root / "reports" / "experiment_log.jsonl"
    monkeypatch.setenv(notebook.LOG_ENV, "data/runtime/x.jsonl")
    assert notebook.notebook_log_path(root) == root / "data" / "runtime" / "x.jsonl"
    monkeypatch.setenv(notebook.LOG_ENV, str(isolated_env / "abs.jsonl"))
    assert notebook.notebook_log_path() == isolated_env / "abs.jsonl"


def test_experiment_log_redirect_captures_eval_records(isolated_env):
    from mailroom_sandbox.datasets import load_jsonl
    from mailroom_sandbox.eval.runners import run_sorter_eval

    real = experiment_log.jsonl_path()
    target = isolated_env / "nb" / "log.jsonl"
    rows = [{"id": "a", "filename": "a.txt", "expected_doc_class": "contract"}]
    with notebook.experiment_log_redirect(target) as path:
        assert path == target
        result = run_sorter_eval(mock=True, rows=rows, profile="ollama", experiment_name="nb_test")
    assert result["scores"]["exact_match"] == 1.0
    records = load_jsonl(target)
    assert [r["experiment_name"] for r in records] == ["nb_test"]
    assert target.with_suffix(".md").is_file()
    assert experiment_log.jsonl_path() == real


def test_experiment_log_redirect_restores_on_error(isolated_env):
    real_jsonl, real_md = experiment_log.jsonl_path(), experiment_log.md_path()
    with pytest.raises(RuntimeError):
        with notebook.experiment_log_redirect():
            assert experiment_log.jsonl_path() == notebook.notebook_log_path()
            raise RuntimeError("boom")
    assert experiment_log.jsonl_path() == real_jsonl
    assert experiment_log.md_path() == real_md


@pytest.fixture
def prepared(isolated_env):
    return prepare_offline_datasets()


def _artifact(summary: dict, key: str) -> Path:
    return notebook._resolve(repo_root(), summary["artifacts"][key])


def test_check_prepared_artifacts_passes_on_fresh_prepare(prepared):
    assert notebook.check_prepared_artifacts(prepared, repo_root()) == []
    # The on-disk manifest checks the same way.
    on_disk = json.loads(Path(prepared["manifest"]).read_text(encoding="utf-8"))
    assert notebook.check_prepared_artifacts(on_disk) == []


def test_check_prepared_artifacts_reports_broken_invariants(prepared):
    root = repo_root()
    fixtures = _artifact(prepared, "fixtures")
    lines = fixtures.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    fixtures.write_text("\n".join([*lines, json.dumps({**first, "text": ""})]) + "\n", encoding="utf-8")

    balanced = _artifact(prepared, "sorter_pilot_balanced")
    balanced.write_text(balanced.read_text(encoding="utf-8") + lines[0] + "\n", encoding="utf-8")
    _artifact(prepared, "hf").write_text("{not json\n", encoding="utf-8")
    agent, rel = next(iter(prepared["artifacts"]["agents"].items()))
    notebook._resolve(root, rel).unlink()

    problems = "\n".join(notebook.check_prepared_artifacts(prepared, root))
    assert "fixtures: manifest count" in problems
    assert f"fixtures: duplicate ids ['{first['id']}']" in problems
    assert f"fixtures: row {first['id']} lacks text" in problems
    assert "fingerprint: manifest" in problems
    assert "sorter_pilot_balanced: more than one row for a class" in problems
    assert "hf: invalid JSONL" in problems
    assert f"agents/{agent}: missing file" in problems


def test_check_prepared_artifacts_flags_missing_paths_and_class_drift(prepared):
    root = repo_root()
    balanced = _artifact(prepared, "sorter_pilot_balanced")
    rows = balanced.read_text(encoding="utf-8").splitlines()
    balanced.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
    broken = {**prepared, "artifacts": {**prepared["artifacts"], "hf": None}}
    broken["counts"] = {**prepared["counts"], "sorter_pilot_balanced": len(rows) - 1}
    problems = notebook.check_prepared_artifacts(broken, root)
    assert "hf: no artifact path in manifest" in problems
    assert "sorter_pilot_balanced: classes differ from the fixture classes" in problems


def test_manifest_extractive_gold_is_grounded_in_fixture_text():
    findings = gold_field_grounding()
    assert findings, "manifest produced no gold values to check"
    assert ungrounded(findings) == []
    by_row = {(f.row_id, f.field, f.value): f.status for f in findings}
    assert by_row[("contract_msa", "parties", "ACME Corporation")] == GROUNDED
    assert by_row[("contract_nda", "parties", "Stellar Advisors LLC")] == GROUNDED
    assert by_row[("merger_agreement", "merger_consideration", "all_cash")] == CATEGORICAL


def test_copied_gold_block_is_reported_ungrounded():
    rows = [
        {
            "id": "msa",
            "text": "Agreement between ACME\n  CORPORATION and ZENITH TECHNOLOGIES LLC.",
            "expected_fields": {
                "parties": ["Acme Corporation", "HarborPoint Holdings, Inc."],
                "communication_type": "internal memo",
                "page_count": 3,
                "governing_law": "",
            },
        }
    ]
    status = {(f.field, f.value): f.status for f in gold_field_grounding(rows)}
    assert status == {
        ("parties", "Acme Corporation"): GROUNDED,
        ("parties", "HarborPoint Holdings, Inc."): UNGROUNDED,
        ("communication_type", "internal memo"): CATEGORICAL,
        ("page_count", 3): NON_TEXT,
        ("governing_law", ""): UNGROUNDED,
    }
    assert [f.value for f in ungrounded(gold_field_grounding(rows, categorical=()))] == [
        "HarborPoint Holdings, Inc.",
        "internal memo",
        "",
    ]


def test_rows_without_gold_yield_no_findings():
    assert (
        gold_field_grounding(
            [{"id": "x", "text": "t"}, {"id": "y", "text": "t", "expected_fields": {}}]
        )
        == []
    )
