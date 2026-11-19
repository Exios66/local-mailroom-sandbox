"""rb1 R13b form-floor calibration: defect build and floor fit. Offline."""

from __future__ import annotations

import importlib.util
import json

import pytest

from mailroom_sandbox.paths import repo_root

_SPEC = importlib.util.spec_from_file_location("rb1_form_floor", repo_root() / "scripts" / "rb1_form_floor.py")
ff = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ff)

CLASSES = ("contract", "corporate_record", "correspondence", "insurance_claim", "merger_agreement")


def _rows(n_per_class=3, short_every=3):
    long_text = " ".join(f"w{i}." if i % 9 == 8 else f"w{i}" for i in range(4000))
    rows = []
    for c in CLASSES:
        for k in range(n_per_class):
            text = "Short note. Thanks." if k % short_every == short_every - 1 else f"TITLE {c} {k}\n{long_text}"
            rows.append({"id": f"DOC-{c[:4]}{k:012d}", "doc_text": text, "expected_doc_class": c,
                         "expected_subclass": "x", "source_revision": "r"})
    return rows


def test_build_is_deterministic_and_each_defect_is_a_defect():
    rows = _rows()
    a, b = ff.build(rows), ff.build(list(reversed(rows)))
    assert a == b
    frags = [r for r in a if r["expected_document_form"] == "fragment_or_excerpt"]
    joins = [r for r in a if r["control"] == "join"]
    assert len(frags) == 10  # 15 sources, the 5 short notes get no fragment
    assert len(joins) == len(CLASSES) * min(ff.JOINS_PER_CLASS, 3)
    assert {r["control"] for r in frags} == {"tail", "head", "cut"}
    src = {r["id"]: r["doc_text"] for r in rows}
    for r in frags:
        assert len(r["doc_text"]) < len(src[r["derived_from"][0]]) and r["class_label_scored"] is True
    for r in joins:
        x, y = r["derived_from"]
        assert x != y and r["class_label_scored"] is False
        assert len({d["expected_doc_class"] for d in rows if d["id"] in (x, y)}) == 2
    assert len({r["id"] for r in a}) == len(a)


def _write_run(path, masses):
    path.mkdir(parents=True)
    path.joinpath("items.jsonl").write_text("".join(
        json.dumps({"item_id": i, "pred": {"document_form_human_mass": m, "abstained": m >= 0.5}}) + "\n"
        for i, m in masses.items()), encoding="utf-8")


def test_fit_picks_the_highest_floor_that_lets_no_defect_through(tmp_path):
    defects = tmp_path / "defects.jsonl"
    defects.write_text("".join(json.dumps({"id": i, "expected_document_form": "fragment_or_excerpt"}) + "\n"
                               for i in ("d1", "d2", "d3")), encoding="utf-8")
    _write_run(tmp_path / "intact", {"i1": 0.1, "i2": 0.55, "i3": 0.79})
    _write_run(tmp_path / "defects", {"d1": 0.97, "d2": 0.88, "d3": 0.86})
    res = ff.fit(tmp_path / "intact", tmp_path / "defects", defects)
    assert res["recommended"]["floor"] == 0.85 and res["recommended"]["intact_parked"] == 0
    assert res["current_parks"] == {"intact_parked": 2, "defects_passed": 0}
    by_floor = {t["floor"]: t for t in res["table"]}
    assert by_floor[0.9]["defects_passed"] == 2 and by_floor[0.5]["intact_parked"] == 2


def test_fit_refuses_missing_results_or_unrecorded_mass(tmp_path):
    defects = tmp_path / "defects.jsonl"
    defects.write_text(json.dumps({"id": "d1", "expected_document_form": "multiple_documents"}) + "\n", encoding="utf-8")
    _write_run(tmp_path / "intact", {"i1": 0.1})
    _write_run(tmp_path / "defects", {})
    with pytest.raises(SystemExit, match="no result"):
        ff.fit(tmp_path / "intact", tmp_path / "defects", defects)
    (tmp_path / "defects" / "items.jsonl").write_text(json.dumps({"item_id": "d1", "pred": {}}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no human mass"):
        ff.fit(tmp_path / "intact", tmp_path / "defects", defects)
