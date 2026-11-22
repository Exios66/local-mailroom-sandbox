"""Published demo output must not disclose the machine used to execute it."""

import importlib.util
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_demo_output_sanitizer_preserves_source_and_images(tmp_path):
    spec = importlib.util.spec_from_file_location("render_demos", ROOT / "scripts/render_notebook_demos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = str(tmp_path / "demo-runtime")
    source = "print('/Users/example/project')"
    nb = {"cells": [{"source": source, "outputs": [
        {"text": ["root=/Users/example/project\n", f"runtime={runtime}/data\n"]},
        {"data": {"text/html": "<td>/Users/example/project/vendor</td>", "image/png": "iVBORw0KGgo="}},
    ]}]}
    module.sanitize_demo_outputs(nb, {"/Users/example": "/demo/home", "/Users/example/project": "/demo/checkout",
                                      runtime: "/demo/runtime"})
    assert nb["cells"][0]["source"] == source
    output = nb["cells"][0]["outputs"]
    assert output[0]["text"] == ["root=/demo/checkout\n", "runtime=/demo/runtime/data\n"]
    assert output[1]["data"]["text/html"] == "<td>/demo/checkout/vendor</td>"
    assert output[1]["data"]["image/png"] == "iVBORw0KGgo="


def test_committed_demos_have_no_machine_paths():
    for path in (ROOT / "notebooks/demos").glob("*.ipynb"):
        nb = json.loads(path.read_text())
        outputs = json.dumps([c.get("outputs", []) for c in nb["cells"]])
        assert "/Users/" not in outputs, path
        assert not re.search(r"/(?:private/)?(?:tmp/|var/folders/)", outputs), path
        assert "/private/demo/" not in outputs, path


@pytest.mark.parametrize("canonical_source", [False, True])
@pytest.mark.parametrize("directory", ["tmp", "var"])
def test_demo_sanitizer_handles_macos_path_aliases(monkeypatch, tmp_path, canonical_source, directory):
    spec = importlib.util.spec_from_file_location("render_demos", ROOT / "scripts/render_notebook_demos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys, "platform", "darwin")
    short = Path("/") / directory / tmp_path.name
    canonical = Path("/") / "private" / directory / tmp_path.name
    nb = {"cells": [{"outputs": [{"text": [f"{short}/log\n", f"{canonical}/log\n"]}]}]}
    source = canonical if canonical_source else short
    module.sanitize_demo_outputs(nb, {str(source): "/demo/runtime"})
    assert nb["cells"][0]["outputs"][0]["text"] == ["/demo/runtime/log\n"] * 2


def test_demo_sanitizer_handles_resolved_symlink_paths(tmp_path):
    spec = importlib.util.spec_from_file_location("render_demos", ROOT / "scripts/render_notebook_demos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    nb = {"cells": [{"outputs": [{"text": f"{target.resolve()}/log"}]}]}
    module.sanitize_demo_outputs(nb, {str(alias): "/demo/runtime"})
    assert nb["cells"][0]["outputs"][0]["text"] == "/demo/runtime/log"
