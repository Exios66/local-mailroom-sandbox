"""scripts/refresh_provider_pins.py: offline (--from-json) report and --write-order. No network."""
from __future__ import annotations

import importlib.util
import json
import sys

import pytest
import yaml

from mailroom_sandbox.paths import repo_root


@pytest.fixture
def script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("refresh_provider_pins", repo_root() / "scripts" / "refresh_provider_pins.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pins = tmp_path / "provider_pins.yaml"
    pins.write_text("# header kept\n\nmodels:\n  a/one:\n    order: []\n  b/two:\n    order: []\n")
    monkeypatch.setattr(mod, "PINS", pins)
    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    saved = tmp_path / "saved"
    saved.mkdir()
    return mod, pins, saved


def _endpoints(*eps):
    return {"data": {"id": "x", "endpoints": [
        {"provider_name": name, "tag": tag, "pricing": {"prompt": price, "completion": price}} for name, tag, price in eps]}}


def _run(mod, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["refresh_provider_pins.py", *argv])
    return mod.main()


def test_write_order_pins_the_cheapest_endpoint_slug_and_keeps_the_header(script, monkeypatch):
    mod, pins, saved = script
    (saved / "a__one.json").write_text(json.dumps(_endpoints(("Google Vertex", "google-vertex/us-east5", "0.1"),
                                                             ("Alibaba", "alibaba", "0.5"))))
    (saved / "b__two.json").write_text(json.dumps(_endpoints(("Alibaba", "alibaba", "0.2"))))
    assert _run(mod, monkeypatch, "--from-json", str(saved), "--write-order") == 0
    text = pins.read_text()
    assert text.startswith("# header kept\n")
    models = yaml.safe_load(text)["models"]
    assert models["a/one"]["order"] == ["google-vertex/us-east5"] and models["b/two"]["order"] == ["alibaba"]


def test_a_failed_lookup_exits_1_and_writes_nothing(script, monkeypatch, capsys):
    mod, pins, saved = script
    before = pins.read_text()
    (saved / "a__one.json").write_text(json.dumps(_endpoints(("Alibaba", "alibaba", "0.1"))))  # b/two missing
    assert _run(mod, monkeypatch, "--from-json", str(saved), "--write-order") == 1
    assert pins.read_text() == before
    assert "nothing written" in capsys.readouterr().err
    assert _run(mod, monkeypatch, "--from-json", str(saved)) == 1  # report mode fails too
