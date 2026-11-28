"""Label EDA tooling (``mailroom_sandbox.label_eda`` and ``scripts/label_eda.py``): offline and read-only."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from mailroom_sandbox import label_eda as eda
from mailroom_sandbox.paths import repo_root

_SCRIPT = repo_root() / "scripts" / "label_eda.py"


def _cli():
    spec = importlib.util.spec_from_file_location("label_eda_cli", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def labels() -> eda.Labels:
    return eda.load()


def test_every_release_cell_is_loaded_with_a_tier(labels):
    summary = json.loads((repo_root() / eda.RELEASE_DIR / f"{eda.STEM}_summary.json").read_text(encoding="utf-8"))
    assert len(labels.docs) == summary["documents"]
    assert len(labels.cells) == summary["label_cells_targeted"]
    assert {c.tier for c in labels.cells} <= set(eda.TIERS)
    assert sum(c.labeled for c in labels.cells) == summary["label_cells_labeled_repaired"]


def test_tiers_follow_what_production_scores(labels):
    gated = labels.gated
    assert eda.tier("corporate_record", "trustee", gated, subclass="indenture") == "gate"
    assert eda.tier("corporate_record", "keywords", gated) == "unscored"  # templated, the gate drops it
    na = eda.not_applicable()
    assert ("corporate_record", "indenture", "filing_number") in na
    assert eda.tier("corporate_record", "filing_number", gated, subclass="indenture", na=na) == "unscored"
    assert eda.tier("corporate_record", "filing_number", gated, subclass="charter_amendment", na=na) == "gate"
    assert eda.tier("contract", "governing_law", gated) == "unit"  # headlined and gated on CUAD
    assert eda.tier("merger_agreement", "acquirer", gated) == "reported"  # merger is never gated


def test_filters_compose(labels):
    flt = eda.Filter(doc_class="corporate_record", subclass="indenture", fields=frozenset({"trustee"}),
                     split="dev")
    cells = eda.select(labels, flt)
    assert cells and all((c.doc_class, c.subclass, c.field, c.split) == ("corporate_record", "indenture",
                                                                         "trustee", "dev") for c in cells)
    near = eda.select(labels, eda.Filter(source="near_gold_two_pass", fields=frozenset({"trustee"})))
    assert near and all("near_gold_two_pass" in c.agreeing_sources.split("|") for c in near)


def test_coverage_and_gaps_count_the_same_open_cells(labels):
    cells = eda.select(labels, eda.Filter(doc_class="corporate_record", split="dev", tiers=frozenset({"gate"})))
    cov = eda.coverage(cells, ["doc_class"])
    open_cells = cov[0]["unlabeled"] + cov[0]["disputed"]
    assert sum(g["open_cells"] for g in eda.gaps(cells, top=10_000)) == open_cells


def test_focus_leaves_unscored_cells_out_and_ranks_unscorable_documents_first(labels):
    out = eda.focus(labels, eda.Filter(split="dev"))
    assert list(out)[1] == "1_unscorable_docs"
    assert all(g["tier"] == "gate" for g in out["2_gate_gaps"])
    assert all(g["tier"] in ("unit", "reported") for g in out["3_suite_and_reported_gaps"])
    for doc in out["1_unscorable_docs"]:
        assert doc["gate_labelled"] < labels.min_labelled


def test_doc_card_joins_cells_and_raw_records(labels):
    doc_id = next(c.doc_id for c in labels.cells if c.field == "trustee" and c.chosen_source == "near_gold_two_pass")
    card = eda.doc_card(labels, doc_id)
    assert card["doc"]["doc_id"] == doc_id
    assert any(r["field"] == "trustee" for r in card["near_gold_records"])
    assert all("votes" in c for c in card["cells"])
    with pytest.raises(KeyError):
        eda.doc_card(labels, "DOC-not-a-document")


def test_cli_commands_run_offline(tmp_path, capsys):
    cli = _cli()
    assert cli.main(["summary", "--class", "corporate_record"]) == 0
    assert "coverage_by_class" in capsys.readouterr().out
    out = tmp_path / "rows.json"
    assert cli.main(["rows", "--class", "corporate_record", "--field", "trustee", "--presence", "populated",
                     "--votes", "--format", "json", "--out", str(out)]) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert rows and all(r["field"] == "trustee" and r["presence"] == "populated" and "votes" in r for r in rows)
    ids = tmp_path / "ids.txt"
    assert cli.main(["focus", "--split", "dev", "--ids-out", str(ids), "--format", "json",
                     "--out", str(tmp_path / "focus.json")]) == 0
    assert ids.read_text(encoding="utf-8").strip()
    assert cli.main(["coverage", "--by", "subclass", "--class", "corporate_record", "--format", "csv"]) == 0
    assert capsys.readouterr().out.startswith("wrote")  # the earlier --out runs; csv follows
    assert cli.main(["doc", "DOC-not-a-document"]) == 2


def test_slice_ids_match_the_production_draw():
    cache = Path(repo_root() / "data/cache/Lucius-Morningstar__mailroom-dataset__ff4ca546d434/ground_truth_all.jsonl")
    if not cache.is_file():
        pytest.skip("cached ground_truth_all.jsonl not present")
    ids = eda.slice_ids("slice-0100")
    assert len(ids) == len(set(ids)) == 100
    assert set(ids) < set(eda.slice_ids("slice-0250"))
