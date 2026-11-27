"""Phase 5 part 2: job.long_document_head, head reads for the sorter (HF-032) and intake (HF-033).

Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 6); design part 5.
"""

from __future__ import annotations

import pytest

from mailroom_sandbox import merger_reads
from mailroom_sandbox import vendor_hotfixes as vh
from mailroom_sandbox.job import call_guard

LONG = "".join(f"Paragraph {n}: the parties agree to the terms set out in this section.\n" for n in range(6_000))
assert len(LONG) > merger_reads.HEAD_THRESHOLD + 100_000


@pytest.fixture
def api(monkeypatch):
    assert vh.apply_hotfixes()["HF-032"] == "applied"
    monkeypatch.setattr(vh, "_api_route", lambda agent_name: True)
    yield
    merger_reads.activate_head(False)


def sorter_input(text: str, monkeypatch, *, head: bool = True, budget: int = 600_000) -> str:
    from agents.sorter import SorterAgent
    from langchain_agents.sorter_agent import SorterAgent as Base

    sent: list[str] = []
    monkeypatch.setattr(Base, "classify_json", lambda self, composed, **kw: sent.append(composed) or
                        {"doc_type": "merger_agreement", "doc_subclass": "all_cash", "confidence": 0.9})
    merger_reads.activate_head(head)
    agent = SorterAgent()
    agent._max_input_chars = budget
    agent.classify_json(text)
    return sent[0]


def intake_result(text: str, monkeypatch, *, head: bool = True, cleaned: str | None = None) -> tuple[dict, list[str]]:
    from agents.intake import IntakeAgent

    windows: list[str] = []

    def one(self, window, label):
        windows.append(window)
        return {"triage": {"primary_doc_class": "merger_agreement", "confidence": 0.8},
                "cleaned_text": cleaned if cleaned is not None else window, "changes_applied": ["x"], "sections": []}

    monkeypatch.setattr(IntakeAgent, "_call_one", one)
    monkeypatch.setattr(IntakeAgent, "_configured_max_input_chars", lambda self: 600_000)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")  # construction only; _call_one is scripted
    merger_reads.activate_head(head)
    return IntakeAgent().intake_run(text, filename="long.txt"), windows


def test_off_by_default_a_long_document_still_reads_whole(api, monkeypatch):
    assert sorter_input(LONG, monkeypatch, head=False) == LONG


def test_on_a_sorter_read_over_the_threshold_sends_head_and_tail_only(api, monkeypatch):
    sent = sorter_input("x" * 400_000, monkeypatch)
    assert len(sent) < 130_000 and sent.startswith("x" * 1000) and "characters of the document omitted" in sent
    assert sent.endswith("x" * merger_reads.SORTER_TAIL)


def test_a_document_at_or_under_the_threshold_is_untouched(api, monkeypatch):
    text = "y" * merger_reads.HEAD_THRESHOLD
    assert sorter_input(text, monkeypatch) == text
    result, windows = intake_result(text, monkeypatch)
    assert windows == [text]


def test_intake_reads_only_the_first_forty_thousand(api, monkeypatch):
    result, windows = intake_result(LONG, monkeypatch)
    assert len(windows) == 1 and windows[0].startswith(LONG[:1000])
    assert len(windows[0]) < merger_reads.INTAKE_HEAD + 200
    assert result["triage"]["primary_doc_class"] == "merger_agreement"


def test_a_head_read_intake_never_replaces_the_document(api, monkeypatch):
    result, _ = intake_result(LONG, monkeypatch, cleaned=LONG[: merger_reads.INTAKE_HEAD].replace("  ", " ") + "!")
    assert not result.get("cleaned") and "clean_stats" not in result and result.get("changed") is False
    assert result["clean_refused"] == "head_read"


def test_a_self_hosted_route_is_left_to_its_windows(monkeypatch):
    assert vh.apply_hotfixes()["HF-032"] == "applied"
    monkeypatch.setattr(vh, "_api_route", lambda agent_name: False)
    try:
        assert sorter_input(LONG, monkeypatch) == LONG
        _, windows = intake_result(LONG, monkeypatch)
        assert windows == [LONG]
    finally:
        merger_reads.activate_head(False)


def test_a_long_contract_extraction_still_reads_the_whole_document(api, monkeypatch):
    from graph import build_graph

    class Specialist:
        agent_name = "contracts_specialist"
        _max_input_chars = 900_000
        seen: list[int] = []

        def __init__(self, *a, **k):
            pass

        def extract(self, doc_text, pages=None):
            Specialist.seen.append(len(doc_text))
            return {"confidence": 0.9}

    merger_reads.activate_head(True)
    monkeypatch.setattr(build_graph, "_specialist_input_budget", lambda agent: 900_000)
    build_graph._run_chunked_extraction(Specialist, LONG, None, None)
    assert Specialist.seen == [len(LONG)]


def test_hf010_still_refuses_a_multi_window_read_when_the_switch_is_off(api, monkeypatch):
    with pytest.raises(vh.WholeDocumentTooLong):
        sorter_input(LONG, monkeypatch, head=False, budget=100_000)


def test_with_the_switch_on_a_read_over_the_budget_is_a_head_read_not_a_refusal(api, monkeypatch):
    sent = sorter_input(LONG, monkeypatch, budget=200_000)
    assert len(sent) < 130_000


def test_the_head_read_is_recorded(api, monkeypatch):
    with call_guard.document() as scope:
        sorter_input(LONG, monkeypatch)
        intake_result(LONG, monkeypatch)
    marks = scope["head_read"]
    assert [m["agent"] for m in marks] == ["sorter", "intake"]
    assert all(m["doc_chars"] == len(LONG) and m["chars_sent"] < m["doc_chars"] for m in marks)


def test_repeated_apply_keeps_one_layer_per_fix_on_a_shared_target():
    from agents.intake import IntakeAgent

    for _ in range(3):
        status = vh.apply_hotfixes()
    assert status["HF-003"] == "applied" and status["HF-033"] == "applied"
    layers, fn = [], IntakeAgent.intake_run
    while fn is not None:
        layers.append(getattr(fn, "__dict__", {}).get("_sandbox_hotfix"))
        fn = getattr(fn, "__wrapped__", None)
    assert [x for x in layers if x] == ["HF-033", "HF-003"]
