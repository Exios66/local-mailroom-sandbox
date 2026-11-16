"""The contract second-pass judge ``TypeError`` (slice-gate task 9, Exios66/llm-mailroom#260).

r3 ``DOC-47d391f2646c0506`` and E3 ``DOC-2fbe8b3db2901e16`` parked as ``judge_error`` with only
"judge verification failed (TypeError)" recorded. Replaying the retried contract extraction through
the judge with a stub LLM runs cleanly (first test), so the judge input is not the cause. A 200
response whose ``choices`` is null, the shape OpenRouter returns when an upstream provider fails,
reproduces the exact ``TypeError``, and it is not classed as transient, so the node parks the
document instead of retrying (second test, strict xfail until the upstream fix is vendored).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("langchain_core")
import mailroom_sandbox  # noqa: E402,F401 — put vendor on sys.path

# The shape of the stored second-pass extraction (E3 DOC-2fbe8b3db2901e16, after the retry): content
# fields, an empty MAUD list on a contract, and a per-field ``reasoning`` dict the judge must drop.
RETRIED_CONTRACT = {
    "document_name": "Strategic Alliance Agreement",
    "parties": ['UTEK Corporation ("UTEK")', 'Manakoa Services Corporation ("MKOS")'],
    "party_roles": ["UTEK Corporation: Service Provider / Ally", "Manakoa Services Corporation: Client / Ally"],
    "signatories": ["Doug Schaedler", "Chris Outwater"],
    "agreement_date": "2006-06-14", "effective_date": None, "expiration_date": None,
    "term_length": "12 months", "termination_notice_period": "30 days", "governing_law": None,
    "dispute_forum": None, "contract_value": "$120,000", "payment_terms": "$120,000 in shares",
    "territory": None, "renewal_terms": "renewed upon mutual, written agreement",
    "cuad_family": "strategic_alliance", "merger_consideration": None,
    "cuad_clauses": ["Parties: UTEK Corporation and Manakoa Services Corporation"], "maud_clauses": [],
    "reasoning": {"summary": "A strategic alliance agreement between UTEK and Manakoa."},
}
DOC_TEXT = "STRATEGIC ALLIANCE AGREEMENT between UTEK Corporation and Manakoa Services Corporation. " * 40


def _judge(create):
    from agents.judge import CompletenessJudge  # type: ignore

    judge = CompletenessJudge.__new__(CompletenessJudge)
    judge.agent_name, judge.model, judge._langfuse_prompt = "judge", "qwen/qwen3.7-flash", None
    judge.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                                   base_url="https://openrouter.ai/api/v1")
    judge.system_prompt = lambda: "sys"
    return judge


def _response(content):
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None, model="qwen/qwen3.7-flash")


def test_second_pass_judge_accepts_retried_contract_extraction():
    from graph.build_graph import _clean_fields_for_judge  # type: ignore

    verdict = {"completeness": 1.0, "completeness_label": "complete", "reasoning": "ok",
               "extraction_correctness": 1.0, "extraction_correctness_label": "accurate"}
    judge = _judge(lambda **kw: _response(json.dumps(verdict)))
    cleaned = _clean_fields_for_judge(RETRIED_CONTRACT)
    assert "reasoning" not in cleaned
    assert judge.judge_completeness(doc_type="contract", extracted=cleaned, doc_text=DOC_TEXT)[
        "completeness_label"] == "complete"
    assert judge.judge_extraction_correctness(doc_type="contract", extracted=cleaned, doc_text=DOC_TEXT)[
        "extraction_correctness_label"] == "accurate"


@pytest.mark.xfail(strict=True, reason="Exios66/llm-mailroom#260: a 200 response with null choices raises a "
                   "non-transient TypeError, so judge_verify_node parks the document as judge_error")
def test_null_choices_response_is_a_transient_provider_error():
    from llm.retry import is_transient_error  # type: ignore

    def create(**kwargs):
        return SimpleNamespace(choices=None, usage=None, model="qwen/qwen3.7-flash",
                               error={"code": 502, "message": "upstream provider error"})

    with pytest.raises(Exception) as caught:
        _judge(create).judge_completeness(doc_type="contract", extracted={"document_name": "x"}, doc_text="text")
    assert is_transient_error(caught.value)
