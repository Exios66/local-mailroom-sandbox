"""Published demo output must not disclose the machine used to execute it."""

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_demo_sanitizer_preserves_binary_mime_payloads():
    spec = importlib.util.spec_from_file_location("render_demos", ROOT / "scripts/render_notebook_demos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    nb = {"cells": [{"outputs": [{"data": {"image/png": "/rootAAA", "application/pdf": "/rootAAA",
                    "image/svg+xml": "<svg>/root/file</svg>", "application/json": {"file": "/root/file"}},
                    "metadata": {"label": "/root/file"}}]}]}
    module.sanitize_demo_outputs(nb, {"/root": "/demo/home"})
    output = nb["cells"][0]["outputs"][0]
    assert output["data"]["image/png"] == output["data"]["application/pdf"] == "/rootAAA"
    assert output["data"]["image/svg+xml"] == "<svg>/demo/home/file</svg>"
    assert output["data"]["application/json"]["file"] == output["metadata"]["label"] == "/demo/home/file"


def test_renderer_sanitizes_the_selected_kernel_interpreter(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("render_demos", ROOT / "scripts/render_notebook_demos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.os, "environ", dict(module.os.environ))
    kernel_python = str(tmp_path / "other-environment" / "bin" / "python")

    class AttrDict(dict):
        __getattr__ = dict.__getitem__

    notebook = AttrDict(cells=[AttrDict(cell_type="code", source="print(sys.executable)", outputs=[])])

    class Client:
        def __init__(self, nb, **kwargs):
            self.nb = nb

        def create_kernel_manager(self):
            return SimpleNamespace(format_kernel_cmd=lambda: [kernel_python, "-m", "ipykernel_launcher"])

        def execute(self):
            self.nb.cells[0]["outputs"] = [{"text": kernel_python}]

    written = []
    monkeypatch.setitem(sys.modules, "nbclient", SimpleNamespace(NotebookClient=Client))
    monkeypatch.setitem(sys.modules, "nbformat", SimpleNamespace(read=lambda *a, **kw: notebook,
                                                               write=lambda nb, dest: written.append(nb)))
    monkeypatch.setattr(module, "NOTEBOOKS", [tmp_path / "source.ipynb"])
    monkeypatch.setattr(sys, "argv", ["render_notebook_demos.py", "--out", str(tmp_path / "out")])
    assert module.main() == 0
    assert written[0].cells[0]["outputs"][0]["text"] == "/demo/python"
