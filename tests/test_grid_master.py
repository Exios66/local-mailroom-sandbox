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
            if shape == "1L4" and card.name.startswith("grid-50-"):
                continue  # real SAND-39 cells; the fixture controls whether SAND-39 is present
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
    assert "identical 250 documents" in md
    assert "SAND-39 pending" not in md


def test_master_ignores_legacy_cells(tmp_path):
    repo = _seed(tmp_path, False)
    legacy = SAND37 / "2L4" / "contracts" / "grid-50-contracts-specialist-awq-2l4-rerun.card.json"
    data = json.loads(legacy.read_text())
    data["run_id"] = "grid-50-contracts-specialist-awq-2l4"  # superseded legacy id
    (repo / "reports/SAND-37/2L4/contracts/legacy.card.json").write_text(json.dumps(data))
    cards = grid_master.collect_master(repo)["cards"]["s37-2l4-n50"]
    assert cards["contracts"]["run_id"] == "grid-50-contracts-specialist-awq-2l4-rerun"


def test_sand40_column_is_pending_with_the_optimized_merger_mark():
    md = grid_master.render_master_md(grid_master.collect_master())
    assert "| SAND-40 | 2×L4 C32 n=100 | 2 | 32 | 100 (merger 50†) | pending |" in md
    assert "pending†" in md


def test_merger_settings_table_shows_what_the_dagger_changes():
    md = grid_master.render_appendix_md(grid_master.collect_master())
    assert "## Merger † settings" in md
    assert "| Serving window | 32,768 tokens on 2×L4 | 32,768 tokens on 2×L4 |" in md
    assert "| **Input** | head + tail, 30,000 chars (rest of the agreement unread) | **whole agreement, chunked: 47,000-char" in md
    assert "**`merger_agreement_specialist_maud_v1`**" in md
    assert "| Result | MAUD accuracy 0.035, coverage 23%, 46/50 ok" in md


def test_committed_master_card_is_current():
    """Committed master + appendix must match a fresh render (regenerate with `sandbox run card --master`)."""
    committed = (SAND37 / f"{grid_master.MASTER_STEM}.md").read_text(encoding="utf-8")
    assert committed == grid_master.render_master_md(grid_master.collect_master())
    appendix = (SAND37 / f"{grid_master.APPENDIX_STEM}.md").read_text(encoding="utf-8")
    assert appendix == grid_master.render_appendix_md(grid_master.collect_master())


def test_master_stays_executive_length():
    """The master card is a two-page executive summary; detail lives in the appendix."""
    md = grid_master.render_master_md(grid_master.collect_master())
    assert len(md.splitlines()) <= grid_master.EXECUTIVE_MAX_LINES
    for heading in (
        "## Per-cell detail",
        "## Clause scoring detail",
        "## Engine telemetry",
        "## Run conditions by specialist",
        "## SAND-40 validation probes",
        "## Figures: posture comparison",
        "## Appendix: posture dashboards",
    ):
        assert heading not in md
    assert f"{grid_master.APPENDIX_STEM}.md" in md


def test_record_metered_round_trips(tmp_path):
    (tmp_path / "reports" / "SAND-37").mkdir(parents=True)
    grid_master.record_metered("SAND-39", 0.623, 0.0, "note", repo=tmp_path)
    data = json.loads((tmp_path / "reports/SAND-37/metered-costs.json").read_text())
    assert data["SAND-39"] == {"metered_usd": 0.62, "billed_usd": 0.0, "note": "note"}


def test_figures_embed_in_master_and_matched_panel_waits_for_sand39(tmp_path):
    from mailroom_sandbox.job import grid_figures

    before = grid_master.collect_master(_seed(tmp_path / "a", False))
    keys = [s["key"] for s in grid_figures.figure_specs(before)]
    assert "cmp-matched" not in keys and "posture-s39-1l4-n50" not in keys
    after = grid_master.collect_master(_seed(tmp_path / "b", True))
    specs = grid_figures.figure_specs(after)
    assert {"cmp-efficiency", "cmp-quality", "cmp-latency-cost", "cmp-matched", "posture-s39-1l4-n50"} <= {
        s["key"] for s in specs
    }
    md = grid_master.render_appendix_md(after)
    assert "](figures/cmp-matched.png)" in md
    assert "](2L4/figures/SAND-37-2xL4-C32-n50.png)" in md
    assert "](1L4/figures/SAND-39-1xL4-C8-n50.png)" in md


def test_write_master_renders_every_linked_figure(tmp_path):
    repo = _seed(tmp_path, True)
    paths = grid_master.write_master(repo)
    md = paths["appendix"].read_text()
    assert grid_master.APPENDIX_STEM in str(paths["appendix"])
    from mailroom_sandbox.job import grid_figures

    for spec in grid_figures.figure_specs(grid_master.collect_master(repo)):
        png = repo / "reports" / "SAND-37" / spec["path"]
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert f"]({spec['path']})" in md


def test_master_is_fully_detailed():
    md = grid_master.render_appendix_md(grid_master.collect_master())
    for heading in (
        "## Per-cell detail",
        "### SAND-37 1×L4 C8 n=20",
        "### SAND-39 1×L4 C8 n=50",
        "### SAND-37 2×L4 C32 n=50",
        "## Clause scoring detail",
        "## Engine telemetry (vLLM /metrics, this run's delta)",
        "## Run conditions by specialist",
        "## SAND-40 validation probes (n = 20, not pooled)",
    ):
        assert heading in md
    # contracts is labeled as what it is: CUAD presence F1 over labeled documents
    assert "| Contracts | CUAD presence F1: labeled-document mean (micro) |" in md
    assert "| SAND-37 2×L4 C32 n=50 | 40 of 49 ok |" in md


def test_probes_are_reported_matched_but_never_pooled():
    data = grid_master.collect_master()
    assert set(data["probes"]) == {"contracts", "merger_agreement"}
    assert all("probe" not in c["run_id"] for p in data["cards"].values() for c in p.values())
    md = grid_master.render_appendix_md(data)
    row = next(line for line in md.splitlines() if line.startswith("| Merger Agreements | 65,536 |"))
    assert "| 18 | 0.114 | 0.033 | +0.081 (14 / 3) |" in row
