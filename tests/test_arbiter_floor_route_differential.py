"""HF-014 at the router: the same states routed with and without the rule (offline, no graph run).

``route_spec.decide_route`` is called for the nodes HF-014 can touch (``arbiter`` and, through
HF-011's skip check, ``judge_verify``) on a grid of states, once with the registered HF-014 rule and
once with that rule removed (the vendored routes plus HF-011). The grid crosses extraction
confidence, source verification, document length (inside the 16k excerpt, past it, past the widened
OpenRouter window), lost chunks, a matter conflict and the Boss's approval of it, the arbiter's decision, the judge's
verdict and pass count and the arbiter retry count. It is a router-level
check, not a model or pipeline measurement.

Pinned: at the default floor (the class ``low``) HF-014 changes no route on either profile; with the
floor lowered to 0.5 it changes routes on OpenRouter only (Modal/vLLM keeps 16k excerpts, so the
rule never answers); a floor above ``low`` (0.95) changes none either, because the rule can only
turn a park into an archive. The counts in ``EXPECTED`` are the figures the CHANGELOG and ``docs/critical-regressions.md``
(row 22) cite.
"""
from __future__ import annotations

import itertools
from collections import Counter
from types import MappingProxyType

import pytest
from _arbiter_harness import activate_profile

from mailroom_sandbox import source_windows

LOW = 0.86  # corporate_record ``low``; asserted against the taxonomy below
FLOOR = 0.5
ABOVE_LOW = 0.95  # a floor above the class ``low``
CONFS = (None, 0.3, LOW - 0.01, LOW, 0.99)
LENGTHS = (100, 20_000, 700_000)  # inside 16k, past 16k, past the widened 600,115-character window
DECISIONS = ("accept_with_caveats", "retry_extraction", "human_review", None)
VERDICTS = ("partial", "incomplete", "complete", None)
#: confidence, judge_source_verified, length, chunks lost, conflict, decision, verdict, passes, retries,
#: conflict approved by the Boss
GRID = tuple(itertools.product(CONFS, (False, True), LENGTHS, (False, True), (False, True), DECISIONS,
                               VERDICTS, (1, 2), (0, 2), (False, True)))
GRID_SIZE = 15_360  # states: 5 * 2 * 3 * 2 * 2 * 4 * 4 * 2 * 2 * 2; each is routed at two nodes

#: per profile and floor: {(node, route without HF-014, route with it): states}
EXPECTED = {
    ("openrouter", None): {},
    ("modal-vllm", None): {},
    ("openrouter", FLOOR): {("arbiter", "human_review", "compile_report"): 96,
                            ("judge_verify", "human_review", "arbiter"): 48},
    ("modal-vllm", FLOOR): {},
    # HF-014 only ever turns a park into an archive, and the vendored route already archives at or
    # above ``low``: a floor above ``low`` parks nothing the vendored route archives (it is a no-op)
    ("openrouter", ABOVE_LOW): {},
    ("modal-vllm", ABOVE_LOW): {},
}


def _state(g):
    from graph.routing import conflict_fingerprint

    conf, verified, length, lost, conflict, decision, verdict, passes, retries, approved = g
    state = {"doc_type": "corporate_record", "extraction_confidence": conf, "judge_source_verified": verified,
             "doc_text": "x" * length, "arbiter_decision": decision, "judge_verdict": verdict,
             "judge_pass_count": passes, "arbiter_retry_count": retries, "boss_conflict_fingerprint": None,
             "extracted_data": {"_failed_chunks": [1]} if lost else {}}  # what ``routing._chunks_lost`` reads
    if conflict:
        details = {"field": "a", "values": ["b", "c"]}
        state.update(conflict_detected=True, conflict_details=details)
        if approved:  # the Boss ruled on this very conflict
            state.update(review_decision="approved", boss_conflict_fingerprint=conflict_fingerprint(details))
    return state


def _routes(route_spec, specs):
    out = {}
    for g in GRID:
        state = _state(g)
        for node, spec in specs.items():
            out[g, node] = route_spec.decide_route(spec, state)
    return out


@pytest.mark.parametrize("floor", [None, FLOOR, ABOVE_LOW], ids=["default-floor", "floor-0.5", "floor-above-low"])
@pytest.mark.parametrize("profile", ["openrouter", "modal-vllm"])
def test_hf014_moves_no_route_at_or_above_the_default_floor_and_only_on_openrouter_below_it(
        profile, floor, monkeypatch, tmp_path):
    from mailroom_sandbox import vendor_hotfixes as vh

    activate_profile(monkeypatch, tmp_path, profile)
    try:
        from graph import route_spec, routing

        assert len(GRID) == GRID_SIZE
        assert routing._thresholds_for({"doc_type": "corporate_record"})["low"] == LOW
        specs = {s.node: s for s in route_spec.ROUTE_SPECS if s.node in ("arbiter", "judge_verify")}
        assert set(specs) == {"arbiter", "judge_verify"}
        assert vh.FULL_SOURCE_RULE in [r.name for r in route_spec.route_rules("arbiter")]
        if floor is not None:  # the key a run's ``confidence`` block would carry
            original = routing._thresholds_for
            monkeypatch.setattr(routing, "_thresholds_for",
                                lambda state: {**original(state), "arbiter_full_source_min_confidence": floor})
        with_rule = _routes(route_spec, specs)
        rules = {node: tuple(r for r in rs if r.name != vh.FULL_SOURCE_RULE)
                 for node, rs in route_spec._RULES.items()}
        monkeypatch.setattr(route_spec, "_RULES", MappingProxyType(rules))
        without_rule = _routes(route_spec, specs)
    finally:
        source_windows.apply_source_windows({})
    diffs = Counter((key[1], without_rule[key], with_rule[key]) for key in with_rule
                    if with_rule[key] != without_rule[key])
    assert dict(diffs) == EXPECTED[profile, floor]
    for g, _node in (key for key in with_rule if with_rule[key] != without_rule[key]):
        conf, _verified, length, lost, conflict, *_, approved = g
        # only an unsure extraction (under the class ``low``, over the lowered floor), whole in the window,
        # with no lost chunk and no conflict the Boss has not ruled on
        assert conf is not None and FLOOR <= conf < LOW and length < 600_115 and not lost, g
        assert approved or not conflict, g
