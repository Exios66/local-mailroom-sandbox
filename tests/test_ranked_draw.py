"""``dataset.draw: ranked`` — an exclusion-stable seeded draw for production slices (#305 review C1).

The default ``shuffle`` draw permutes the whole candidate list, so excluding one more document
reshuffles every bucket: a slice re-run after a tuning run draws different documents and the
nested slices stop nesting. ``ranked`` orders each bucket by a per-document hash, so removing ids
leaves the remaining documents in the same order.
"""
from __future__ import annotations

from mailroom_sandbox.corpus import select_rows
from mailroom_sandbox.job.spec import DatasetSpec


def _rows(n_per_class: int = 60) -> list[dict]:
    rows = []
    for cls in ("contract", "correspondence"):
        for i in range(n_per_class):
            rows.append({"id": f"DOC-{cls[:4]}-{i:03d}", "filename": f"{cls}/{i:03d}.txt",
                         "expected_doc_class": cls})
    return rows


def _draw(rows, counts, *, draw, exclude=None):
    strata = {"buckets": [{"doc_class": c, "count": n} for c, n in counts.items()]}
    picked = select_rows(rows, strata=strata, sample_seed=3302, limit=None,
                         exclude_ids=exclude, draw=draw)
    return {r["id"] for r in picked}


def test_ranked_draw_is_stable_when_unpicked_ids_are_excluded():
    rows = _rows()
    small = _draw(rows, {"contract": 5, "correspondence": 10}, draw="ranked")
    others = [r["id"] for r in rows if r["id"] not in small][:20]
    assert _draw(rows, {"contract": 5, "correspondence": 10}, draw="ranked", exclude=set(others)) == small


def test_ranked_draw_replaces_only_the_excluded_documents():
    rows = _rows()
    small = _draw(rows, {"contract": 5, "correspondence": 10}, draw="ranked")
    gone = sorted(small)[:3]
    after = _draw(rows, {"contract": 5, "correspondence": 10}, draw="ranked", exclude=set(gone))
    assert len(small & after) == len(small) - 3


def test_ranked_draws_nest():
    rows = _rows()
    small = _draw(rows, {"contract": 5, "correspondence": 10}, draw="ranked")
    big = _draw(rows, {"contract": 12, "correspondence": 25}, draw="ranked")
    assert small <= big


def test_shuffle_default_is_unchanged_and_not_exclusion_stable():
    """The default keeps every existing config's draw; it is the mode C1 found unstable."""
    rows = _rows()
    small = _draw(rows, {"contract": 5, "correspondence": 10}, draw="shuffle")
    others = [r["id"] for r in rows if r["id"] not in small][:20]
    assert _draw(rows, {"contract": 5, "correspondence": 10}, draw="shuffle", exclude=set(others)) != small
    strata = {"buckets": [{"doc_class": "contract", "count": 5}, {"doc_class": "correspondence", "count": 10}]}
    default = select_rows(rows, strata=strata, sample_seed=3302, limit=None)
    assert {r["id"] for r in default} == small


def test_draw_mode_is_hashed_only_when_ranked():
    base = DatasetSpec(provider="huggingface", sample_seed=1)
    ranked = DatasetSpec(provider="huggingface", sample_seed=1, draw="ranked")
    assert "draw" not in base.request_core()
    assert ranked.request_core()["draw"] == "ranked"
