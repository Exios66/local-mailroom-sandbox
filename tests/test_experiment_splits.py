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
                and min(m.exposure_tier for m in comps[d.component]) == 2]
    assert untuned_train_out and not tuned_in  # tuned only when linked to a less-exposed doc
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
