"""SHF-013: subclass scoring for isolated sorter / sorter_reviewer runs, with reviewed subclass corrections.

Raw (``raw_dojo``) is the Hub truth; the headline applies ``data/labels/review/subclass_corrections.jsonl``.
Network-free; no LLM calls.
"""
from __future__ import annotations

import json
import types

import pytest

from mailroom_sandbox import scoring_hotfixes as sh
from mailroom_sandbox.eval import scoring
from mailroom_sandbox.eval.agents import _score_sorter, spec_for
from mailroom_sandbox.paths import repo_root

CORRECTION = {"doc_id": "DOC-B", "doc_class": "merger_agreement", "hub_subclass": "other",
              "subclass": "all_cash", "verdict": "correct"}


@pytest.fixture
def corrections(monkeypatch):
    table = {"DOC-B": dict(CORRECTION)}
    monkeypatch.setattr(sh, "subclass_corrections", lambda: table)
    return table


def _row(doc_id, cls, sub):
    return {"id": doc_id, "expected_doc_class": cls, "expected_subclass": sub}


# --- the fix and its reviewed file ------------------------------------------------------------

def test_shf013_is_registered_current_and_bound_to_the_corrections_file():
    fix = next(f for f in sh.HOTFIXES if f.id == "SHF-013")
    assert sh.status(refresh=True)["SHF-013"] == "current"
    targets = dict(fix.targets)
    file_target = "file:" + sh.SUBCLASS_CORRECTIONS
    assert file_target in targets and sh.target_sha(file_target) == targets[file_target]
    described = next(f for f in sh.describe()["fixes"] if f["id"] == "SHF-013")
    assert {t["target"] for t in described["targets"]} == set(targets)


def test_an_edited_corrections_file_makes_shf013_stale(monkeypatch):
    fix = next(f for f in sh.HOTFIXES if f.id == "SHF-013")
    edited = sh.ScoringHotfix(fix.id, fix.layer, tuple((t, "0" * 64 if t.startswith("file:") else s)
                                                       for t, s in fix.targets), fix.upstream, fix.summary)
    monkeypatch.setattr(sh, "HOTFIXES", tuple(edited if f.id == fix.id else f for f in sh.HOTFIXES))
    monkeypatch.setattr(sh, "_STATUS", {})
    assert sh.status()["SHF-013"] == "stale"
    assert scoring.sorter_subclass_scores([(_row("DOC-B", "merger_agreement", "other"), {"pred": {}})]) == {}
    monkeypatch.setattr(sh, "_STATUS", {})


def test_the_reviewed_corrections_file_is_well_formed_and_quotes_its_evidence():
    path = repo_root() / sh.SUBCLASS_CORRECTIONS
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len({e["doc_id"] for e in lines}) == len(lines)
    for e in lines:
        assert set(e) >= {"doc_id", "doc_class", "hub_subclass", "subclass", "review", "evidence", "verdict"}
        assert e["verdict"] in {"correct", "held", "rejected"} and e["subclass"] != e["hub_subclass"]
        assert e["review"]["reviewer"] == "Claude (agent)" and e["review"]["note"]
        assert e["evidence"] and all(isinstance(q, str) and q.strip() for q in e["evidence"])
    applied = sh.subclass_corrections()
    assert set(applied) == {e["doc_id"] for e in lines if e["verdict"] == "correct"}
    assert sh.corrected_subclass("DOC-59d072355f2c3b14", "corporate_record", "board_resolution") == "charter_amendment"
    assert sh.corrected_subclass("DOC-cf1ba08690065ad0", "merger_agreement", "other") == "all_cash"
    assert sh.corrected_subclass("DOC-f4ce492b979c34e3", "correspondence", "demand") is None  # rejected: Hub demand stands


def test_a_correction_applies_only_to_the_class_and_hub_value_it_reviewed(corrections):
    assert sh.corrected_subclass("DOC-B", "merger_agreement", "Other") == "all_cash"  # canonical token
    assert sh.corrected_subclass("DOC-B", "merger_agreement", "all_stock") is None  # the Hub changed
    assert sh.corrected_subclass("DOC-B", "contract", "other") is None
    assert sh.corrected_subclass("DOC-X", "merger_agreement", "other") is None


# --- one row ----------------------------------------------------------------------------------

@pytest.mark.parametrize(("cls", "truth", "pred", "expected"), [
    ("contract", "Distributor", {"doc_type": "contract", "doc_subclass": "distributor"}, 1.0),
    ("contract", "Affiliate_Agreements", {"doc_type": "contract", "contract_subtype": "affiliate"}, 1.0),
    ("contract", "Affiliate_Agreements", {"doc_type": "contract", "doc_subclass": "license"}, 0.0),
    ("contract", "Distributor", {"doc_type": "corporate_record", "doc_subclass": "distributor"}, 0.0),
    ("contract", "Distributor", {"doc_type": "contract", "doc_subclass": "distributor", "abstained": True}, 0.0),
    ("contract", "Distributor", {"doc_type": "Contract"}, 0.0),
])
def test_row_subclass_is_joint_with_the_class_on_canonical_tokens(cls, truth, pred, expected):
    out = scoring.sorter_subclass_row(_row("DOC-A", cls, truth), pred)
    assert out["subclass_match"] == out["hub_subclass_match"] == expected
    assert "subclass_corrected" not in out


def test_a_row_without_a_truth_subclass_is_unscored():
    assert scoring.sorter_subclass_row(_row("DOC-A", "contract", ""), {"doc_type": "contract"}) is None
    scored = _score_sorter(_row("DOC-A", "contract", None), {"doc_type": "contract", "doc_subclass": "x"})
    assert "subclass_match" not in scored and scored["match"] == 1.0


def test_item_score_is_dual_reported_with_the_hub_truth_raw(corrections):
    scored = _score_sorter(_row("DOC-B", "merger_agreement", "other"),
                           {"doc_type": "merger_agreement", "doc_subclass": "all_cash"})
    assert scored["match"] == 1.0 and scored["subclass_match"] == 1.0
    assert scored["raw_dojo"]["subclass_match"] == 0.0
    assert scored["subclass_corrected"] is True and scored["hub_subclass"] == "other"
    assert scored["expected_subclass"] == "all_cash"
    assert "SHF-013" in scored["scoring_hotfixes"] and "SHF-007" in scored["scoring_hotfixes"]
    assert "subclass_match" in scored["scoring_hotfixes_changed"]
    assert spec_for("sorter").score_one is _score_sorter and spec_for("sorter_reviewer").score_one is _score_sorter


# --- the run headline -------------------------------------------------------------------------

def _fixture_pairs():
    rows = [_row("DOC-A", "contract", "Distributor"),
            _row("DOC-B", "merger_agreement", "other"),
            _row("DOC-C", "merger_agreement", "all_stock"),
            _row("DOC-D", "contract", "Affiliate_Agreements"),
            _row("DOC-E", "contract", ""),
            _row("DOC-F", "corporate_record", "bylaws")]
    entries = [{"pred": {"doc_type": "contract", "doc_subclass": "distributor"}},
               {"pred": {"doc_type": "merger_agreement", "doc_subclass": "all_cash"}},
               {"pred": {"doc_type": "merger_agreement", "doc_subclass": "all_cash"}},
               {"pred": {"doc_type": "contract", "contract_subtype": "affiliate"}},
               {"pred": {"doc_type": "contract", "doc_subclass": "license"}},
               {"pred": {}, "error": "TimeoutError: x"}]
    return list(zip(rows, entries))


def test_run_subclass_metric_per_class_and_failed_rows_on_a_fixture():
    out = scoring.sorter_subclass_scores(_fixture_pairs())
    assert out["subclass_scored"] == 5  # DOC-E has no truth subclass
    assert out["subclass_match"] == pytest.approx(2 / 5)  # DOC-B, DOC-C wrong; DOC-F errored: wrong
    assert out["subclass_by_class"] == {
        "contract": {"n": 2, "correct": 2, "accuracy": 1.0},
        "corporate_record": {"n": 1, "correct": 0, "accuracy": 0.0},
        "merger_agreement": {"n": 2, "correct": 0, "accuracy": 0.0},
    }
    assert out["subclass_corrections_applied"] == 0
    assert out["raw_dojo"]["subclass_match"] == out["subclass_match"] and out["scoring_hotfixes_changed"] == []
    assert out["scoring_hotfixes"] == ["SHF-013"]


def test_run_corrections_are_applied_counted_and_dual_reported(corrections):
    out = scoring.sorter_subclass_scores(_fixture_pairs())
    assert out["subclass_corrections_applied"] == 1
    assert out["subclass_match"] == pytest.approx(3 / 5)
    assert out["raw_dojo"]["subclass_match"] == pytest.approx(2 / 5)
    assert out["subclass_by_class"]["merger_agreement"]["accuracy"] == 0.5
    assert out["raw_dojo"]["subclass_by_class"]["merger_agreement"]["accuracy"] == 0.0
    assert set(out["scoring_hotfixes_changed"]) == {"subclass_match", "subclass_by_class"}


def test_isolated_run_headline_carries_the_subclass_metric(monkeypatch, corrections, tmp_path):
    from mailroom_sandbox.eval import experiment_log, runners

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(experiment_log, "append", lambda record: None)
    monkeypatch.setattr(runners, "emit", lambda *a, **k: None)
    pairs = _fixture_pairs()[:4]
    preds = {r["id"]: e["pred"] for r, e in pairs}
    monkeypatch.setattr(runners, "_predict_spec", lambda spec, row, mock: (dict(preds[row["id"]]), False))
    rows = [{**r, "filename": r["id"], "doc_text": "t"} for r, _ in pairs]
    scores = runners.run_isolated_eval("sorter", mock=True, rows=rows)["scores"]
    assert scores["exact_match"] == 1.0 and scores["raw_dojo"]["exact_match"] == 1.0  # class side unchanged
    assert scores["subclass_scored"] == 4 and scores["subclass_match"] == pytest.approx(3 / 4)
    assert scores["raw_dojo"]["subclass_match"] == pytest.approx(2 / 4)
    assert scores["subclass_corrections_applied"] == 1
    assert "SHF-013" in scores["scoring_hotfixes"] and "subclass_match" in scores["scoring_hotfixes_changed"]


def test_campaign_report_renders_the_subclass_metric():
    from mailroom_sandbox import report_campaigns as rc

    scores = {"exact_match": 1.0, "n": 4, **scoring.sorter_subclass_scores(_fixture_pairs()[:4])}
    head = rc._headline(scores)
    assert head["subclass_match"] == pytest.approx(2 / 4) and head["subclass_scored"] == 4
    assert head["subclass_corrections_applied"] == 0 and head["subclass_match_hub_truth"] == pytest.approx(2 / 4)
    by_class = rc._subclass_by_class(scores)
    assert by_class["merger_agreement"] == {"n": 2, "correct": 0, "accuracy": 0.0, "hub_truth_accuracy": 0.0}
    assert rc._subclass_by_class({"exact_match": 1.0}) is None
    report = {"campaign": "rb1", "experiment": "rb1-r13b", "run_id": "r", "iteration": "i001", "status": "done",
              "items": {"ok": 4, "failed": 0, "total": 4}, "headline": head, "subclass_by_class": by_class}
    md = rc._render_report_md(report, types.SimpleNamespace(stem="r"))
    assert "| subclass_match | 0.5000 |" in md and "Subclass by truth class (SHF-013" in md
    assert "| merger_agreement | 2 | 0 |" in md
