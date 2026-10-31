"""The decision reviewer is frozen in the run spec (network-free)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mailroom_sandbox.job import preflight
from mailroom_sandbox.job.spec import DatasetSpec, ReviewerSpec, RunSpec, spec_core
from mailroom_sandbox.runtime import activate

# Computed with the spec implementation at 48c3f8f, before reviewer existed.
# Pin the model and use a Hub request: local /tmp resolves differently on macOS.
PRE_REVIEWER_HASH = "0b474bf41250f04433674038acc55a3e03326be20863bbf0fc0f74506837efd2"


def _reviewer(**overrides) -> dict:
    base = {"backend": "jev", "model": "jev-1.13.0", "classes": {"contract": 0.9}}
    base.update(overrides)
    return base


def _spec(**overrides) -> RunSpec:
    base = dict(
        task="sorter",
        dataset=DatasetSpec(repo="example/corpus", revision="a" * 40),
        engine={"kind": "vllm-local", "model": "Qwen/Qwen3-8B", "modal": None},
    )
    base.update(overrides)
    return RunSpec(**base)


def test_hash_unchanged_without_reviewer():
    spec = _spec()
    assert spec.reviewer is None
    assert "reviewer" not in spec_core(spec)
    assert spec.spec_hash() == PRE_REVIEWER_HASH


def test_hash_changes_with_reviewer_and_cutoff():
    plain = _spec().spec_hash()
    low = _spec(reviewer=_reviewer(classes={"contract": 0.8})).spec_hash()
    high = _spec(reviewer=_reviewer(classes={"contract": 0.9})).spec_hash()
    assert len({plain, low, high}) == 3
    assert _spec(reviewer=_reviewer()).spec_hash() == high


def test_hash_changes_with_cutoff():
    a = _spec(reviewer=_reviewer(classes={"contract": 0.8}))
    b = _spec(reviewer=_reviewer(classes={"contract": 0.85}))
    assert a.spec_hash() != b.spec_hash()


def test_core_freezes_backend_model_and_cutoffs():
    core = spec_core(_spec(reviewer=_reviewer(classes={"contract": 0.9, "insurance_claim": 0.7})))
    assert core["reviewer"] == {
        "backend": "jev",
        "model": "jev-1.13.0",
        "classes": {"contract": 0.9, "insurance_claim": 0.7},
    }


def test_rejects_correspondence_for_live_backend():
    with pytest.raises(ValidationError, match="correspondence"):
        _spec(reviewer=_reviewer(classes={"correspondence": 0.9}))


def test_mock_backend_may_use_correspondence_offline():
    spec = _spec(reviewer=_reviewer(backend="mock", model="mock", classes={"correspondence": 0.9}))
    assert spec.reviewer.classes == {"correspondence": 0.9}


@pytest.mark.parametrize("cutoff", [-0.01, 1.01, float("nan"), float("inf"), True])
def test_rejects_cutoff_outside_unit_interval(cutoff):
    with pytest.raises(ValidationError):
        _spec(reviewer=_reviewer(classes={"contract": cutoff}))


def test_accepts_unit_interval_ends():
    spec = _spec(reviewer=_reviewer(classes={"contract": 0.0, "insurance_claim": 1.0}))
    assert spec.reviewer.classes == {"contract": 0.0, "insurance_claim": 1.0}


def test_rejects_empty_classes():
    with pytest.raises(ValidationError):
        _spec(reviewer=_reviewer(classes={}))


@pytest.mark.parametrize("model", ["jev-latest", "jev-preview", "jev-1", "gpt-4o"])
def test_rejects_unpinned_jev_model(model):
    with pytest.raises(ValidationError, match="pinned|Jev"):
        _spec(reviewer=_reviewer(model=model))


def test_rejects_unknown_backend():
    with pytest.raises(ValidationError):
        _spec(reviewer=_reviewer(backend="gpt"))


def test_rejects_unknown_reviewer_field():
    with pytest.raises(ValidationError):
        _spec(reviewer=_reviewer(extra=1))


def _file_spec(tmp_path, **overrides) -> RunSpec:
    path = tmp_path / "f.jsonl"
    path.write_text(
        json.dumps({"id": "d0", "filename": "0.txt", "doc_text": "t0",
                    "expected": "contract", "expected_subclass": "service"}) + "\n",
        encoding="utf-8",
    )
    return RunSpec(
        run_id=overrides.pop("run_id", "rv-1"),
        task="sorter",
        dataset=DatasetSpec(local_path=f"file://{path}", limit=1),
        engine={"kind": "vllm-local", "modal": None},
        trace={"sink": "none"},
        **overrides,
    )


def _failed_detail(report) -> str:
    assert report["status"] == "failed", report
    return " ".join(c["detail"] for c in report["checks"] if not c["ok"])


def test_preflight_requires_typesafe_key_for_jev(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    spec = _file_spec(tmp_path, reviewer=_reviewer(), job={"mock": False})
    detail = _failed_detail(preflight.preflight(spec, offline=True))
    assert "TYPESAFE_API_KEY" in detail and "backend mock" in detail


def test_preflight_refuses_jev_in_a_mock_run(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-secret-value")
    spec = _file_spec(tmp_path, run_id="rv-jev-mock", reviewer=_reviewer(), job={"mock": True})
    detail = _failed_detail(preflight.preflight(spec, offline=True))
    assert "mock run" in detail and "backend mock" in detail
    assert "ts-secret-value" not in detail


def test_preflight_refuses_unknown_reviewer_class(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    spec = _file_spec(tmp_path, run_id="rv-typo", reviewer=_reviewer(backend="mock", model="mock", classes={"contrat": 0.9}))
    detail = _failed_detail(preflight.preflight(spec, offline=True))
    assert "contrat" in detail and "contract" in detail


def test_preflight_passes_with_key_and_never_echoes_it(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-secret-value")
    spec = _file_spec(tmp_path, run_id="rv-key", reviewer=_reviewer(), job={"mock": False})
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    assert "ts-secret-value" not in json.dumps(report)


def test_preflight_mock_backend_needs_no_key(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    spec = _file_spec(tmp_path, run_id="rv-mock", reviewer=_reviewer(backend="mock", model="mock"))
    assert preflight.preflight(spec, offline=True)["status"] == "prepared"


def test_lock_freezes_the_reviewer(tmp_path, job_data_dir, monkeypatch):
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-secret-value")
    spec = _file_spec(tmp_path, run_id="rv-lock", reviewer=_reviewer(), job={"mock": False})
    report = preflight.preflight(spec, offline=True)
    lock = RunStore(run_dir(report["run_id"])).read_lock()
    assert lock["reviewer"] == spec.reviewer.model_dump()
    assert "ts-secret-value" not in json.dumps(lock)


@pytest.fixture
def registry():
    from agents import decision_backend

    activate("ollama", load_env_file=False)  # puts the mailroom source on sys.path
    decision_backend.register_decision_backend(None)
    yield decision_backend
    decision_backend.register_decision_backend(None)
    activate("ollama", load_env_file=False)  # rewrite the reviewer block back to all-llm


def test_activate_registers_backend_and_class_modes(registry):
    reviewer = ReviewerSpec(backend="mock", model="mock", classes={"contract": 0.85})
    activate("ollama", load_env_file=False, reviewer=reviewer)

    assert registry.get_decision_backend() is not None
    from pipeline.config import get_review_mode, get_reviewer_config

    assert get_review_mode("contract") == "decision_only"
    assert get_review_mode("insurance_claim") == "llm"
    cfg = get_reviewer_config()
    assert cfg["default_mode"] == "llm"
    assert cfg["by_class"] == {"contract": {"mode": "decision_only", "cutoff": 0.85}}


def test_llm_only_spec_registers_nothing(registry):
    activate("ollama", load_env_file=False)
    assert registry.get_decision_backend() is None
    from pipeline.config import get_review_mode, get_reviewer_config

    assert get_reviewer_config()["by_class"] == {}
    assert get_review_mode("contract") == "llm"


def test_llm_only_activate_after_reviewer_run_clears_everything(registry):
    reviewer = ReviewerSpec(backend="mock", model="mock", classes={"contract": 0.85})
    activate("ollama", load_env_file=False, reviewer=reviewer)
    assert registry.get_decision_backend() is not None

    activate("ollama", load_env_file=False)

    assert registry.get_decision_backend() is None
    from pipeline.config import get_review_mode

    assert get_review_mode("contract") == "llm"


def test_locked_runtime_activates_the_frozen_reviewer(registry):
    from mailroom_sandbox.runtime import locked_runtime

    lock = {"profile": "ollama", "reviewer": _reviewer(backend="mock", model="mock", classes={"contract": 0.7})}
    with locked_runtime(lock, {}):
        activate(
            "ollama", load_env_file=False,
            reviewer=ReviewerSpec(backend="mock", model="mock", classes={"insurance_claim": 0.5}),
        )
    from pipeline.config import get_review_mode

    assert registry.get_decision_backend() is not None
    assert get_review_mode("contract") == "decision_only"
    assert get_review_mode("insurance_claim") == "llm"  # the argument is ignored under a lock


def test_activate_does_not_log_the_api_key(registry, monkeypatch, caplog):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-secret-value")
    with caplog.at_level("DEBUG"):
        activate(
            "ollama", load_env_file=False,
            reviewer=ReviewerSpec(backend="jev", model="jev-1.13.0", classes={"contract": 0.9}),
        )
    assert "ts-secret-value" not in caplog.text


@pytest.fixture
def create_experiment(tmp_path):
    from mailroom_sandbox import cli

    source = tmp_path / "docs.jsonl"
    source.write_text("".join(
        json.dumps({"id": f"c{i}", "doc_text": "Email from Jane to John.", "expected_doc_class": "contract",
                    "expected_subclass": "nda", "expected_stage": "archived",
                    "expected_fields": {"cuad_clause_labels": ["nda"]}}) + "\n"
        for i in range(3)
    ))

    def create(*options):
        root = tmp_path / ("exp-" + str(len(list(tmp_path.glob("exp-*")))))
        args = ["experiment", "create", root.name, "--doc-class", "contract", "--samples", "3",
                "--local-dataset", str(source), "--trace-sink", "none", "--mock", "--output", str(root), *options]
        return cli.main(args), root

    return create


def test_experiment_create_freezes_the_reviewer(create_experiment):
    from mailroom_sandbox.job.spec import load_run_spec

    code, root = create_experiment(
        "--decision-reviewer", "jev:jev-1.13.0",
        "--decision-class", "contract=0.9", "--decision-class", "insurance_claim=0.75",
    )
    assert code == 0
    spec = load_run_spec(next((root / "runs").glob("*.yaml")))
    assert spec.reviewer.model_dump() == {
        "backend": "jev", "model": "jev-1.13.0", "classes": {"contract": 0.9, "insurance_claim": 0.75},
    }


def test_experiment_create_without_flags_has_no_reviewer(create_experiment):
    from mailroom_sandbox.job.spec import load_run_spec

    code, root = create_experiment()
    assert code == 0
    assert load_run_spec(next((root / "runs").glob("*.yaml"))).reviewer is None


@pytest.mark.parametrize("options", [
    ["--decision-reviewer", "jev:jev-1.13.0"],
    ["--decision-class", "contract=0.9"],
    ["--decision-reviewer", "jev-1.13.0", "--decision-class", "contract=0.9"],
    ["--decision-reviewer", "jev:jev-latest", "--decision-class", "contract=0.9"],
    ["--decision-reviewer", "jev:jev-1.13.0", "--decision-class", "contract"],
    ["--decision-reviewer", "jev:jev-1.13.0", "--decision-class", "contract=high"],
    ["--decision-reviewer", "jev:jev-1.13.0", "--decision-class", "contract=1.5"],
    ["--decision-reviewer", "jev:jev-1.13.0", "--decision-class", "correspondence=0.9"],
    ["--decision-reviewer", "jev:jev-1.13.0", "--decision-class", "contrat=0.9"],
    ["--decision-reviewer", "mock:mock", "--decision-class", "contract=0.9", "--decision-class", "contract=0.8"],
])
def test_experiment_create_refuses_bad_reviewer_flags(create_experiment, options, tmp_path):
    code, _ = create_experiment(*options)
    assert code == 1
    assert not list(tmp_path.glob("exp-*/experiment.yaml"))


def test_experiment_create_names_bad_key_and_valid_classes(create_experiment, capsys):
    code, _ = create_experiment("--decision-reviewer", "mock:mock", "--decision-class", "contrat=0.9")
    err = capsys.readouterr().err
    assert code == 1 and "contrat" in err and "contract" in err and "insurance_claim" in err


@pytest.mark.parametrize("key", [None, "local-secret"])
@pytest.mark.parametrize("mock", [False, True])
def test_jev_modal_job_rejected_before_key_check(monkeypatch, key, mock):
    if key is None:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TYPESAFE_API_KEY", key)
    spec = _spec(reviewer=_reviewer(), job={"mode": "modal", "mock": mock})
    errors = preflight._engine_errors(spec)
    assert len(errors) == 1
    assert ("mock run" if mock else "modal jobs") in errors[0]
    assert "TYPESAFE_API_KEY" not in errors[0]
