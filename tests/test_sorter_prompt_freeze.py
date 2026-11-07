"""V15 stays frozen as the sorter reference; production is the condensed lineage
(mirror of llm-mailroom's src/tests/test_sorter_prompt_freeze.py), so a vendor sync
cannot bring back V14."""

import hashlib

import pytest

prompts = pytest.importorskip("langchain_agents.prompts")

SORTER_V15_SHA256 = "78f95ca4b6b40bc35e91c7e8fcf4593a3ae3f7fb0989350a4a6ca49d83d50666"
BROKEN_SHA256 = {"905abc696c1975d5fe29c3f773738ac6836993d8f8e4cef40d1f6c30012e164f"}  # V14


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_vendored_v15_is_frozen():
    assert _sha(prompts.PROMPT_VERSIONS["sorter_v15"]) == SORTER_V15_SHA256


def test_production_is_the_condensed_lineage():
    """Production is the adopted condensed prompt, kept byte-equal with the sandbox lineage file."""
    from mailroom_sandbox.paths import prompts_dir

    production = prompts.PROMPT_VERSIONS["sorter"]
    assert production is prompts.PROMPT_VERSIONS["sorter_condensed_v5"]
    assert production == (prompts_dir() / "sorter_condensed_v5.txt").read_text(encoding="utf-8")
    assert _sha(production) not in BROKEN_SHA256
    assert len(production) * 4 < len(prompts.PROMPT_VERSIONS["sorter_v15"])
    for clause in (
        "indenture",
        "All mailbox text is correspondence",
        "carrier, never outpatient",
        "officer_certificate, never rights_instrument",
        "FIRST form in catalog order",
        "conversion section",
        "a bylaw amendment is bylaws, never board_resolution",
    ):
        assert clause in production, clause
    assert "bylaw amendment is board_resolution" not in production


def test_every_later_version_keeps_the_guards():
    for key, text in prompts.PROMPT_VERSIONS.items():
        tail = key.removeprefix("sorter_v")
        if tail.isdigit() and int(tail) >= 15:
            assert all(g in text for g in prompts.SORTER_V15_GUARDS), key


def test_sandbox_registry_pins_the_condensed_lineage():
    from mailroom_sandbox.prompt_registry import FAMILY_B_KEYS

    assert FAMILY_B_KEYS["sorter"] == "sorter_condensed_v5"
