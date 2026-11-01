"""Decision-model cutoff calibration: bound, split, selection, report (network-free)."""

from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path

import pytest

from mailroom_sandbox import calibration, cli
from mailroom_sandbox.calibration import (
    CalibrationError,
    Row,
    calibrate,
    clopper_pearson_upper,
    decision_flags,
    expected_calibration_error,
    in_tune,
    is_accepted,
    load_rows,
    parse_rows,
    render_markdown,
    select_cutoff,
    write_report,
)
from mailroom_sandbox.experiments import _reviewer_settings
from mailroom_sandbox.job.spec import ReviewerSpec
from mailroom_sandbox.overlay import live_doc_classes

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "calibration" / "decision_mock.jsonl"
LIVE = ("contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim")
PIN = "jev-1.13.0"


def _row(doc_id: str, *, gold="contract", sorter=None, decision=None, confidence=0.9, model=PIN, **extra) -> Row:
    sorter = gold if sorter is None else sorter
    decision = sorter if decision is None else decision
    return Row(doc_id, gold, sorter, decision, confidence, model, extra.get("cost_usd"), extra.get("cause"), 1)


def _ids(count: int, *, tune: bool, prefix: str = "doc", fraction: float = 0.5) -> list[str]:
    """The first ``count`` ids that land on the requested side of the split."""
    found, index = [], 0
    while len(found) < count:
        doc_id = f"{prefix}-{index}"
        if in_tune(doc_id, fraction) == tune:
            found.append(doc_id)
        index += 1
    return found


def _rows(*, tune: int, held_out: int, doc_class="contract", confidence=0.9, wrong_held_out=0) -> list[Row]:
    """Clean tune rows plus held-out rows, the first ``wrong_held_out`` of them wrong."""
    gold_other = "corporate_record" if doc_class != "corporate_record" else "contract"
    rows = [_row(i, gold=doc_class, confidence=confidence) for i in _ids(tune, tune=True, prefix=doc_class)]
    for index, doc_id in enumerate(_ids(held_out, tune=False, prefix=doc_class)):
        gold = gold_other if index < wrong_held_out else doc_class
        rows.append(_row(doc_id, gold=gold, sorter=doc_class, decision=doc_class, confidence=confidence))
    return rows


def _run(rows, **kwargs):
    kwargs.setdefault("live_classes", LIVE)
    return calibrate(rows, **kwargs)


def _line(doc_id="d1", **overrides) -> str:
    data = {
        "doc_id": doc_id, "doc_class": "contract", "sorter_label": "contract", "decision_label": "contract",
        "decision_confidence": 0.9, "model": PIN,
    }
    data.update(overrides)
    return json.dumps({k: v for k, v in data.items() if v is not ...})


# Bound -----------------------------------------------------------------------


def test_clopper_pearson_pins_the_zero_error_boundary():
    assert clopper_pearson_upper(0, 299) <= 0.01
    assert clopper_pearson_upper(0, 298) > 0.01


def test_clopper_pearson_matches_closed_form_and_reference_values():
    assert clopper_pearson_upper(0, 299) == pytest.approx(0.009969146792899269, abs=1e-10)
    assert clopper_pearson_upper(0, 298) == pytest.approx(0.010002432437677691, abs=1e-10)
    assert clopper_pearson_upper(2, 20) == pytest.approx(0.28261852488586087, abs=1e-10)  # scipy beta.ppf


def test_clopper_pearson_edges():
    assert clopper_pearson_upper(0, 0) == 1.0
    assert clopper_pearson_upper(5, 5) == 1.0
    with pytest.raises(ValueError):
        clopper_pearson_upper(3, 2)
    with pytest.raises(ValueError):
        clopper_pearson_upper(-1, 2)


@pytest.mark.parametrize("wrong,required", [(0, 299), (1, 473), (2, 628), (3, 773)])
def test_each_error_raises_the_required_clean_count(wrong, required):
    assert clopper_pearson_upper(wrong, required) <= 0.01
    assert clopper_pearson_upper(wrong, required - 1) > 0.01


@pytest.mark.parametrize("held_out,verdict", [(299, "decision_only"), (298, "llm")])
def test_held_out_accept_boundary_end_to_end(held_out, verdict):
    report = _run(_rows(tune=5, held_out=held_out))
    result = report["classes"]["contract"]
    assert result["samples"]["held_out_accepts"] == held_out
    assert result["verdict"] == verdict


def test_one_held_out_error_needs_more_accepts():
    assert _run(_rows(tune=5, held_out=472, wrong_held_out=1))["classes"]["contract"]["verdict"] == "llm"
    assert _run(_rows(tune=5, held_out=473, wrong_held_out=1))["classes"]["contract"]["verdict"] == "decision_only"


def test_markdown_does_not_round_a_failing_bound_onto_the_bar():
    report = _run(_rows(tune=5, held_out=298))
    assert "0.010002" in render_markdown(report)


# Accept rule -----------------------------------------------------------------


def test_accept_rule_matches_the_pipeline_function():
    from pipeline.decision_review import DecisionAnswer, decide_review

    cases = [
        ("contract", "contract", 0.9), ("contract", "contract", 0.8), ("contract", "contract", 0.79),
        ("contract", "contract", None), ("contract", "contract", float("nan")), ("contract", "contract", True),
        ("contract", "contract", 1.2), ("contract", "contract", -0.1), ("contract", "contract", "0.9"),
        ("contract", "merger_agreement", 0.99), ("contract", None, 0.99),
    ]
    for sorter, decision, confidence in cases:
        answer = None if decision is None else DecisionAnswer(decision, None, confidence, PIN)
        route = decide_review(
            sorter, answer, eligible={"contract", "merger_agreement"},
            cutoffs={"contract": 0.8, "merger_agreement": 0.8}, has_text=True,
        )
        row = _row("d", sorter=sorter, confidence=confidence)
        row = Row(row.doc_id, row.doc_class, sorter, decision, confidence, PIN, None, None, 1)
        assert is_accepted(row, 0.8) == (route.destination == "extract"), (sorter, decision, confidence)


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), True, 1.01, -0.5, "0.99", 10**400])
def test_invalid_confidence_is_never_accepted_and_is_not_malformed(confidence):
    rows = [_row(i, confidence=confidence) for i in _ids(4, tune=True) + _ids(4, tune=False)]
    result = _run(rows)["classes"]["contract"]
    assert result["cutoff"] is None
    assert result["samples"]["tune_accepts"] == result["samples"]["held_out_accepts"] == 0
    assert result["samples"]["held_out_rows"] == 4
    assert result["human_review_rate"] == 1.0
    assert result["verdict"] == "llm"


def test_missing_confidence_key_parses_as_not_accepted():
    row = parse_rows(_line(decision_confidence=...))[0]
    assert row.decision_confidence is None
    assert not is_accepted(row, 0.0)


# Split -----------------------------------------------------------------------


def test_split_is_deterministic_and_order_free():
    rows = [_row(f"doc-{i}") for i in range(300)]
    first = _run(rows, tune_fraction=0.5)
    second = _run(list(reversed(rows)), tune_fraction=0.5)
    assert first == second


def test_split_pins_the_sha256_rule():
    expected = [
        int.from_bytes(hashlib.sha256(f"doc-{i}".encode()).digest()[:8], "big") / 2**64 < 0.5 for i in range(64)
    ]
    assert [in_tune(f"doc-{i}", 0.5) for i in range(64)] == expected


def test_tune_fraction_is_respected():
    ids = [f"doc-{i}" for i in range(4000)]
    assert 0.27 < sum(in_tune(i, 0.3) for i in ids) / 4000 < 0.33
    assert 0.47 < sum(in_tune(i, 0.5) for i in ids) / 4000 < 0.53


@pytest.mark.parametrize("kwargs", [
    {"tune_fraction": 0.0}, {"tune_fraction": 1.0}, {"tune_fraction": float("nan")},
    {"risk_bar": 0.0}, {"risk_bar": 1.0}, {"risk_bar": float("nan")},
])
def test_bad_settings_are_refused(kwargs):
    with pytest.raises(CalibrationError):
        _run(_rows(tune=1, held_out=1), **kwargs)


# Cutoff selection ------------------------------------------------------------


def test_select_cutoff_picks_lowest_that_meets_the_bar():
    rows = [
        _row("w", gold="merger_agreement", sorter="contract", decision="contract", confidence=0.6),
        _row("a", confidence=0.7), _row("b", confidence=0.8), _row("c", confidence=0.9),
    ]
    assert select_cutoff(rows, 0.01) == 0.7


def test_select_cutoff_ignores_rows_that_could_not_be_accepted():
    rows = [
        _row("d", sorter="contract", decision="merger_agreement", confidence=0.2),
        _row("a", confidence=0.7),
    ]
    assert select_cutoff(rows, 0.01) == 0.7


def test_select_cutoff_none_when_nothing_meets_the_bar():
    rows = [_row("w", gold="merger_agreement", sorter="contract", decision="contract", confidence=0.9)]
    assert select_cutoff(rows, 0.01) is None
    assert select_cutoff([], 0.01) is None


def test_no_selection_on_held_out():
    rows = _rows(tune=5, held_out=300, confidence=0.9)
    baseline = _run(rows)["classes"]["contract"]["cutoff"]
    # Held-out confidences far below the tuned cutoff, and all wrong: the cutoff must not move.
    mangled = [
        row if in_tune(row.doc_id, 0.5)
        else Row(row.doc_id, "merger_agreement", "contract", "contract", 0.1, PIN, None, None, 1)
        for row in rows
    ]
    result = _run(mangled)["classes"]["contract"]
    assert result["cutoff"] == baseline == 0.9
    assert result["samples"]["held_out_accepts"] == 0


def test_bound_uses_held_out_only():
    clean_tune = _run(_rows(tune=2000, held_out=10))["classes"]["contract"]
    assert clean_tune["samples"]["tune_accepts"] == 2000
    assert clean_tune["samples"]["held_out_accepts"] == 10
    assert clean_tune["wrong_accept_upper_bound"] == pytest.approx(clopper_pearson_upper(0, 10))
    assert clean_tune["verdict"] == "llm"


def test_wrong_accept_counts_against_the_class_whose_cutoff_admitted_it():
    # Gold says merger_agreement, both models say contract: the pipeline reads the
    # contract cutoff, so the error must land on contract, not on merger_agreement.
    rows = [_row(i) for i in _ids(5, tune=True)]
    held_out = _ids(475, tune=False)
    rows += [_row(i) for i in held_out[2:]]
    rows += [_row(i, gold="merger_agreement", sorter="contract", decision="contract") for i in held_out[:2]]
    result = _run(rows)["classes"]
    assert result["contract"]["samples"]["held_out_wrong_accepts"] == 2
    assert result["contract"]["verdict"] == "llm"
    assert result["merger_agreement"]["samples"]["held_out_accepts"] == 0
    assert result["merger_agreement"]["samples"]["gold_rows"] == 2


# Outcomes --------------------------------------------------------------------


def test_empty_class_list_is_refused():
    with pytest.raises(CalibrationError, match="no rows"):
        _run([])


def test_class_with_no_held_out_rows_stays_on_llm():
    rows = _rows(tune=4, held_out=0)
    result = _run(rows)["classes"]["contract"]
    assert result["verdict"] == "llm"
    assert result["wrong_accept_upper_bound"] == 1.0
    assert result["accuracy"] is None and result["human_review_rate"] is None and result["ece"] is None
    assert "no held-out accepts" in result["reason"]


def test_gold_class_with_no_routed_rows_is_still_reported():
    rows = [_row(i, gold="merger_agreement", sorter="contract", decision="contract") for i in _ids(3, tune=False)]
    result = _run(rows)["classes"]["merger_agreement"]
    assert result["verdict"] == "llm"
    assert result["samples"]["tune_rows"] == result["samples"]["held_out_rows"] == 0


def test_all_wrong_stays_on_llm_with_the_supported_bound():
    rows = [
        _row(i, gold="merger_agreement", sorter="contract", decision="contract")
        for i in _ids(6, tune=True) + _ids(6, tune=False)
    ]
    report = _run(rows)
    result = report["classes"]["contract"]
    assert result["cutoff"] is None and result["verdict"] == "llm"
    assert result["accuracy"] == 0.0
    # No tuned cutoff, so the bound covers every agreeing held-out row.
    assert result["samples"]["held_out_wrong_accepts"] == 6
    assert result["wrong_accept_upper_bound"] == 1.0
    assert decision_flags(report) is None


def test_no_class_qualifying_is_a_valid_report():
    report = _run(_rows(tune=3, held_out=3))
    assert decision_flags(report) is None
    assert "No class qualifies" in render_markdown(report)


def test_failing_class_reports_the_bound_the_data_supports():
    report = _run(_rows(tune=5, held_out=100))
    result = report["classes"]["contract"]
    assert result["verdict"] == "llm"
    assert result["wrong_accept_upper_bound"] == pytest.approx(clopper_pearson_upper(0, 100))
    assert "0.029513" in result["reason"]


def test_metrics_cost_and_causes():
    tune = _ids(2, tune=True)
    held = _ids(4, tune=False)
    rows = [
        _row(tune[0], confidence=0.8, cost_usd=0.5),
        _row(tune[1], confidence=0.8, cost_usd=None),
        _row(held[0], confidence=0.9, cost_usd=0.25),
        _row(held[1], confidence=0.5, cause="reviewer_low_confidence"),
        _row(held[2], decision="merger_agreement", confidence=0.9, cause="reviewer_disagreement"),
        _row(held[3], confidence=None, cause="reviewer_low_confidence"),
    ]
    result = _run(rows)["classes"]["contract"]
    assert result["cutoff"] == 0.8
    assert result["accuracy"] == 0.75
    assert result["human_review_rate"] == 0.75
    assert result["cause_counts"] == {"reviewer_disagreement": 1, "reviewer_low_confidence": 2}
    assert result["cost"] == {"measured_usd": 0.75, "rows_with_cost": 2, "rows_without_cost": 4}
    assert result["samples"]["confidence_invalid_held_out"] == 1


def test_cost_is_unknown_rather_than_zero_when_unmeasured():
    result = _run(_rows(tune=1, held_out=1))["classes"]["contract"]
    assert result["cost"]["measured_usd"] is None


def test_expected_calibration_error_uses_ten_equal_bins():
    rows = [_row("a", confidence=1.0), _row("b", gold="merger_agreement", sorter="contract", confidence=0.05)]
    assert expected_calibration_error(rows) == pytest.approx(0.025)
    assert expected_calibration_error([]) is None
    assert expected_calibration_error([_row("c", confidence=None)]) is None
    assert calibration.ECE_BINS == 10


# Input validation ------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "{not json", "[1, 2]", _line(doc_id=""), _line(doc_id=7), _line(doc_id=...), _line(doc_class=None),
    _line(sorter_label=...), _line(decision_label=...), _line(decision_label=3), _line(model=""),
    _line(cost_usd=-1), _line(cost_usd="free"), _line(cost_usd=True), _line(cost_usd=float("nan")), _line(cause=3),
])
def test_malformed_row_fails_with_its_line_number(line):
    good = _line("ok")
    with pytest.raises(CalibrationError, match=r"line 3\b"):
        parse_rows(f"{good}\n\n{line}\n")


def test_null_decision_label_is_an_unavailable_answer_not_malformed():
    row = parse_rows(_line(decision_label=None))[0]
    assert row.decision_label is None and not is_accepted(row, 0.0)


def test_mixed_models_are_rejected():
    text = "\n".join([_line("a"), _line("b", model="jev-1.14.0")])
    with pytest.raises(CalibrationError, match="mix"):
        parse_rows(text)


@pytest.mark.parametrize("model", ["jev-latest", "jev-preview", "jev-1", "JEV-latest", "jev-1.13.0\n", "other-1.0", "mock-latest"])
def test_floating_or_unknown_model_ids_are_rejected(model):
    with pytest.raises(CalibrationError, match="pinned"):
        parse_rows(_line(model=model))


def test_duplicate_doc_ids_are_rejected_with_the_line():
    with pytest.raises(CalibrationError, match=r"line 2\b.*duplicate"):
        parse_rows(f"{_line('a')}\n{_line('a')}\n")


def test_empty_and_missing_input(tmp_path):
    with pytest.raises(CalibrationError, match="no rows"):
        parse_rows("\n\n")
    with pytest.raises(CalibrationError, match="cannot read"):
        load_rows(tmp_path / "absent.jsonl")


def test_constructed_rows_cannot_bypass_the_input_checks():
    with pytest.raises(CalibrationError, match="mix"):
        _run([_row("a"), _row("b", model="jev-1.14.0")])
    with pytest.raises(CalibrationError, match="pinned"):
        _run([_row("a", model="jev-latest")])
    with pytest.raises(CalibrationError, match="duplicate"):
        _run([_row("a"), _row("a")])


# Class rules -----------------------------------------------------------------


def test_insurance_note_on_class_and_report():
    report = _run(_rows(tune=2, held_out=2, doc_class="insurance_claim"))
    assert "synthetic" in report["classes"]["insurance_claim"]["notes"][0]
    assert any("not evidence about real insurance claims" in note for note in report["notes"])
    assert "not evidence about real insurance claims" in render_markdown(report)


def test_insurance_note_when_only_a_model_said_insurance():
    rows = [_row("a", decision="insurance_claim")]
    assert any("synthetic" in note for note in _run(rows)["notes"])


def test_no_insurance_note_without_such_a_row():
    assert not any("synthetic" in note for note in _run(_rows(tune=1, held_out=1))["notes"])


def test_correspondence_refused_for_live_model():
    with pytest.raises(CalibrationError, match="--allow-correspondence"):
        _run(_rows(tune=2, held_out=2, doc_class="correspondence"))


def test_correspondence_allowed_by_flag_is_reported_but_never_printed():
    report = _run(_rows(tune=5, held_out=400, doc_class="correspondence"), allow_correspondence=True)
    result = report["classes"]["correspondence"]
    assert result["verdict"] == "llm"
    assert "correspondence" in result["reason"]
    assert decision_flags(report) is None
    # SAND-086 was cancelled on main: no backend refuses correspondence any more, so the
    # calibration tool's own refusal to print a correspondence flag is the only gate left.
    assert ReviewerSpec(backend="jev", model=PIN, classes={"correspondence": 0.9}).classes == {"correspondence": 0.9}


def test_correspondence_on_mock_needs_no_flag():
    rows = [Row(r.doc_id, r.doc_class, r.sorter_label, r.decision_label, r.decision_confidence, "mock", None, None, 1)
            for r in _rows(tune=2, held_out=2, doc_class="correspondence")]
    assert _run(rows)["classes"]["correspondence"]["verdict"] == "llm"


def test_retired_class_cannot_qualify():
    report = _run(_rows(tune=5, held_out=300, doc_class="compliance_filing"))
    assert report["classes"]["compliance_filing"]["verdict"] == "llm"
    assert decision_flags(report) is None


# Output ----------------------------------------------------------------------


def _qualifying() -> dict:
    rows = [
        Row(r.doc_id, r.doc_class, r.sorter_label, r.decision_label, 0.87654321012345, PIN, None, None, 1)
        for r in _rows(tune=5, held_out=320)
    ]
    rows += _rows(tune=5, held_out=20, doc_class="corporate_record")
    return _run(rows, live_classes=live_doc_classes())


def test_flags_are_exact():
    assert decision_flags(_qualifying()) == (
        "--decision-reviewer jev:jev-1.13.0 --decision-class contract=0.87654321012345"
    )


def test_flags_round_trip_through_reviewer_spec():
    report = _qualifying()
    words = shlex.split(decision_flags(report))
    assert words[0] == "--decision-reviewer"
    assert words[2] == "--decision-class"
    backend, _, model = words[1].partition(":")
    name, _, cutoff = words[3].partition("=")
    spec = ReviewerSpec(backend=backend, model=model, classes={name: float(cutoff)})
    assert spec.classes == {"contract": report["classes"]["contract"]["cutoff"]}
    assert spec.model == PIN
    assert _reviewer_settings(words[1], [words[3]]) == spec.model_dump()


def test_flags_list_every_qualifying_class_only():
    rows = _rows(tune=5, held_out=300) + _rows(tune=5, held_out=300, doc_class="merger_agreement")
    rows += _rows(tune=5, held_out=10, doc_class="corporate_record")
    assert decision_flags(_run(rows)) == (
        "--decision-reviewer jev:jev-1.13.0 --decision-class contract=0.9 --decision-class merger_agreement=0.9"
    )


def test_write_report_writes_json_and_markdown(tmp_path):
    report = _qualifying()
    out = tmp_path / "nested" / "out"
    write_report(report, out)
    assert json.loads((out / "calibration.json").read_text()) == report
    text = (out / "calibration.md").read_text()
    assert "contract" in text and "decision_only" in text
    assert "--decision-class contract=0.87654321012345" in text
    assert sorted(p.name for p in out.iterdir()) == ["calibration.json", "calibration.md"]


def test_fixture_is_labelled_mock_and_says_so():
    rows = load_rows(FIXTURE)
    assert {row.model for row in rows} == {"mock"}
    assert all(row.doc_id.startswith("mock-") for row in rows)
    assert {row.doc_class for row in rows} == set(LIVE)
    for line in FIXTURE.read_text().splitlines():
        assert "MOCK" in json.loads(line)["note"]
    report = _run(rows)
    text = render_markdown(report)
    assert "not model evidence" in text
    assert "not evidence about real insurance claims" in text


def test_cli_runs_the_fixture_and_writes_no_config(tmp_path, capsys):
    out = tmp_path / "out"
    code = cli.main(["calibrate", "decision", "--input", str(FIXTURE), "--out", str(out)])
    captured = capsys.readouterr()
    assert code == 0
    assert "not model evidence" in captured.out
    assert (out / "calibration.json").is_file()
    report = json.loads((out / "calibration.json").read_text())
    assert report["model"] == "mock" and report["input"]["name"] == FIXTURE.name
    assert len(report["input"]["sha256"]) == 64


def test_cli_prints_the_exact_flags(tmp_path, capsys):
    source = tmp_path / "rows.jsonl"
    source.write_text("\n".join(
        json.dumps({
            "doc_id": r.doc_id, "doc_class": r.doc_class, "sorter_label": r.sorter_label,
            "decision_label": r.decision_label, "decision_confidence": r.decision_confidence, "model": r.model,
        }) for r in _rows(tune=5, held_out=300)
    ))
    assert cli.main(["calibrate", "decision", "--input", str(source), "--out", str(tmp_path / "o")]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert "--decision-reviewer jev:jev-1.13.0 --decision-class contract=0.9" in printed


def test_cli_reports_refusal_as_one_line(tmp_path, capsys):
    source = tmp_path / "rows.jsonl"
    source.write_text(_line(model="jev-latest"))
    assert cli.main(["calibrate", "decision", "--input", str(source), "--out", str(tmp_path / "o")]) == 1
    assert "pinned" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_cli_refuses_an_out_dir_inside_config(tmp_path, capsys):
    from mailroom_sandbox.paths import repo_root

    target = repo_root() / "config" / "calibration-test-refused"
    assert cli.main(["calibrate", "decision", "--input", str(FIXTURE), "--out", str(target)]) == 1
    assert "config" in capsys.readouterr().err
    assert not target.exists()


def test_cli_reference_unescapes_percent_signs():
    """The generated reference shows help as argparse prints it (``95%``, not ``95%%``)."""
    text = (Path(__file__).resolve().parents[1] / "docs" / "cli-reference.md").read_text(encoding="utf-8")
    assert "%%" not in text and "maximum 95% upper bound" in text
