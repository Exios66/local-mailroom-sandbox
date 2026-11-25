"""On a context-fitted OpenRouter route the judge and both arbiters read the whole document.

Network-free. Each case preflights a run spec offline, activates it through the run lock
(``locked_runtime`` + ``activate()``, as ``runner`` does), and records the prompts the vendored
judge and arbiter agents build for a long synthetic document. Modal/vLLM keeps the vendored
16k-char excerpts.
"""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox import source_windows

# A 250k-character document: longer than every vendored 16k excerpt and the old 120k decision
# windows, shorter than every fitted OpenRouter budget. Only the last line holds the marker.
_LINE = "Section {n}. Cedar Sample Ltd shall deliver the goods described in Schedule A to Birch Example LLC.\n"
TAIL = "FINAL CLAUSE: this agreement is governed by the laws of Exampleshire."
LONG_DOC = "".join(_LINE.format(n=n) for n in range(2500)) + TAIL
TRUNCATED = "document truncated"


@pytest.fixture
def activated(tmp_path, monkeypatch):
    """Activate ``profile`` the way a locked run does; restore the vendored windows afterwards."""
    from mailroom_sandbox.job import preflight
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, run_dir
    from mailroom_sandbox.runtime import activate, locked_runtime

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    data = tmp_path / "f.jsonl"
    data.write_text(json.dumps({"id": "d0", "filename": "0.txt", "doc_text": "t", "expected": "contract",
                                "expected_subclass": "service"}) + "\n")
    engines = {"openrouter": {"kind": "openrouter", "model": "qwen/qwen3.5-9b", "modal": None},
               "modal-vllm": {"kind": "vllm-local", "modal": None}}

    def _activate(profile: str):
        spec = RunSpec(run_id=f"full-source-{profile}", task="pipeline", profile=profile,
                       dataset=DatasetSpec(local_path=f"file://{data}", limit=1), engine=engines[profile],
                       trace={"sink": "none"},
                       job={"mock": True, "max_wall_seconds": 600, "cost_cap_usd": 0.1, "api_cost_cap_usd": 0.1})
        report = preflight.preflight(spec, offline=True)
        assert report["status"] == "prepared", report
        store = RunStore(run_dir(report["run_id"]))
        with locked_runtime(store.read_lock(), store.read_prompt_lock() or {}):
            activate()
        return store.read_lock()

    yield _activate
    source_windows.apply_source_windows({})


@pytest.fixture
def prompts(monkeypatch):
    """Every user prompt the judge and arbiter agents send, by agent."""
    seen: dict[str, list[str]] = {"judge": [], "arbiter": [], "carb": []}

    def install():
        from agents.arbiter import ArbiterAgent, ClassificationArbiterAgent
        from agents.judge import CompletenessJudge

        def judge(self, user_message, *a, **k):
            seen["judge"].append(user_message)
            if user_message.startswith("Evaluate extraction completeness"):
                return {"completeness": 0.97, "completeness_label": "complete", "reasoning": "ok"}
            return {"extraction_correctness": 0.97, "extraction_correctness_label": "accurate", "reasoning": "ok"}

        def arbiter(self, user_message, *a, **k):
            if "SORTER ANSWER" in user_message:
                seen["carb"].append(user_message)
                return {"decision": "accept_sorter", "confidence": 0.99, "reasoning": "ok"}
            seen["arbiter"].append(user_message)
            return {"decision": "accept_with_caveats", "fields_to_fix": [], "reasoning": "ok", "handoff_summary": ""}

        monkeypatch.setattr(CompletenessJudge, "_call_structured", judge)
        monkeypatch.setattr(ArbiterAgent, "_call_structured", arbiter)
        monkeypatch.setattr(ClassificationArbiterAgent, "_call_structured", arbiter)
        return CompletenessJudge, ArbiterAgent, ClassificationArbiterAgent

    return seen, install


def _exercise(install, doc: str) -> dict:
    judge_cls, arbiter_cls, carb_cls = install()
    extracted = {"parties": ["Cedar Sample Ltd", "Birch Example LLC"]}
    judge = judge_cls.__new__(judge_cls)
    judge.judge_completeness("contract", extracted, doc)
    judge.judge_extraction_correctness("contract", extracted, doc)
    arbiter_cls.__new__(arbiter_cls).arbitrate(
        doc_type="contract", extracted=extracted, judge_verdict="partial", judge_findings=["x"], doc_text=doc)
    return carb_cls.__new__(carb_cls).arbitrate_classification(
        sorter={"doc_type": "contract", "confidence": 0.9}, reviewer={"doc_type": "unknown", "confidence": 0.0},
        causes=["reviewer_unavailable"], labels=["contract", "correspondence"], doc_text=doc)


def test_openrouter_judge_and_arbiters_read_the_whole_long_document(activated, prompts):
    import agents.arbiter as arbiter_mod
    import agents.judge as judge_mod

    seen, install = prompts
    lock = activated("openrouter")
    assert len(LONG_DOC) > 200_000
    windows = {"judge": judge_mod.JUDGE_SOURCE_CHARS, "arbiter": arbiter_mod.SOURCE_CHARS,
               "classification_arbiter": arbiter_mod.CLASSIFICATION_SOURCE_CHARS}
    assert min(windows.values()) >= len(LONG_DOC), windows
    assert judge_mod.CompletenessJudge._truncate(LONG_DOC) == LONG_DOC
    applied = (lock.get("context_fit") or {}).get("applied") or {}
    assert {"judge", "arbiter"} <= set(applied), sorted(applied)

    ruling = _exercise(install, LONG_DOC)
    assert len(seen["judge"]) == 2 and len(seen["arbiter"]) == 1
    for prompt in seen["judge"] + seen["arbiter"]:
        assert TAIL in prompt and TRUNCATED not in prompt
    # the classification arbiter made its model call instead of the oversize skip
    assert len(seen["carb"]) == 1 and TAIL in seen["carb"][0]
    assert ruling["decision"] == "accept_sorter"


def test_modal_vllm_keeps_the_vendored_16k_excerpts(activated, prompts):
    import agents.arbiter as arbiter_mod
    import agents.judge as judge_mod

    seen, install = prompts
    activated("openrouter")  # a widened activation first: Modal must not inherit it
    activated("modal-vllm")
    assert (judge_mod.JUDGE_SOURCE_CHARS, arbiter_mod.SOURCE_CHARS,
            arbiter_mod.CLASSIFICATION_SOURCE_CHARS) == (16000, 16000, 16000)

    ruling = _exercise(install, LONG_DOC)
    for prompt in seen["judge"] + seen["arbiter"]:
        assert TAIL not in prompt and TRUNCATED in prompt
    assert seen["carb"] == [] and ruling["decision"] == "human_review"
