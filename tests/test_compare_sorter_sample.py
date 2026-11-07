"""compare_sorter_prompt --sample: the controlled, per-stratum validation set."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "compare_sorter_prompt", Path(__file__).resolve().parents[1] / "scripts" / "compare_sorter_prompt.py")
csp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(csp)


def _t(cls, sub, *, class_ok=True, sub_ok=True, got="contract", status="label", evidence=(), name=None):
    return {"filename": name or f"{cls}-{sub}", "target_status": status, "target_evidence": list(evidence),
            "use_for_class": True, "use_for_subclass": True, "target_doc_class": cls, "target_subclass": sub,
            "sorter_class_correct": class_ok, "sorter_subclass_correct": sub_ok,
            "sorter_doc_type": cls if class_ok else got, "sorter_doc_subclass": sub if sub_ok else "x"}


def _targets():
    t = {}
    for i in range(10):
        t[f"cls-{i}"] = _t("corporate_record", "indenture", class_ok=False)
    for i in range(8):
        t[f"sub-{i}"] = _t("correspondence", "memo", sub_ok=False)
        t[f"ok-{i}"] = _t("correspondence", "memo")
    t["rare-ok"] = _t("merger_agreement", "mixed_cash_stock_election")
    t["unscored"] = {**_t("contract", "license"), "use_for_class": False}
    return t


def test_sample_keeps_every_class_error_and_draws_per_stratum():
    chosen = csp.select_sample(_targets(), errors_per_stratum=3, controls_per_stratum=2, seed=42)
    assert {d for d in chosen if d.startswith("cls-")} == {f"cls-{i}" for i in range(10)}
    assert sum(d.startswith("sub-") for d in chosen) == 3
    assert sum(d.startswith("ok-") for d in chosen) == 2
    assert chosen["rare-ok"] == "control"  # a stratum smaller than the draw is taken whole
    assert "unscored" not in chosen
    assert chosen["cls-0"] == "class corporate_record -> contract"
    assert all(chosen[d] == "subclass correspondence/memo -> x" for d in chosen if d.startswith("sub-"))


def test_sample_is_deterministic_per_seed():
    a = csp.select_sample(_targets(), seed=42)
    assert a == csp.select_sample(_targets(), seed=42)
    assert set(a) != set(csp.select_sample(_targets(), seed=7))


def test_prime_keeps_only_the_highest_quality_labels():
    cuad = "theatticusproject/cuad"
    targets = {
        "ok": _t("contract", "license", name="a.pdf"),
        "ex10": _t("contract", "license", name="b.htm"),
        "stale": _t("corporate_record", "charter_amendment", status="corrected", name="c.htm"),
        "ambiguous": {**_t("contract", "license", name="d.pdf"), "target_status": "ambiguous"},
        "unscored": {**_t("merger_agreement", None, name="e.htm"), "use_for_subclass": False},
        "unconfirmed": _t("corporate_record", "indenture", class_ok=False, name="f.htm"),
        "confirmed": _t("corporate_record", "indenture", class_ok=False, name="g.htm",
                        evidence=["title line confirms corporate_record"]),
    }
    current = {
        "a.pdf": {"class": "contract", "subclass": "license", "source": cuad},
        "b.htm": {"class": "contract", "subclass": "license", "source": "sec_edgar"},
        "c.htm": {"class": "corporate_record", "subclass": "board_resolution", "source": "sec_edgar"},
        "d.pdf": {"class": "contract", "subclass": "license", "source": cuad},
        "e.htm": {"class": "merger_agreement", "subclass": "other", "source": "maud"},
        "f.htm": {"class": "corporate_record", "subclass": "indenture", "source": "sec_edgar"},
        "g.htm": {"class": "corporate_record", "subclass": "indenture", "source": "sec_edgar"},
    }
    kept, dropped = csp.prime_targets(targets, current, {"confirmed": "INDENTURE\nbetween A and B"})
    assert set(kept) == {"ok", "confirmed"}
    assert dropped == {"class error with an unconfirmed label": 1,
                       "class or subclass not scored": 1,
                       "contract subclass from the EX-10 exhibit-title heuristic": 1,
                       "status ambiguous": 1,
                       "target disagrees with the published label": 1}


def test_current_labels_normalize_cuad_folders(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    (tmp_path / "train").mkdir()
    pq.write_table(pa.Table.from_pylist([
        {"filename": "x.pdf", "expected": "contract", "expected_subclass": "Joint Venture _ Filing",
         "annotation_source": "theatticusproject/cuad"},
        {"filename": "y.txt", "expected": "correspondence", "expected_subclass": "memo",
         "annotation_source": "enron"}]), tmp_path / "train" / "train-0.parquet")
    labels = csp.current_labels(tmp_path)
    assert labels["x.pdf"]["subclass"] == "joint_venture" and labels["y.txt"]["subclass"] == "memo"


def test_prime_needs_a_verified_corporate_subclass_and_no_reviewer_dispute():
    def corp(sub, name, review=None):
        return {**_t("corporate_record", sub, name=name), "reviewer_evidence": review}
    agree = {"doc_type": "corporate_record", "doc_subclass": "board_resolution", "p": 0.95}
    targets = {
        "title": corp("bylaws", "1.htm"),
        "review": corp("board_resolution", "2.htm", agree),
        "unverified": corp("officer_certificate", "3.htm"),
        "title_other": corp("bylaws", "4.htm", {**agree, "doc_subclass": "bylaws"}),
        "low_p": corp("board_resolution", "5.htm", {**agree, "p": 0.5}),
        "disputed_memo": {**_t("correspondence", "memo", name="6.txt"),
                          "reviewer_evidence": {"doc_type": "correspondence", "doc_subclass": "letter", "p": 1.0}},
    }
    current = {x["filename"]: {"class": x["target_doc_class"], "subclass": x["target_subclass"], "source": "s"}
               for x in targets.values()}
    texts = {"title": "BYLAWS OF ACME CORP", "title_other": "INDENTURE dated as of", "unverified": "Resolved, that"}
    kept, dropped = csp.prime_targets(targets, current, texts)
    assert set(kept) == {"title", "review"}
    assert dropped == {"corporate subclass disputed by the title line": 1,
                       "corporate subclass unverified (no title rule or reviewer confirms it)": 2,
                       "the reviewer disputes the label": 1}


def test_prime_revision_is_required_before_loading_labels(tmp_path, monkeypatch):
    import argparse
    import pytest

    directory = tmp_path / "data" / "parquet" / "ground_truth"
    directory.mkdir(parents=True)
    marker = directory.parent.parent / ".hub_revision"
    args = argparse.Namespace(name="baseline", split="train", prime=True, current_labels=directory)
    monkeypatch.setattr(csp, "_targets", lambda *a: {})

    def unexpected(*a):
        pytest.fail("labels must not be read or filtered before validating their revision")

    monkeypatch.setattr(csp, "current_labels", unexpected)
    monkeypatch.setattr(csp, "prime_targets", unexpected)
    with pytest.raises(SystemExit, match="marker missing"):
        csp._targets_for(args, tmp_path, {})
    for revision in ("", "unknown", "ccd040f6", "ccd040f6" + "0" * 32, "v9.3"):
        marker.write_text(revision + "\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="revision mismatch"):
            csp._targets_for(args, tmp_path, {})

    marker.write_text(csp.PRIME_LABELS_REVISION + "\n", encoding="utf-8")
    monkeypatch.setattr(csp, "current_labels", lambda path: {"published": {}})
    monkeypatch.setattr(csp, "prime_targets", lambda targets, labels, texts: (labels, {}))
    kept, quality = csp._targets_for(args, tmp_path, {})
    assert kept == {"published": {}}
    assert quality["prime"]["labels_revision"] == csp.PRIME_LABELS_REVISION


def test_score_requires_the_run_to_lock_rows_of_the_selected_sample(tmp_path, monkeypatch):
    import argparse
    import hashlib
    import json
    import pytest

    monkeypatch.setattr(csp, "repo_root", lambda: tmp_path)
    targets = {"a": _t("correspondence", "memo"), "b": _t("correspondence", "memo")}
    monkeypatch.setattr(csp, "_targets", lambda *a: targets)
    args = argparse.Namespace(name="baseline", split="train", prime=True, sample=True, run="new")
    dataset = csp._dataset_path(tmp_path, args)
    dataset.parent.mkdir(parents=True)
    rows = [{"id": "a", "doc_text": "one\u2028x"}, {"id": "b", "doc_text": "two"}]
    dataset.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
    selection = csp._selection_path(dataset)
    selection.write_text(json.dumps({"dataset_sha256": sha, "name": "baseline", "chosen": {"a": "control", "b": "control"}}),
                         encoding="utf-8")
    run_dir = tmp_path / "data" / "runtime" / "runs" / args.run
    run_dir.mkdir(parents=True)
    locked = run_dir / "dataset.jsonl"
    report = tmp_path / "reports" / "sorter-handoff" / "new.compare.json"
    monkeypatch.setattr(csp, "_run_answers", lambda *a: pytest.fail("answers read before the dataset check"))

    with pytest.raises(SystemExit, match="drawn from --name baseline"):
        csp.cmd_score(argparse.Namespace(**{**vars(args), "name": "other-pass"}))
    with pytest.raises(SystemExit, match="locked dataset missing"):
        csp.cmd_score(args)
    # The lock re-serializes rows (its own sha256 differs from the sample file's), so rows are compared parsed.
    for bad in ([{"id": "a", "doc_text": "one\u2028x changed"}], [{"id": "c", "doc_text": "three"}]):
        locked.write_text("".join(json.dumps(r) + "\n" for r in bad), encoding="utf-8")
        with pytest.raises(SystemExit, match="not rows of the selected sample"):
            csp.cmd_score(args)
    locked.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")  # a subset (a smoke) is fine
    dataset.write_text(dataset.read_text(encoding="utf-8") + json.dumps({"id": "z"}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="changed since the selection"):
        csp.cmd_score(args)
    assert not report.exists()

    dataset.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(csp, "_run_answers", lambda *a: {"a": {"doc_type": "correspondence", "doc_subclass": "memo"}})
    assert csp.cmd_score(args) == 0
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["dataset_sha256"] == sha
    assert result["locked_rows"] == 1
    assert result["totals"]["class_still_right"] == 1 and result["totals"]["no_answer"] == 1
    assert "class_broken" not in result["totals"]  # "b" was outside the smoke's lock

    locked.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert csp.cmd_score(args) == 0  # the run locked "b" and failed it: it broke a right answer
    totals = json.loads(report.read_text(encoding="utf-8"))["totals"]
    assert totals["class_broken"] == 1 and totals["subclass_broken"] == 1 and totals["no_answer"] == 1
