"""Release/cache contracts; every HTTP response is an offline fixture."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest

from mailroom_sandbox import snapshots as s

COMMIT = "a" * 40
TAG = "v0.28.1"


def wheel(files=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in (
            files
            if files is not None
            else {"llm_dojo_scoring/__init__.py": '__version__ = "0.28.1"\n'}
        ).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def archive(files=None, *, link=False):
    buffer = io.BytesIO()
    files = (
        files
        if files is not None
        else {
            "root/pyproject.toml": '[project]\nname = "mailroom"\nversion = "0.9.3"\n',
            "root/src/pipeline/__init__.py": "",
            "root/src/pipeline/config.py": "",
            "root/src/graph/build_graph.py": "",
            "root/src/agents/__init__.py": "",
            "root/src/llm/__init__.py": "",
            "root/src/legalbench/__init__.py": "",
        }
    )
    with tarfile.open(fileobj=buffer, mode="w:gz") as output:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            data = content.encode()
            member.size = len(data)
            if link:
                member.type, member.linkname, member.size = tarfile.SYMTYPE, "/tmp/escape", 0
            output.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


@pytest.fixture
def release_api(monkeypatch, tmp_path):
    monkeypatch.setattr(s, "cache_root", lambda: tmp_path / "cache")
    monkeypatch.delenv("SANDBOX_DOJO_SNAPSHOT", raising=False)
    monkeypatch.delenv("SANDBOX_PIPELINE_SNAPSHOT", raising=False)
    name = "llm_dojo_scoring-0.28.1-py3-none-any.whl"
    state = {
        "data": wheel(),
        "component": "dojo",
        "tag": TAG,
        "calls": [],
        "assets": True,
        "annotated": False,
    }

    def get(url, **kwargs):
        state["calls"].append(url)
        component, tag = state["component"], state["tag"]
        base = (
            "https://github.com/Exios66/"
            + s.COMPONENTS[component]
            + "/releases/download/"
            + tag
            + "/"
        )
        checksum = state.get("checksum", s.digest(state["data"]))
        if "/releases/" in url and "/download/" not in url:
            return json.dumps(
                {
                    "tag_name": tag,
                    "draft": False,
                    "prerelease": state.get("prerelease", False),
                    "published_at": "2026-11-07T10:00:00Z",
                    "assets": [
                        {"name": n, "browser_download_url": base + n}
                        for n in (name, "release-manifest.json", "SHA256SUMS")
                        if state["assets"]
                    ],
                }
            ).encode()
        if "/git/ref/" in url:
            return json.dumps(
                {"object": {"type": "tag" if state["annotated"] else "commit", "sha": COMMIT}}
            ).encode()
        if "/git/tags/" in url:
            return json.dumps({"object": {"type": "commit", "sha": COMMIT}}).encode()
        if url.endswith("release-manifest.json"):
            return json.dumps(
                {
                    "package": s.COMPONENTS[component],
                    "commit": state.get("manifest_commit", COMMIT),
                    "tag": tag,
                    "version": tag.removeprefix("v"),
                    "files": [
                        {
                            "name": name,
                            "kind": "wheel",
                            "sha256": checksum,
                            "size": len(state["data"]),
                        }
                    ],
                }
            ).encode()
        if url.endswith("SHA256SUMS"):
            return f"{state.get('sums', checksum)}  {name}\n".encode()
        return state["data"]

    monkeypatch.setattr(s, "_get", get)
    return state


def test_explicit_fetch_reuses_cache_without_network(release_api, monkeypatch):
    first = s.fetch("dojo", version=TAG)
    assert first["commit"] == COMMIT and first["cache_hit"] is False
    monkeypatch.setattr(s, "_get", lambda *a, **k: pytest.fail("cache hit used network"))
    second = s.fetch("dojo", version=TAG)
    assert second["cache_hit"] and second["tree_sha256"] == first["tree_sha256"]
    # A download alone is not permission to upgrade the reviewed pin.
    assert s.selected("dojo")[0] is None
    monkeypatch.setenv("SANDBOX_DOJO_SNAPSHOT", first["lock_path"])
    assert s.selected("dojo")[0]["commit"] == COMMIT


def test_stable_resolves_once_and_refresh_is_explicit(release_api, monkeypatch):
    first = s.fetch("dojo")
    release_api["calls"].clear()
    assert s.fetch("dojo")["cache_hit"] and not release_api["calls"]
    assert s.fetch("dojo", refresh=True)["cache_hit"] and release_api["calls"]
    assert first["resolved_stable"]


@pytest.mark.parametrize(
    "change,error",
    [
        ({"checksum": "f" * 64}, "checksum/size"),
        ({"sums": "f" * 64}, "disagree"),
        ({"manifest_commit": "b" * 40}, "identity"),
        ({"assets": False}, "missing"),
        ({"prerelease": True}, "stable"),
        ({"data": b"truncated"}, "Invalid archive"),
        ({"data": wheel({})}, "Empty"),
        ({"data": wheel({"../escape": "bad"})}, "Unsafe"),
        ({"data": wheel({"readme.txt": "no runtime"})}, "runtime"),
    ],
)
def test_failure_preserves_prior_cache(release_api, change, error):
    first = s.fetch("dojo", version=TAG)
    before = {
        p.relative_to(s.cache_root()).as_posix(): p.read_bytes()
        for p in s.cache_root().rglob("*")
        if p.is_file()
    }
    release_api.update(change)
    release_api["tag"] = "v0.28.2"
    with pytest.raises(s.SnapshotError, match=error):
        s.fetch("dojo", version="v0.28.2", refresh=True)
    after = {
        p.relative_to(s.cache_root()).as_posix(): p.read_bytes()
        for p in s.cache_root().rglob("*")
        if p.is_file()
    }
    assert after == before
    assert s.verify(Path(first["lock_path"]), "dojo")["commit"] == COMMIT


def test_cache_tampering_is_rejected(release_api):
    first = s.fetch("dojo", version=TAG)
    (Path(first["path"]) / "llm_dojo_scoring/__init__.py").write_text("tampered")
    entries, errors = s.cached("dojo")
    assert entries == [] and "inventory" in errors[0]


def test_pipeline_peels_annotated_tag_and_uses_commit_archive(release_api):
    release_api.update(
        component="pipeline", tag="v0.9.3", assets=False, data=archive(), annotated=True
    )
    result = s.fetch("pipeline", version="v0.9.3")
    assert result["commit"] == COMMIT
    assert result["source_url"].endswith("/tarball/" + COMMIT)
    assert result["verification"] == "github-commit-archive; locally-computed-sha256"
    assert any("/git/tags/" in url for url in release_api["calls"])
    assert s.valid_source("pipeline", Path(result["path"]))


@pytest.mark.parametrize(
    "data,error",
    [
        (archive({"../escape": "x"}), "Unsafe"),
        (archive({"root/link": ""}, link=True), "links"),
        (archive({}), "Empty"),
        (b"truncated", "Invalid archive"),
    ],
)
def test_tar_rejects_unsafe_members(tmp_path, data, error):
    with pytest.raises(s.SnapshotError, match=error):
        s._extract(data, tmp_path, wheel=False)
    assert not (tmp_path.parent / "escape").exists()


def test_zip_rejects_links_and_duplicates(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as output:
        entry = zipfile.ZipInfo("escape")
        entry.external_attr = 0o120777 << 16
        output.writestr(entry, "/tmp/escape")
    with pytest.raises(s.SnapshotError, match="links"):
        s._extract(buffer.getvalue(), tmp_path, wheel=True)
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(buffer := io.BytesIO(), "w") as output:
            output.writestr("duplicate", "a")
            output.writestr("duplicate", "b")
    with pytest.raises(s.SnapshotError, match="duplicate"):
        s._extract(buffer.getvalue(), tmp_path, wheel=True)


def test_extraction_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "MAX_EXPANDED", 1)
    with pytest.raises(s.SnapshotError, match="limits"):
        s._extract(wheel(), tmp_path, wheel=True)


def test_readonly_check_and_cli(release_api, monkeypatch, capsys):
    from mailroom_sandbox.cli import build_parser

    root = s.cache_root()
    parser = build_parser()
    args = parser.parse_args(["deps", "fetch", "--component", "dojo", "--check", "--version", TAG])
    assert args.handler(args) == 1  # requested cache match absent
    report = json.loads(capsys.readouterr().out)[0]
    assert all(key in report for key in ("vendored_pin", "installed", "cached", "latest_stable"))
    assert not root.exists()
    monkeypatch.setattr(s, "_get", lambda *a, **k: pytest.fail("offline check used network"))
    args = parser.parse_args(
        ["--profile", "ollama", "deps", "fetch", "--check", "--offline", "--profile", "modal-vllm"]
    )
    assert args.profile == "modal-vllm" and args.handler(args) == 0
    assert not root.exists()


def test_bounded_download_without_credential_forwarding(monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"oversized"))
    monkeypatch.setattr(
        s.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    with pytest.raises(s.SnapshotError, match="exceeds"):
        s._get("https://api.github.com/test", limit=1)
    with pytest.raises(s.SnapshotError, match="Unexpected"):
        s._get("https://evil.test/file")


def test_fresh_process_imports_cache_without_installed_or_vendor(release_api):
    result = s.fetch("dojo", version=TAG)
    import os

    environment = {
        **os.environ,
        "SANDBOX_ROOT": str(s.cache_root().parent),
        "SANDBOX_SKIP_DOTENV": "1",
        "SANDBOX_DOJO_SNAPSHOT": result["lock_path"],
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import mailroom_sandbox; import llm_dojo_scoring as d; from mailroom_sandbox import dojo_source; print(dojo_source.current().source, d.__version__, d.__file__)",
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
    )
    assert child.returncode == 0, child.stderr
    assert "cached 0.28.1" in child.stdout and result["path"] in child.stdout


def test_cache_source_symlink_and_invalid_metadata_are_rejected(release_api, tmp_path):
    result = s.fetch("dojo", version=TAG)
    lock_path = Path(result["lock_path"])
    source = Path(result["path"])
    other = tmp_path / "other"
    source.rename(other)
    source.symlink_to(other, target_is_directory=True)
    with pytest.raises(s.SnapshotError, match="symlinked"):
        s.verify(lock_path, "dojo")
    source.unlink()
    other.rename(source)
    lock = json.loads(lock_path.read_text())
    lock["fetched_at"] = None
    lock_path.write_text(json.dumps(lock))
    assert "fetch date" in s.cached("dojo")[1][0]


def test_release_pin_commits_match_vendor_refresh_contract():
    from mailroom_sandbox.cli import _VENDOR_PINS

    pins = {name: sha for name, _tag, _url, sha in _VENDOR_PINS}
    assert all(
        s.PINS[component]["commit"] == pins[repo] for component, repo in s.COMPONENTS.items()
    )


@pytest.mark.parametrize("missing_bytes", [1, 8, 12])
def test_truncated_gzip_trailer_is_refused(tmp_path, missing_bytes):
    with pytest.raises(s.SnapshotError, match="Invalid archive"):
        s._extract(archive()[:-missing_bytes], tmp_path, wheel=False)


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/git/ref/", {"object": []}),
        ("/releases/", {"tag_name": TAG, "draft": False, "prerelease": False, "assets": [None]}),
        (
            "release-manifest.json",
            {"package": "llm-dojo-scoring", "tag": TAG, "commit": COMMIT, "files": [None]},
        ),
    ],
)
def test_invalid_release_metadata_is_refused(release_api, monkeypatch, endpoint, payload):
    original = s._get
    monkeypatch.setattr(
        s,
        "_get",
        lambda url, **kwargs: (
            json.dumps(payload).encode() if endpoint in url else original(url, **kwargs)
        ),
    )
    with pytest.raises(s.SnapshotError, match="Invalid"):
        s.fetch("dojo", version=TAG)
    assert not list(s.cache_root().glob("*/**/snapshot.lock.json"))
