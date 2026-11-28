"""Phase 5 part 2: the confirming arms, the preflight merger_reads block and the resume refusal.

Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 8); design part 8.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from mailroom_sandbox import merger_reads
from mailroom_sandbox.job import preflight
from mailroom_sandbox.job.spec import load_run_spec as load_spec

RUNS = Path("config/runs")
SPLIT = Path("config/splits/runbook-v2")


def _flat(value, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, inner in value.items():
            out.update(_flat(inner, f"{prefix}{key}."))
        return out
    return {prefix[:-1]: value}


def spec_diff(a: str, b: str) -> set[str]:
    """Dotted keys whose value differs between two run configs (a key in one only counts)."""
    fa, fb = (_flat(yaml.safe_load(Path(p).read_text())) for p in (a, b))
    keys = set(fa) | set(fb)
    # A whole sub-block present on one side only is reported once, at its top key.
    collapsed = {k for k in keys if fa.get(k, object()) != fb.get(k, object())}
    return {k if not any(k.startswith(p + ".") for p in ("job.merger",)) else "job.merger" for k in collapsed}


def _ids(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")}


def test_the_merger_arm_differs_from_the_baseline_only_in_its_switches_and_the_merger_judge():
    diff = spec_diff(RUNS / "p4-s1-verify-gov-off.yaml", RUNS / "p5-s2-merger-reads.yaml")
    assert diff == {"run_id", "job.merger", "job.long_document_head",
                    "confidence.by_class.merger_agreement.judge_max_passes",
                    "confidence.by_class.merger_agreement.arbiter_retry_max", "trace.tags"}
    spec = load_spec(RUNS / "p5-s2-merger-reads.yaml")
    assert spec.job.merger.model_dump() == {"subclass_fields": True, "question_groups": True, "gap_retry": True,
                                            "groups": 3}
    assert spec.job.long_document_head is True and spec.job.api_cost_cap_usd == 9.0
    assert spec.confidence["by_class"]["merger_agreement"] == {"judge_max_passes": 0, "arbiter_retry_max": 0}


def test_the_sorter_arms_differ_only_in_the_head_switch():
    assert spec_diff(RUNS / "p5-s2-head-sorter-off.yaml", RUNS / "p5-s2-head-sorter-on.yaml") == {
        "run_id", "job.long_document_head", "trace.tags"}
    off, on = (load_spec(RUNS / f"p5-s2-head-sorter-{s}.yaml") for s in ("off", "on"))
    assert off.job.long_document_head is False and on.job.long_document_head is True
    assert on.task == "isolated"        # the sorter alone: one read per document, no graph extraction
    assert on.job.api_cost_cap_usd and on.job.max_wall_seconds


def test_the_sorter_arms_draw_only_documents_over_the_threshold_from_dev():
    manifest = json.loads((SPLIT / "dev-long.json").read_text())
    long_ids, dev = _ids(SPLIT / "dev-long.ids"), _ids(SPLIT / "dev.ids")
    universe = dev | _ids(SPLIT / "dev.exclude.ids")
    assert long_ids and long_ids <= dev
    assert _ids(SPLIT / "dev-long.exclude.ids") == universe - long_ids
    assert manifest["threshold"] == merger_reads.HEAD_THRESHOLD
    assert set(manifest["chars"]) == long_ids and min(manifest["chars"].values()) > merger_reads.HEAD_THRESHOLD
    for side in ("off", "on"):
        ds = yaml.safe_load((RUNS / f"p5-s2-head-sorter-{side}.yaml").read_text())["dataset"]
        assert ds["exclude_ids_file"] == str(SPLIT / "dev-long.exclude.ids")
        assert ds["limit"] == len(long_ids) and ds["revision"] == manifest["revision"]
        # Neither arm refuses a document (HF-010) the other reads: both finish the same documents.
        knobs = yaml.safe_load((RUNS / f"p5-s2-head-sorter-{side}.yaml").read_text())["agent_knobs"]
        assert knobs["sorter"]["max_input_chars"] > max(manifest["chars"].values())


def _rows() -> list[dict]:
    from _merger_fixture import FIXTURE

    long_merger = FIXTURE + "\n" + "Filler clause of the agreement.\n" * 12_000
    assert len(long_merger) > merger_reads.HEAD_THRESHOLD
    return [{"id": "m1", "expected_doc_class": "merger_agreement", "doc_text": long_merger},
            {"id": "c1", "expected_doc_class": "contract", "doc_text": "short contract"}]


def test_preflight_reports_the_merger_reads_block_and_estimate():
    arm = preflight.merger_reads_block(load_spec(RUNS / "p5-s2-merger-reads.yaml"), _rows())
    base = preflight.merger_reads_block(load_spec(RUNS / "p4-s1-verify-gov-off.yaml"), _rows())
    assert arm["switches"] == {"subclass_fields": True, "question_groups": True, "gap_retry": True, "groups": 3,
                               "long_document_head": True}
    assert arm["merger_judge"]["judge_max_passes"] == 0 and arm["merger_judge"]["arbiter_retry_max"] == 0
    assert arm["merger_judge"]["judge_rule"] is True
    assert arm["estimate"]["mergers"] == 1 and base["estimate"]["mergers"] == 1
    per = arm["estimate"]["per_merger"]
    assert set(per) >= {"sorter", "intake", "extract", "groups", "gap_retry", "total"}
    assert per["sorter"] < 1 and per["intake"] < 1 and per["extract"] == 1 and 0 < per["groups"] < 1
    assert per["total"] == pytest.approx(per["sorter"] + per["intake"] + 1 + per["groups"] + per["gap_retry"], abs=1e-3)
    assert base["estimate"]["per_merger"]["total"] == 3 and base["switches"]["question_groups"] is False
    assert per["total"] < base["estimate"]["per_merger"]["total"]


def test_preflight_refuses_a_merger_judge_at_zero_without_question_groups():
    spec = load_spec(RUNS / "p5-s2-merger-reads.yaml")
    spec.job.merger.question_groups = False
    spec.job.merger.gap_retry = False
    block = preflight.merger_reads_block(spec, _rows())
    assert block["errors"] and "question_groups" in block["errors"][0]
    assert preflight.merger_reads_block(load_spec(RUNS / "p5-s2-merger-reads.yaml"), _rows())["errors"] == []


def test_a_run_with_no_merger_and_no_switch_gets_no_block():
    spec = load_spec(RUNS / "p5-s2-head-sorter-off.yaml")
    assert preflight.merger_reads_block(spec, [{"id": "c1", "expected_doc_class": "contract", "doc_text": "x"}]) is None


def test_a_resume_after_this_change_names_the_new_hotfixes():
    from mailroom_sandbox import vendor_hotfixes
    from mailroom_sandbox.job.preflight import _hotfix_change, _hotfix_drift_detail

    now = vendor_hotfixes.describe()
    new = ("HF-030", "HF-032", "HF-033")
    older = {**now, "fixes": [f for f in now["fixes"] if f["id"] not in new]}
    assert _hotfix_change(older, now) == "added HF-030, HF-032, HF-033"
    detail = _hotfix_drift_detail({"vendor_hotfixes": older}, None)
    assert "added HF-030, HF-032, HF-033" in detail and "--force" in detail
    assert "HF-031" not in {f["id"] for f in now["fixes"]}       # released unused, never reassigned


def test_a_refused_merger_judge_stops_preflight_before_the_lock():
    spec = load_spec(RUNS / "p5-s2-merger-reads.yaml")
    spec.job.merger.question_groups = False
    spec.job.merger.gap_retry = False

    class Store:
        def dataset_rows(self):
            return _rows()

    report: dict = {"status": "prepared", "checks": []}
    assert preflight._record_merger_reads(report, spec, Store()) is False
    assert report["status"] == "failed" and report["checks"][-1]["name"] == "merger_reads"
    ok: dict = {"status": "prepared", "checks": []}
    assert preflight._record_merger_reads(ok, load_spec(RUNS / "p5-s2-merger-reads.yaml"), Store()) is True
    assert ok["status"] == "prepared" and ok["merger_reads"]["estimate"]["mergers"] == 1


def test_the_merger_judge_refusal_holds_when_the_estimate_raises(monkeypatch):
    from mailroom_sandbox import merger_sections

    spec = load_spec(RUNS / "p5-s2-merger-reads.yaml")
    spec.job.merger.question_groups = False
    spec.job.merger.gap_retry = False

    def boom(*_a, **_k):
        raise RuntimeError("locator failed")

    monkeypatch.setattr(merger_sections, "question_excerpts", boom)
    monkeypatch.setattr(merger_sections, "locate", boom)

    class Store:
        def dataset_rows(self):
            return _rows()

    class Broken:
        def dataset_rows(self):
            raise RuntimeError("no rows")

    for store in (Store(), Broken()):
        report: dict = {"status": "prepared", "checks": []}
        assert preflight._record_merger_reads(report, spec, store) is False
        assert report["status"] == "failed" and "question_groups" in report["checks"][-1]["detail"]
