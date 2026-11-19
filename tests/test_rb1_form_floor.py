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


def _write_run(path, masses, locked=None, source=None, question_set=None):
    import hashlib

    path.mkdir(parents=True)
    sha = hashlib.sha256(source.read_bytes()).hexdigest() if source else None
    path.joinpath("spec.lock.json").write_text(json.dumps({
        "engine": {"model": "luna"}, "dataset": {"metadata": {"sha256": sha}},
        "reviewer": {"model": "luna", "question_set": question_set or {"version": "4.0.1"}}}), encoding="utf-8")
    path.joinpath("dataset.jsonl").write_text("".join(json.dumps({"id": i}) + "\n" for i in (locked or masses)),
                                              encoding="utf-8")
    path.joinpath("items.jsonl").write_text("".join(
        json.dumps({"item_id": i, "pred": {"document_form_human_mass": m, "abstained": m >= 0.5}}) + "\n"
        for i, m in masses.items()), encoding="utf-8")


def test_fit_picks_the_highest_floor_that_lets_no_defect_through(tmp_path):
    defects = tmp_path / "defects.jsonl"
    defects.write_text("".join(json.dumps({"id": i, "expected_document_form": "fragment_or_excerpt"}) + "\n"
                               for i in ("d1", "d2", "d3")), encoding="utf-8")
    _write_run(tmp_path / "intact", {"i1": 0.1, "i2": 0.55, "i3": 0.79})
    _write_run(tmp_path / "defects", {"d1": 0.97, "d2": 0.88, "d3": 0.86}, source=defects)
    res = ff.fit(tmp_path / "intact", tmp_path / "defects", defects)
    assert res["recommended"]["floor"] == 0.85 and res["recommended"]["intact_parked"] == 0
    assert res["current_parks"] == {"intact_parked": 2, "defects_passed": 0}
    by_floor = {t["floor"]: t for t in res["table"]}
    assert by_floor[0.9]["defects_passed"] == 2 and by_floor[0.5]["intact_parked"] == 2


def test_fit_refuses_missing_results_or_unrecorded_mass(tmp_path):
    defects = tmp_path / "defects.jsonl"
    defects.write_text(json.dumps({"id": "d1", "expected_document_form": "multiple_documents"}) + "\n", encoding="utf-8")
    _write_run(tmp_path / "intact", {"i1": 0.1})
    _write_run(tmp_path / "defects", {}, locked=["d1"], source=defects)
    with pytest.raises(SystemExit, match="1 locked rows without a result"):
        ff.fit(tmp_path / "intact", tmp_path / "defects", defects)
    (tmp_path / "defects" / "items.jsonl").write_text(json.dumps({"item_id": "d1", "pred": {}}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no human mass"):
        ff.fit(tmp_path / "intact", tmp_path / "defects", defects)


def test_fit_refuses_a_partial_or_duplicated_run(tmp_path):
    defects = tmp_path / "defects.jsonl"
    defects.write_text(json.dumps({"id": "d1", "expected_document_form": "fragment_or_excerpt"}) + "\n", encoding="utf-8")
    _write_run(tmp_path / "defects", {"d1": 0.9}, source=defects)
    _write_run(tmp_path / "intact", {"i1": 0.1}, locked=["i1", "i2"])  # i2 never ran
    with pytest.raises(SystemExit, match="1 locked rows without a result"):
        ff.fit(tmp_path / "intact", tmp_path / "defects", defects)
    items = tmp_path / "intact" / "items.jsonl"
    items.write_text(items.read_text() * 2, encoding="utf-8")
    (tmp_path / "intact" / "dataset.jsonl").write_text(json.dumps({"id": "i1"}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="1 duplicated results"):
        ff.fit(tmp_path / "intact", tmp_path / "defects", defects)
    _write_run(tmp_path / "intact2", {"i1": 0.1, "stray": 0.9}, locked=["i1"])  # a result it never locked
    with pytest.raises(SystemExit, match="1 results outside its locked dataset"):
        ff.fit(tmp_path / "intact2", tmp_path / "defects", defects)


def test_fit_refuses_mismatched_runs_an_edited_defects_file_and_an_empty_side(tmp_path):
    defects = tmp_path / "defects.jsonl"
    defects.write_text(json.dumps({"id": "d1", "expected_document_form": "fragment_or_excerpt"}) + "\n", encoding="utf-8")
    _write_run(tmp_path / "defects", {"d1": 0.9}, source=defects)
    _write_run(tmp_path / "intact", {"i1": 0.1}, question_set={"version": "4.0.0"})
    with pytest.raises(SystemExit, match="differ in model or question set"):
        ff.fit(tmp_path / "intact", tmp_path / "defects", defects)
    _write_run(tmp_path / "intact2", {"i1": 0.1})
    defects.write_text(defects.read_text() + "\n", encoding="utf-8")  # edited after the run locked it
    with pytest.raises(SystemExit, match="is not the file the defects run locked"):
        ff.fit(tmp_path / "intact2", tmp_path / "defects", defects)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    _write_run(tmp_path / "defects-empty", {}, source=empty)
    with pytest.raises(SystemExit, match="both must be non-empty"):
        ff.fit(tmp_path / "intact2", tmp_path / "defects-empty", empty)


def test_jsonl_keeps_unicode_line_separators_inside_text(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps({"id": "a", "doc_text": "one\u2028two\u2029three"}, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    assert ff._jsonl(path) == [{"id": "a", "doc_text": "one\u2028two\u2029three"}]


def test_cut_lands_in_the_newest_message_and_a_signed_closing_instrument_is_no_tail():
    top = " ".join(f"line{i}." if i % 7 == 6 else f"line{i}" for i in range(300))
    thread = f"Hi Ann, {top}\n-----Original Message-----\nFrom: Bob Sent: Monday\n" + "old " * 2000
    cut = ff.fragment({"doc_text": thread}, "cut")
    assert cut is not None and len(cut) < len(thread.split("-----Original")[0]) and "Original" not in cut
    # newest message too short to cut: no fragment, since a cut in the history leaves a whole email
    assert ff.fragment({"doc_text": "Thanks, will do.\n" + "-----Original Message----- " + "x " * 900}, "cut") is None
    body = "w " * 4000
    addendum = body + "By /s/ A 13 ADDENDUM TO ENDORSEMENT AGREEMENT This addendum adds a clause. " + "s " * 800
    assert ff.fragment({"doc_text": addendum}, "tail") is None
    plain = body + "IN WITNESS WHEREOF [SIGNATURE PAGE TO AMENDMENT NO. 1] By /s/ A " + "s " * 800
    assert ff.fragment({"doc_text": plain}, "tail") == plain[-ff.TAIL_CHARS:]


def test_exclude_adds_the_used_rows_to_the_split_complement(tmp_path):
    base = tmp_path / "calibration.exclude.ids"
    base.write_text("# complement\nDOC-a\nDOC-b\n", encoding="utf-8")
    used = tmp_path / "run" / "dataset.jsonl"
    used.parent.mkdir()
    used.write_text("".join(json.dumps({"id": i}) + "\n" for i in ("DOC-c", "DOC-a")), encoding="utf-8")
    out = tmp_path / "draw2.exclude.ids"
    assert ff.main(["exclude", "--base", str(base), "--used", str(used), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert [ln for ln in text.splitlines() if not ln.startswith("#")] == ["DOC-a", "DOC-b", "DOC-c"]
    assert str(tmp_path) not in text  # no local paths in a committed file
