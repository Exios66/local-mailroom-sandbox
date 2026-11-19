"""House figure style, per-run figures and sorter-arm comparison figures: colour roles, text
conventions, determinism and the titles that state each figure's finding. Offline."""

from __future__ import annotations

import pytest

from mailroom_sandbox import comparison_figures as cf
from mailroom_sandbox import decision_figures as dfig
from mailroom_sandbox import figure_style as fs


@pytest.mark.parametrize(("kind", "text", "problem"), [
    ("title", "routing outcome per group", "lower-case"),
    ("title", "Nine documents were misarchived.", "full stop"),
    ("title", "Only 1 class error(s) in the run", "hedged plural"),
    ("xlabel", "document_form_human_mass", "identifier"),
    ("title", "Latency for rb1-r13b-smoke20c", "run or document id"),
    ("title", "x" * 81, "over 80"),
])
def test_lint_text_flags_each_convention(kind, text, problem):
    assert any(problem in p for p in fs.lint_text(kind, text))


def test_lint_text_accepts_house_text():
    assert fs.lint_text("title", "Decision model runs finished 3.7–6.3× faster than the LLM sorter") == []
    assert fs.lint_text("xlabel", "Total run time (s)") == []
    assert fs.lint_text("source", "Source: run rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1") == []


def test_humanize_and_reason_labels():
    assert fs.humanize("corporate_record") == "Corporate record"
    assert dfig.reason_label("document_form:fragment_or_excerpt") == "Document form: fragment or excerpt"
    assert dfig.reason_label("margin") == "Class margin too small"
    assert dfig.plural(1, "class error") == "1 class error" and dfig.plural(3, "class error") == "3 class errors"


def test_system_colours_follow_the_task():
    assert fs.SYSTEM_COLOURS[fs.system_of_task("sorter_reviewer")] == fs.DECISION
    assert fs.SYSTEM_COLOURS[fs.system_of_task("isolated")] == fs.LLM
    assert fs.system_of_task("specialist") == "other"


def test_wilson_and_risk_coverage():
    lo, hi = fs.wilson(3, 8)
    assert 0.13 < lo < 0.14 and 0.69 < hi < 0.70
    assert fs.wilson(0, 0) == (0.0, 1.0)
    rows = [{"forced_correct": ok, "class_probability": p} for ok, p in
            ((True, 0.99), (True, 0.9), (False, 0.9), (True, 0.5))]
    # ties at 0.9 enter together; the last point is the full-coverage error rate
    assert dfig.risk_coverage(rows) == [(0.25, 0.0), (0.75, 1 / 3), (1.0, 0.25)]


def _item(i, *, cls="contract", right=True, parked=False, p=0.95, mass=0.1, sub=1.0):
    pred = {"doc_type": cls if right else "correspondence", "doc_type_probability": p,
            "document_form": "complete_instrument", "document_form_human_mass": mass,
            "abstained": parked, "abstain_reasons": ["margin"] if parked else [],
            "usage": {"input_tokens": 4000 + 100 * i, "cost": 0.0004}}
    score = {"expected": cls, "outcome": "correct" if right else "wrong", "subclass_match": sub}
    return {"item_id": f"DOC-{i:04d}", "pred": pred, "score": score, "latency_ms": 500.0 + 10 * i}


def _decision_items():
    items = [_item(i, cls=("contract", "insurance_claim")[i % 2]) for i in range(24)]
    items += [_item(30 + i, right=False, p=0.4 + 0.05 * i) for i in range(5)]
    items += [_item(40, parked=True, p=0.3), _item(41, mass=0.9, parked=True, sub=0.0)]
    return items


def test_decision_run_figure_set_is_lint_clean_and_deterministic():
    items = _decision_items()
    a, rows = dfig.build("rb1-r13b-test-decision", items, wall_s=30.0)
    b, _ = dfig.build("rb1-r13b-test-decision", list(items), wall_s=30.0)
    assert a == b
    assert set(a) == {"routing", "confidence", "risk-coverage", "form-mass", "park-reasons", "subclass", "latency"}
    for name, svg in a.items():
        assert fs.lint_svg(svg) == [], name
        assert "Helvetica Neue" in svg and "rb1-r13b-test-decision" in svg  # stack declared; run id in the source line
    assert len(rows) == len(items) and {"state", "parked", "class_probability"} <= set(rows[0])
    assert "5 of 31 documents were misarchived and 2 parked" in a["routing"]
    assert fs.DECISION in a["subclass"]  # single-series marks wear the system colour


def test_llm_run_reads_string_confidence_and_wears_the_llm_colour():
    items = [{"item_id": f"D{i}", "latency_ms": 2000.0, "prompt_tokens": 3000,
              "pred": {"doc_type": "contract" if i else "correspondence", "confidence": "0.9" if i else "0.4"},
              "score": {"expected": "contract", "outcome": "correct" if i else "wrong", "subclass_match": 1.0}}
             for i in range(6)]
    figs, rows = dfig.build("rb1-r13b-test-llm", items)
    assert rows[1]["class_probability"] == 0.9
    assert {"routing", "confidence", "risk-coverage", "subclass", "latency"} <= set(figs)
    assert fs.LLM in figs["latency"] and fs.DECISION not in figs["latency"]



def test_an_explicit_zero_probability_stays_zero():
    # critical regression 12: a numeric zero is a value, never "missing" with a fallback
    items = [{"item_id": "D0", "pred": {"doc_type": "contract", "doc_type_probability": 0.0, "confidence": 0.9},
              "score": {"expected": "contract", "outcome": "correct"}},
             {"item_id": "D1", "pred": {"doc_type": "contract", "confidence": 0},
              "score": {"expected": "contract", "outcome": "correct"}}]
    rows = dfig.figure_rows(items)
    assert [r["class_probability"] for r in rows] == [0.0, 0.0]

def _arm(run_id, task, model, secs, cost, unit, parked, billed):
    return {"run_id": run_id, "task": task, "model": model, "n": 20, "failed": 0, "unit_accuracy": unit,
            "runtime": {"run_wall_seconds": secs, "run_items": 20, "answered": 20, "failed": 0,
                        "docs_per_minute": 20 / secs * 60, "concurrency": 8,
                        "hours_per_100k_docs": 100_000 / (20 / secs * 60) / 60},
            "routing": {"auto_routed": 20 - parked, "auto_class_accuracy": 1.0, "abstained": parked,
                        "abstain_rate": parked / 20},
            "cost": {"per_1k_docs_usd": cost, "provider_reported_docs": 20 if billed else 0,
                     "provider_reported_usd": cost * 20 / 1000 if billed else None}}


def _report():
    return {"reference": "rb1-r13b-x-llm", "n": 20, "experiment_key": "rb1-r13b", "set": None,
            "margins": {"class_macro_f1": 0.02, "unit_accuracy": 0.04},
            "arms": [_arm("rb1-r13b-x-llm", "isolated", "qwen/qwen3.7-flash", 14.0, 2.01, 0.95, 5, False),
                     _arm("rb1-r13b-b-dec", "sorter_reviewer", "openai/gpt-6-luna-decisions", 4.0, 2.29, 1.0, 4, True),
                     _arm("rb1-r13b-c-dec", "sorter_reviewer", "openai/gpt-6-luna-decisions", 2.0, 2.29, 1.0, 4, True)],
            "pairs": {rid: {"differences": {"class_accuracy": {"estimate": 0.0, "ci95": [0.0, 0.0]},
                                            "class_macro_f1": {"estimate": 0.0, "ci95": [0.0, 0.0]},
                                            "unit_accuracy": {"estimate": 0.05, "ci95": [0.0, 0.15]}},
                            "tests": {"noninferiority_macro_f1": {"non_inferior": False, "lower95_one_sided": -0.17},
                                      "noninferiority_unit": {"non_inferior": False,
                                                             "lower95_one_sided": -0.16}}}
                      for rid in ("rb1-r13b-b-dec", "rb1-r13b-c-dec")}}


def test_arm_labels_name_the_system_and_tell_same_system_runs_apart():
    labels = cf.arm_labels(_report()["arms"])
    assert labels == {"rb1-r13b-x-llm": "LLM sorter", "rb1-r13b-b-dec": "Decision model, b",
                      "rb1-r13b-c-dec": "Decision model, c"}


def test_comparison_titles_state_the_finding_and_the_cost_basis():
    figs = cf.build(_report(), {"rb1-r13b-x-llm": [3.0, 2.5], "rb1-r13b-b-dec": [0.7, 0.8], "rb1-r13b-c-dec": [0.6]})
    assert set(figs) == {"runtime", "latency", "quality", "routing", "cost-quality", "pricing"}
    for name, svg in figs.items():
        assert fs.lint_svg(svg) == [], name
    assert "Decision model runs finished 3.5–7.0× faster than the LLM sorter" in figs["runtime"]
    # 20 documents with an estimated LLM sorter cost: no cost direction is claimed
    assert "Cost is not yet comparable: n = 20 and LLM sorter cost estimated" in figs["cost-quality"]
    assert "list price × tokens; no billed cost: LLM sorter" in figs["cost-quality"]
    for word in ("more per 1,000", "less per 1,000", "cheaper", "cheapest"):
        assert word not in figs["cost-quality"]
    assert "List input price per million tokens, by prompt size" in figs["pricing"]
    assert "OpenRouter list prices" in figs["pricing"]
    assert "Non-inferiority not shown at n = 20: test bounds fall below the margins" in figs["quality"]
    assert "test bound -17.0" in figs["quality"]  # the bound the test decides on is drawn and labelled
    assert "test bound -16.0" in figs["quality"]
    assert figs == cf.build(_report(), {"rb1-r13b-x-llm": [3.0, 2.5], "rb1-r13b-b-dec": [0.7, 0.8],
                                        "rb1-r13b-c-dec": [0.6]})


def test_lint_cli_refuses_an_empty_or_missing_target(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        fs.main(["lint", "--help"])
    assert exc.value.code == 0 and "SVG file or a folder" in capsys.readouterr().out
    assert fs.main(["lint", str(tmp_path)]) == 2  # no SVG: an empty check never passes
    assert fs.main(["lint", str(tmp_path / "missing")]) == 2
    assert "no SVG found" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        fs.main([])
    assert exc.value.code == 2


def test_lint_cli_reports_and_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "bad.svg"
    bad.write_text('<svg><g id="title"><text>lower case title.</text></g></svg>', encoding="utf-8")
    assert fs.main(["lint", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "starts lower-case" in out and "system font stack" in out


def test_cost_direction_is_claimed_only_on_billed_costs_over_a_clean_sample():
    def report(n, billed_llm):
        r = _report()
        r["n"] = n
        for a in r["arms"]:
            a["n"] = n
            bill = billed_llm or not a["run_id"].endswith("-llm")
            a["cost"]["provider_reported_docs"] = n if bill else 0
            a["cost"]["provider_reported_usd"] = a["cost"]["per_1k_docs_usd"] * n / 1000 if bill else None
        return r

    small = cf.build(report(20, True))["cost-quality"]
    assert "Cost is not yet comparable: n = 20" in small and "more per 1,000" not in small
    big_estimated = cf.build(report(cf.COST_CLAIM_MIN_DOCS, False))["cost-quality"]
    assert "Cost is not yet comparable: LLM sorter cost estimated" in big_estimated
    clean = cf.build(report(cf.COST_CLAIM_MIN_DOCS, True))["cost-quality"]
    assert "Decision model runs cost $0.28 more per 1,000 documents than the LLM sorter" in clean
    assert "all costs as billed" in clean
    for svg in (small, big_estimated, clean):
        assert fs.lint_svg(svg) == []


def test_pricing_figure_marks_each_documents_prompt_size():
    svg = cf.build(_report(), prompt_tokens={"rb1-r13b-x-llm": [5_000.0, 40_000.0],
                                             "rb1-r13b-b-dec": [6_000.0, 41_000.0]})["pricing"]
    assert "LLM sorter calls" in svg and "Decision model calls" in svg
    assert fs.LLM in svg and fs.DECISION in svg
    assert fs.lint_svg(svg) == []


def _run_item(i, **kw):
    item = {"item_id": f"D{i}", "latency_ms": 1000.0 * (i + 1), "prompt_tokens": 3000,
            "pred": {"doc_type": "contract", "confidence": 0.9},
            "score": {"expected": "contract", "outcome": "correct", "subclass_match": 1.0}}
    item.update(kw)
    return item


def test_a_failed_request_is_its_own_state_never_archived():
    rows = dfig.figure_rows([_run_item(0), _run_item(1, ok=False, error="timeout", pred={}, score={})])
    assert [r["state"] for r in rows] == ["correct", "failed"]
    assert rows[1]["forced_correct"] is None
    figs, _ = dfig.build("rb1-r13b-test-llm", [_run_item(0), _run_item(1, ok=False, error="timeout", pred={}, score={})])
    assert "Failed, no answer" in figs["routing"] and "failed 50%" in figs["routing"]


def test_whole_run_sorter_items_with_top_level_truth_are_scored():
    items = [{"item_id": "D0", "expected": "contract", "predicted": "Contract", "ok": True},
             {"item_id": "D1", "expected": "insurance_claim", "predicted": "correspondence", "ok": True}]
    rows = dfig.figure_rows(items)
    assert [r["state"] for r in rows] == ["correct", "misarchived"]
    figs, _ = dfig.build("rb1-r13b-test-llm", items)
    assert "1 of 2 documents was misarchived" in figs["routing"]


def test_forced_answers_fold_labels_as_the_scorer_does():
    from mailroom_sandbox.eval.agents import _fold

    rows = dfig.figure_rows([_run_item(0, pred={"doc_type": "Insurance claim"},
                                       score={"expected": "insurance_claim", "outcome": "correct"}),
                             _run_item(1, pred={"doc_type": "insurance-claim"},
                                       score={"expected": "insurance_claim", "outcome": "correct"})])
    assert [r["forced_correct"] for r in rows] == [True, True]
    for label in ("Insurance claim", "insurance-claim", " INSURANCE   claim "):
        assert dfig._fold(label) == _fold(label)


def test_latency_median_and_p95_use_the_shared_definitions():
    figs, _ = dfig.build("rb1-r13b-test-llm", [_run_item(0, latency_ms=1000.0), _run_item(1, latency_ms=9000.0)])
    assert "Median latency was 5.00 s per document" in figs["latency"]


def test_auroc_titles_follow_its_direction_and_keep_a_zero():
    items = [_run_item(i, pred={"doc_type": "contract", "confidence": 0.1}) for i in range(5)] + [
        _run_item(i + 5, pred={"doc_type": "letter", "confidence": 0.9},
                  score={"expected": "contract", "outcome": "wrong"}) for i in range(5)]
    figs, _ = dfig.build("rb1-r13b-test-llm", items)
    assert "Class probability ranks wrong above right answers (AUROC 0.00)" in figs["confidence"]
    assert "AUROC 0.000" in figs["confidence"]


def test_simulated_comparisons_say_so_on_every_figure():
    r = _report()
    r["simulated"] = True
    figs = cf.build(r, {"rb1-r13b-x-llm": [3.0], "rb1-r13b-b-dec": [0.7], "rb1-r13b-c-dec": [0.6]})
    for name, svg in figs.items():
        assert "SIMULATED: mock runs, not evidence" in svg, name
        assert "Simulated" in svg, name


def test_latency_strip_skips_a_series_with_no_positive_values():
    figs = cf.build(_report(), {"rb1-r13b-x-llm": [0.0], "rb1-r13b-b-dec": [1.0, 9.0]})
    assert "median 5.00 s" in figs["latency"]


def test_runtime_uses_active_time_when_the_comparison_is_a_subset_of_the_run():
    r = _report()
    for a in r["arms"]:
        a["runtime"]["run_items"] = 100  # a --set subset of a larger run
        a["runtime"]["active_seconds"] = a["runtime"]["run_wall_seconds"] / 2
    svg = cf.build(r)["runtime"]
    assert "Active time, first request to last answer, on the same 20 documents" in svg
    r["arms"][0]["runtime"]["answered"] = 0  # an explicit zero is not replaced by n
    zero = cf.build(r)["runtime"]
    assert zero.count("documents/min") == 2  # the arm that answered nothing shows no rate, not n per minute


def test_font_shorthand_from_matplotlib_3_8_is_normalised_and_checked():
    old = '<g id="title"><text style="font: 700 12px \'DejaVu Sans\'; text-anchor: start">Fine title</text></g>'
    new = fs.system_fonts(old)
    assert "font: 700 12px system-ui" in new and "text-anchor: start" in new
    assert fs.lint_svg(new) == []
    assert any("below the" in p for p in fs.lint_svg(new.replace("12px", "6px")))
