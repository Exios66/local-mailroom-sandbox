"""G0 checkpoint script: every Phase 0 gate is listed, and missing evidence fails G0."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("check_g0", ROOT / "scripts/check_g0.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_committed_smoke_config_is_a_gate():
    g0 = _load()
    names = [name for name, _, _ in g0.gates()]
    smoke = sorted(p.stem.removeprefix("runbook-r01-smoke-") for p in (ROOT / "config/runs").glob("runbook-r01-smoke-*.yaml"))
    assert smoke, "R01 smoke configs are committed"
    assert [n.removeprefix("R01 smoke ") for n in names if n.startswith("R01 smoke ")] == smoke
    assert names[:2] == ["R00 split audit", "R00 schemas registry"]
    assert "R02 scorer hand-check" in names
    assert [n for n in names if n.startswith("R03")] == [f"R03 gold audit {x}" for x in g0.R03_LINEAGES]


def test_missing_evidence_is_reported_and_fails(tmp_path):
    g0 = _load()
    (tmp_path / "config/runs").mkdir(parents=True)
    (tmp_path / "config/runs/runbook-r01-smoke-m.yaml").write_text("x: 1\n")
    rows = {name: (cmd, missing) for name, cmd, missing in g0.gates(tmp_path)}
    assert rows["R01 smoke m"][0] is None and "served-m.jsonl" in rows["R01 smoke m"][1]
    assert rows["R03 gold audit sorter"][0] is None


def test_present_evidence_becomes_a_command(tmp_path):
    g0 = _load()
    (tmp_path / "config/runs").mkdir(parents=True)
    (tmp_path / "config/runs/runbook-r01-smoke-m.yaml").write_text("x: 1\n")
    (tmp_path / "data/runtime/r01").mkdir(parents=True)
    (tmp_path / "data/runtime/r01/served-m.jsonl").write_text("")
    (tmp_path / "data/labels/review").mkdir(parents=True)
    (tmp_path / "data/labels/review/r03-merger-audit.csv").write_text("")
    rows = {name: cmd for name, cmd, _ in g0.gates(tmp_path)}
    assert "--ledger" in rows["R01 smoke m"] and rows["R01 smoke m"][-1].endswith("runbook-r01-smoke-m.yaml")
    assert rows["R03 gold audit merger"][-2:] == ["--summarize", str(tmp_path / "data/labels/review/r03-merger-audit.csv")]
