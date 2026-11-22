"""The committed notebooks under ``notebooks/``: structure always, execution when nbclient exists."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from mailroom_sandbox.paths import repo_root

NOTEBOOK_DIR = repo_root() / "notebooks"
NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
EXPECTED = [
    "01_offline_environment_setup.ipynb",
    "02_load_clean_prepare_data.ipynb",
    "03_offline_sandbox_smoke.ipynb",
    "04_experiment_log_explorer.ipynb",
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source(cell: dict) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src


def test_expected_notebooks_present():
    assert [p.name for p in NOTEBOOKS] == EXPECTED


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_notebook_structure(path):
    nb = _load(path)
    assert nb["nbformat"] == 4 and nb["nbformat_minor"] >= 5
    assert nb["metadata"]["kernelspec"]["name"] == "python3"
    cells = nb["cells"]
    ids = [c.get("id") for c in cells]
    assert all(ids) and len(set(ids)) == len(ids), "every cell needs a unique id"

    number = path.name[:2]
    assert cells[0]["cell_type"] == "markdown"
    assert re.match(rf"# {number} — \S", _source(cells[0])), "first cell is the '# NN — Title' heading"

    code_cells = [c for c in cells if c["cell_type"] == "code"]
    assert "bootstrap(" in _source(code_cells[0]), "first code cell must call notebook.bootstrap()"
    for cell in code_cells:
        assert cell.get("outputs") == [], f"{cell['id']}: commit notebooks without outputs"
        assert cell.get("execution_count") is None, f"{cell['id']}: clear execution counts"
        ast.parse(_source(cell))  # plain Python, no magics


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_notebooks_never_launch_paid_work(path):
    code = "\n".join(_source(c) for c in _load(path)["cells"] if c["cell_type"] == "code")
    for banned in ("mock=False", "--real", "--live", "run start", "modal deploy", "modal run", "subprocess"):
        assert banned not in code, f"{path.name} must stay offline/mock ({banned!r})"


def test_readme_lists_every_notebook():
    readme = (NOTEBOOK_DIR / "README.md").read_text(encoding="utf-8")
    for path in NOTEBOOKS:
        assert path.name in readme, f"notebooks/README.md does not link {path.name}"


def test_demo_renderer_executes_and_sanitizes_a_real_kernel(tmp_path, monkeypatch):
    """Hosted notebook CI verifies the renderer's actual kernel-manager integration."""
    import importlib.util
    import os
    import sys

    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    spec = importlib.util.spec_from_file_location("render_demos", repo_root() / "scripts/render_notebook_demos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "kernel-smoke.ipynb"
    nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("import sys; print(sys.executable)")]), source)
    monkeypatch.setattr(module, "NOTEBOOKS", [source])
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(sys, "argv", ["render_notebook_demos.py", "--out", str(tmp_path / "demos")])
    assert module.main() == 0
    result = nbformat.read(tmp_path / "demos" / source.name, as_version=4)
    assert result.cells[0].outputs[0].text == "/demo/python\n"


def test_notebooks_execute(tmp_path, monkeypatch):
    """Run all notebooks in order from notebooks/, as Jupyter would, with writes under tmp_path."""
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("pandas")
    pytest.importorskip("matplotlib")

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SANDBOX_NOTEBOOK_LOG", str(tmp_path / "log" / "experiment_log.jsonl"))
    monkeypatch.setenv("SANDBOX_NOTEBOOK_LOG_VIEW", str(tmp_path / "log" / "experiment_log.jsonl"))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.setenv("SANDBOX_NOTEBOOK_OBSERVABILITY", "none")  # no trace sink from the host env
    monkeypatch.delenv("SANDBOX_PROFILE", raising=False)
    monkeypatch.delenv("SANDBOX_NOTEBOOK_PROBE", raising=False)

    dotenv = repo_root() / ".env"
    had_dotenv = dotenv.exists()
    try:
        for path in NOTEBOOKS:
            nb = nbformat.read(path, as_version=4)
            client = nbclient.NotebookClient(
                nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(NOTEBOOK_DIR)}}
            )
            client.execute()
    finally:
        if not had_dotenv and dotenv.exists():
            dotenv.unlink()  # notebook 01 creates it; leave the checkout as found

    assert not (NOTEBOOK_DIR / "data").exists(), "a notebook wrote a run store inside notebooks/"
    log = tmp_path / "log" / "experiment_log.jsonl"
    names = {json.loads(line)["experiment_name"] for line in log.read_text(encoding="utf-8").splitlines()}
    assert {"notebook_sorter_fixtures", "notebook_sorter_balanced", "notebook_offline_pipeline"} <= names


def test_setup_dotenv_cell_honours_the_test_opt_out(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    import dotenv
    from mailroom_sandbox import prep

    env_path = tmp_path / '.env'
    env_path.write_text('SANDBOX_PROFILE=sentinel\n', encoding='utf-8')
    monkeypatch.setattr(prep, 'ensure_dotenv_from_example', lambda: env_path)
    calls = []
    monkeypatch.setattr(dotenv, 'dotenv_values', lambda path: calls.append(path) or {})
    cell = next(c for c in _load(NOTEBOOK_DIR / EXPECTED[0])['cells'] if c['id'] == '01-06')
    scope = {'os': os, 'ctx': SimpleNamespace(root=tmp_path, profile='ollama')}
    monkeypatch.setenv('SANDBOX_SKIP_DOTENV', '1')
    exec(compile(_source(cell), 'notebook-dotenv-cell', 'exec'), scope)
    assert calls == []
    monkeypatch.delenv('SANDBOX_SKIP_DOTENV')
    exec(compile(_source(cell), 'notebook-dotenv-cell', 'exec'), scope)
    assert calls == [env_path]
