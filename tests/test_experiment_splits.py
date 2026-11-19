"""Runbook split builder (R00): synthetic corpus, no Hub access."""

from __future__ import annotations

import json

import pytest

from mailroom_sandbox import experiment_splits as es

FAMILIES = {
    "min_scored": 30,
    "min_pooled_per_set": 4,
    "families": {"alpha": {"small_pair": ["s3", "s4"]}},
}
SIZES = {"dev": 90, "calibration": 40, "heldout": 90, "pool": 20}


def _corpus(tuned: set[str] | None = None) -> list[es.Doc]:
    tuned = tuned or set()
    plan = [("alpha", "s1", 60), ("alpha", "s2", 34), ("alpha", "s3", 8), ("alpha", "s4", 6),
            ("beta", "t1", 72), ("beta", "t2", 60)]
    docs = []
    k = 0
    for cls, sub, n in plan:
        for i in range(n):
            did = f"DOC-{k:04d}"
            links = [f"doc:{did}"]
            if k in (10, 11, 12):  # one thread of three
                links.append("msg:thread-a")
            docs.append(es.Doc(
                id=did, doc_class=cls, subclass=sub, band=es.BANDS[i % 3],
                source_corpus=f"src-{cls}", annotation_method="source_native",
                hf_split="test" if k % 9 == 0 else "train", tuned=did in tuned, links=links,
            ))
            k += 1
    return docs


def _ids(path):
    return es.read_id_file(path)


def test_units_promote_large_subclasses_and_pool_small_families():
    docs = _corpus()
    units = es.assign_units(docs, FAMILIES)
    assert units["alpha/s1"]["kind"] == "subclass"
    assert units["alpha/s2"]["kind"] == "subclass"
    assert units["alpha/family:small_pair"]["kind"] == "pooled"  # 14 docs < 30
    assert units["alpha/family:small_pair"]["subclasses"] == ["s3", "s4"]


def test_quota_rule_matches_design():
    assert es.unit_quota("subclass", 120, 10) == 20
    assert es.unit_quota("subclass", 34, 10) == 17
    assert es.unit_quota("subclass", 30, 10) == 15
    assert es.unit_quota("pooled", 14, 10) == 7


def test_components_join_threads_and_shared_text():
    docs = _corpus()
    docs[0].links.append("text:same")
    docs[50].links.append("text:same")
    comps = es.build_components(docs)
    sizes = sorted(len(m) for m in comps.values() if len(m) > 1)
    assert sizes == [2, 3]
    assert docs[10].component == docs[12].component == "DOC-0010"


def test_build_is_exact_deterministic_and_keeps_components_together(tmp_path):
    docs = _corpus()
    a = es.build_split(docs, FAMILIES, seed=7, sizes=SIZES)
    b = es.build_split(_corpus(), FAMILIES, seed=7, sizes=SIZES)
    assert a.assignment == b.assignment
    from collections import Counter

    assert Counter(a.assignment.values()) == Counter(SIZES)
    assert len({a.assignment[f"DOC-{i:04d}"] for i in (10, 11, 12)}) == 1
    assert set(a.looks["dev-look1"]) <= set(a.looks["dev-look2"])
    assert set(a.looks["dev-look2"]) <= {i for i, s in a.assignment.items() if s == "dev"}


def test_quotas_larger_than_a_set_refuse():
    with pytest.raises(es.SplitError, match="quotas need"):
        es.build_split(_corpus(), FAMILIES, seed=1, sizes={"dev": 70, "calibration": 60, "heldout": 70, "pool": 40})


def test_heldout_prefers_never_tuned_documents():
    tuned = {f"DOC-{i:04d}" for i in range(0, 300, 9)[:5]}
    docs = _corpus(tuned)
    res = es.build_split(docs, FAMILIES, seed=3, sizes=SIZES)
    never = [d.id for d in docs if d.never_tuned]
    assert all(res.assignment[i] == "heldout" for i in never)


def test_size_mismatch_refuses():
    with pytest.raises(es.SplitError, match="sum to"):
        es.build_split(_corpus(), FAMILIES, seed=1, sizes={**SIZES, "pool": 1})


def _written(tmp_path, monkeypatch):
    fam = tmp_path / "families.yaml"
    fam.write_text(json.dumps(FAMILIES))
    monkeypatch.setattr(es, "REPO_ROOT", tmp_path)
    docs = _corpus()
    res = es.build_split(docs, FAMILIES, seed=5, sizes=SIZES)
    out = tmp_path / "split"
    manifest = es.write_split(res, out, seed=5, revision="r" * 40, families_path=fam, exposure_path=None)
    return out, manifest


def test_written_files_select_each_set_and_audit_passes(tmp_path, monkeypatch):
    out, manifest = _written(tmp_path, monkeypatch)
    all_ids = {d.id for d in _corpus()}
    for s in es.SETS:
        assert _ids(out / f"{s}.ids") | _ids(out / f"{s}.exclude.ids") == all_ids
        assert not _ids(out / f"{s}.ids") & _ids(out / f"{s}.exclude.ids")
    assert manifest["sizes"] == SIZES
    checks = es.audit(out, _corpus(), FAMILIES)
    failed = [c.name for c in checks if c.gate and not c.ok]
    assert failed == []


def test_audit_catches_tampering_and_leaks(tmp_path, monkeypatch):
    out, _ = _written(tmp_path, monkeypatch)
    dev = sorted(_ids(out / "dev.ids"))
    cal = sorted(_ids(out / "calibration.ids"))
    # move one dev doc into calibration without updating hashes
    (out / "calibration.ids").write_text("\n".join(cal + [dev[0]]) + "\n")
    names = {c.name: c for c in es.audit(out, _corpus(), FAMILIES)}
    assert not names["file hashes match manifest"].ok
    assert not names["sets disjoint"].ok


def test_load_cached_rows_explains_a_cold_cache(monkeypatch):
    import huggingface_hub

    def missing(*a, **k):
        raise FileNotFoundError("not cached")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", missing)
    with pytest.raises(es.SplitError, match="sandbox datasets pull"):
        es.load_cached_rows(revision="a" * 40)


def test_audit_catches_a_consistent_swap(tmp_path, monkeypatch):
    """Swap one dev and one calibration doc and re-hash every file: only the rebuild sees it."""
    out, _ = _written(tmp_path, monkeypatch)
    a = sorted(_ids(out / "dev.ids"))[0]
    b = sorted(_ids(out / "calibration.ids"))[0]
    swap = {a: b, b: a}
    for name in [p.name for p in out.glob("*.ids")]:
        ids = {swap.get(i, i) for i in _ids(out / name)}
        (out / name).write_text("\n".join(sorted(ids)) + "\n")
    rows = [json.loads(line) for line in (out / "assignments.jsonl").read_text().splitlines()]
    for r in rows:
        if r["id"] in swap:
            r["set"] = {"dev": "calibration", "calibration": "dev"}[r["set"]]
    (out / "assignments.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["files"] = {n: es._sha((out / n).read_bytes()) for n in manifest["files"]}
    (out / "manifest.json").write_text(json.dumps(manifest))
    names = {c.name: c for c in es.audit(out, _corpus(), FAMILIES)}
    assert names["file hashes match manifest"].ok
    assert not names["split reproduces from its seed and inputs"].ok


def test_audit_catches_a_changed_exposure_list(tmp_path, monkeypatch):
    fam = tmp_path / "families.yaml"
    fam.write_text(json.dumps(FAMILIES))
    exposure = tmp_path / "excluded-ids.txt"
    exposure.write_text("DOC-0001\n")
    monkeypatch.setattr(es, "REPO_ROOT", tmp_path)
    docs = _corpus({"DOC-0001"})
    res = es.build_split(docs, FAMILIES, seed=5, sizes=SIZES)
    out = tmp_path / "split"
    es.write_split(res, out, seed=5, revision="r" * 40, families_path=fam, exposure_path=exposure)
    exposure.write_text("DOC-0001\nDOC-0002\n")
    names = {c.name: c for c in es.audit(out, docs, FAMILIES)}
    assert not names["tuning exposure list unchanged since build"].ok


def test_heldout_prefers_untuned_train_over_tuned():
    tuned = {f"DOC-{i:04d}" for i in range(240) if i % 2}
    docs = _corpus(tuned)
    res = es.build_split(docs, FAMILIES, seed=3, sizes=SIZES)
    untuned_train_out = [d for d in docs if d.exposure_tier == 1 and res.assignment[d.id] != "heldout"]
    comps = es.build_components(docs)
    tuned_in = [d for d in docs if res.assignment[d.id] == "heldout"
                and max(m.exposure_tier for m in comps[d.component]) == 2]
    assert untuned_train_out and not tuned_in  # no tuning-exposed component while clean ones remain
    assert [d.exposure_tier for d in docs[:3]] == [0, 2, 1]


def test_build_refuses_when_a_leak_component_starves_a_quota():
    docs = _corpus()
    for d in docs:  # tie 30 of s2's 34 docs into one thread: dev cannot reach its quota
        if d.subclass == "s2" and int(d.id[4:]) < 90:
            d.links.append("msg:big-thread")
    with pytest.raises(es.SplitError, match="quotas not met"):
        es.build_split(docs, FAMILIES, seed=1, sizes=SIZES)


def test_correspondence_subjects_link_reply_threads():
    def row(i, subject, cls="correspondence"):
        return {"id": f"DOC-{i}", "expected_doc_class": cls, "expected_subclass": "email",
                "metadata": {"subject": subject}, "split": "train"}

    rows = [row(1, "Budget plan Q3"), row(2, "RE: Fwd:  budget plan q3"), row(3, "Hi"), row(4, "hi"),
            row(5, "Budget plan Q3", cls="contract")]
    docs = es.docs_from_rows(rows, set())
    comps = es.build_components(docs)
    comp = {d.id: d.component for d in docs}
    assert comp["DOC-1"] == comp["DOC-2"]
    assert comp["DOC-3"] != comp["DOC-4"]  # subjects under 4 chars are not a thread signal
    assert comp["DOC-5"] != comp["DOC-1"]  # only correspondence links by subject
    assert len(comps[comp["DOC-1"]]) == 2


def _resign(out, name):
    """Rewrite one file's manifest hash, as a careless hand edit would."""
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["files"][name] = es._sha((out / name).read_bytes())
    (out / "manifest.json").write_text(json.dumps(manifest))


def test_heldout_skips_a_never_tuned_doc_linked_to_a_tuned_one():
    docs = _corpus()
    docs[9].links.append("msg:thread-b")  # DOC-0009: never-tuned (test split)
    docs[1].links.append("msg:thread-b")  # DOC-0001: tuned below
    docs[1].tuned = True
    res = es.build_split(docs, FAMILIES, seed=3, sizes=SIZES)
    assert res.assignment["DOC-0009"] != "heldout" and res.assignment["DOC-0001"] != "heldout"


def test_a_missing_exposure_file_is_refused_not_read_as_empty(tmp_path):
    with pytest.raises(es.SplitError, match="does not exist"):
        es.read_id_file(tmp_path / "typo.txt", required=True)
    assert es.read_id_file(None, required=True) == set()


def test_identical_content_links_documents():
    rows = [{"id": "A", "expected_doc_class": "contract", "content_sha256": "f" * 64},
            {"id": "B", "expected_doc_class": "contract", "content_sha256": "f" * 64},
            {"id": "C", "expected_doc_class": "contract", "content_sha256": "0" * 64}]
    docs = es.docs_from_rows(rows, set())
    comps = es.build_components(docs)
    by = {d.id: d.component for d in docs}
    assert by["A"] == by["B"] != by["C"] and len(comps[by["A"]]) == 2


def test_audit_catches_an_edited_ledger_and_look_complement(tmp_path, monkeypatch):
    out, _ = _written(tmp_path, monkeypatch)
    rows = [json.loads(line) for line in (out / "assignments.jsonl").read_text().splitlines()]
    rows[0]["tuned"] = not rows[0]["tuned"]
    (out / "assignments.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    _resign(out, "assignments.jsonl")
    (out / "dev-look1.exclude.ids").write_text("# emptied\n")
    _resign(out, "dev-look1.exclude.ids")
    names = {c.name: c for c in es.audit(out, _corpus(), FAMILIES)}
    assert names["file hashes match manifest"].ok
    assert not names["assignments.jsonl matches the rebuild"].ok
    assert not names["dev-look1.exclude.ids is the exact complement"].ok


@pytest.mark.parametrize("name", ["../escape", "/abs", "a/b", "..", ""])
def test_split_name_rejects_paths(name):
    import argparse

    from mailroom_sandbox import splits_cli

    with pytest.raises(argparse.ArgumentTypeError):
        splits_cli._split_name(name)
    assert splits_cli._split_name("runbook-v2.1") == "runbook-v2.1"


def test_cli_refuses_a_missing_exposure_list(tmp_path, capsys):
    from mailroom_sandbox.cli import main

    assert main(["splits", "build", "--dry-run", "--exposure", str(tmp_path / "typo.txt")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_show_prints_the_frozen_revision(capsys):
    from mailroom_sandbox.cli import main

    assert main(["splits", "show", "--set", "heldout"]) == 0
    manifest = json.loads((es.current_split_dir() / "manifest.json").read_text())
    assert f"revision: {manifest['dataset']['revision']}" in capsys.readouterr().out


def test_class_gates_keep_a_short_class_whole_in_calibration():
    """Decision 6: a class that cannot fund its own gate gives its pool share to calibration."""
    from collections import Counter

    fams = {**FAMILIES, "calibration": {"target_error": 0.05, "confidence": 0.95}}  # needs 59 accepts
    docs = _corpus() + [es.Doc(id=f"DOC-9{i:03d}", doc_class="beta", subclass="t1", band=es.BANDS[i % 3],
                               source_corpus="src-beta", annotation_method="source_native", hf_split="train",
                               tuned=False, links=[f"doc:DOC-9{i:03d}"]) for i in range(80)]
    sizes = {**SIZES, "calibration": 100, "pool": 40}
    res = es.build_split(docs, fams, seed=7, sizes=sizes)
    by = Counter((d.doc_class, res.assignment[d.id]) for d in docs)
    assert by[("alpha", "pool")] == 0 and by[("alpha", "calibration")] > 0  # alpha is short of 59
    assert by[("beta", "pool")] == 40
    plain = es.build_split(docs, FAMILIES, seed=7, sizes=sizes)  # no calibration block: old mix
    assert Counter(d.doc_class for d in docs if plain.assignment[d.id] == "pool")["alpha"] > 0


def _audit_of(res, docs, fams, tmp_path, monkeypatch):
    fam = tmp_path / "families.yaml"
    fam.write_text(json.dumps(fams))
    monkeypatch.setattr(es, "REPO_ROOT", tmp_path)
    out = tmp_path / "split"
    es.write_split(res, out, seed=7, revision="r" * 40, families_path=fam, exposure_path=None)
    return es.audit(out, docs, fams)


def test_class_gate_audit_flags_a_short_class_left_in_the_pool(tmp_path, monkeypatch):
    fams = {**FAMILIES, "calibration": {"target_error": 0.05, "confidence": 0.95}}
    docs = _corpus()
    res = es.build_split(docs, FAMILIES, seed=7, sizes=SIZES)  # built without the gate rule
    checks = {c.name: c for c in _audit_of(res, docs, fams, tmp_path, monkeypatch)}
    (name,) = [n for n in checks if n.startswith("classes short of")]
    assert not checks[name].ok and "in pool" in checks[name].detail


def _relabel(docs, method_of):
    import dataclasses

    return [dataclasses.replace(d, annotation_method=method_of(d)) for d in docs]


def test_a_method_constant_within_class_and_source_leaves_the_draw_unchanged():
    """Why runbook-v1 (v9.1: one annotation method per class) still rebuilds byte for byte
    after the method joined the draw strata: such a corpus partitions as before."""
    base = es.build_split(_corpus(), FAMILIES, seed=5, sizes=SIZES)
    other = es.build_split(_relabel(_corpus(), lambda d: f"m-{d.doc_class}"), FAMILIES, seed=5, sizes=SIZES)
    assert other.assignment == base.assignment and other.looks == base.looks


def _method_follows_subclass(d):
    # v9.3-like: the large subclasses are mostly LLM-labelled (7 in 8), the smaller ones mostly
    # not (4 in 5). Moduli stay off the fixture's 9-cycle of test-split documents, which the
    # held-out tier order would otherwise alias with the method.
    n = int(d.id.split("-")[1])
    if d.subclass in ("s1", "t1"):
        return "llm" if n % 8 else "human"
    return "human" if n % 5 else "llm"


def test_the_mix_gate_reads_the_unit_adjusted_corpus(tmp_path, monkeypatch):
    """Quotas oversample small units, so a method that follows the subclass moves the plain
    within-class mix by design (informational); the gate tests the draw inside each unit."""
    docs = _relabel(_corpus(), _method_follows_subclass)
    res = es.build_split(docs, FAMILIES, seed=5, sizes=SIZES)
    checks = {c.name: c for c in _audit_of(res, docs, FAMILIES, tmp_path, monkeypatch)}
    gate = checks["annotation_method mix within ±5 pts of the unit-adjusted corpus (dev/held-out, within class)"]
    plain = checks["annotation_method mix vs corpus (dev/held-out, within class, informational)"]
    assert gate.gate and gate.ok, gate.detail
    gap = float(gate.detail.split()[2])
    assert not plain.gate and float(plain.detail.split()[2]) > es.MIX_TOLERANCE_PTS > gap


def test_the_unit_adjusted_gate_still_catches_a_biased_draw(tmp_path, monkeypatch):
    docs = _relabel(_corpus(), _method_follows_subclass)
    res = es.build_split(docs, FAMILIES, seed=5, sizes=SIZES)
    dev = {i for i, s in res.assignment.items() if s == "dev"}
    # relabel dev's alpha/s1 documents only: within their unit the draw is now all "human"
    biased = _relabel(docs, lambda d: "human" if d.id in dev and d.subclass == "s1" else d.annotation_method)
    checks = {c.name: c for c in _audit_of(res, biased, FAMILIES, tmp_path, monkeypatch)}
    gate = checks["annotation_method mix within ±5 pts of the unit-adjusted corpus (dev/held-out, within class)"]
    assert not gate.ok, gate.detail


def test_audit_and_show_default_to_the_manifest_inputs(tmp_path, monkeypatch):
    """A split built with its own exposure list (runbook-v2) is audited against that list,
    not the production default."""
    import argparse

    from mailroom_sandbox import splits_cli

    monkeypatch.setattr(es, "REPO_ROOT", tmp_path)
    manifest = {"inputs": {"families": {"path": "config/splits/families.yaml"},
                           "exposure": {"path": "config/splits/own-exposure.txt"}}}
    args = argparse.Namespace(families=None, exposure=None)
    splits_cli._manifest_inputs(args, manifest)
    assert args.exposure == str(tmp_path / "config/splits/own-exposure.txt")
    assert args.families == str(tmp_path / "config/splits/families.yaml")
    none = argparse.Namespace(families=None, exposure=None)
    splits_cli._manifest_inputs(none, {"inputs": {"exposure": {"path": None}}})
    assert none.exposure == ""  # built with no list: audited with none
    given = argparse.Namespace(families="f.yaml", exposure="x.txt")
    splits_cli._manifest_inputs(given, manifest)
    assert (given.families, given.exposure) == ("f.yaml", "x.txt")


def _fake_split(root, name, revision):
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"dataset": {"revision": revision}}))
    return d


def test_a_run_finds_its_split_by_exclude_file_then_revision(tmp_path):
    from mailroom_sandbox.job.spec import FAMILY_HF_DATA_REVISION, FAMILY_HF_REVISION, FAMILY_HF_TAG

    v1 = _fake_split(tmp_path, "runbook-v1", "a" * 40)
    v2 = _fake_split(tmp_path, "runbook-v2", FAMILY_HF_REVISION)
    assert es.split_dirs(tmp_path) == [v1, v2]
    for spelling in (FAMILY_HF_REVISION, FAMILY_HF_DATA_REVISION, FAMILY_HF_TAG):
        assert es.split_dir_for_revision(spelling, tmp_path) == v2
    assert es.split_dir_of_spec({"exclude_ids_file": "config/splits/runbook-v1/dev.exclude.ids",
                                 "revision": FAMILY_HF_REVISION}, tmp_path) == v1  # the file wins
    assert es.split_dir_of_spec({"revision": "a" * 40}, tmp_path) == v1
    assert es.split_dir_of_spec({"revision": "b" * 40}, tmp_path) is None
    assert es.split_dir_of_spec({}, tmp_path) is None
    _fake_split(tmp_path, "runbook-v1b", "a" * 40)
    with pytest.raises(es.SplitError, match="2 committed splits"):
        es.split_dir_for_revision("a" * 40, tmp_path)
    assert es.split_dir_of_spec({"revision": "a" * 40}, tmp_path) is None  # ambiguous: not guessed


def test_the_committed_splits_and_the_current_one():
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION, LEGACY_FAMILY_HF_REVISIONS

    assert es.split_revision(es.current_split_dir()) == FAMILY_HF_REVISION
    assert es.split_revision(es.DEFAULT_OUT_ROOT / "runbook-v1") == LEGACY_FAMILY_HF_REVISIONS["v9.1"][0]
    v2 = json.loads((es.current_split_dir() / "manifest.json").read_text())
    v1 = json.loads((es.DEFAULT_OUT_ROOT / "runbook-v1" / "manifest.json").read_text())
    assert v2["inputs"]["exposure"]["path"] == "config/splits/runbook-v2-exposure.txt"
    assert v2["seed"] == v1["seed"] and v2["sizes"] == v1["sizes"]
    # runbook-v1's spent look stays out of the new held-out set
    exposure = es.read_id_file(es.REPO_ROOT / v2["inputs"]["exposure"]["path"])
    assert es.read_id_file(es.DEFAULT_OUT_ROOT / "runbook-v1" / "dev-look1.ids") <= exposure
    assert not exposure & es.read_id_file(es.current_split_dir() / "heldout.ids")


def test_the_committed_exposure_list_is_current():
    import subprocess
    import sys

    script = es.REPO_ROOT / "scripts" / "build_split_exposure.py"
    text = script.read_text(encoding="utf-8")
    cmd = text[text.index("python scripts/build_split_exposure.py"):text.index("--out config/splits/runbook-v2-exposure.txt")]
    argv = [a for a in cmd.split()[2:] if a.strip("\\")]
    proc = subprocess.run([sys.executable, str(script), *argv, "--out", "config/splits/runbook-v2-exposure.txt",
                           "--check"], cwd=es.REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_rb1_configs_draw_whole_sets_of_the_split_they_name():
    """A per-class R03 config must take every dev document of its class in its split (a stale
    count after a split change would drop or pad documents silently), and each set-sized config
    its whole set."""
    from collections import Counter

    from mailroom_sandbox.job.spec import load_run_spec

    runs = es.REPO_ROOT / "config" / "runs"
    checked = 0
    for path in sorted(runs.glob("rb1-*.yaml")):
        spec = load_run_spec(path)
        exclude = str(spec.dataset.exclude_ids_file or "")
        if "config/splits/" not in exclude:
            continue
        split_dir = es.split_dir_of_spec({"exclude_ids_file": exclude}, es.DEFAULT_OUT_ROOT)
        assert split_dir is not None, path.name
        assert es.split_revision(split_dir) == spec.dataset.revision, path.name
        set_name = exclude.rsplit("/", 1)[1].removesuffix(".exclude.ids")
        ids = es.read_id_file(split_dir / f"{set_name}.ids")
        rows = [json.loads(line) for line in (split_dir / "assignments.jsonl").read_text().splitlines() if line]
        per_class = Counter(r["doc_class"] for r in rows if r["id"] in ids)
        strata = list((spec.dataset.strata or {}).get("buckets") or [])
        if path.stem.startswith("rb1-r03-") and len(strata) == 1:
            want = per_class[strata[0]["doc_class"]]
            assert strata[0]["count"] == want == spec.dataset.limit, (path.name, strata[0]["count"], want)
            checked += 1
        elif not strata and spec.dataset.limit and spec.dataset.limit >= 300:
            assert spec.dataset.limit == len(ids), (path.name, spec.dataset.limit, len(ids))
            checked += 1
    assert checked >= 9


def test_current_split_excludes_every_formcal_draw1_document_from_heldout():
    used = es.read_id_file(es.REPO_ROOT / "config/splits/rb1-r13b/formcal-draw1.ids", required=True)
    exposed = es.read_id_file(es.REPO_ROOT / "config/splits/runbook-v2-exposure.txt", required=True)
    held = es.read_id_file(es.current_split_dir() / "heldout.ids", required=True)
    assert len(used) == 50
    assert used <= exposed
    assert used.isdisjoint(held)


def test_spent_formcal_draw1_keeps_its_v91_config():
    from mailroom_sandbox.job.spec import LEGACY_FAMILY_HF_REVISIONS, load_run_spec

    spec = load_run_spec(es.REPO_ROOT / "config/runs/rb1-r13b-formcal-intact-decision-luna-v4.0.1.yaml")
    assert spec.dataset.revision == LEGACY_FAMILY_HF_REVISIONS["v9.1"][0]
    assert "runbook-v1/calibration.exclude.ids" in str(spec.dataset.exclude_ids_file)
