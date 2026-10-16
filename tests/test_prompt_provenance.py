"""Prompt provenance for experiment logs (issue #39)."""

from __future__ import annotations

import pytest

from mailroom_sandbox.eval.prompt_provenance import (
    resolve_logged_prompt_version,
    stamp_prompt_provenance,
)


@pytest.mark.parametrize(
    "agent,sha",
    (
        (
            "corporate_records_specialist",
            "fe13501f667fcd9f64f7dfbf8b0f124f81d9dd039f4109288b43f106f82b1399",
        ),
        (
            "correspondence_specialist",
            "2b0b81ff98920b9207627707443e2b023db39212fda5bdcba7bfbded39fa38b6",
        ),
    ),
)
@pytest.mark.parametrize("source", ("explicit_stem", "explicit_key", "agent_lock", "default_lock"))
def test_refrozen_prompt_provenance_uses_corrected_catalog_digest(agent, sha, source):
    """All catalog resolution paths must log the corrected v1 digest."""
    stem = f"{agent}_simplified"
    key = f"{agent}_v1"
    prompt_version = None
    prompt_lock = None
    if source == "explicit_stem":
        prompt_version = stem
    elif source == "explicit_key":
        prompt_version = key
    elif source == "agent_lock":
        prompt_lock = {"agents": {agent: {"source": "local", "file": stem}}}
    else:
        prompt_lock = {"default": {"source": "local", "file": stem}}

    label, actual_sha = resolve_logged_prompt_version(
        prompt_version, task=agent, prompt_lock=prompt_lock
    )
    assert (label, actual_sha) == (key, sha)

    record = {"task": agent}
    stamp_prompt_provenance(record, label, actual_sha)
    assert record == {
        "task": agent,
        "prompt_version": key,
        "prompt_sha256": sha,
        "eval_environment_prompt_key": key,
        "prompt_stem": stem,
    }


@pytest.mark.parametrize(
    "agent,previous_sha",
    (
        (
            "corporate_records_specialist",
            "484e64dd847b7bb35afebca74edc1fb6c381f0f7d5e9367ad8673bec0b8af45c",
        ),
        (
            "correspondence_specialist",
            "eab63b5afd29906b1ad3aca2d7698bf5c15d4b7f4ce9ade3b744be535d18d4f3",
        ),
    ),
)
def test_historical_prompt_lock_keeps_its_previous_digest(agent, previous_sha):
    """Historical scores must retain the identity of the bytes actually used."""
    label, sha = resolve_logged_prompt_version(
        None,
        task=agent,
        prompt_lock={
            "agents": {
                agent: {"source": "local", "file": f"{agent}_simplified", "sha256": previous_sha}
            }
        },
    )

    assert (label, sha) == (f"{agent}_v1", previous_sha)
    record = {"task": agent}
    stamp_prompt_provenance(record, label, sha)
    assert record["prompt_sha256"] == previous_sha


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


def test_resolve_catalog_stem_logs_eval_environment_key():
    """Resolve a catalog stem to its eval-environment key and locked digest."""
    label, sha = resolve_logged_prompt_version(
        None,
        task="correspondence_specialist",
        prompt_lock={
            "agents": {
                "correspondence_specialist": {
                    "source": "local",
                    "file": "correspondence_specialist_simplified",
                    "sha256": "2b0b81ff98920b9207627707443e2b023db39212fda5bdcba7bfbded39fa38b6",
                }
            }
        },
    )
    assert label == "correspondence_specialist_v1"
    assert sha == "2b0b81ff98920b9207627707443e2b023db39212fda5bdcba7bfbded39fa38b6"


def test_resolve_explicit_simplified_stem_is_eval_environment_v1():
    """Map an explicit simplified stem to its frozen v1 label and digest."""
    label, sha = resolve_logged_prompt_version(
        "contracts_specialist_v33_simplified",
        task="contracts_specialist",
    )
    assert label == "contracts_specialist_v1"
    assert sha == "d91de3967cc3b12cbd222cc5a4ae167b39578125abc83be7422498dc5024fd24"


def test_resolve_bound_prompt_when_unpinned():
    label, sha = resolve_logged_prompt_version(None, task="sorter")
    assert label != "mailroom-default"
    assert sha is None
