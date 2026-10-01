"""The plain-language reader report stays in sync with the cards and free of internal shorthand."""

from __future__ import annotations

import json
import re

from mailroom_sandbox.job import grid_master, grid_reader


def test_reader_md_is_current():
    paths = grid_reader.reader_paths()
    expected = grid_reader.render_reader_md(grid_master.collect_master())
    assert paths["md"].read_text(encoding="utf-8") == expected, "run: sandbox run card --master"


def test_reader_notebook_text_is_current_and_charts_are_rendered():
    nb = json.loads(grid_reader.reader_paths()["ipynb"].read_text(encoding="utf-8"))
    md_cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown"]
    report = grid_reader.render_reader_md(grid_master.collect_master())
    for text in md_cells:
        if not text.startswith("The charts below"):
            assert text in report
    pngs = [o for c in nb["cells"] for o in c.get("outputs", []) if "image/png" in o.get("data", {})]
    assert len(pngs) == 2


def test_reader_body_has_no_internal_shorthand():
    md = grid_reader.render_reader_md(grid_master.collect_master())
    body = md.split("## Run name cross-reference")[0]
    for pattern in (r"SAND-\d", r"×L4", r"\bC(8|32)\b", r"\bn=\d", "†", "posture", "specialist"):
        assert not re.search(pattern, body), pattern
    assert "No American Family Insurance data was used or shared." in body
    assert "| **All runs** | 1,050 |" in md
