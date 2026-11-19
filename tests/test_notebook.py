"""Notebook bootstrap helpers and gold-field grounding (``mailroom_sandbox.notebook``), network-free."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mailroom_sandbox import notebook
from mailroom_sandbox.eval import experiment_log
from mailroom_sandbox.notebook import (
    ALIAS_FORM,
    CATEGORICAL,
    DATE_FORM,
    GROUNDED,
    GROUNDED_NORMALIZED,
    NON_TEXT,
    NUMBER_FORM,
    NUMERAL_FORM,
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
    # Outside any checkout: the installed package's checkout, never the invalid SANDBOX_ROOT.
    assert notebook.find_repo_root(tmp_path) == root != tmp_path


def test_find_repo_root_without_any_checkout_uses_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_ROOT", str(tmp_path / "nowhere"))
    monkeypatch.setattr(notebook, "_is_checkout", lambda path: False)
    monkeypatch.chdir(tmp_path)
    assert notebook.find_repo_root(tmp_path) == Path.cwd()


def test_base_dir_set_only_in_dotenv_is_honoured(tmp_path, monkeypatch):
    monkeypatch.delenv("SANDBOX_SKIP_DOTENV", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"MAILROOM_BASE_DIR={tmp_path / 'elsewhere'}\n", encoding="utf-8")
    monkeypatch.delenv("MAILROOM_BASE_DIR", raising=False)
    monkeypatch.setattr(notebook.paths, "dotenv_files", lambda: [env_file])
    assert notebook._absolute_base_dir(repo_root()) == (tmp_path / "elsewhere").resolve()
    env_file.write_text("MAILROOM_BASE_DIR=./rel\n", encoding="utf-8")
    assert notebook._absolute_base_dir(repo_root()) == (repo_root() / "rel").resolve()
    # The kernel's own value wins over .env.
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path / "kernel"))
    assert notebook._absolute_base_dir(repo_root()) == (tmp_path / "kernel").resolve()


def test_notebook_honours_the_suite_dotenv_opt_out(tmp_path, monkeypatch):
    monkeypatch.delenv("MAILROOM_BASE_DIR", raising=False)
    monkeypatch.setenv("SANDBOX_SKIP_DOTENV", "1")
    monkeypatch.setattr(notebook.paths, "dotenv_files", lambda: pytest.fail("dotenv must not be read"))
    assert notebook._absolute_base_dir(tmp_path) == tmp_path / "data"


@pytest.mark.parametrize(
    ("spec", "override", "refused"),
    [
        ({"name": "ollama", "base_url": "http://localhost:11434/v1"}, None, None),
        ({"name": "ollama", "base_url": "http://ollama:11434/v1"}, None, None),
        ({"name": "openrouter", "base_url": "https://openrouter.ai/api/v1"}, None, "openrouter.ai"),
        ({"name": "modal-vllm"}, "https://someone--vllm.modal.run/v1", "modal.run"),
        ({"name": "modal-vllm"}, None, "no endpoint"),
    ],
)
def test_probe_refusal_allows_only_local_endpoints(monkeypatch, spec, override, refused):
    from mailroom_sandbox import health, overlay

    monkeypatch.setattr(overlay, "load_profile", lambda name: dict(spec))
    monkeypatch.setattr(health, "_effective_base_url", lambda profile: override)
    reason = notebook.probe_refusal(spec["name"])
    if refused is None:
        assert reason is None
    else:
        assert reason and refused in reason


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


def test_check_prepared_artifacts_reports_malformed_rows_instead_of_crashing(prepared):
    root = repo_root()
    fixtures = _artifact(prepared, "fixtures")
    lines = fixtures.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    no_id = {k: v for k, v in first.items() if k not in ("id", "filename")}
    fixtures.write_text("\n".join([*lines, "[1, 2]", json.dumps(no_id)]) + "\n", encoding="utf-8")
    problems = "\n".join(notebook.check_prepared_artifacts(prepared, root))
    assert "fixtures: 1 line(s) are not JSON objects" in problems
    assert "fixtures: row ? lacks id or filename" in problems


def test_manifest_extractive_gold_is_grounded_in_fixture_text():
    findings = gold_field_grounding()
    assert findings, "manifest produced no gold values to check"
    assert ungrounded(findings) == []
    by_row = {(f.row_id, f.field, f.value): f.status for f in findings}
    assert by_row[("contract_msa", "parties", "ACME Corporation")] == GROUNDED
    assert by_row[("contract_nda", "parties", "Stellar Advisors LLC")] == GROUNDED
    assert by_row[("merger_agreement", "merger_consideration", "all_cash")] == CATEGORICAL
    sec = next(f for f in findings if (f.row_id, f.field) == ("compliance_10k", "regulatory_body"))
    assert (sec.status, sec.form) == (GROUNDED_NORMALIZED, ALIAS_FORM)


def test_copied_gold_block_is_reported_ungrounded():
    rows = [
        {
            "id": "msa",
            "text": "Agreement between ACME\n  CORPORATION and ZENITH TECHNOLOGIES LLC.",
            "expected_fields": {
                "parties": ["Acme Corporation", "HarborPoint Holdings, Inc."],
                "communication_type": "internal memo",
                "page_count": 3,
                "signed": True,
                "governing_law": "",
            },
        }
    ]
    status = {(f.field, f.value): f.status for f in gold_field_grounding(rows)}
    assert status == {
        ("parties", "Acme Corporation"): GROUNDED,
        ("parties", "HarborPoint Holdings, Inc."): UNGROUNDED,
        ("communication_type", "internal memo"): CATEGORICAL,
        ("page_count", 3): UNGROUNDED,
        ("signed", True): NON_TEXT,
        ("governing_law", ""): UNGROUNDED,
    }
    assert [f.value for f in ungrounded(gold_field_grounding(rows, categorical=()))] == [
        "HarborPoint Holdings, Inc.",
        "internal memo",
        3,
        "",
    ]


def test_rows_without_gold_yield_no_findings():
    assert (
        gold_field_grounding(
            [{"id": "x", "text": "t"}, {"id": "y", "text": "t", "expected_fields": {}}]
        )
        == []
    )


_CONTRACT = (
    "This Agreement is entered into as of January 15, 2024. Invoices are paid within "
    "thirty (30) days. The total contract value shall not exceed $2,500,000 over a "
    "term of three (3) years. Notice is due on the 1st day of March, 2025 or 4/1/2025. "
    "Coverage of USD 1.2 million; renewal for twenty-four months."
)


@pytest.mark.parametrize(
    ("value", "form"),
    [
        ("2024-01-15", DATE_FORM),
        ("15th day of January 2024", DATE_FORM),
        ("2025-03-01", DATE_FORM),
        ("2025-04-01", DATE_FORM),
        (2500000, NUMBER_FORM),
        (2500000.0, NUMBER_FORM),
        ("2.5M", NUMBER_FORM),
        ("2500000 USD", NUMBER_FORM),
        (1200000, NUMBER_FORM),
        ("3 years", NUMERAL_FORM),
        ("three years", NUMERAL_FORM),
        ("30 days", NUMERAL_FORM),
        ("24 months", NUMERAL_FORM),
    ],
)
def test_canonical_gold_is_grounded_in_its_written_form(value, form):
    rows = [{"id": "c", "text": _CONTRACT, "expected_fields": {"f": value}}]
    [finding] = gold_field_grounding(rows)
    assert (finding.status, finding.form) == (GROUNDED_NORMALIZED, form)


@pytest.mark.parametrize(
    "value",
    [
        "2024-02-01",
        "2024-15-01",
        2600000,
        "$2.6M",
        "4 years",
        "signed on 1/15/2024 by both",
        "2 years",
    ],
)
def test_canonical_gold_not_in_the_text_stays_ungrounded(value):
    rows = [{"id": "c", "text": _CONTRACT, "expected_fields": {"f": value}}]
    [finding] = gold_field_grounding(rows)
    assert (finding.status, finding.form) == (UNGROUNDED, "")


def test_literal_match_wins_over_normalized():
    rows = [
        {"id": "c", "text": _CONTRACT, "expected_fields": {"f": ["January 15, 2024", "$2,500,000"]}}
    ]
    assert {(f.status, f.form) for f in gold_field_grounding(rows)} == {(GROUNDED, "")}


@pytest.mark.parametrize(
    ("value", "status"),
    [
        (-500, GROUNDED_NORMALIZED),  # a minus sign is part of the amount
        ("-$75", GROUNDED_NORMALIZED),
        ("−500", GROUNDED_NORMALIZED),  # U+2212 MINUS SIGN
        (500, UNGROUNDED),
        (15, UNGROUNDED),  # the day of an ISO date is not a number in the text
        ("3 years", UNGROUNDED),  # not inside "thirteen (13) years"
        ("13 years", GROUNDED_NORMALIZED),
        ("Delaware", UNGROUNDED),  # not inside "Delawarean"
        (9007199254740993, GROUNDED_NORMALIZED),
        (9007199254740992, UNGROUNDED),  # no float rounding above 2**53
    ],
)
def test_signs_word_edges_and_large_integers(value, status):
    text = (
        "A loss of -500 and a credit of $-75. Dated 2024-01-15. A term of thirteen (13) years "
        "under Delawarean practice; reference 9007199254740993."
    )
    [finding] = gold_field_grounding([{"id": "x", "text": text, "expected_fields": {"f": value}}])
    assert finding.status == status


def test_alias_needs_its_written_form_not_a_longer_word():
    def status(text):
        rows = [{"id": "x", "text": text, "expected_fields": {"regulatory_body": "SEC"}}]
        return gold_field_grounding(rows)[0].status

    assert status("Filed under SECTION 13 of the Act.") == UNGROUNDED
    assert status("Filed with the Securities and Exchange Commission.") == GROUNDED_NORMALIZED
    assert status("Filed with the SEC.") == GROUNDED
