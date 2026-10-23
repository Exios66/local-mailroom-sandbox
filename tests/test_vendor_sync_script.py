"""The local snapshot helper must attempt every requested source tree."""
import importlib.util
from pathlib import Path


def test_sync_vendor_script_refreshes_later_source_after_failure(tmp_path, monkeypatch):
    """An absent first source does not prevent a valid later snapshot refresh."""
    script = Path(__file__).resolve().parents[1] / "scripts/sync_vendor.py"
    spec = importlib.util.spec_from_file_location("sandbox_vendor_sync_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "second-source"
    source.mkdir()
    (source / "scorer.py").write_text("SOURCE_SENTINEL = 42\n")
    (source / "tests").mkdir()
    (source / "tests/ignored.py").write_text("ignored = True\n")
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "_SNAPSHOTS", [
        ("first", tmp_path / "vendor/first", tmp_path / "missing"),
        ("second", tmp_path / "vendor/second", source),
    ])
    monkeypatch.setattr("sys.argv", [str(script)])
    assert module.main() == 1
    assert (tmp_path / "vendor/second/scorer.py").read_text() == "SOURCE_SENTINEL = 42\n"
    assert not (tmp_path / "vendor/second/tests").exists()
