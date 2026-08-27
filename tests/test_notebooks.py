"""Headless, network-free execution of the demonstration notebooks."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = REPO_ROOT / "notebooks"
NETWORK_HINTS = re.compile(
    r"\b(requests\.|urllib|httpx|socket\.|openai\.OpenAI)\b",
    re.IGNORECASE,
)

NOTEBOOK_MARKERS = {
    "01_activate_overlay.ipynb": ("profiles:", "judge after surgical override:"),
    "02_fixtures_catalog.ipynb": ("n manifest rows:", "HONEST GAP:"),
    "03_isolated_agent_evals.ipynb": ("retired (no runners):", "judge  scores:"),
    "04_pipeline_and_scoring.ipynb": ("connected:", "extraction overall:"),
    "05_tracing_contract.ipynb": ("root name :", "public GT  :"),
    "06_prompts_matrix_log.ipynb": ("variants:", "n cells:"),
}


def _paths() -> list[Path]:
    return sorted(NOTEBOOKS.glob("0*.ipynb"))


def test_notebook_inventory_matches_readme():
    names = [p.name for p in _paths()]
    assert names == list(NOTEBOOK_MARKERS)
    readme = (NOTEBOOKS / "README.md").read_text(encoding="utf-8")
    for name in names:
        assert name in readme


@pytest.mark.parametrize("path", _paths(), ids=lambda p: p.name)
def test_notebook_is_valid_and_cwd_proof(path: Path):
    nb = nbformat.read(path, as_version=4)
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    assert len(nb.cells) >= 6
    assert len(code_cells) >= 4
    first = code_cells[0].source
    assert "find_repo_root" in first
    assert "pyproject.toml" in first
    for cell in code_cells:
        assert not NETWORK_HINTS.search(cell.source), cell.source[:200]


@pytest.mark.parametrize("path", _paths(), ids=lambda p: p.name)
def test_notebook_executes_headless_from_hostile_cwd(path: Path, tmp_path):
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    from nbclient import NotebookClient

    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(
        nb,
        timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(NOTEBOOKS)}},
    )
    client.execute()
    streams = [
        o.get("text", "")
        for c in nb.cells
        if c.cell_type == "code"
        for o in c.get("outputs") or []
        if o.get("output_type") == "stream"
    ]
    joined = "\n".join(streams)
    for marker in NOTEBOOK_MARKERS[path.name]:
        assert marker in joined, f"missing {marker!r} in {path.name}\n{joined[-1500:]}"
