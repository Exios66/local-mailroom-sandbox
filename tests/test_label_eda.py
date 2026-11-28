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


def _staged_cut_pulled() -> bool:
    """The production slices' staged cut is pulled (the draw and the contract count overlay it)."""
    from mailroom_sandbox import staged_overlay as so

    version = eda.production_dataset().staged_overlay
    return not version or so.cut_dir(version).is_dir()


def test_slice_ids_match_the_production_draw():
    cache = Path(repo_root() / "data/cache/Lucius-Morningstar__mailroom-dataset__ff4ca546d434/ground_truth_all.jsonl")
    if not cache.is_file():
        pytest.skip("cached ground_truth_all.jsonl not present")
    if not _staged_cut_pulled():
        pytest.skip("the production slices' staged cut is not pulled")
    ids = eda.slice_ids("slice-0100")
    assert len(ids) == len(set(ids)) == 100
    assert set(ids) < set(eda.slice_ids("slice-0250"))


def test_an_empty_selection_selects_nothing(tmp_path, capsys):
    assert eda.catalog_records(doc_ids=frozenset()) == []
    assert eda.interim_records(fields=frozenset()) == []
    cli = _cli()
    empty = tmp_path / "ids.txt"
    empty.write_text("", encoding="utf-8")
    out = tmp_path / "rows.json"
    assert cli.main(["rows", "--ids-file", str(empty), "--format", "json", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == []


def test_raw_stores_honour_split_and_refuse_cell_filters(labels, tmp_path, capsys):
    cli = _cli()
    out = tmp_path / "cat.json"
    assert cli.main(["catalog", "--split", "dev", "--class", "corporate_record", "--format", "json",
                     "--out", str(out)]) == 0
    recs = json.loads(out.read_text(encoding="utf-8"))
    assert recs and all(labels.docs[r["doc_id"]].split == "dev" for r in recs)
    assert cli.main(["interim", "--tier", "gate"]) == 2
    assert "--tier" in capsys.readouterr().err


def test_out_is_never_truncated_and_csv_needs_rows(tmp_path, capsys):
    cli = _cli()
    out = tmp_path / "rows.txt"
    assert cli.main(["rows", "--class", "corporate_record", "--field", "trustee", "--limit", "2",
                     "--out", str(out)]) == 0
    n = len(eda.select(eda.load(), eda.Filter(doc_class="corporate_record", fields=frozenset({"trustee"}))))
    assert n > 2 and len(out.read_text(encoding="utf-8").splitlines()) == n + 2  # header, rule, rows
    assert cli.main(["focus", "--format", "csv"]) == 2
    assert "table or json" in capsys.readouterr().err


def test_focus_counts_gated_contracts_as_the_production_draw_does(labels):
    out = eda.focus(labels, eda.Filter(doc_class="contract"))
    if not eda.cache_path().is_file() or not _staged_cut_pulled():
        assert out["unit_class_count"].startswith("skipped")
        return
    from mailroom_sandbox.corpus import apply_label_overlays
    from mailroom_sandbox.job.gate import labelled_count

    ds = eda.production_dataset()
    raw = [r for r in eda._read_jsonl(eda.cache_path()) if str(r.get("id")) in labels.docs]
    overlaid, _ = apply_label_overlays(raw, {"source": "local"}, interim=bool(ds.interim_labels),
                                       near_gold=bool(ds.near_gold_labels), staged=ds.staged_overlay)
    rows = {r["id"]: r for r in overlaid}
    listed = out["1_unscorable_docs"]
    contracts = [i for i, d in labels.docs.items() if d.doc_class == "contract" and i in rows]
    assert contracts and all(d["doc_class"] == "contract" for d in listed)
    # exactly the contracts the draw cannot score; a CUAD-empty one counts its overlaid field labels
    assert {d["doc_id"] for d in listed} == {i for i in contracts
                                             if labelled_count(rows[i], "contract") < labels.min_labelled}
    assert all(labelled_count(rows[d["doc_id"]], "contract") == d["gate_labelled"] for d in listed)


def test_slice_ids_draws_with_the_slices_own_label_overlay(tmp_path, monkeypatch):
    """With task_gt_min_field_labels the draw counts a CUAD-empty contract's field labels on the
    overlaid row, so turning the overlay off would draw a different set than production."""
    import mailroom_sandbox.corpus as corpus
    from mailroom_sandbox.job.spec import load_run_spec

    cache = tmp_path / "ground_truth_all.jsonl"
    cache.write_text("", encoding="utf-8")
    monkeypatch.setattr(eda, "cache_path", lambda root=None, revision=None: cache)
    seen = {}

    def fake_prepare(ds, dest):
        seen["ds"] = ds
        Path(dest).write_text(json.dumps({"id": "DOC-a"}) + "\n", encoding="utf-8")

    monkeypatch.setattr(corpus, "prepare_subset", fake_prepare)
    assert eda.slice_ids("slice-0100") == ["DOC-a"]
    want = load_run_spec(eda.repo_root() / "config/runs/production/slice-0100.yaml").dataset
    ds = seen["ds"]
    assert (ds.provider, ds.local_path) == ("file", str(cache))
    assert (ds.staged_overlay, ds.interim_labels, ds.near_gold_labels) == (
        want.staged_overlay, want.interim_labels, want.near_gold_labels)
    assert ds.task_gt_min_field_labels == want.task_gt_min_field_labels


def test_focus_counts_a_contract_on_the_overlaid_row_as_the_draw_does(tmp_path, monkeypatch):
    import mailroom_sandbox.corpus as corpus
    import mailroom_sandbox.job.gate as gate

    cache = tmp_path / "ground_truth_all.jsonl"
    cache.write_text("".join(json.dumps({"id": i}) + "\n" for i in ("DOC-drawn", "DOC-short")), encoding="utf-8")
    monkeypatch.setattr(eda, "cache_path", lambda root=None, revision=None: cache)
    docs = {i: eda.Doc(i, "contract", "other", "other", "dev", 100) for i in ("DOC-drawn", "DOC-short")}
    labels = eda.Labels(docs=docs, cells=[], gated=("contract",), min_labelled=2)
    calls = {}

    def fake_overlay(rows, meta, *, interim, near_gold, staged=None):
        calls["staged"] = staged
        return [{**r, "overlaid": r["id"] == "DOC-drawn"} for r in rows], meta

    monkeypatch.setattr(corpus, "apply_label_overlays", fake_overlay)
    monkeypatch.setattr(gate, "labelled_count", lambda row, doc_class: 3 if row.get("overlaid") else 0)
    listed = eda.unit_unscorable(labels, eda.Filter())
    assert calls["staged"] == eda.production_dataset().staged_overlay
    assert [d["doc_id"] for d in listed] == ["DOC-short"]  # the overlay's field labels draw DOC-drawn

    def unpulled(*a, **k):
        from mailroom_sandbox.staged_overlay import StagedOverlayError
        raise StagedOverlayError("staged overlay 9.3.1-rc.10 is not pulled")

    monkeypatch.setattr(corpus, "apply_label_overlays", unpulled)
    assert eda.unit_unscorable(labels, eda.Filter()) is None
    assert eda.focus(labels, eda.Filter())["unit_class_count"].startswith("skipped")


def test_out_creates_its_directory(tmp_path):
    out = tmp_path / "gold" / "nested" / "open.json"
    assert _cli().main(["rows", "--class", "corporate_record", "--field", "trustee", "--format", "json",
                        "--out", str(out)]) == 0
    assert isinstance(json.loads(out.read_text(encoding="utf-8")), list)


def test_narrow_queue_keeps_one_line_per_document_with_exactly_its_open_fields():
    def cell(doc, f, presence):
        return eda.Cell(doc, "corporate_record", "indenture", "dev", f, "gate", presence, "", "", "", "", False, False)

    cells = [cell("DOC-a", "trustee", "unlabeled"), cell("DOC-a", "entity_name", "populated"),
             cell("DOC-a", "maturity_date", "disputed_unresolved"), cell("DOC-b", "trustee", "populated"),
             cell("DOC-c", "trustee", "unlabeled")]
    queue = [{"doc_id": d, "doc_class": "corporate_record", "filename": f"{d}.txt", "content_sha256": "x",
              "revision": "r", "subclass": "indenture", "fields": ["entity_name"]} for d in ("DOC-a", "DOC-b")]
    lines, info = eda.narrow_queue(queue, cells)
    assert lines == [{**queue[0], "fields": ["maturity_date", "trustee"]}]  # DOC-b has nothing open
    assert info == {"docs": 1, "fields": 2, "not_in_queue": ["DOC-c"]}


def test_queue_writes_the_narrowed_queue_as_jsonl(tmp_path, labels):
    open_cell = next(c for c in labels.cells if not c.labeled and c.tier == "gate")
    full = tmp_path / "queue.jsonl"
    full.write_text(json.dumps({"doc_id": open_cell.doc_id, "doc_class": open_cell.doc_class, "filename": "f",
                                "content_sha256": "x", "revision": "r", "subclass": open_cell.subclass,
                                "fields": []}) + "\n", encoding="utf-8")
    out = tmp_path / "gold" / "focus-queue.jsonl"
    cli = _cli()
    assert cli.main(["queue", "--queue", str(full), "--doc", open_cell.doc_id, "--out", str(out)]) == 0
    (line,) = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert open_cell.field in line["fields"] and line["filename"] == "f"
    assert cli.main(["queue", "--queue", str(full)]) == 2  # a queue needs --out


def test_an_unpulled_staged_cut_is_a_clean_error(monkeypatch, capsys):
    from mailroom_sandbox.staged_overlay import StagedOverlayError

    def unpulled(name, root=None):
        raise StagedOverlayError("staged overlay 9.3.1-rc.10 is not pulled")

    monkeypatch.setattr(eda, "slice_ids", unpulled)
    assert _cli().main(["summary", "--slice", "slice-0100"]) == 2
    assert "not pulled" in capsys.readouterr().err
