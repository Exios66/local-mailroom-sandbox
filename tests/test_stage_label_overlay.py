"""scripts/stage_label_overlay.py: assist join rules, Hub-delta overlay and override sign-off."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stage_label_overlay.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("stage_label_overlay", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


TEXT = ("This Agreement renews for one (1) year periods unless either Party notifies the other Party "
        "not less than six (6) months before the end of the term. Either party may terminate upon "
        "ninety (90) days' prior written notice. For material breach, written notice and at least "
        "sixty (60) days to cure.")


@pytest.mark.parametrize("phrase, expected", [
    ("at least sixty 90 days", True), ("eighty (180) days", False), ("with 60 days", False),
    ("sixty (60) days", False), ("Thirty (30) business days", False), ("forty-five (45) days", False),
    ("forty-five 40 days", True),
])
def test_garbled(mod, phrase, expected):
    assert mod.garbled(phrase) is expected


def test_assist_terms_add_only_grounded_notice_periods(mod):
    assist = ("one (1) year periods unless either Party notifies the other Party not less than six (6) "
              "months before the end; upon ninety (90) days' prior written notice; written notice and "
              "at least sixty (60) days to cure")
    extra, refused = mod.assist_notice_terms(assist, "ninety (90) days", TEXT)
    assert extra == ["not less than six (6) months"]
    assert any(r.startswith("not a notice period: one (1) year") for r in refused)
    assert any(r.startswith("cure or breach period") for r in refused)


def test_assist_term_must_occur_in_text(mod):
    extra, refused = mod.assist_notice_terms("at least forty-five (45) days prior notice", "", TEXT)
    assert extra == [] and refused == ["not in document text: at least forty-five (45) days"]


def _cell(**kw):
    base = {"document_id": "DOC-1", "doc_class": "contract", "field": "f", "value": "v", "presence": "populated",
            "chosen_source": "interim_reviewed", "agreeing_sources": "interim_reviewed", "agreement": "1-of-2",
            "rule": "weighted_vote", "conflict": "False", "needs_human": "False", "evidence": "[]", "votes": "{}"}
    return base | kw


def test_overlay_is_the_hub_delta_and_flags_overrides(mod):
    prov = [
        _cell(field="a", chosen_source="hub_v9.3", agreeing_sources="hub_v9.3", votes='{"hub_v9.3": "v"}'),
        _cell(field="b", votes='{"hub_v9.3": "old", "interim_reviewed": "v"}'),
        _cell(field="c", votes='{"near_gold_reviewed": "v"}'),
        _cell(field="d", presence="unlabeled"),
        _cell(field="e", agreeing_sources="hub_v9.3|interim_reviewed", votes='{"hub_v9.3": "v"}'),
    ]
    overlay = mod.overlay_records(prov, {"DOC-1": "sha"})
    labels = overlay["contract"][0]["labels"]
    assert set(labels) == {"b", "c"}
    assert labels["b"]["override"] is True and labels["c"]["override"] is False
    assert overlay["contract"][0]["content_sha256"] == "sha"
    signoff = mod.signoff_rows(prov)
    assert [(r["field"], r["hub_v9_3_value"], r["decided_by"]) for r in signoff] == [("b", "old", "")]


def test_join_fills_and_extends_notice_cells(mod):
    cols = ["document_id", "doc_class", "fields_targeted", "fields_labeled", "label_completeness",
            "termination_notice_period", "duplicate_of"]
    rows = [
        {"document_id": "DOC-1", "doc_class": "contract", "fields_targeted": "4", "fields_labeled": "2",
         "label_completeness": "0.5", "termination_notice_period": "ninety (90) days", "duplicate_of": ""},
        {"document_id": "DOC-2", "doc_class": "contract", "fields_targeted": "4", "fields_labeled": "1",
         "label_completeness": "0.25", "termination_notice_period": "", "duplicate_of": "DOC-1"},
    ]
    prov = [_cell(document_id="DOC-1", field="termination_notice_period", value="ninety (90) days",
                  chosen_source="cuad_span", agreeing_sources="cuad_span"),
            _cell(document_id="DOC-2", field="termination_notice_period", value="", presence="unlabeled",
                  chosen_source="", agreeing_sources="")]
    comp = [{"doc_class": "contract", "field": "termination_notice_period", "documents": "2",
             "labeled_hub_v9_3": "0", "labeled_repaired": "1", "populated": "1", "documented_absence": "0",
             "unlabeled": "1", "disputed_unresolved": "0", "completeness_hub_v9_3": "0.0",
             "completeness_repaired": "0.5", "conflicts": "0", "needs_human": "0", "top_source": "cuad_span"}]
    assist = [dict(rows[0], termination_notice_period="notifies the other Party not less than six (6) months before"),
              dict(rows[1], termination_notice_period="upon ninety (90) days' prior written notice", duplicate_of="DOC-9")]
    builder = {"labels": (cols, rows), "provenance": (list(prov[0]), prov), "completeness": (list(comp[0]), comp)}
    out = mod.join(builder, assist, {"DOC-1": TEXT, "DOC-2": TEXT})
    _, joined = out["labels"]
    assert joined[0]["termination_notice_period"] == "ninety (90) days; not less than six (6) months"
    assert joined[0]["fields_labeled"] == "2"  # extended, not newly filled
    assert joined[1]["termination_notice_period"] == "ninety (90) days"
    assert (joined[1]["fields_labeled"], joined[1]["label_completeness"]) == ("2", "0.5")
    assert joined[1]["duplicate_of"] == "DOC-1"  # reviewed keeper wins
    _, p = out["provenance"]
    assert p[1]["chosen_source"] == "assist_upload" and json.loads(p[1]["evidence"])[0]["text"]
    assert out["completeness"][0]["labeled_repaired"] == 2
    assert out["counts"]["kept_builder_duplicate_keeper"] == 1 and out["queue"] == []
    # the input tables are not mutated
    assert rows[1]["termination_notice_period"] == "" and prov[1]["presence"] == "unlabeled"
