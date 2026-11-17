"""scripts/refresh_decision_models.py: catalog rows from an OpenRouter response, aliases dropped, drift."""
from __future__ import annotations

import json
import sys

import yaml

from mailroom_sandbox.paths import repo_root

sys.path.insert(0, str(repo_root() / "scripts"))
import refresh_decision_models as rdm  # noqa: E402


def _entry(model_id, prompt="0.000000042", **extra):
    return {"id": model_id, "canonical_slug": model_id + "-20261014", "context_length": 262144,
            "pricing": {"prompt": prompt, "completion": "0"}, "endpoints": ["/api/alpha/decisions"], **extra}


def test_build_converts_prices_and_drops_aliases():
    doc = rdm.build([_entry("typesafe/jev-1.14"), _entry("~typesafe/jev-latest"), _entry("x/y-latest")], today="2026-11-17")
    assert doc["checked"] == "2026-11-17"
    assert list(doc["models"]) == ["typesafe/jev-1.14"]
    assert doc["models"]["typesafe/jev-1.14"] == {
        "canonical_slug": "typesafe/jev-1.14-20261014", "endpoints": ["/api/alpha/decisions"],
        "context_length": 262144, "prompt": 0.042}


def test_diff_reports_added_removed_changed():
    old = rdm.build([_entry("a/one"), _entry("a/two")], today="d")
    new = rdm.build([_entry("a/two", prompt="0.0000001"), _entry("a/three")], today="d")
    assert rdm.diff(old, new) == ["removed: a/one", "added: a/three", "changed: a/two"]


def test_committed_catalog_matches_a_rebuild_of_itself(tmp_path):
    committed = yaml.safe_load((repo_root() / "config" / "decision_models.yaml").read_text(encoding="utf-8"))
    response = {"data": [{"id": k, "canonical_slug": v["canonical_slug"], "context_length": v["context_length"],
                          "endpoints": v["endpoints"], "pricing": {"prompt": str(v["prompt"] / 1_000_000)}}
                         for k, v in committed["models"].items()]}
    src = tmp_path / "models.json"
    src.write_text(json.dumps(response))
    out = tmp_path / "decision_models.yaml"
    out.write_text((repo_root() / "config" / "decision_models.yaml").read_text(encoding="utf-8"))
    assert rdm.main(["--file", str(out), "--from-json", str(src), "--check"]) == 0
    response["data"][0]["pricing"]["prompt"] = "0.5"
    src.write_text(json.dumps(response))
    assert rdm.main(["--file", str(out), "--from-json", str(src), "--check"]) == 1
