"""Published demo output must not disclose the machine used to execute it."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_output_sanitizer_preserves_source_and_images():
    spec = importlib.util.spec_from_file_location("render_demos", ROOT / "scripts/render_notebook_demos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = "print('/Users/example/project')"
    nb = {"cells": [{"source": source, "outputs": [
        {"text": ["root=/Users/example/project\n", "runtime=/tmp/demo-123/data\n"]},
        {"data": {"text/html": "<td>/Users/example/project/vendor</td>", "image/png": "iVBORw0KGgo="}},
    ]}]}
    module.sanitize_demo_outputs(nb, {"/Users/example": "/demo/home", "/Users/example/project": "/demo/checkout",
                                      "/tmp/demo-123": "/demo/runtime"})
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
        assert "/private/tmp/" not in outputs, path
