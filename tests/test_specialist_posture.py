"""DMR-078 specialist posture — Qwen L4 context fit + per-doc-type guards."""

from __future__ import annotations

from pathlib import Path

from mailroom_sandbox.job.benchmark_check import (
    SPECIALIST_LOCAL_PROMPTS,
    check_benchmark_posture,
)
from mailroom_sandbox.job.spec import load_run_spec
from mailroom_sandbox.job.specialist_posture import (
    GRID_RUNS,
    SPECIALIST_LIMIT_BY_RUN,
    SPECIALIST_POSTURE,
    agent_knobs_for_run,
    context_fit_ok,
    expected_concurrency,
    expected_limit,
    validate_mapping,
)


def _stub_modal(monkeypatch):
    monkeypatch.setattr(
        "mailroom_sandbox.job.benchmark_check.active_modal_profile_name",
        lambda: "hermes-agent-jjb",
    )
    monkeypatch.setattr(
        "mailroom_sandbox.job.benchmark_check._modal_cli_ok",
        lambda: {"ok": True, "version": "modal stub"},
    )


def test_grid_decode_budget_above_4096_length_cap():
    """grid-20-merger 1×L4 hit LengthFinishReasonError at exactly 4096 tokens."""
    for run_id in GRID_RUNS:
        row = SPECIALIST_POSTURE[run_id]
        assert int(row["max_tokens"]) > 4096, run_id
        knobs = agent_knobs_for_run(run_id)
        assert knobs is not None
        agent = row["agent"]
        assert knobs[agent]["max_tokens"] == row["max_tokens"]


def test_merger_1l4_retry_decode_16384():
    run_id = "grid-20-merger-specialist-awq-1l4-retry"
    row = SPECIALIST_POSTURE[run_id]
    assert row["max_tokens"] == 16384
    assert row["concurrency"] == 8
    assert row["replicas"] == 1
    assert context_fit_ok(row["max_tokens"], row["max_input_chars"], 32768)
    spec = load_run_spec(
        Path(__file__).resolve().parents[1] / "config" / "runs" / f"{run_id}.yaml"
    )
    assert spec.run_id == run_id
    assert spec.engine.vllm.enable_thinking is False
    assert spec.engine.vllm.max_inputs == 8
    assert spec.job.max_retries == 1
    assert spec.job.concurrency == 8
    assert spec.engine.modal.max_containers == 1


def test_posture_context_fit_and_invariants():
    from mailroom_sandbox.job.specialist_posture import GRID_RUNS, SAND032_RUNS, SAND032_SORTER_RUNS

    assert validate_mapping() == []
    for run_id, row in SPECIALIST_POSTURE.items():
        window = int(row.get("max_model_len", 16384))
        assert context_fit_ok(row["max_tokens"], row["max_input_chars"], window), run_id
        if "-probe" in run_id:
            # Single-doc probes are serial by design (benchmark_check exempts
            # them from the c>=2 floor).
            assert row["concurrency"] == 1, run_id
        elif run_id in SAND032_RUNS or run_id in SAND032_SORTER_RUNS or run_id in GRID_RUNS:
            # SAND-032 / grid rows scale the band per replica / max_num_seqs (up to
            # c=32 on 2×L4); validate_mapping above enforces that ceiling.
            continue
        else:
            assert 2 <= row["concurrency"] <= 8, run_id


def test_run_20_contracts_single_class_posture():
    """SAND-018: the 20-contract single-class variant is a first-class posture."""
    row = SPECIALIST_POSTURE["run-20-contracts-specialist"]
    assert row["task"] == "contracts_specialist"
    assert row["doc_class"] == "contract"
    assert row["prompt_file"] == "contracts_specialist_v33_simplified"
    assert expected_limit("run-20-contracts-specialist") == 20
    # No posture row may rely on the silent default limit (coverage honesty).
    assert set(SPECIALIST_POSTURE) <= set(SPECIALIST_LIMIT_BY_RUN)
    assert expected_limit("run-30-contracts-specialist") == 30


def test_run_20_yaml_full_corpus_logged_sample():
    root = Path(__file__).resolve().parents[1] / "config" / "runs"
    spec = load_run_spec(root / "run-20-contracts-specialist.yaml")
    assert spec.dataset.split == "all"
    assert spec.dataset.limit == 20
    assert spec.dataset.sample_seed == 42
    assert spec.dataset.strata["buckets"] == [{"doc_class": "contract", "count": 20}]
    assert spec.effective_revision() == "ed7576b676343e0b402ec5412cded301e629bdee"
    assert spec.job.cost_cap_usd == 0.55
    assert spec.job.max_wall_seconds == 3200
    agents = spec.prompt.get("agents") or {}
    assert agents["contracts_specialist"]["file"] == "contracts_specialist_v33_simplified"


def test_run_20_contracts_awq_c8_posture():
    """SAND-019: the corrected 8-concurrency AWQ contracts variant."""
    row = SPECIALIST_POSTURE["run-20-contracts-awq-c8"]
    assert row["task"] == "contracts_specialist"
    assert row["concurrency"] == 8
    assert row["max_model_len"] == 32768
    assert row["max_tokens"] == 8192          # > 4096, clears the length error
    assert row["prompt_file"] == "contracts_specialist_v33_simplified"
    assert expected_limit("run-20-contracts-awq-c8") == 20
    assert context_fit_ok(row["max_tokens"], row["max_input_chars"], 32768)


def test_run_20_correspondence_c8_posture():
    """SAND-019: the 8-concurrency correspondence variant is first-class."""
    row = SPECIALIST_POSTURE["run-20-correspondence-awq-c8"]
    assert row["task"] == "correspondence_specialist"
    assert row["concurrency"] == 8
    assert row["prompt_file"] == "correspondence_specialist_simplified"
    assert expected_limit("run-20-correspondence-awq-c8") == 20


def test_run_20_insurance_awq_posture():
    """20-doc AWQ insurance at concurrency 8 (legacy AWQ completion posture)."""
    row = SPECIALIST_POSTURE["run-20-insurance-claims-specialist-awq"]
    assert row["task"] == "insurance_claims_specialist"
    assert row["concurrency"] == 8
    assert row["max_model_len"] == 32768
    assert row["prompt_file"] == "insurance_claims_specialist_simplified"
    assert expected_limit("run-20-insurance-claims-specialist-awq") == 20
    assert context_fit_ok(row["max_tokens"], row["max_input_chars"], 32768)
    root = Path(__file__).resolve().parents[1] / "config" / "runs"
    spec = load_run_spec(root / "run-20-insurance-claims-specialist-awq.yaml")
    assert spec.dataset.limit == 20
    assert spec.job.concurrency == 8
    assert spec.engine.model == "Qwen/Qwen3-8B-AWQ"
    assert spec.engine.vllm.quantization == "awq"
    assert spec.engine.vllm.max_model_len == 32768
    buckets = (spec.dataset.strata or {}).get("buckets") or []
    assert buckets and buckets[0].get("doc_class") == "insurance_claim"
    sub = buckets[0].get("sub_buckets") or []
    assert sum(int(b["count"]) for b in sub) == 20


def test_run_20_correspondence_specialist_awq_posture():
    """Run A: 20-doc AWQ correspondence at concurrency 8 on 2×L4."""
    row = SPECIALIST_POSTURE["run-20-correspondence-specialist-awq"]
    assert row["task"] == "correspondence_specialist"
    assert row["concurrency"] == 8
    assert row["max_model_len"] == 32768
    assert row["prompt_file"] == "correspondence_specialist_production"
    assert expected_limit("run-20-correspondence-specialist-awq") == 20
    assert context_fit_ok(row["max_tokens"], row["max_input_chars"], 32768)
    root = Path(__file__).resolve().parents[1] / "config" / "runs"
    spec = load_run_spec(root / "run-20-correspondence-specialist-awq.yaml")
    assert spec.dataset.limit == 20
    assert spec.job.concurrency == 8
    assert spec.engine.model == "Qwen/Qwen3-8B-AWQ"
    assert spec.engine.vllm.quantization == "awq"
    assert spec.engine.vllm.max_model_len == 32768
    assert spec.engine.modal.max_containers == 2
    assert spec.engine.modal.min_containers == 2
    buckets = (spec.dataset.strata or {}).get("buckets") or []
    assert buckets and buckets[0].get("doc_class") == "correspondence"
    sub = buckets[0].get("sub_buckets") or []
    assert sum(int(b["count"]) for b in sub) == 20
    agents = spec.prompt.get("agents") or {}
    assert agents["correspondence_specialist"]["file"] == "correspondence_specialist_production"


def test_run_50_correspondence_specialist_awq_posture():
    """Run B: 50-doc AWQ correspondence at concurrency 8 on 2×L4."""
    row = SPECIALIST_POSTURE["run-50-correspondence-specialist-awq"]
    assert row["task"] == "correspondence_specialist"
    assert row["concurrency"] == 8
    assert row["max_model_len"] == 32768
    assert row["prompt_file"] == "correspondence_specialist_production"
    assert expected_limit("run-50-correspondence-specialist-awq") == 50
    assert context_fit_ok(row["max_tokens"], row["max_input_chars"], 32768)
    root = Path(__file__).resolve().parents[1] / "config" / "runs"
    spec = load_run_spec(root / "run-50-correspondence-specialist-awq.yaml")
    assert spec.dataset.limit == 50
    assert spec.job.concurrency == 8
    assert spec.engine.model == "Qwen/Qwen3-8B-AWQ"
    assert spec.engine.vllm.quantization == "awq"
    assert spec.engine.modal.max_containers == 2
    assert spec.engine.modal.min_containers == 2
    assert float(spec.job.cost_cap_usd) == 0.80
    assert int(spec.job.max_wall_seconds) == 3600
    buckets = (spec.dataset.strata or {}).get("buckets") or []
    assert buckets and buckets[0].get("doc_class") == "correspondence"
    sub = buckets[0].get("sub_buckets") or []
    assert sum(int(b["count"]) for b in sub) == 50


def test_run_20_correspondence_fp16_c8_posture():
    """issue #21: FP16 twin is first-class posture, not an ad-hoc YAML."""
    row = SPECIALIST_POSTURE["run-20-correspondence-fp16-c8"]
    assert row["task"] == "correspondence_specialist"
    assert row["concurrency"] == 8
    # Isolation vs the already-scored AWQ c8 run (production prompt). SAND-026
    # retargeted the AWQ YAML to `*_simplified`; do not silently retarget this
    # twin — that is an experiment-design choice (see PR notes).
    assert row["prompt_file"] == "correspondence_specialist_production"
    assert expected_limit("run-20-correspondence-fp16-c8") == 20
    spec = load_run_spec(
        Path(__file__).resolve().parents[1]
        / "config"
        / "runs"
        / "run-20-correspondence-fp16-c8.yaml"
    )
    assert spec.engine.model == "Qwen/Qwen3-8B"
    assert spec.engine.vllm.quantization in ("", None)
    assert spec.engine.vllm.max_model_len == 16384
    assert spec.dataset.sample_seed == 42
    assert spec.dataset.limit == 20
    assert spec.job.concurrency == 8


def test_run_20_gate_enforces_limit_20(monkeypatch):
    """The loud gate must cover run-20 too — a wrong limit cannot pass green."""
    _stub_modal(monkeypatch)
    root = Path(__file__).resolve().parents[1] / "config" / "runs"
    spec = load_run_spec(root / "run-20-contracts-specialist.yaml")
    report = check_benchmark_posture(spec=spec, require_hermes=True)
    assert report["ok"], report["errors"]
    assert report["checks"]["spec"]["limit"] == 20
    assert report["checks"]["spec"]["local_prompts"] == {
        "contracts_specialist": "contracts_specialist_v33_simplified"
    }
    bad = spec.model_copy(
        update={"dataset": spec.dataset.model_copy(update={"limit": 30})}
    )
    bad_report = check_benchmark_posture(spec=bad, require_hermes=True)
    assert bad_report["ok"] is False
    assert any("dataset.limit" in e for e in bad_report["errors"])


def test_merger_is_dedicated_specialist():
    row = SPECIALIST_POSTURE["run-30-merger-specialist"]
    assert row["task"] == "merger_agreement_specialist"
    assert row["agent"] == "merger_agreement_specialist"
    assert SPECIALIST_LOCAL_PROMPTS["run-30-merger-specialist"] == {
        "merger_agreement_specialist": "merger_agreement_specialist_simplified"
    }


def test_run_yamls_match_posture(monkeypatch):
    monkeypatch.setattr(
        "mailroom_sandbox.job.benchmark_check.active_modal_profile_name",
        lambda: "hermes-agent-jjb",
    )
    monkeypatch.setattr(
        "mailroom_sandbox.job.benchmark_check._modal_cli_ok",
        lambda: {"ok": True, "version": "modal stub"},
    )
    root = Path(__file__).resolve().parents[1] / "config" / "runs"
    from mailroom_sandbox.job.specialist_posture import (
        GRID_CELLS,
        GRID_RUNS,
        SAND032_RUNS,
        SAND032_SORTER_RUNS,
    )

    for run_id, row in SPECIALIST_POSTURE.items():
        if run_id in SAND032_RUNS or run_id in SAND032_SORTER_RUNS:
            continue  # own gate + env-drift coverage in tests/test_sand032_configs.py
        if run_id in GRID_CELLS:
            continue  # SAND-037 aligned grid: test_grid_cells_share_one_engine_prompt_and_decode
        if run_id in GRID_RUNS and int(row.get("replicas", 1)) == 2:
            # 2×L4 grid cells pin awq + seqs16 + graphs; not the 1×L4 awq/eager pair.
            spec = load_run_spec(root / f"{run_id}.yaml")
            assert spec.task == row["task"]
            assert spec.job.concurrency == expected_concurrency(run_id)
            assert spec.engine.model == "Qwen/Qwen3-8B-AWQ"
            assert spec.engine.vllm.max_num_seqs == 16
            assert spec.engine.modal.max_containers == 2
            continue
        spec = load_run_spec(root / f"{run_id}.yaml")
        assert spec.task == row["task"]
        assert spec.job.concurrency == expected_concurrency(run_id)
        assert float(spec.job.cost_cap_usd) == float(row["cost_cap_usd"])
        assert int(spec.job.max_wall_seconds) == int(row["max_wall_seconds"])
        # SAND-018/019: AWQ variants (incl. the -awq-c8 suffix) run the quantized
        # checkpoint; SAND-027 Granite twins (incl. probes) run the Granite FP8
        # checkpoint; every other specialist run stays on the bf16 default.
        if "-granite" in run_id:
            assert spec.engine.model == "ibm-granite/granite-4.2-8b-fp8"
        elif "-awq" in run_id:
            assert spec.engine.model == "Qwen/Qwen3-8B-AWQ"
            assert spec.engine.vllm.quantization == "awq"
        else:
            assert spec.engine.model == "Qwen/Qwen3-8B"
        report = check_benchmark_posture(spec=spec, require_hermes=True)
        assert report["ok"], (run_id, report["errors"])



def _grid_spec(run_id):
    root = Path(__file__).resolve().parents[1] / "config" / "runs"
    return load_run_spec(root / f"{run_id}.yaml")


def test_grid_has_twenty_aligned_cells():
    from mailroom_sandbox.job.specialist_posture import GRID_CELLS

    assert len(GRID_CELLS) == 20
    shapes = {(r.split("-")[1], r.split("-awq-")[1].split("-")[0]) for r in GRID_CELLS}
    assert shapes == {("20", "1l4"), ("20", "2l4"), ("50", "1l4"), ("50", "2l4")}


def test_grid_cells_share_one_engine_prompt_and_decode(monkeypatch):
    """SAND-037: only n, replica count and concurrency vary across the grid."""
    from mailroom_sandbox.job.deploy_env import spec_env
    from mailroom_sandbox.job.specialist_posture import GRID_CELLS, GRID_TEMPERATURE

    _stub_modal(monkeypatch)

    engines = set()
    for run_id in GRID_CELLS:
        spec = _grid_spec(run_id)
        row = SPECIALIST_POSTURE[run_id]
        vllm = spec.engine.vllm
        assert vllm.quantization == "awq_marlin", run_id
        assert vllm.kv_cache_dtype == "fp8", run_id
        assert vllm.enforce_eager is False, run_id
        assert vllm.enable_thinking is False, run_id
        assert vllm.max_num_seqs == 16 and vllm.max_inputs == 32, run_id
        engines.add(repr(vllm))
        replicas = int(row["replicas"])
        assert spec.engine.modal.max_containers == spec.engine.modal.min_containers == replicas
        assert spec.job.concurrency == (8 if replicas == 1 else 32), run_id
        assert spec.job.max_retries == 2, run_id
        assert spec.prompt["agents"][row["agent"]]["file"] == row["prompt_file"], run_id
        knobs = agent_knobs_for_run(run_id)[row["agent"]]
        assert knobs["max_tokens"] == 8192, run_id
        if row["doc_class"] in ("contract", "merger_agreement"):
            assert knobs["temperature"] == GRID_TEMPERATURE == 0.7, run_id
        else:
            assert "temperature" not in knobs, run_id  # call-site 0.1, as in SAND-032
        assert float(spec.job.cost_cap_usd) == float(row["cost_cap_usd"]), run_id
        assert int(spec.job.max_wall_seconds) == int(row["max_wall_seconds"]), run_id
        report = check_benchmark_posture(spec=spec, require_hermes=True, env=spec_env(spec))
        assert report["ok"], (run_id, report["errors"])
    assert len(engines) == 1


def test_grid_draws_are_split_all_and_nested():
    """Every class draws one seed-42 split=all bucket; n=20 is the n=50 spec at count 20."""
    from mailroom_sandbox.job.specialist_posture import GRID_CELLS

    by_key = {}
    for run_id in GRID_CELLS:
        spec = _grid_spec(run_id)
        ds = spec.dataset
        assert ds.split == "all" and ds.sample_seed == 42, run_id
        assert ds.revision.startswith("ed7576b6"), run_id
        n = int(run_id.split("-")[1])
        assert ds.limit == n, run_id
        cls = run_id.split("-")[2]
        by_key.setdefault(cls, {})[(n, run_id.split("-awq-")[1][:3])] = spec
    for cls, cells in by_key.items():
        assert len(cells) == 4, cls
        # same draw spec on both fleets at each n; prompts identical everywhere
        for n in (20, 50):
            assert cells[(n, "1l4")].dataset == cells[(n, "2l4")].dataset, (cls, n)
        prompts = {repr(c.prompt) for c in cells.values()}
        assert len(prompts) == 1, cls


def test_grid_legacy_cells_keep_their_historical_posture():
    for run_id in (
        "grid-20-merger-specialist-awq-1l4",
        "grid-20-merger-specialist-awq-1l4-retry",
        "grid-50-contracts-specialist-awq-2l4",
    ):
        assert "temperature" not in SPECIALIST_POSTURE[run_id], run_id
