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
            "id": "org/repo", "gated": False,
            "tags": ["text-generation"], "downloads": 10, "sha": "abc",
            "cardData": {"license": "apache-2.0"},
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

    def test_card_prefers_the_top_level_license(self, capsys, monkeypatch):
        # The official client reads cardData; a present top-level license still wins.
        payload = {"id": "org/repo", "license": "mit", "cardData": {"license": "apache-2.0"}}
        recorder = Recorder(json.dumps(payload).encode())
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        run(["card", "org/repo"])
        assert json.loads(capsys.readouterr().out)["license"] == "mit"

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
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        missing = tmp_path / "no-cache-here"
        monkeypatch.setattr(hf_tool, "cache_root", lambda: missing)
        recorder = Recorder()  # a call would prove an offline leak: the suite must stay network-free
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        run(["status"])
        record = json.loads(capsys.readouterr().out)
        assert record["cache"]["root"] == str(missing)
        assert record["cache"]["exists"] is False
        assert record["hub_head"] is None
        assert "revision" in record
        assert recorder.calls == []

    def test_status_online_reports_pin_is_head(self, capsys, monkeypatch, tmp_path):
        from mailroom_sandbox.job.spec import FAMILY_HF_REVISION, HF_DEFAULT_REPO

        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        monkeypatch.setattr(hf_tool, "cache_root", lambda: tmp_path)
        recorder = Recorder(json.dumps({"sha": FAMILY_HF_REVISION}).encode())
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        run(["status"])
        record = json.loads(capsys.readouterr().out)
        assert record["pin_is_head"] is True
        assert record["hub_head"] == FAMILY_HF_REVISION
        url, headers = recorder.calls[0]
        assert url == f"https://huggingface.co/api/datasets/{HF_DEFAULT_REPO}"

    def test_status_online_flags_a_stale_pin(self, capsys, monkeypatch, tmp_path):
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        monkeypatch.setattr(hf_tool, "cache_root", lambda: tmp_path)
        recorder = Recorder(json.dumps({"sha": "e" * 40}).encode())
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        run(["status"])
        record = json.loads(capsys.readouterr().out)
        assert record["pin_is_head"] is False
        assert record["hub_head"] == "e" * 40


class TestHubHttpErrorHandling:
    def test_status_reports_the_cache_record_on_http_error(self, capsys, monkeypatch, tmp_path):
        # A 401 from the Hub is a status, not a crash: the cache report still emits and
        # the command still exits 0 (docs/critical-regressions.md row 10: no crash paths).
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        monkeypatch.setattr(hf_tool, "cache_root", lambda: tmp_path)
        recorder = Recorder(body=b'{"error": "Unauthorized"}', status=401)
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        assert run(["status"]) == 0
        record = json.loads(capsys.readouterr().out)
        assert record["cache"]["root"] == str(tmp_path)
        assert "401" in record["hub_error"] and "hub_head" not in record


class TwoPageTransport:
    """A fake Hub tree split across two Link-paginated pages."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url, headers):
        self.calls.append(url)
        if "page" not in url:
            body = json.dumps([{"path": "a.parquet", "size": 1, "type": "file"}]).encode()
            return 200, body, {"Link": '<https://huggingface.co/next?page=2>; rel="next"'}
        return 200, json.dumps([{"path": "b.parquet", "size": 2, "type": "file"}]).encode(), {}


class TestFilesPaginationAndEncoding:
    def test_files_follows_the_next_page_before_exiting(self, capsys, monkeypatch):
        transport = TwoPageTransport()
        monkeypatch.setattr(hf_tool, "TRANSPORT", transport)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        assert run(["files", "org/repo", "--revision", "ff4ca546"]) == 0
        assert len(transport.calls) == 2
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [row["path"] for row in lines] == ["a.parquet", "b.parquet"]

    def test_cross_host_pagination_is_ignored(self, capsys, monkeypatch):
        # A server-controlled Link must never take the caller's token off the Hub host.
        class HostileLinkTransport:
            def __init__(self):
                self.calls: list[str] = []

            def __call__(self, url, headers):
                self.calls.append(url)
                body = json.dumps([{"path": "a.parquet", "size": 1, "type": "file"}]).encode()
                return 200, body, {"Link": '<https://evil.example/steal>; rel="next"'}

        transport = HostileLinkTransport()
        monkeypatch.setattr(hf_tool, "TRANSPORT", transport)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        assert run(["files", "org/repo", "--revision", "ff4ca546"]) == 0
        assert transport.calls == [
            "https://huggingface.co/api/datasets/org/repo/tree/ff4ca546?recursive=1"]

    def test_page_cap_stops_a_runaway_pagination(self, capsys, monkeypatch, caplog):
        class EndlessTransport:
            def __call__(self, url, headers):
                body = json.dumps([{"path": "x.parquet", "size": 1, "type": "file"}]).encode()
                return 200, body, {"Link": '<https://huggingface.co/next?page=2>; rel="next"'}

        monkeypatch.setattr(hf_tool, "TRANSPORT", EndlessTransport())
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        with pytest.raises(SystemExit) as exc:
            run(["files", "org/repo", "--revision", "ff4ca546"])
        assert exc.value.code == 1
        assert "100 pages" in capsys.readouterr().err

    def test_revision_is_one_encoded_path_component(self, capsys, monkeypatch):
        recorder = Recorder(json.dumps([]).encode())
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        run(["files", "org/repo", "--revision", "refs/pr/1"])
        url, _ = recorder.calls[0]
        assert "tree/refs%2Fpr%2F1" in url

    def test_hex_revisions_are_unchanged(self, capsys, monkeypatch):
        recorder = Recorder(json.dumps([]).encode())
        monkeypatch.setattr(hf_tool, "TRANSPORT", recorder)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        run(["files", "org/repo", "--revision", "f" * 40])
        url, _ = recorder.calls[0]
        assert f"tree/{'f' * 40}" in url
