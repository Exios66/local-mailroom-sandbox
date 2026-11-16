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
    assert "# run-b: 1 row" in text.splitlines()
    # round-trips through the corpus reader
    out = tmp_path / "ids.txt"
    out.write_text(text, encoding="utf-8")
    assert read_id_list(out) == ["DOC-1", "DOC-2"]


def test_check_detects_drift(mod, tmp_path):
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


def test_check_fails_when_output_file_is_missing(mod, tmp_path):
    _run(tmp_path, "run-a", ["DOC-1"])
    args = ["--runs-dir", str(tmp_path), "--run", "run-a", "--out", str(tmp_path / "absent.txt")]
    assert mod.main([*args, "--check"]) == 1


@pytest.mark.parametrize("bad_line", ["{not json", '{"filename": "x.htm"}'])
def test_malformed_row_names_file_and_line(mod, tmp_path, bad_line):
    run = _run(tmp_path, "run-a", ["DOC-1"])
    dataset = run / "dataset.jsonl"
    dataset.write_text(dataset.read_text(encoding="utf-8") + bad_line + "\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod.read_ids(run)
    assert str(dataset) in str(exc.value)
    assert ":2" in str(exc.value)


def test_duplicate_run_values_are_deduplicated(mod, tmp_path):
    _run(tmp_path, "run-a", ["DOC-1", "DOC-2"])
    _run(tmp_path, "run-b", ["DOC-3"])
    out = tmp_path / "ids.txt"
    args = ["--runs-dir", str(tmp_path), "--run", "run-a", "--run", "run-b", "--run", "run-a", "--out", str(out)]
    assert mod.main(args) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines.count("# run-a: 2 rows") == 1
    assert [ln for ln in lines if ln.startswith("# run-")] == ["# run-a: 2 rows", "# run-b: 1 row"]


def test_committed_list_is_clean():
    path = Path(__file__).resolve().parents[1] / "config" / "production" / "excluded-ids.txt"
    ids = read_id_list(path)
    assert ids
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert all(i.startswith("DOC-") for i in ids)
    assert "/Users" not in path.read_text(encoding="utf-8")
