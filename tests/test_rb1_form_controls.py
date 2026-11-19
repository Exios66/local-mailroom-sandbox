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
