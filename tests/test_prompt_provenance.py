"""Prompt provenance for experiment logs (issue #39)."""

from __future__ import annotations

from mailroom_sandbox.eval.prompt_provenance import resolve_logged_prompt_version


def test_resolve_prefers_explicit_prompt_version():
    label, sha = resolve_logged_prompt_version(
        "sorter_local_v0",
        task="sorter",
        prompt_lock={
            "agents": {
                "sorter": {
                    "source": "local",
                    "file": "ignored_when_explicit",
                    "sha256": "deadbeef",
                }
            }
        },
    )
    assert label == "sorter_local_v0"
    assert sha == "deadbeef"


def test_resolve_local_lock_stem():
    label, sha = resolve_logged_prompt_version(
        None,
        task="contracts_specialist",
        prompt_lock={
            "agents": {
                "contracts_specialist": {
                    "source": "local",
                    "file": "contracts_specialist_v33",
                    "sha256": "abc123",
                }
            }
        },
    )
    assert label == "contracts_specialist_v33"
    assert sha == "abc123"


def test_resolve_bound_prompt_when_unpinned():
    label, sha = resolve_logged_prompt_version(None, task="sorter")
    assert label != "mailroom-default"
    assert sha is None
