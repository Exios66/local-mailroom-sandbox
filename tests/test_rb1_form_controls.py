"""rb1 R13b document-form positive controls: deterministic build and the run check. Offline."""

from __future__ import annotations

import importlib.util
import json

from mailroom_sandbox.paths import repo_root

_SPEC = importlib.util.spec_from_file_location("rb1_form_controls", repo_root() / "scripts" / "rb1_build_form_controls.py")
fc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fc)


def _source(tmp_path):
    words = " ".join(f"word{i}." if i % 9 == 8 else f"word{i}" for i in range(4000))
    rows = []
    for _, _, sources, _ in fc.CONTROLS:
        for doc_id in sources:
            rows.append({"id": doc_id, "doc_text": f"TITLE {doc_id}\n{words}\nSigned.", "expected_doc_class": "contract",
                         "expected_subclass": "x", "source_revision": "r"})
    path = tmp_path / "dataset.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in {r["id"]: r for r in rows}.values()), encoding="utf-8")
    return path


def test_build_is_deterministic_and_known_by_construction(tmp_path):
    src = _source(tmp_path)
    for name in ("a.jsonl", "b.jsonl"):
        assert fc.main(["--source", str(src), "--out", str(tmp_path / name)]) == 0
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()
    rows = {r["id"]: r for r in map(json.loads, (tmp_path / "a.jsonl").read_text().splitlines())}
    assert len(rows) == len(fc.CONTROLS)
    assert len(rows["CTRL-signature-page"]["doc_text"]) == fc.TAIL_CHARS
    cut = rows["CTRL-cut-mid-sentence"]["doc_text"]
    assert cut[-1] not in ".;:!?" and not cut.endswith("Signed.")
    joined = rows["CTRL-claim-plus-email"]
    assert joined["derived_from"] == ["DOC-bf518ec27ab190de", "DOC-6775dc31dac37ceb"] and "\n\n" in joined["doc_text"]
    assert joined["class_label_scored"] is False and rows["CTRL-signature-page"]["class_label_scored"] is True
    forms = {r["expected_document_form"] for r in rows.values()}
    assert forms == {"fragment_or_excerpt", "multiple_documents", "complete_instrument"}


def test_check_run_needs_the_form_and_the_park(tmp_path, capsys):
    src = _source(tmp_path)
    controls = tmp_path / "controls.jsonl"
    fc.main(["--source", str(src), "--out", str(controls)])
    run = tmp_path / "run"
    run.mkdir()
    rows = [json.loads(line) for line in controls.read_text().splitlines()]

    def write(mutate):
        items = []
        for r in rows:
            form = r["expected_document_form"]
            pred = {"document_form": form, "abstained": form != "complete_instrument"}
            mutate(r["id"], pred)
            items.append({"item_id": r["id"], "pred": pred})
        (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")

    write(lambda _id, _p: None)
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 0
    # Right form but not parked is still a miss: the park is what protects extraction.
    write(lambda doc_id, p: p.update(abstained=False) if doc_id == "CTRL-signature-page" else None)
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 1
    assert "MISS CTRL-signature-page" in capsys.readouterr().out


def test_check_run_counts_a_missing_control_as_a_miss(tmp_path, capsys):
    src = _source(tmp_path)
    controls = tmp_path / "controls.jsonl"
    fc.main(["--source", str(src), "--out", str(controls)])
    run = tmp_path / "run"
    run.mkdir()
    rows = [json.loads(line) for line in controls.read_text().splitlines()][1:]  # first control never ran
    items = [{"item_id": r["id"], "pred": {"document_form": r["expected_document_form"],
                                            "abstained": r["expected_document_form"] != "complete_instrument"}}
             for r in rows]
    (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 1
    assert "no item in the run" in capsys.readouterr().out


def test_check_run_fails_an_empty_run_and_a_duplicate_result(tmp_path, capsys):
    src = _source(tmp_path)
    controls = tmp_path / "controls.jsonl"
    fc.main(["--source", str(src), "--out", str(controls)])
    run = tmp_path / "run"
    run.mkdir()
    (run / "items.jsonl").write_text("", encoding="utf-8")
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 1
    assert f"0/{len(fc.CONTROLS)} controls correct" in capsys.readouterr().out
    rows = [json.loads(line) for line in controls.read_text().splitlines()]
    items = [{"item_id": r["id"], "pred": {"document_form": r["expected_document_form"],
                                            "abstained": r["expected_document_form"] != "complete_instrument"}}
             for r in rows]
    (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items + items[:1]), encoding="utf-8")
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 1
    assert "duplicate result" in capsys.readouterr().out


def test_check_run_fails_a_truncated_or_edited_controls_file(tmp_path, capsys):
    src = _source(tmp_path)
    controls = tmp_path / "controls.jsonl"
    fc.main(["--source", str(src), "--out", str(controls)])
    run = tmp_path / "run"
    run.mkdir()
    rows = [json.loads(line) for line in controls.read_text().splitlines()]
    items = [{"item_id": r["id"], "pred": {"document_form": r["expected_document_form"],
                                            "abstained": r["expected_document_form"] != "complete_instrument"}}
             for r in rows]
    (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 0
    capsys.readouterr()
    controls.write_text("".join(json.dumps(r) + "\n" for r in rows[1:]), encoding="utf-8")  # six rows, six results
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 1
    out = capsys.readouterr().out
    assert f"{len(fc.CONTROLS) - 1}/{len(fc.CONTROLS)} controls correct" in out and "controls file has None" in out
    controls.write_text("", encoding="utf-8")
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 1
    assert f"0/{len(fc.CONTROLS)} controls correct" in capsys.readouterr().out


def test_check_run_reads_the_v41_form_flags(tmp_path, capsys):
    """4.1.0 reports yes/no flags (fragment, bundle, ...); a control passes when any fired flag names its form."""
    src = _source(tmp_path)
    controls = tmp_path / "controls.jsonl"
    fc.main(["--source", str(src), "--out", str(controls)])
    run = tmp_path / "run"
    run.mkdir()
    rows = [json.loads(line) for line in controls.read_text().splitlines()]
    to_flag = {v: k for k, v in fc.FLAG_FORMS.items()}

    def write(extra_flag=None, drop_flags=False):
        items = []
        for r in rows:
            form = r["expected_document_form"]
            flags = [] if form == "complete_instrument" or drop_flags else [to_flag[form]]
            if extra_flag and flags:
                flags = [extra_flag, *flags]                 # a cut-off bundle fires both; order must not matter
            pred = {"document_form": flags[0] if flags else "complete_instrument", "document_form_flags": flags,
                    "abstained": bool(flags) or (drop_flags and form != "complete_instrument")}
            items.append({"item_id": r["id"], "pred": pred})
        (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")

    write()
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 0
    write(extra_flag="unreadable")
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 0
    # Parked for another reason (no flag fired) is a miss: the form question did not catch the defect.
    write(drop_flags=True)
    assert fc.main(["--check-run", str(run), "--controls", str(controls)]) == 1
    assert "MISS" in capsys.readouterr().out
