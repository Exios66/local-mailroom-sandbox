"""``scripts/build_excluded_ids.py`` builds the committed held-out exclusion list."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from mailroom_sandbox.corpus import read_id_list

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_excluded_ids.py"


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("build_excluded_ids_script", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(root: Path, name: str, ids: list[str]) -> Path:
    run = root / name
    run.mkdir(parents=True)
    rows = [{"id": i, "filename": f"{i}.htm", "doc_text": "x"} for i in ids]
    (run / "dataset.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return run


def test_build_unions_and_sorts_ids(mod, tmp_path):
    a = _run(tmp_path, "run-a", ["DOC-3", "DOC-1", "DOC-2"])
    b = _run(tmp_path, "run-b", ["DOC-2", "DOC-4"])
    assert mod.build([a, b]) == ["DOC-1", "DOC-2", "DOC-3", "DOC-4"]


def test_header_names_each_source(mod, tmp_path):
    a = _run(tmp_path, "run-a", ["DOC-1", "DOC-2"])
    b = _run(tmp_path, "run-b", ["DOC-2"])
    text = mod.render([a, b])
    assert "# run-a: 2 rows" in text.splitlines()
    assert "# run-b: 1 rows" in text.splitlines()
    # round-trips through the corpus reader
    out = tmp_path / "ids.txt"
    out.write_text(text, encoding="utf-8")
    assert read_id_list(out) == ["DOC-1", "DOC-2"]


def test_check_detects_drift(mod, tmp_path, capsys):
    _run(tmp_path, "run-a", ["DOC-1", "DOC-2"])
    out = tmp_path / "ids.txt"
    args = ["--runs-dir", str(tmp_path), "--run", "run-a", "--out", str(out)]
    assert mod.main(args) == 0
    assert mod.main([*args, "--check"]) == 0
    out.write_text(out.read_text().replace("DOC-2\n", ""), encoding="utf-8")
    assert mod.main([*args, "--check"]) == 1


def test_run_resolves_in_first_runs_dir_that_has_it(mod, tmp_path):
    r1, r2 = tmp_path / "r1", tmp_path / "r2"
    _run(r1, "run-a", ["DOC-1"])
    _run(r2, "run-a", ["DOC-9"])
    _run(r2, "run-b", ["DOC-2"])
    dirs = mod.resolve_runs([r1, r2], ["run-a", "run-b"])
    assert [d.name for d in dirs] == ["run-a", "run-b"]
    assert mod.build(dirs) == ["DOC-1", "DOC-2"]


def test_missing_run_is_an_error(mod, tmp_path):
    with pytest.raises(SystemExit):
        mod.resolve_runs([tmp_path], ["nope"])
