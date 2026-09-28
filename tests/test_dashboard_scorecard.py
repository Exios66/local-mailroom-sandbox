"""Scorecard page stays in sync with the tracked reports it is built from."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "build_scorecard", ROOT / "reports" / "dashboard" / "build_scorecard.py"
)
build_scorecard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_scorecard)


def test_every_figure_resolves_and_cross_checks_pass():
    data = build_scorecard.build()
    assert len(data["provenance"]) > 100
    for p in data["provenance"]:
        assert (ROOT / "reports" / p["source"]).is_file(), p


def test_known_issues_still_reproduce():
    data = build_scorecard.build()
    assert {i["key"] for i in data["issues"]} == set(build_scorecard.KNOWN)


def test_committed_page_is_current():
    assert build_scorecard.main(["--check"]) == 0
