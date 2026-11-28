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


def test_a_corrections_file_edited_after_validation_stops_scoring(monkeypatch, tmp_path):
    # The bytes parsed are the bytes checked: an edit after SHF-013 was validated must not feed new truth
    # to a run that reports the old fingerprint.
    path = tmp_path / "corrections.jsonl"
    path.write_bytes((repo_root() / sh.SUBCLASS_CORRECTIONS).read_bytes())
    monkeypatch.setattr(sh, "data_path", lambda _rel: path)
    monkeypatch.setattr(sh, "_CORRECTIONS_CACHE", {})
    assert "DOC-59d072355f2c3b14" in sh.subclass_corrections()
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed since SHF-013 was validated"):
        sh.subclass_corrections()


def test_a_corrections_file_removed_after_validation_stops_scoring(monkeypatch, tmp_path):
    path = tmp_path / "corrections.jsonl"
    path.write_bytes((repo_root() / sh.SUBCLASS_CORRECTIONS).read_bytes())
    monkeypatch.setattr(sh, "data_path", lambda _rel: path)
    monkeypatch.setattr(sh, "_CORRECTIONS_CACHE", {})
    monkeypatch.setattr(sh, "_STATUS", {"SHF-013": "current"})
    assert sh.subclass_corrections()
    path.unlink()
    with pytest.raises(RuntimeError, match="disappeared after SHF-013 was validated"):
        sh.subclass_corrections()
    # Never validated as current (unavailable from the start): no corrections, no error.
    monkeypatch.setattr(sh, "_STATUS", {"SHF-013": "unavailable"})
    assert sh.subclass_corrections() == {}


# --- the pipeline item and run-level subclass scores take the same corrections -----------------

PIPELINE_CORRECTED = [("DOC-59d072355f2c3b14", "corporate_record", "board_resolution", "charter_amendment"),
                      ("DOC-cf1ba08690065ad0", "merger_agreement", "other", "all_cash")]


@pytest.mark.parametrize("doc_id,cls,hub,fixed", PIPELINE_CORRECTED)
def test_a_pipeline_item_scores_the_reviewed_subclass(doc_id, cls, hub, fixed):
    from mailroom_sandbox.eval import runners

    row = {"id": doc_id, "expected_doc_class": cls, "expected_subclass": hub}
    score = runners.pipeline_item_score(row, {"doc_type": cls, "doc_subclass": fixed, "stage": "archived"}, None)
    assert score["subclass_correct"] == 1.0 and score["raw_dojo_subclass_correct"] == 0.0
    assert score["subclass_corrected"] is True
    hub_answer = runners.pipeline_item_score(row, {"doc_type": cls, "doc_subclass": hub, "stage": "archived"}, None)
    assert hub_answer["subclass_correct"] == 0.0 and hub_answer["raw_dojo_subclass_correct"] == 1.0


def test_a_pipeline_item_keeps_the_hub_subclass_when_the_correction_does_not_bind():
    from mailroom_sandbox.eval import scoring

    # a Hub relabel (different Hub value) or a missing id never takes the reviewed correction
    assert scoring.subclass_correct("corporate_record", "bylaws", "corporate_record", "charter_amendment",
                                    doc_id="DOC-59d072355f2c3b14") == (0.0, 0.0)
    assert scoring.subclass_correct("corporate_record", "board_resolution", "corporate_record",
                                    "charter_amendment") == (0.0, 0.0)
    # a rejected entry (verdict held/rejected) is never applied
    assert scoring.subclass_correct("correspondence", "demand", "correspondence", "email",
                                    doc_id="DOC-f4ce492b979c34e3") == (0.0, 0.0)


def test_pipeline_run_subclass_scores_take_the_corrections_and_keep_the_hub_raw():
    from mailroom_sandbox.eval.scoring import score_subclass

    ids = [d for d, *_ in PIPELINE_CORRECTED]
    classes = [c for _, c, _, _ in PIPELINE_CORRECTED]
    out = score_subclass(classes, [h for *_, h, _ in PIPELINE_CORRECTED], classes,
                         [f for *_, f in PIPELINE_CORRECTED], doc_ids=ids)
    assert out["subclass_accuracy"] == 1.0 and out["subclass_raw_dojo"]["subclass_accuracy"] == 0.0
    assert out["subclass_corrections_applied"] == 2
    assert out["subclass_scoring_hotfixes"] == ["SHF-012", "SHF-013"]
    plain = score_subclass(classes, [h for *_, h, _ in PIPELINE_CORRECTED], classes,
                           [f for *_, f in PIPELINE_CORRECTED])
    assert plain["subclass_accuracy"] == 0.0 and "subclass_corrections_applied" not in plain


# --- extraction scoring and the gate diagnosis score the reviewed subclass ----------------------

def _spy_subclasses(monkeypatch):
    seen: list[object] = []  # score_extraction_row scores the raw side first, then the headline
    real = scoring._score_extraction_row_once

    def spy(doc_type, predicted, expected, doc_text=None, doc_subclass=None, expected_subclass=None, **kw):
        seen.append(expected_subclass)
        return real(doc_type, predicted, expected, doc_text, doc_subclass, expected_subclass, **kw)

    monkeypatch.setattr(scoring, "_score_extraction_row_once", spy)
    return seen


def test_extraction_headline_scores_the_corrected_subclass_and_raw_keeps_the_hub(monkeypatch, corrections):
    corrections["DOC-C"] = {"doc_id": "DOC-C", "doc_class": "corporate_record", "hub_subclass": "board_resolution",
                            "subclass": "bylaws", "verdict": "correct"}
    seen = _spy_subclasses(monkeypatch)
    expected = {"entity_name": "Acme Corp.", "effective_date": "2020-01-02"}
    out = scoring.score_extraction_row("corporate_record", dict(expected), dict(expected),
                                       expected_subclass="board_resolution", doc_id="DOC-C")
    assert seen == ["board_resolution", "bylaws"]
    assert out["subclass_corrected"] == "bylaws" and "SHF-013" in out["scoring_hotfixes"]
    assert "subclass_corrected" not in out["raw_dojo"]


@pytest.mark.parametrize("doc_id, hub", [(None, "board_resolution"), ("DOC-UNREVIEWED", "board_resolution"),
                                         ("DOC-C", "bylaws")])  # no id, no correction, Hub moved on
def test_extraction_without_a_binding_correction_keeps_the_hub_subclass(monkeypatch, corrections, doc_id, hub):
    corrections["DOC-C"] = {"doc_id": "DOC-C", "doc_class": "corporate_record", "hub_subclass": "board_resolution",
                            "subclass": "bylaws", "verdict": "correct"}
    seen = _spy_subclasses(monkeypatch)
    out = scoring.score_extraction_row("corporate_record", {"entity_name": "Acme"}, {"entity_name": "Acme"},
                                       expected_subclass=hub, doc_id=doc_id)
    assert seen == [hub, hub]
    assert "subclass_corrected" not in out and "SHF-013" not in out["scoring_hotfixes"]


def test_the_gate_diagnosis_scores_the_corrected_subclass(monkeypatch, corrections):
    from mailroom_sandbox.job import gate_causes

    corrections["DOC-C"] = {"doc_id": "DOC-C", "doc_class": "corporate_record", "hub_subclass": "board_resolution",
                            "subclass": "bylaws", "verdict": "correct"}
    calls: list[dict] = []

    class Suite:
        def score(self, expected, predicted, doc_text=None, detailed=False, **kw):
            calls.append(kw)
            return types.SimpleNamespace(field_scores={k: 1.0 for k in expected})

    monkeypatch.setattr(scoring, "suite_for_doc_type", lambda _cls: Suite())
    row = {"id": "DOC-C", "expected_doc_class": "corporate_record", "expected_subclass": "board_resolution",
           "expected_fields": {"entity_name": "Acme Corp."}}
    gate_causes._field_scores(row, {"extracted_data": {"entity_name": "Acme Corp."}})
    gate_causes._field_scores({**row, "id": "DOC-OTHER"}, {"extracted_data": {"entity_name": "Acme Corp."}})
    assert [c.get("doc_subclass") for c in calls] == ["bylaws", "board_resolution"]


def test_the_committed_file_relabels_the_bylaw_amendments_425_extends():
    # DOC-443542beadaf2839 and DOC-78f2456f571403a9 are amendments to the bylaws (guide: bylaws, never
    # board_resolution); extraction scoring now reads them as bylaws on the headline.
    for doc_id in ("DOC-443542beadaf2839", "DOC-78f2456f571403a9"):
        assert sh.corrected_subclass(doc_id, "corporate_record", "board_resolution") == "bylaws"


# --- the subclass-derived truth follows a correction --------------------------------------------

CORP = "DOC-18f2fafa6d8fd491"  # a charter amendment the Hub labelled board_resolution (reviewed correction)


def _corp_truth(**over):
    truth = {"entity_name": "Acme Holdings, Inc.", "record_type": "other", "intent": "corporate_action_approval",
             "effective_date": "2004-05-03"}
    truth.update(over)
    truth["gt_presence"] = json.dumps({k: "populated" for k in truth})
    return truth


def test_shf013_derived_corporate_truth_follows_the_reviewed_subclass():
    truth = _corp_truth()
    answer = {"entity_name": "Acme Holdings, Inc.", "record_type": "articles_of_incorporation",
              "intent": "entity_formation", "effective_date": "2004-05-03"}
    out = scoring.score_extraction_row("corporate_record", answer, truth, "CERTIFICATE OF AMENDMENT",
                                       expected_subclass="board_resolution", doc_id=CORP)
    assert out["subclass_corrected"] == "charter_amendment"
    assert out["subclass_derived_truth"] == {"record_type": ["other", "articles_of_incorporation"],
                                             "intent": ["corporate_action_approval", "entity_formation"]}
    assert out["overall_extraction_score"] > out["raw_dojo"]["overall_extraction_score"]
    assert "SHF-013" in out["scoring_hotfixes"]


def test_shf013_keeps_a_derived_value_an_overlay_or_review_set():
    fixed, moved = sh.corrected_derived_truth("corporate_record", "board_resolution", "charter_amendment",
                                              _corp_truth(record_type="bylaws"))
    assert "record_type" not in moved and fixed["record_type"] == "bylaws"
    assert moved == {"intent": ["corporate_action_approval", "entity_formation"]}


def test_shf013_moves_contract_family_and_fills_merger_consideration():
    fixed, moved = sh.corrected_derived_truth("contract", "IP", "Consulting Agreements", {"cuad_family": "ip"})
    assert moved == {"cuad_family": ["ip", "consulting"]} and fixed["cuad_family"] == "consulting"
    truth = {"merger_consideration": None, "gt_presence": json.dumps({"merger_consideration": "unlabeled"})}
    fixed, moved = sh.corrected_derived_truth("merger_agreement", "other", "mixed_cash_stock", truth)
    assert moved == {"merger_consideration": [None, "mixed_cash_stock"]}
    assert json.loads(fixed["gt_presence"])["merger_consideration"] == "populated"
    # a merger subclass that names no consideration, an unchanged subclass, an unmapped one: nothing
    assert sh.corrected_derived_truth("merger_agreement", "all_cash", "other", {"merger_consideration": "all_cash"})[1] == {}
    assert sh.corrected_derived_truth("contract", "IP", "ip", {"cuad_family": "ip"})[1] == {}
    assert sh.corrected_derived_truth("corporate_record", "board_resolution", "certificate_of_formation",
                                      _corp_truth())[1] == {}


def test_shf013_the_corporate_mapping_is_the_production_prompts_and_the_dojo_vocabulary():
    from llm_dojo_scoring.schemas.corporate_record_schema import RECORD_TYPES

    assert {rt for rt, _ in sh.CORPORATE_SUBCLASS_TRUTH.values()} <= set(RECORD_TYPES)
    prompt = (repo_root() / "config" / "prompts" / "corporate_records_specialist_condensed_v1.txt").read_text()
    for sub in ("bylaws", "charter_amendment", "powers_of_attorney", "rights_instrument", "indenture",
                "board_resolution", "officer_certificate", "subsidiary_list"):
        record_type, intent = sh.CORPORATE_SUBCLASS_TRUTH[sub]
        assert f"{record_type}, {intent}" in prompt, sub


def test_shf013_the_lowest_field_diagnosis_reads_the_derived_truth():
    from mailroom_sandbox.job import gate_causes

    row = {"id": CORP, "expected_doc_class": "corporate_record", "expected_subclass": "board_resolution",
           "doc_text": "CERTIFICATE OF AMENDMENT", "expected_fields": json.dumps(_corp_truth())}
    scores = gate_causes._field_scores(row, {"extracted_data": {
        "entity_name": "Acme Holdings, Inc.", "record_type": "articles_of_incorporation",
        "intent": "entity_formation", "effective_date": "2004-05-03"}})
    assert scores.get("record_type") == 1.0
