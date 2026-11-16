"""SAND-032: run YAML → MODAL_VLLM_* env rendering and shell-drift detection."""

from mailroom_sandbox.job.deploy_env import env_drift, render_exports, spec_env
from mailroom_sandbox.job.spec import RunSpec


def _spec(**vllm):
    base = {"max_model_len": 32768, "quantization": "awq_marlin", "enforce_eager": False,
            "kv_cache_dtype": "fp8", "enable_thinking": False,
            "cudagraph_capture_sizes": [1, 2, 4, 8, 16], "max_num_seqs": 16}
    base.update(vllm)
    return RunSpec.model_validate({
        "schema": "sandbox.run/v1", "run_id": "sand032-test", "task": "correspondence_specialist",
        "profile": "modal-vllm",
        "job": {"concurrency": 8},
        "engine": {"kind": "modal-vllm", "model": "Qwen/Qwen3-8B-AWQ", "vllm": base,
                   "modal": {"gpu": "L4", "max_containers": 2, "min_containers": 2,
                             "scaledown_seconds": 120}},
    })


def test_spec_env_renders_every_knob():
    env = spec_env(_spec())
    assert env["MODAL_VLLM_MODEL"] == "Qwen/Qwen3-8B-AWQ"
    assert env["MODAL_VLLM_QUANTIZATION"] == "awq_marlin"
    assert env["MODAL_VLLM_KV_CACHE_DTYPE"] == "fp8"
    assert env["MODAL_VLLM_DEFAULT_CHAT_TEMPLATE_KWARGS"] == '{"enable_thinking": false}'
    assert env["MODAL_VLLM_CUDAGRAPH_CAPTURE_SIZES"] == "1,2,4,8,16"
    assert env["MODAL_VLLM_ENFORCE_EAGER"] == "0"
    assert env["MODAL_VLLM_MAX_NUM_SEQS"] == "16"
    assert env["MODAL_VLLM_GPU_MEMORY_UTILIZATION"] == "0.90"
    assert env["MODAL_VLLM_MAX_CONTAINERS"] == "2"
    assert env["MODAL_VLLM_MIN_CONTAINERS"] == "2"
    assert env["MODAL_VLLM_SCALEDOWN_SECONDS"] == "120"


def test_thinking_none_renders_empty_kwargs():
    env = spec_env(_spec(enable_thinking=None))
    assert env["MODAL_VLLM_DEFAULT_CHAT_TEMPLATE_KWARGS"] == ""


def test_env_drift_names_every_mismatch():
    spec = _spec()
    environ = dict(spec_env(spec))
    environ["MODAL_VLLM_KV_CACHE_DTYPE"] = ""          # stale shell: fp8 missing
    environ["MODAL_VLLM_MAX_NUM_SEQS"] = "6"           # stale shell: old value
    drift = env_drift(spec, environ)
    assert any("MODAL_VLLM_KV_CACHE_DTYPE" in d for d in drift)
    assert any("MODAL_VLLM_MAX_NUM_SEQS" in d and "'6'" in d and "'16'" in d for d in drift)
    assert len(drift) == 2


def test_env_drift_treats_unset_as_empty():
    spec = _spec(kv_cache_dtype="", enable_thinking=None, cudagraph_capture_sizes=[],
                 enforce_eager=True)
    environ = {k: v for k, v in spec_env(spec).items() if v != ""}
    assert env_drift(spec, environ) == []


def test_render_exports_is_sourceable_and_secret_free():
    text = render_exports(_spec())
    assert "export MODAL_VLLM_KV_CACHE_DTYPE=fp8" in text
    assert "HF_TOKEN" not in text and "API_TOKEN" not in text


def test_cli_deploy_env_prints_exports(capsys):
    from mailroom_sandbox.cli import main
    from mailroom_sandbox.paths import config_dir

    rc = main(["run", "deploy-env", "--config",
               str(config_dir() / "runs" / "legacy" / "run-50-correspondence-specialist-awq.yaml")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "export MODAL_VLLM_MODEL=Qwen/Qwen3-8B-AWQ" in out
    assert "export MODAL_VLLM_MAX_CONTAINERS=2" in out


def test_named_image_reaches_the_deploy_and_stale_shells_show_as_drift():
    spec = _spec()
    assert spec_env(spec)["MODAL_VLLM_USE_NAMED_IMAGE"] == ""
    assert any("USE_NAMED_IMAGE" in line for line in env_drift(spec, {**spec_env(spec), "MODAL_VLLM_USE_NAMED_IMAGE": "1"}))
    named = spec.model_copy(deep=True)
    named.engine.modal.named_image = True
    assert spec_env(named)["MODAL_VLLM_USE_NAMED_IMAGE"] == "1"


def test_an_experiment_deploy_sees_the_named_image_switch():
    import os

    from mailroom_sandbox.experiments import _environment

    spec = _spec()
    spec.engine.modal.named_image = True
    with _environment(spec):
        assert os.environ["MODAL_VLLM_USE_NAMED_IMAGE"] == "1"


def test_spec_env_covers_every_key_the_deploy_reads():
    """Review #1: any MODAL_VLLM_* key the deploy reads but spec_env omits is a
    knob a stale shell can change without benchmark-check noticing."""
    import re

    from mailroom_sandbox.paths import repo_root

    src = (repo_root() / "deploy" / "modal_vllm.py").read_text()
    read_keys = set(re.findall(r'os\.environ\.get\(\s*"(MODAL_VLLM_[A-Z_]+)"', src))
    rendered = set(spec_env(_spec()))
    secret = {"MODAL_VLLM_API_TOKEN"}
    assert read_keys - secret - rendered == set()


def test_drift_catches_stale_reasoning_parser_from_granite_runbook():
    spec = _spec()
    environ = dict(spec_env(spec))
    environ["MODAL_VLLM_REASONING_PARSER"] = "granite"
    environ["MODAL_VLLM_ATTENTION_BACKEND"] = "flashinfer"
    drift = env_drift(spec, environ)
    assert any("MODAL_VLLM_REASONING_PARSER" in d for d in drift)
    assert any("MODAL_VLLM_ATTENTION_BACKEND" in d for d in drift)


def test_render_exports_resets_unset_knobs():
    text = render_exports(_spec())
    # empty = deploy default → UNSET (an exported "" would crash int() parsing in
    # modal_vllm.py, e.g. STARTUP_TIMEOUT_SECONDS)
    assert "unset MODAL_VLLM_REASONING_PARSER" in text
    assert "unset MODAL_VLLM_TP_SIZE" in text
    assert "unset MODAL_VLLM_STARTUP_TIMEOUT_SECONDS" in text
    assert 'MODAL_VLLM_REASONING_PARSER=""' not in text


def test_spec_env_renders_dedicated_app_name():
    spec = _spec()
    spec.engine.modal.app = "sandbox-vllm-sand032"
    assert spec_env(spec)["MODAL_VLLM_APP_NAME"] == "sandbox-vllm-sand032"


def test_lock_uses_openrouter_names_every_openrouter_caller():
    from mailroom_sandbox.job.deploy_env import lock_uses_openrouter

    assert lock_uses_openrouter({"engine": {"kind": "openrouter"}})
    assert lock_uses_openrouter({"profile": "openrouter", "engine": {"kind": "vllm-modal"}})
    assert lock_uses_openrouter({"engine": {"kind": "vllm-modal"},
                                 "agent_routes": {"judge": {"provider": "openrouter", "model": "m"}}})
    assert lock_uses_openrouter({"engine": {"kind": "vllm-modal"}, "reviewer": {"backend": "decisions"}})
    assert lock_uses_openrouter({"engine": {"kind": "vllm-modal"}, "extraction_gate": {"model": "m"}})
    assert not lock_uses_openrouter({"engine": {"kind": "vllm-modal"}, "reviewer": {"backend": "jev"}})
    assert not lock_uses_openrouter({"engine": {"kind": "openrouter"}, "job": {"mock": True}})


def test_scope_openrouter_key_drops_it_for_runs_that_never_call_openrouter(monkeypatch):
    from mailroom_sandbox.job import deploy_env
    from mailroom_sandbox.job.deploy_env import scope_openrouter_key

    monkeypatch.setattr(deploy_env, "_SECRET_OPENROUTER_KEY", {})

    env = {"OPENROUTER_API_KEY": "k", "OTHER": "x"}
    assert scope_openrouter_key({"engine": {"kind": "vllm-modal"}}, env) is False
    assert env == {"OTHER": "x"}
    env = {"OPENROUTER_API_KEY": "k"}
    assert scope_openrouter_key({"engine": {"kind": "openrouter"}}, env) is True and env["OPENROUTER_API_KEY"] == "k"
    monkeypatch.setattr(deploy_env, "_SECRET_OPENROUTER_KEY", {})
    assert scope_openrouter_key({"engine": {"kind": "openrouter"}}, {}) is False


def test_a_warm_worker_restores_the_key_for_an_openrouter_run_after_a_run_without_it(monkeypatch):
    """Modal reuses one process for many inputs; dropping the key once must not lose it."""
    from mailroom_sandbox.job import deploy_env
    from mailroom_sandbox.job.deploy_env import scope_openrouter_key

    monkeypatch.setattr(deploy_env, "_SECRET_OPENROUTER_KEY", {})
    env = {"OPENROUTER_API_KEY": "k"}
    assert scope_openrouter_key({"engine": {"kind": "vllm-modal"}}, env) is False
    assert "OPENROUTER_API_KEY" not in env
    assert scope_openrouter_key({"engine": {"kind": "openrouter"}}, env) is True
    assert env["OPENROUTER_API_KEY"] == "k"
    assert scope_openrouter_key({"engine": {"kind": "vllm-modal"}}, env) is False
    assert "OPENROUTER_API_KEY" not in env


def test_modal_job_ships_the_openrouter_key_only_through_the_deploy_secret():
    """The key is a deploy-Secret key (read from the deploying shell), never an image env value."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "deploy" / "modal_job.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    keys = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_DEPLOY_ENV_KEYS" for t in n.targets))
    image_env = [ast.literal_eval(k) for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "env"
                 for arg in n.args if isinstance(arg, ast.Dict) for k in arg.keys]
    assert "OPENROUTER_API_KEY" in keys
    assert image_env and "OPENROUTER_API_KEY" not in image_env
    assert "scope_openrouter_key(lock, os.environ)" in source
