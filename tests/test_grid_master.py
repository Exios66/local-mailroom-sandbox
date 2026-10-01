"""SAND-039: the master card is generated from committed cards and fills in SAND-39."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mailroom_sandbox.job import grid_master
from mailroom_sandbox.paths import repo_root

SAND37 = repo_root() / "reports" / "SAND-37"


def _seed(tmp: Path, with_sand39: bool) -> Path:
    root = tmp / "reports" / "SAND-37"
    for shape in ("1L4", "2L4"):
        for card in (SAND37 / shape).glob("*/*.card.json"):
            dst = root / shape / card.parent.name / card.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(card, dst)
    if with_sand39:
        # Stand-in SAND-39 cells: the 2×L4 n=50 cards re-keyed to the 1×L4 C8 run ids.
        for card in (SAND37 / "2L4").glob("*/grid-50-*.card.json"):
            data = json.loads(card.read_text())
            stem = data["run_id"].replace("-2l4-rerun", "-1l4").replace("-2l4", "-1l4")
            data["run_id"] = stem
            data["conditions"].update(replicas=1, concurrency=8)
            dst = root / "1L4" / card.parent.name / f"{stem}.card.json"
            dst.write_text(json.dumps(data))
    return tmp


def test_sand39_pending_before_its_cells_exist(tmp_path):
    md = grid_master.render_master_md(grid_master.collect_master(_seed(tmp_path, False)))
    assert "| SAND-39 | 1×L4 C8 n=50 | 1 | 8 | 50 | pending |" in md
    assert "SAND-39 pending" in md
    assert "| SAND-37 | 2×L4 C32 n=50 | 2 | 32 | 50 | 5 of 5 cells |" in md


def test_sand39_populates_and_becomes_the_matched_sample_baseline(tmp_path):
    md = grid_master.render_master_md(grid_master.collect_master(_seed(tmp_path, True)))
    assert "| SAND-39 | 1×L4 C8 n=50 | 1 | 8 | 50 | 5 of 5 cells |" in md
    assert "identical 250 documents (SAND-39 1×L4 C8 n=50 vs SAND-37 2×L4 C32 n=50)" in md
    assert "SAND-39 pending" not in md


def test_master_ignores_legacy_cells(tmp_path):
    repo = _seed(tmp_path, False)
    legacy = SAND37 / "2L4" / "contracts" / "grid-50-contracts-specialist-awq-2l4-rerun.card.json"
    data = json.loads(legacy.read_text())
    data["run_id"] = "grid-50-contracts-specialist-awq-2l4"  # superseded legacy id
    (repo / "reports/SAND-37/2L4/contracts/legacy.card.json").write_text(json.dumps(data))
    cards = grid_master.collect_master(repo)["cards"]["s37-2l4-n50"]
    assert cards["contracts"]["run_id"] == "grid-50-contracts-specialist-awq-2l4-rerun"


def test_committed_master_card_is_current():
    """The committed master card must match a fresh render (regenerate with `sandbox run card --master`)."""
    committed = (SAND37 / f"{grid_master.MASTER_STEM}.md").read_text(encoding="utf-8")
    assert committed == grid_master.render_master_md(grid_master.collect_master())


def test_record_metered_round_trips(tmp_path):
    (tmp_path / "reports" / "SAND-37").mkdir(parents=True)
    grid_master.record_metered("SAND-39", 0.623, 0.0, "note", repo=tmp_path)
    data = json.loads((tmp_path / "reports/SAND-37/metered-costs.json").read_text())
    assert data["SAND-39"] == {"metered_usd": 0.62, "billed_usd": 0.0, "note": "note"}
