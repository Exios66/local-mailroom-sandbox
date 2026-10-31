"""Offline cutoff calibration for the decision-model reviewer.

Decides, per document class and pinned model version, whether a class may skip
the backup LLM reviewer (``decision_only``) and at what confidence cutoff. Input
is a JSONL file with one row per reviewer-band document. Nothing here calls a
model or writes config: the output is a report plus the exact
``--decision-reviewer`` and ``--decision-class`` flags for an operator to review.

Method:

* Rows split on SHA-256 of ``doc_id`` into tune and held-out. The cutoff comes
  from tune only; the bound comes from held-out only.
* Rows belong to the class the sorter gave them, not to their gold class. The
  pipeline reads the cutoff of the label both models agreed on, so a wrong accept
  must count against the class whose cutoff admitted it. Grouping on gold would
  leave a class blind to documents wrongly accepted into it.
* A class qualifies when the one-sided 95% Clopper-Pearson upper bound on held-out
  wrong accepts is at or under the risk bar. Zero errors need 299 accepts.

The accept rule mirrors ``pipeline.decision_review.decide_review``, which is not
imported because this module stays stdlib-only and usable before ``activate``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Collection, Iterable, Optional

from mailroom_sandbox.decision_backends import jev_backend

SCHEMA = "sandbox.calibration.decision/v1"
DEFAULT_RISK_BAR = 0.01
DEFAULT_TUNE_FRACTION = 0.5
CONFIDENCE_LEVEL = 0.95
ECE_BINS = 10

_BISECTION_STEPS = 80
_REQUIRED_TEXT = ("doc_id", "doc_class", "sorter_label", "model")

_MOCK_NOTE = "Mock data: results from this file are not model evidence."
_INSURANCE_NOTE = (
    "insurance_claim is synthetic; results for it are not evidence about real insurance claims."
)
_CORRESPONDENCE_NOTE = (
    "correspondence was calibrated by request, but its live use waits for the sanitised "
    "dataset, so it stays on llm for this model."
)


class CalibrationError(ValueError):
    """The input or settings cannot produce a sound calibration."""


@dataclass(frozen=True)
class Row:
    """One reviewer-band document. ``decision_confidence`` is kept as given, valid or not."""

    doc_id: str
    doc_class: str
    sorter_label: str
    decision_label: Optional[str]
    decision_confidence: Any
    model: str
    cost_usd: Optional[float]
    cause: Optional[str]
    line: int


def _valid_confidence(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and 0.0 <= value <= 1.0


def is_accepted(row: Row, cutoff: float) -> bool:
    """The pipeline's accept rule: labels agree, confidence valid and at or over the cutoff."""
    if row.decision_label is None or row.decision_label != row.sorter_label:
        return False
    return _valid_confidence(row.decision_confidence) and float(row.decision_confidence) >= cutoff


def _is_wrong(row: Row) -> bool:
    return row.decision_label != row.doc_class


def in_tune(doc_id: str, tune_fraction: float = DEFAULT_TUNE_FRACTION) -> bool:
    """Deterministic split: the document's SHA-256 alone places it, whatever the file order."""
    digest = hashlib.sha256(doc_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < tune_fraction


def _binomial_cdf(successes: int, trials: int, probability: float) -> float:
    log_p, log_q = math.log(probability), math.log1p(-probability)
    log_trials = math.lgamma(trials + 1)
    return math.fsum(
        math.exp(
            log_trials - math.lgamma(i + 1) - math.lgamma(trials - i + 1)
            + i * log_p + (trials - i) * log_q
        )
        for i in range(successes + 1)
    )


def clopper_pearson_upper(wrong: int, accepts: int, confidence: float = CONFIDENCE_LEVEL) -> float:
    """One-sided Clopper-Pearson upper bound on the wrong-accept rate, by bisection.

    Returns the upper end of the final bracket, so float error cannot flatter a class.
    With no accepts, or every accept wrong, the data supports nothing better than 1.0.
    """
    if accepts < 0 or not 0 <= wrong <= accepts:
        raise ValueError(f"need 0 <= wrong <= accepts, got {wrong} of {accepts}")
    if accepts == 0 or wrong == accepts:
        return 1.0
    alpha = 1.0 - confidence
    low, high = 0.0, 1.0
    for _ in range(_BISECTION_STEPS):
        middle = (low + high) / 2
        if _binomial_cdf(wrong, accepts, middle) > alpha:
            low = middle
        else:
            high = middle
    return high


def select_cutoff(rows: Iterable[Row], risk_bar: float) -> Optional[float]:
    """Lowest observed confidence whose wrong-accept rate meets the bar (None when none does).

    Only rows the rule could accept supply candidates. The lowest passing cutoff
    is the one with the most coverage, because accepts only shrink as it rises.
    """
    rows = list(rows)
    candidates = sorted({float(r.decision_confidence) for r in rows if is_accepted(r, 0.0)})
    for cutoff in candidates:
        accepted = [r for r in rows if is_accepted(r, cutoff)]
        if sum(_is_wrong(r) for r in accepted) / len(accepted) <= risk_bar:
            return cutoff
    return None


def expected_calibration_error(rows: Iterable[Row]) -> Optional[float]:
    """ECE over ``ECE_BINS`` equal-width bins of valid confidence; None without any."""
    bins: list[list[Row]] = [[] for _ in range(ECE_BINS)]
    for row in rows:
        if _valid_confidence(row.decision_confidence):
            bins[min(int(float(row.decision_confidence) * ECE_BINS), ECE_BINS - 1)].append(row)
    total = sum(len(group) for group in bins)
    if not total:
        return None
    gaps = []
    for group in bins:
        if group:
            accuracy = sum(not _is_wrong(r) for r in group) / len(group)
            mean_confidence = math.fsum(float(r.decision_confidence) for r in group) / len(group)
            gaps.append(len(group) / total * abs(accuracy - mean_confidence))
    return math.fsum(gaps)


def _backend_for(model: str) -> str:
    """The reviewer backend of a pinned model id; anything floating or unknown is refused."""
    if model == "mock":
        return "mock"
    if model.startswith("jev-") and not any(c.isspace() for c in model):
        try:
            jev_backend(model)  # the pin check lives with the backends; no network
        except ValueError as exc:
            raise CalibrationError(str(exc)) from exc
        return "jev"
    raise CalibrationError(f"{model!r} is not a pinned reviewer model (expected e.g. 'jev-1.13.0' or 'mock')")


def _check_rows(rows: list[Row]) -> str:
    """Whole-file rules; returns the single pinned model."""
    if not rows:
        raise CalibrationError("no rows to calibrate")
    seen: set[str] = set()
    for row in rows:
        if row.doc_id in seen:
            raise CalibrationError(f"line {row.line}: duplicate doc_id {row.doc_id!r}")
        seen.add(row.doc_id)
    models = sorted({row.model for row in rows})
    if len(models) > 1:
        raise CalibrationError(f"input must not mix model versions; found {models}")
    _backend_for(models[0])
    return models[0]


def _parse_row(raw: str, line: int) -> Row:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise CalibrationError(f"line {line}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CalibrationError(f"line {line}: expected a JSON object")
    for name in _REQUIRED_TEXT:
        value = data.get(name)
        if not isinstance(value, str) or not value:
            raise CalibrationError(f"line {line}: {name} must be a non-empty string")
    if "decision_label" not in data:
        raise CalibrationError(f"line {line}: decision_label is required (null when the model gave no answer)")
    label = data["decision_label"]
    if label is not None and (not isinstance(label, str) or not label):
        raise CalibrationError(f"line {line}: decision_label must be a non-empty string or null")
    cost = data.get("cost_usd")
    if cost is not None and (
        isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0
    ):
        raise CalibrationError(f"line {line}: cost_usd must be a finite number >= 0")
    cause = data.get("cause")
    if cause is not None and not isinstance(cause, str):
        raise CalibrationError(f"line {line}: cause must be a string")
    return Row(
        data["doc_id"], data["doc_class"], data["sorter_label"], label,
        data.get("decision_confidence"), data["model"], cost, cause, line,
    )


def parse_rows(text: str) -> list[Row]:
    """Rows from JSONL text. Blank lines are skipped; errors name the line."""
    rows = [_parse_row(raw, line) for line, raw in enumerate(text.splitlines(), 1) if raw.strip()]
    _check_rows(rows)
    return rows


def _read_text(path: str | Path) -> str:
    try:
        return Path(path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CalibrationError(f"cannot read {path}: {exc}") from exc


def load_rows(path: str | Path) -> list[Row]:
    return parse_rows(_read_text(path))


def _rate(part: int, whole: int) -> Optional[float]:
    return part / whole if whole else None


def _reason(
    cutoff: Optional[float], accepts: int, bound: float, risk_bar: float, blocker: Optional[str]
) -> str:
    supported = (
        f"the data supports an upper bound of {bound:.6f}" if accepts
        else "there are no held-out accepts, so the data supports no bound"
    )
    if cutoff is None:
        return f"no tuned cutoff meets the risk bar on tune; {supported} with no cutoff applied"
    if not accepts:
        return f"at cutoff {cutoff!r} {supported}"
    if bound > risk_bar:
        return f"{supported}, above the risk bar of {risk_bar:g}"
    if blocker:
        return f"{blocker} ({supported})"
    return f"held-out upper bound {bound:.6f} is within the risk bar of {risk_bar:g}"


def _class_result(
    name: str,
    routed: list[Row],
    gold_rows: int,
    *,
    risk_bar: float,
    tune_fraction: float,
    blocker: Optional[str],
) -> dict[str, Any]:
    tune = [r for r in routed if in_tune(r.doc_id, tune_fraction)]
    held_out = [r for r in routed if not in_tune(r.doc_id, tune_fraction)]
    cutoff = select_cutoff(tune, risk_bar)
    # Without a tuned cutoff the bound still needs a basis fixed before held-out is
    # read: every agreeing row, which is what a cutoff of zero admits.
    applied = 0.0 if cutoff is None else cutoff
    accepted = [r for r in held_out if is_accepted(r, applied)]
    wrong = sum(_is_wrong(r) for r in accepted)
    bound = clopper_pearson_upper(wrong, len(accepted))
    qualifies = cutoff is not None and bool(accepted) and bound <= risk_bar and not blocker
    costs = [r.cost_usd for r in routed if r.cost_usd is not None]
    return {
        "verdict": "decision_only" if qualifies else "llm",
        "reason": _reason(cutoff, len(accepted), bound, risk_bar, blocker),
        "cutoff": cutoff,
        "bound_basis": "tuned_cutoff" if cutoff is not None else "no_cutoff",
        "wrong_accept_upper_bound": bound,
        "accuracy": _rate(sum(not _is_wrong(r) for r in held_out), len(held_out)),
        "ece": expected_calibration_error(held_out),
        "human_review_rate": _rate(len(held_out) - len(accepted), len(held_out)),
        "cause_counts": dict(sorted(Counter(r.cause for r in routed if r.cause).items())),
        "cost": {
            "measured_usd": math.fsum(costs) if costs else None,
            "rows_with_cost": len(costs),
            "rows_without_cost": len(routed) - len(costs),
        },
        "samples": {
            "gold_rows": gold_rows,
            "tune_rows": len(tune),
            "held_out_rows": len(held_out),
            "tune_accepts": sum(is_accepted(r, applied) for r in tune),
            "held_out_accepts": len(accepted),
            "held_out_wrong_accepts": wrong,
            "confidence_invalid_held_out": sum(not _valid_confidence(r.decision_confidence) for r in held_out),
        },
        "notes": [_INSURANCE_NOTE] if name == "insurance_claim" else [],
    }


def _blocker(name: str, backend: str, live_classes: Collection[str]) -> Optional[str]:
    """Why a class may not qualify whatever its numbers; the printed flags would be refused."""
    if name not in live_classes:
        return f"{name} is not a live taxonomy class"
    if name == "correspondence" and backend == "jev":
        return "correspondence cannot use a live model until the sanitised dataset exists"
    return None


def calibrate(
    rows: list[Row],
    *,
    live_classes: Collection[str],
    risk_bar: float = DEFAULT_RISK_BAR,
    tune_fraction: float = DEFAULT_TUNE_FRACTION,
    allow_correspondence: bool = False,
) -> dict[str, Any]:
    """Per-class report for one pinned model. No class qualifying is a valid outcome."""
    for name, value in (("risk bar", risk_bar), ("tune fraction", tune_fraction)):
        if not math.isfinite(value) or not 0 < value < 1:
            raise CalibrationError(f"{name} must be strictly between 0 and 1, got {value}")
    model = _check_rows(rows)
    backend = _backend_for(model)
    gold = Counter(r.doc_class for r in rows)
    if backend == "jev" and gold["correspondence"] and not allow_correspondence:
        raise CalibrationError(
            f"{gold['correspondence']} correspondence rows refused for live model {model}: its live "
            "use waits for the sanitised dataset (--allow-correspondence to calibrate it anyway)"
        )
    labels = {r.doc_class for r in rows} | {r.sorter_label for r in rows}
    labels |= {r.decision_label for r in rows if r.decision_label}
    classes = {
        name: _class_result(
            name, [r for r in rows if r.sorter_label == name], gold[name],
            risk_bar=risk_bar, tune_fraction=tune_fraction,
            blocker=_blocker(name, backend, live_classes),
        )
        for name in sorted(labels)
    }
    notes = []
    if model == "mock":
        notes.append(_MOCK_NOTE)
    if "insurance_claim" in labels:
        notes.append(_INSURANCE_NOTE)
    if backend == "jev" and gold["correspondence"]:
        notes.append(_CORRESPONDENCE_NOTE)
    return {
        "schema": SCHEMA,
        "model": model,
        "backend": backend,
        "risk_bar": risk_bar,
        "tune_fraction": tune_fraction,
        "confidence_level": CONFIDENCE_LEVEL,
        "ece_bins": ECE_BINS,
        "rows": len(rows),
        "notes": notes,
        "classes": classes,
    }


def calibrate_file(path: str | Path, **settings: Any) -> dict[str, Any]:
    """``calibrate`` over a JSONL file, recording which bytes produced the report."""
    text = _read_text(path)
    report = calibrate(parse_rows(text), **settings)
    report["input"] = {"name": Path(path).name, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return report


def decision_flags(report: dict[str, Any]) -> Optional[str]:
    """The exact flags for qualifying classes only (None when none qualifies).

    ``repr`` keeps the cutoff exact: a rounded one would be a cutoff nobody tested.
    """
    passed = [(name, c["cutoff"]) for name, c in report["classes"].items() if c["verdict"] == "decision_only"]
    if not passed:
        return None
    flags = [f"--decision-reviewer {report['backend']}:{report['model']}"]
    flags += [f"--decision-class {name}={cutoff!r}" for name, cutoff in passed]
    return " ".join(flags)


def _cell(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.6f}"


def render_markdown(report: dict[str, Any]) -> str:
    """Readable report; every number is the one in the JSON, bounds to six places."""
    lines = [
        "# Decision reviewer calibration", "",
        f"- Model pin: `{report['model']}` (backend `{report['backend']}`)",
        f"- Rows: {report['rows']}; tune fraction {report['tune_fraction']:g}, split on SHA-256 of doc_id",
        f"- Risk bar: {report['risk_bar']:g}, one-sided {report['confidence_level']:.0%} Clopper-Pearson upper bound",
        "- Rows are grouped by sorter label, the class whose cutoff the pipeline applies.",
        "- Cutoffs come from tune. Bound, accuracy, ECE and human-review rate come from held-out only.",
        f"- ECE uses {report['ece_bins']} equal-width confidence bins. Causes and cost cover tune and held-out.",
    ]
    if "input" in report:
        lines.append(f"- Input: `{report['input']['name']}`, sha256 `{report['input']['sha256']}`")
    if report["notes"]:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in report["notes"]]
    lines += [
        "", "## Results", "",
        "| Class | Verdict | Cutoff | Upper bound | Accuracy | ECE | Human review | Cost USD | Tune | Held-out | Accepts | Wrong |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, result in report["classes"].items():
        samples = result["samples"]
        cutoff = "none" if result["cutoff"] is None else repr(result["cutoff"])
        lines.append(
            f"| {name} | {result['verdict']} | {cutoff} | {result['wrong_accept_upper_bound']:.6f} "
            f"| {_cell(result['accuracy'])} | {_cell(result['ece'])} | {_cell(result['human_review_rate'])} "
            f"| {_cell(result['cost']['measured_usd'])} | {samples['tune_rows']} | {samples['held_out_rows']} "
            f"| {samples['held_out_accepts']} | {samples['held_out_wrong_accepts']} |"
        )
    lines += ["", "## Reasons", ""]
    for name, result in report["classes"].items():
        causes = ", ".join(f"{cause} {count}" for cause, count in result["cause_counts"].items()) or "none recorded"
        lines.append(f"- **{name}**: {result['reason']}. Causes: {causes}.")
    lines += ["", "## Flags", ""]
    flags = decision_flags(report)
    if flags:
        lines += ["```", flags, "```"]
    else:
        lines.append("No class qualifies. This is a valid outcome; every class stays on `llm`.")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out: str | Path) -> Path:
    """Write ``calibration.json`` and ``calibration.md`` under ``out``, and nothing else."""
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    (root / "calibration.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (root / "calibration.md").write_text(render_markdown(report), encoding="utf-8")
    return root
