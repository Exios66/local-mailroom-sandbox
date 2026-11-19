"""In-house Hugging Face integration tooling: ``scripts/hf_tool.py``.

The sandbox's HF law (pinned revisions, sandbox-local cache, offline-first) already lives
in ``corpus.py`` / ``job/spec.py``; this tool exposes it as composable, pipe-friendly CLI
scripts (NDJSON out, ``--help`` everywhere, ``HF_TOKEN`` auth). Tests stay network-free:
the HTTP transport is injected and every network command refuses when offline is forced
(``docs/critical-regressions.md`` row 10).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("hf_tool", REPO / "scripts" / "hf_tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hf_tool = _load()


class Recorder:
    """A fake transport: records ``(url, headers)`` and serves canned bodies."""

    def __init__(self, body=b"[]", status=200):
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.body = body
        self.status = status

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        return self.status, self.body


def run(argv):
    return hf_tool.main(argv)


class TestHelp:
    @pytest.mark.parametrize("command", ["pins", "verify-pin", "status", "whoami", "search", "card", "files"])
    def test_every_subcommand_has_help(self, command, capsys):
        with pytest.raises(SystemExit) as exc:
            run([command, "--help"])
        assert exc.value.code == 0
        assert command in capsys.readouterr().out


class TestPins:
    def test_pins_dumps_the_family_ledger(self, capsys):
        run(["pins"])
        out = json.loads(capsys.readouterr().out)
        from mailroom_sandbox.job.spec import FAMILY_HF_REVISION, FAMILY_HF_DATA_REVISION, FAMILY_HF_TAG

        assert out["tag"] == FAMILY_HF_TAG
        assert out["revision"] == FAMILY_HF_REVISION
        assert out["data_revision"] == FAMILY_HF_DATA_REVISION
        assert out["legacy"]["v9.1"]["revision"].startswith("bc9eab28")

    def test_verify_pin_known_and_unknown(self, capsys):
        from mailroom_sandbox.job.spec import FAMILY_HF_REVISION

        assert run(["verify-pin", FAMILY_HF_REVISION]) == 0
        assert run(["verify-pin", "0" * 40]) == 1
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[-1]["known"] is False


class TestOfflineRefusal:
    def test_network_commands_refuse_offline(self, capsys, monkeypatch):
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        for argv in (["search", "qwen"], ["card", "org/repo"], ["whoami"], ["files", "org/repo"]):
            with pytest.raises(SystemExit) as exc:
                run(argv)
            assert exc.value.code == 3
            assert "offline" in capsys.readouterr().err.lower()


class TestTransport:
    def test_search_uses_token_header_and_query(self, capsys, monkeypatch):
        recorder = Recorder(json.dumps([{"id": "a/m", "downloads": 5}]).encode())
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        monkeypatch.setenv("HF_TOKEN", "tok-123")
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        assert run(["search", "qwen", "--type", "model", "--limit", "1"]) == 0
        url, headers = recorder.calls[0]
        assert "/api/models?search=qwen" in url and "limit=1" in url
        assert headers.get("Authorization") == "Bearer tok-123"
        (line,) = capsys.readouterr().out.splitlines()
        assert json.loads(line) == {"id": "a/m", "downloads": 5}

    def test_no_token_no_header(self, monkeypatch):
        recorder = Recorder()
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        run(["search", "qwen"])
        _, headers = recorder.calls[0]
        assert "Authorization" not in headers

    def test_http_error_is_a_loud_failure(self, monkeypatch, capsys):
        recorder = Recorder(body=b'{"error": "no"}', status=404)
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        with pytest.raises(SystemExit) as exc:
            run(["card", "org/missing"])
        assert exc.value.code == 1
        assert "404" in capsys.readouterr().err


class TestCardAndFiles:
    def test_card_emits_ndjson_summary(self, capsys, monkeypatch):
        payload = {
            "id": "org/repo", "license": "apache-2.0", "gated": False,
            "tags": ["text-generation"], "downloads": 10, "sha": "abc",
        }
        recorder = Recorder(json.dumps(payload).encode())
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        run(["card", "org/repo", "--type", "dataset"])
        url, _ = recorder.calls[0]
        assert url.endswith("/api/datasets/org/repo")
        (line,) = capsys.readouterr().out.splitlines()
        record = json.loads(line)
        assert record["license"] == "apache-2.0" and record["gated"] is False and record["sha"] == "abc"

    def test_files_lists_the_tree(self, capsys, monkeypatch):
        payload = [{"path": "data/train.parquet", "size": 123, "type": "file"},
                   {"path": "data", "type": "directory"}]
        recorder = Recorder(json.dumps(payload).encode())
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        run(["files", "org/repo", "--revision", "ff4ca546"])
        url, _ = recorder.calls[0]
        assert "tree/ff4ca546" in url
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[0]["path"] == "data/train.parquet" and lines[0]["size"] == 123
        assert all("size" not in row or row.get("type") != "directory" for row in lines) or lines[1].get("size") is None

    def test_status_reports_offline_cache_without_network(self, capsys, monkeypatch, tmp_path):
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        missing = tmp_path / "no-cache-here"
        monkeypatch.setattr(hf_tool, "cache_root", lambda: missing)
        run(["status"])
        record = json.loads(capsys.readouterr().out)
        assert record["cache"]["root"] == str(missing)
        assert record["cache"]["exists"] is False
        assert "revision" in record
