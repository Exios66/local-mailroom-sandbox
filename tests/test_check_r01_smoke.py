"""scripts/check_r01_smoke.py: the R01 provider-pin gate over a served-provider ledger. Offline."""
from __future__ import annotations

import importlib.util
import json

import pytest
import yaml

from mailroom_sandbox.paths import repo_root

RUNS = repo_root() / "config" / "runs"
QWEN = RUNS / "runbook-r01-smoke-qwen3.7-flash.yaml"
LUNA = RUNS / "runbook-r01-smoke-gpt-6-luna-decisions.yaml"
QWEN_RUN = yaml.safe_load(QWEN.read_text())["run_id"]
LUNA_RUN = yaml.safe_load(LUNA.read_text())["run_id"]
# The pipeline smoke draws 2 docs per class: the sorter (10) and the contract and merger
# specialists (4) are LangChain calls, the other 6 specialists go through the retry path.
PIPELINE_PATHS = ["langchain"] * 14 + ["retry_chat_completion"] * 6


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_r01_smoke", repo_root() / "scripts" / "check_r01_smoke.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(model, status="verified", provider="Alibaba", served=None, path="langchain", run_id=None):
    if run_id is None:
        run_id = LUNA_RUN if path == "decisions" else QWEN_RUN
    return {"requested_model": model, "served_model": served or model, "served_provider": provider,
            "pinned_order": ["Alibaba"], "status": status, "mismatch": status == "mismatch", "call_path": path,
            "run_id": run_id}


def _pipeline_rows(model="qwen/qwen3.7-flash", extra=0):
    return [_row(model, path=p) for p in PIPELINE_PATHS + ["retry_chat_completion"] * extra]


def _ledger(tmp_path, rows, name="served.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def _run(gate, capsys, *args):
    code = gate.main([str(a) for a in args])
    return code, capsys.readouterr()


def test_twenty_verified_rows_pass_the_pipeline_smoke(gate, tmp_path, capsys):
    rows = _pipeline_rows()
    code, out = _run(gate, capsys, "--ledger", _ledger(tmp_path, rows), "--config", QWEN)
    assert code == 0, out.out
    assert "PASS qwen/qwen3.7-flash: 20 rows (>= 20 expected" in out.out
    assert "R01 gate: PASS" in out.out


def test_no_rows_fails(gate, tmp_path, capsys):
    code, out = _run(gate, capsys, "--ledger", _ledger(tmp_path, []), "--config", QWEN)
    assert code == 1 and "no ledger rows" in out.out


def test_fewer_rows_than_expected_calls_fails(gate, tmp_path, capsys):
    rows = [_row("qwen/qwen3.7-flash")] * 19
    code, out = _run(gate, capsys, "--ledger", _ledger(tmp_path, rows), "--config", QWEN)
    assert code == 1 and "19 rows < 20 expected (10 docs x 2 per-doc agents)" in out.out


@pytest.mark.parametrize("bad", [{"status": "unverified"}, {"status": "mismatch"}, {"status": None}])
def test_any_row_that_is_not_verified_fails(gate, tmp_path, capsys, bad):
    rows = _pipeline_rows(extra=4)
    rows[3].update(bad)
    if bad["status"] is None:
        del rows[3]["status"]  # an old-format row carries no status: never evidence
    code, out = _run(gate, capsys, "--ledger", _ledger(tmp_path, rows), "--config", QWEN, "--json")
    result = json.loads(out.out)
    assert code == 1 and result["ok"] is False
    assert result["models"]["qwen/qwen3.7-flash"]["reasons"][0].startswith("1 row(s) not verified")


def test_mismatch_false_without_verified_status_is_not_evidence(gate, tmp_path, capsys):
    rows = [{**r, "status": "unverified", "mismatch": False} for r in _pipeline_rows()]
    code, _ = _run(gate, capsys, "--ledger", _ledger(tmp_path, rows), "--config", QWEN)
    assert code == 1


def test_rows_for_an_unnamed_model_fail_unless_allowed(gate, tmp_path, capsys):
    rows = _pipeline_rows() + [_row("deepseek/deepseek-v4-flash", status="unverified")]
    ledger = _ledger(tmp_path, rows)
    code, out = _run(gate, capsys, "--ledger", ledger, "--config", QWEN)
    assert code == 1 and "FAIL rows for models no config names: {'deepseek/deepseek-v4-flash': 1}" in out.out
    code, out = _run(gate, capsys, "--ledger", ledger, "--config", QWEN, "--allow-extra-models")
    assert code == 0 and "note rows for models" in out.out


def test_decision_smoke_expects_one_decision_per_document(gate, tmp_path, capsys):
    rows = [_row("openai/gpt-6-luna-decisions", served="openai/gpt-6-luna-decisions-20261006", provider=None,
                 path="decisions") for _ in range(10)]
    code, out = _run(gate, capsys, "--ledger", _ledger(tmp_path, rows), "--config", LUNA)
    assert code == 0, out.out
    assert ">= 10 expected; sorter_reviewer (decisions)" in out.out


def test_ledgers_and_configs_pool(gate, tmp_path, capsys):
    a = _ledger(tmp_path, _pipeline_rows(), "a.jsonl")
    b = _ledger(tmp_path, [_row("openai/gpt-6-luna-decisions", path="decisions")] * 10, "b.jsonl")
    code, out = _run(gate, capsys, "--ledger", a, "--ledger", b, "--config", QWEN, LUNA)
    assert code == 0, out.out
    assert out.out.count("PASS ") == 2


def test_per_doc_override_and_unreadable_input(gate, tmp_path, capsys):
    rows = _pipeline_rows(extra=10)
    code, out = _run(gate, capsys, "--ledger", _ledger(tmp_path, rows), "--config", QWEN, "--per-doc", "4")
    assert code == 1 and "30 rows < 40 expected" in out.out
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n")
    code, out = _run(gate, capsys, "--ledger", bad, "--config", QWEN)
    assert code == 2 and "not JSON" in out.err
    code, out = _run(gate, capsys, "--ledger", tmp_path / "missing.jsonl", "--config", QWEN)
    assert code == 2 and "cannot read ledger" in out.err


def test_expected_calls_by_task(gate):
    from mailroom_sandbox.job.spec import load_run_spec

    sorter = load_run_spec(RUNS / "runbook-r03-sorter-v0-dev.yaml")
    assert gate.expected_calls(sorter) == {"qwen/qwen3.7-flash": {"docs": 900, "per_doc": 1, "agents": ["sorter"],
                                                                  "paths": {"langchain": 900}}}
    pipeline = load_run_spec(QWEN)
    table = {"sorter": {"provider": "openrouter", "model": "a/m"},
             "contracts_specialist": {"provider": "openrouter", "model": "a/m"},
             "merger_agreement_specialist": {"provider": "openrouter", "model": "b/m"}}
    with pytest.raises(gate.GateInputError, match="split across models"):
        gate.expected_calls(pipeline, assignments=table)
    table["merger_agreement_specialist"]["model"] = "a/m"
    assert gate.expected_calls(pipeline, assignments=table)["a/m"]["per_doc"] == 2
    assert gate.expected_calls(pipeline, assignments=table)["a/m"]["paths"] == {"langchain": 14, "retry_chat_completion": 6}
    table["sorter"] = {"provider": "modal-vllm", "model": "Qwen/x"}
    with pytest.raises(gate.GateInputError, match="not served over OpenRouter"):
        gate.expected_calls(pipeline, assignments=table)


def test_every_pinned_chat_model_has_a_smoke_config_that_calls_only_that_model(gate):
    """One R01 smoke per provider_pins.yaml model; every OpenRouter agent in it is on that model."""
    from mailroom_sandbox.agent_routes import describe
    from mailroom_sandbox.job.spec import load_run_spec

    pins = yaml.safe_load((repo_root() / "config" / "provider_pins.yaml").read_text())["models"]
    seen = {}
    for path in sorted(RUNS.glob("runbook-r01-smoke-*.yaml")):
        spec = load_run_spec(path)
        text = path.read_text()
        assert spec.run_id == path.stem and spec.dataset.limit == 10
        assert spec.dataset.exclude_ids_file == "config/splits/runbook-v1/dev-look1.exclude.ids"
        assert spec.dataset.revision == load_run_spec(RUNS / "runbook-r03-sorter-v0-dev.yaml").dataset.revision
        assert spec.job.max_wall_seconds and spec.job.api_cost_cap_usd and spec.job.cost_cap_usd
        assert f"SANDBOX_SERVED_LOG=data/runtime/r01/served-{path.stem.removeprefix('runbook-r01-smoke-')}.jsonl" in text
        assert "--initials <XX>" in text and "sandbox run start" in text
        expected = gate.expected_calls(spec)
        assert len(expected) == 1
        (model, want), = expected.items()
        seen[model] = want["per_doc"]
        if spec.task == "pipeline":
            models = {a["model"] for a in describe(spec).values() if a["provider"] == "openrouter"}
            assert models == {model}, f"{path.name} routes other models: {models}"
    assert {m: seen.get(m) for m in pins} == {m: 2 for m in pins}
    assert seen.get("openai/gpt-6-luna-decisions") == 1 and seen.get("typesafe/jev-1.14") == 1


def test_right_total_with_no_langchain_rows_fails(gate, tmp_path, capsys):
    """Retry-path rows (specialists, judge passes) cannot stand in for an unrecorded LangChain path."""
    rows = [_row("qwen/qwen3.7-flash", path="retry_chat_completion") for _ in range(24)]
    code, out = _run(gate, capsys, "--ledger", _ledger(tmp_path, rows), "--config", QWEN)
    assert code == 1 and "0 langchain rows < 14 expected on that call path" in out.out


def test_rows_from_another_run_are_set_aside(gate, tmp_path, capsys):
    """A relaunch appending to the same ledger file never pools the earlier run's rows."""
    stale = [{**r, "run_id": "an-earlier-launch"} for r in _pipeline_rows()]
    unstamped = [{k: v for k, v in r.items() if k != "run_id"} for r in _pipeline_rows()]
    code, out = _run(gate, capsys, "--ledger", _ledger(tmp_path, stale + unstamped), "--config", QWEN)
    assert code == 1 and "no ledger rows" in out.out
    assert "rows from other runs set aside: {'None': 20, 'an-earlier-launch': 20}" in out.out
    code, _ = _run(gate, capsys, "--ledger", _ledger(tmp_path, stale, "s.jsonl"), "--config", QWEN, "--any-run")
    assert code == 0
