"""Dojo v0.22 provenance + ``identity_mixed`` handling in the sandbox.

The dojo refuses to emit a serving scorecard without a provenance stamp
(``dataset_revision`` above all) and refuses a comparison leg that pools runs
of different identity. These tests run the REAL ``Emitter`` / ``LocalManifestSink``
(no monkeypatched emitter) so that enforcement is exercised, and cover a
multi-model log, the shape the old pooling code silently broke.
"""

from __future__ import annotations

import json

import pytest
from llm_dojo_scoring.scorecard_honesty import ProvenanceExportError
from llm_dojo_scoring.serving import _LEG_IDENTITY_KEYS, compare_serving

from mailroom_sandbox.datasets import load_serving_fixtures
from mailroom_sandbox.eval import experiment_log, runners, scoring
from mailroom_sandbox.job import metrics
from mailroom_sandbox.job.spec import FAMILY_HF_REVISION
from mailroom_sandbox.serving_groups import LEG_IDENTITY_FIELDS, select_pair

REV = FAMILY_HF_REVISION


def _row(kind, model, *, prompt="mailroom-default", task="sorter", fp="abc123", rev=REV, ttft=0.4, **extra):
    profile, provider = {
        "local": ("ollama", "ollama"),
        "modal": ("modal-vllm", "vllm"),
        "api": ("openrouter", "openrouter"),
    }[kind]
    rec = {
        "profile": profile,
        "provider": provider,
        "model": model,
        "prompt_version": prompt,
        "task": task,
        "dataset_fingerprint": fp,
        "ttft_seconds": ttft,
        "e2e_latency_seconds": 2.0,
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "n": 5,
        "scores": {"exact_match": 1.0, "f1_macro": 1.0, "accuracy": 1.0},
    }
    if rev:
        rec["dataset_revision"] = rev
    rec.update(extra)
    return experiment_log.new_record(**rec)


def _multi_model_log():
    """Two local models and one API model on the SAME draw."""
    return [
        _row("local", "qwen3:8b"),
        _row("local", "qwen3:8b", ttft=0.6),  # a repeat run of the same leg
        _row("local", "llama3.1:8b", ttft=0.3),
        _row("api", "qwen/qwen3.7-flash", ttft=0.2),
    ]


def test_leg_identity_fields_track_the_dojo():
    assert tuple(LEG_IDENTITY_FIELDS) == tuple(_LEG_IDENTITY_KEYS)


def test_serving_fixtures_carry_the_pinned_dataset_revision():
    fixtures = load_serving_fixtures()
    for side in ("local", "api"):
        assert fixtures[side]["dataset_revision"] == REV
    # never the fingerprint stand-in
    assert fixtures["local"]["dataset_revision"] != fixtures["local"]["dataset_fingerprint"]


def test_fixture_scorecard_emits_through_the_real_emitter(tmp_path, monkeypatch):
    monkeypatch.setattr(scoring, "reports_dir", lambda: tmp_path / "reports")
    fx = load_serving_fixtures()
    comparison = scoring.compare_local_vs_api(fx["local"], fx["api"])
    scoring.emit_local_vs_api_scorecard(comparison, run_id="sand32-fixture")
    path = tmp_path / "reports" / "scores" / "SAND-32" / "scores.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows, "the real sink must have received the serving metrics"
    ttft = [r for r in rows if r["metric"].endswith("ttft_seconds") or "ttft" in json.dumps(r)]
    assert ttft
    assert REV in path.read_text(encoding="utf-8")


def test_missing_dataset_revision_is_refused_with_a_sandbox_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(scoring, "reports_dir", lambda: tmp_path / "reports")
    fx = load_serving_fixtures()
    local, api = dict(fx["local"]), dict(fx["api"])
    local.pop("dataset_revision")
    api.pop("dataset_revision")
    comparison = scoring.compare_local_vs_api(local, api)
    with pytest.raises(ProvenanceExportError, match="dataset_revision") as err:
        scoring.emit_local_vs_api_scorecard(comparison, run_id="no_rev")
    assert "run lock" in str(err.value)
    # explicit, caller-supplied provenance is honoured (and only then)
    stamp = {"dataset_revision": REV}
    scoring.emit_local_vs_api_scorecard(
        comparison, run_id="with_rev", provenance={"local": stamp, "api": stamp}
    )


def test_dataset_revision_is_never_derived_from_the_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(scoring, "reports_dir", lambda: tmp_path / "reports")
    compared = scoring.compare_from_records(
        [_row("local", "qwen3:8b", rev=None), _row("api", "qwen/qwen3.7-flash", rev=None)]
    )
    (outcome,) = scoring.emit_group_scorecards(compared, run_id="fp_only")
    assert outcome["emitted"] is False
    assert "dataset_revision" in outcome["reason"]


def test_pooling_a_multi_model_log_is_identity_mixed_in_the_dojo():
    """Negative control: this is what the pre-grouping code handed the dojo."""
    log = [scoring.to_dojo_serving_record(r) for r in _multi_model_log()]
    pooled = compare_serving(
        [r for r in log if r["serving_kind"] == "local"],
        [r for r in log if r["serving_kind"] == "api"],
    )
    assert pooled["incomparable"] is True
    assert pooled["incomparable_reason"] == "identity_mixed"


def test_compare_from_records_groups_a_multi_model_log():
    compared = scoring.compare_from_records(_multi_model_log())
    assert len(compared["groups"]) == 2
    for entry in compared["groups"]:
        comparison = entry["comparison"]
        assert not comparison.get("incomparable")
        assert comparison["local"].get("identity_conflict") is None
        assert comparison["api"].get("identity_conflict") is None
    sizes = {g["local_identity"]["model"]: g["local_n"] for g in compared["groups"]}
    assert sizes == {"qwen3:8b": 2, "llama3.1:8b": 1}
    # several groups and no selector: no pooled headline, and the note says how to pick
    assert compared["comparison"] is None and compared["selected_group"] is None
    assert "--group" in compared["note"]
    assert "### Group 1" in compared["markdown"]


def test_group_selector_by_index_and_label():
    by_index = scoring.compare_from_records(_multi_model_log(), group=2)
    assert by_index["selected_group"] == 2
    assert by_index["comparison"] is by_index["groups"][1]["comparison"]
    by_label = scoring.compare_from_records(_multi_model_log(), group="llama3")
    assert by_label["groups"][by_label["selected_group"] - 1]["local_identity"]["model"] == "llama3.1:8b"
    with pytest.raises(ValueError, match="matches no group"):
        scoring.compare_from_records(_multi_model_log(), group="mistral")
    with pytest.raises(ValueError, match="ambiguous"):
        scoring.compare_from_records(_multi_model_log(), group="8b")
    with pytest.raises(ValueError, match="out of range"):
        select_pair([], 3)


def test_single_comparable_pair_keeps_the_flat_payload():
    compared = scoring.compare_from_records(
        [_row("local", "qwen3:8b"), _row("api", "qwen/qwen3.7-flash")]
    )
    assert len(compared["groups"]) == 1 and compared["selected_group"] == 1
    assert compared["comparison"]["markdown"].startswith("# local vs API serving scorecard")
    assert compared["table"] and compared["scorecard"]


def test_legs_that_measured_different_things_are_not_paired():
    compared = scoring.compare_from_records(
        [
            _row("local", "qwen3:8b", prompt="p-a"),
            _row("api", "qwen/qwen3.7-flash", prompt="p-b"),
        ]
    )
    assert compared["groups"] == [] and compared["comparison"] is None
    assert {u["side"] for u in compared["unpaired"]} == {"local", "api"}
    assert "nothing comparable" in compared["note"]


def test_differing_dataset_revisions_split_groups():
    other = "0" * 40
    compared = scoring.compare_from_records(
        [
            _row("local", "qwen3:8b"),
            _row("local", "qwen3:8b", rev=other),
            _row("api", "qwen/qwen3.7-flash"),
        ]
    )
    assert len(compared["groups"]) == 1
    assert compared["groups"][0]["key"]["dataset_revision"] == REV
    assert [u["identity"]["dataset_revision"] for u in compared["unpaired"]] == [other]


def test_derived_comparison_records_are_not_serving_legs():
    log = _multi_model_log() + [
        experiment_log.new_record(task="local_vs_api", profile="ollama", provider="ollama", scores={})
    ]
    compared = scoring.compare_from_records(log)
    assert compared["derived_skipped_n"] == 1
    assert compared["unpaired"] == []


def test_modal_vs_api_groups_when_no_local_leg():
    compared = scoring.compare_from_records(
        [_row("modal", "Qwen/Qwen3-8B"), _row("api", "qwen/qwen3.7-flash")]
    )
    assert compared["left_serving"] == "modal" and len(compared["groups"]) == 1


def test_emit_group_scorecards_per_group_with_the_real_emitter(tmp_path, monkeypatch):
    monkeypatch.setattr(scoring, "reports_dir", lambda: tmp_path / "reports")
    compared = scoring.compare_from_records(_multi_model_log())
    outcomes = scoring.emit_group_scorecards(compared, run_id="sand77-multi")
    assert [o["run_id"] for o in outcomes] == ["sand77-multi.g1", "sand77-multi.g2"]
    assert all(o["emitted"] for o in outcomes)
    path = tmp_path / "reports" / "scores" / "SAND-77" / "scores.jsonl"
    run_ids = {json.loads(line)["run_id"] for line in path.read_text(encoding="utf-8").splitlines()}
    assert {"sand77-multi.g1:local", "sand77-multi.g2:local"} <= run_ids


def test_emit_group_scorecards_reports_a_refused_group(tmp_path, monkeypatch):
    monkeypatch.setattr(scoring, "reports_dir", lambda: tmp_path / "reports")
    log = [
        _row("local", "qwen3:8b"),
        _row("api", "qwen/qwen3.7-flash"),
        _row("local", "llama3.1:8b", rev=None, fp="zzz"),
        _row("api", "qwen/qwen3.7-flash", rev=None, fp="zzz"),
    ]
    outcomes = scoring.emit_group_scorecards(scoring.compare_from_records(log), run_id="mixed_rev")
    assert [o["emitted"] for o in outcomes] == [True, False]
    assert "dataset_revision" in outcomes[1]["reason"]


def test_run_local_vs_api_from_a_multi_model_log(tmp_path, monkeypatch):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    log = tmp_path / "experiment_log.jsonl"
    monkeypatch.setattr(experiment_log, "jsonl_path", lambda: log)
    monkeypatch.setattr(experiment_log, "md_path", lambda: tmp_path / "experiment_log.md")
    monkeypatch.setattr(scoring, "reports_dir", lambda: tmp_path / "reports")
    for rec in _multi_model_log():
        experiment_log.append(rec)

    result = runners.run_local_vs_api_eval(from_log=True, experiment_name="sand88_multi")
    assert result["scores"]["groups_n"] == 2
    assert result["scores"]["scorecards_emitted"] == 2 and result["scores"]["scorecards_refused"] == 0
    assert result["scores"]["ttft_seconds_local"] is None  # no pooled headline
    assert "--group" in result["comparison"]["note"]

    picked = runners.run_local_vs_api_eval(from_log=True, experiment_name="sand88_pick", group="llama3")
    assert picked["scores"]["ttft_seconds_local"] == pytest.approx(0.3)
    assert picked["scores"]["ttft_seconds_api"] == pytest.approx(0.2)
    # the earlier run's own comparison record is not pooled back in
    assert picked["comparison"]["derived_skipped_n"] == 1


def test_cli_group_flag_is_wired(monkeypatch):
    from mailroom_sandbox.cli import main

    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return {"scores": {}}

    monkeypatch.setattr(runners, "run_local_vs_api_eval", fake)
    assert main(["eval", "local_vs_api", "--mock", "--from-log", "--group", "2"]) == 0
    assert seen["group"] == "2" and seen["from_log"] is True


def test_metrics_compare_groups_pairwise_instead_of_pooling():
    rows = [scoring.to_dojo_serving_record(r) for r in _multi_model_log()]
    result = metrics.compare(rows)
    assert set(result["pairwise"]) == {"local_vs_api[1]", "local_vs_api[2]"}
    for payload in result["pairwise"].values():
        assert not payload.get("incomparable")
    assert result["buckets"]["local"]["identity_mixed"] == ["model"]
    assert "identity_mixed" in result["markdown"]
    assert len(result["groups"]) == 2


def test_metrics_compare_single_pair_keeps_its_historical_key():
    rows = [scoring.to_dojo_serving_record(r) for r in (_row("local", "qwen3:8b"), _row("api", "qwen/qwen3.7-flash"))]
    result = metrics.compare(rows)
    assert set(result["pairwise"]) == {"local_vs_api"}
    assert "identity_mixed" not in result["buckets"]["local"]


def test_metrics_compare_surfaces_incomparable_legs():
    rows = [
        scoring.to_dojo_serving_record(r)
        for r in (_row("local", "qwen3:8b", prompt="a"), _row("api", "qwen/qwen3.7-flash", prompt="b"))
    ]
    result = metrics.compare(rows)
    assert result["pairwise"] == {}
    assert len(result["unpaired"]) == 2
    assert "Incomparable legs" in result["markdown"]


HUB_LOCK = {
    "dataset": {
        "split": "test",
        "revision": "v9.1",
        "revision_resolved": REV,
        "sample_seed": 42,
        "metadata": {"source": "huggingface"},
    }
}


def test_lock_dataset_provenance_uses_the_resolved_hub_sha():
    assert metrics.lock_dataset_provenance(HUB_LOCK) == {
        "dataset_revision": REV,
        "split": "test",
        "draw_seed": "42",
    }


def test_lock_dataset_provenance_never_invents_a_revision():
    assert metrics.lock_dataset_provenance(None) == {}
    local = {"dataset": {"revision": REV, "split": "test", "metadata": {"source": "local"}}}
    assert metrics.lock_dataset_provenance(local) == {}  # offline file: no Hub revision
    tag_only = {"dataset": {"revision": "v9.1", "metadata": {"source": "huggingface"}, "sample_seed": 0}}
    assert metrics.lock_dataset_provenance(tag_only) == {"draw_seed": "0"}


def test_record_from_run_stamps_dataset_provenance():
    rec = metrics.record_from_run(
        run_id="r1", spec_hash="h", task="sorter", profile="ollama", model="qwen3:8b",
        prompt_version="mailroom-default", dataset_fingerprint="abc123",
        items=[{"latency_ms": 100, "ok": True}],
        dataset_provenance=metrics.lock_dataset_provenance(HUB_LOCK),
    )
    assert rec["dataset_revision"] == REV and rec["split"] == "test" and rec["draw_seed"] == "42"
    bare = metrics.record_from_run(
        run_id="r2", spec_hash="h", task="sorter", profile="ollama", model="qwen3:8b",
        prompt_version="mailroom-default", dataset_fingerprint="abc123",
        items=[{"latency_ms": 100, "ok": True}],
    )
    assert "dataset_revision" not in bare
