"""Paired control/treatment report for ladder runs, with and without templated GT fields.

Both arms of a ladder pair draw the same documents. This module re-scores each arm's
archived predictions offline against the locked rows (``dataset.jsonl``, which already
carries any interim labels the run enabled) twice: on every labelled field, and with the
fields whose Hub labels are templated removed. Corporate-record and correspondence
``keywords`` / ``subject_matter`` are filing metadata or a ``"<subclass> of <Company>"``
template on most rows (llm-dojo-scoring #164, #94), so a correct extraction scores low on
them. No LLM call; nothing is written.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

# Fields whose Hub labels are templated for the class (llm-dojo-scoring #164 corporate, #94 correspondence).
TEMPLATED_FIELDS: dict[str, tuple[str, ...]] = {
    "corporate_record": ("keywords", "subject_matter"),
    "correspondence": ("keywords", "subject_matter"),
}

# Two-sided 95% Student t critical values by degrees of freedom (normal beyond 30).
_T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23,
        11: 2.20, 12: 2.18, 13: 2.16, 14: 2.14, 15: 2.13, 16: 2.12, 17: 2.11, 18: 2.10, 19: 2.09,
        20: 2.09, 21: 2.08, 22: 2.07, 23: 2.07, 24: 2.06, 25: 2.06, 26: 2.06, 27: 2.05, 28: 2.05,
        29: 2.05, 30: 2.04}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _fields(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("expected_fields")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {}
    return dict(raw or {})


def without_fields(row: Mapping[str, Any], drop: Iterable[str]) -> dict[str, Any]:
    """The row with ``drop`` removed from its expected fields (a copy)."""
    drop = set(drop)
    fields = {k: v for k, v in _fields(row).items() if k not in drop}
    return {**row, "expected_fields": fields}


def load_arm(run_dir: Path) -> dict[str, dict[str, Any]]:
    """``{doc_id: {"row", "item", "nodes"}}`` for one run directory.

    ``dataset.jsonl`` and ``items.jsonl`` are required: a misspelled run id raises
    ``FileNotFoundError`` instead of yielding an empty report. ``nodes.jsonl`` is optional telemetry.
    """
    for required in ("dataset.jsonl", "items.jsonl"):
        if not (run_dir / required).is_file():
            raise FileNotFoundError(f"{run_dir}: missing {required}")
    rows = {str(r.get("id")): r for r in _jsonl(run_dir / "dataset.jsonl")}
    items = {str(r.get("item_id")): r for r in _jsonl(run_dir / "items.jsonl")}
    nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in _jsonl(run_dir / "nodes.jsonl"):
        if n.get("status") == "done":
            nodes[str(n.get("doc"))].append(n)
    return {doc: {"row": rows[doc], "item": items[doc],
                  "nodes": sorted(nodes.get(doc, []), key=lambda n: float(n.get("ts") or 0))}
            for doc in items if doc in rows}


def _score(row: Mapping[str, Any], pred: Mapping[str, Any]) -> float | None:
    from mailroom_sandbox.eval.runners import _score_pipeline_extraction

    if not _fields(row):
        return None
    scored = _score_pipeline_extraction(dict(row), dict(pred)) or {}
    value = scored.get("overall_extraction_score")
    return float(value) if isinstance(value, (int, float)) else None


def _ci(diffs: list[float]) -> tuple[float, float, float] | None:
    if not diffs:
        return None
    mean = statistics.fmean(diffs)
    if len(diffs) < 2:
        return mean, math.nan, math.nan
    half = _T95.get(len(diffs) - 1, 1.96) * statistics.stdev(diffs) / math.sqrt(len(diffs))
    return mean, mean - half, mean + half


def _doc_stats(doc: Mapping[str, Any]) -> dict[str, Any]:
    item, seq = doc["item"], doc["nodes"]
    score = item.get("score") or {}
    names = [n.get("node") for n in seq]
    verdicts = [d.get("answer") for n in seq if n.get("node") == "judge_verify"
                for d in n.get("decisions") or [] if d.get("question") == "extraction_verdict"]
    return {
        "stage": (item.get("pred") or {}).get("stage"),
        "cuad_fp": score.get("cuad_fp"), "cuad_fn": score.get("cuad_fn"),
        "judge_calls": names.count("judge_verify"), "retries": names.count("retry_extract"),
        "verdicts": verdicts,
        "tokens": int(item.get("prompt_tokens") or 0) + int(item.get("completion_tokens") or 0),
    }


def paired_report(control_dir: Path, treatment_dir: Path,
                  templated: Mapping[str, tuple[str, ...]] = TEMPLATED_FIELDS) -> dict[str, Any]:
    """Per-class paired summary over the documents both arms finished."""
    control, treatment = load_arm(control_dir), load_arm(treatment_dir)
    common = sorted(set(control) & set(treatment))
    # A document whose locked labels differ between the arms (for example interim labels in one
    # arm only) would show the label change as a pipeline difference, so it is not paired.
    label_mismatch = [d for d in common if _fields(control[d]["row"]) != _fields(treatment[d]["row"])]
    shared = [d for d in common if d not in set(label_mismatch)]
    by_class: dict[str, list[str]] = defaultdict(list)
    for doc in shared:
        by_class[str(control[doc]["row"].get("expected_doc_class"))].append(doc)
    out: dict[str, Any] = {"control": control_dir.name, "treatment": treatment_dir.name,
                           "shared_docs": len(shared),
                           "only_control": sorted(set(control) - set(treatment)),
                           "only_treatment": sorted(set(treatment) - set(control)),
                           "label_mismatch": label_mismatch, "classes": {}}
    for cls, docs in sorted(by_class.items()):
        drop = templated.get(cls, ())
        lanes: dict[str, dict[str, list[float]]] = {"all_fields": {"c": [], "t": []}}
        if drop:
            lanes["without_templated"] = {"c": [], "t": []}
        arms: dict[str, Counter] = {"c": Counter(), "t": Counter()}
        verdicts: dict[str, Counter] = {"c": Counter(), "t": Counter()}
        for doc in docs:
            for key, arm in (("c", control[doc]), ("t", treatment[doc])):
                pred = (arm["item"].get("pred") or {})
                lanes["all_fields"][key].append(_score(arm["row"], pred))
                if drop:
                    lanes["without_templated"][key].append(_score(without_fields(arm["row"], drop), pred))
                stats = _doc_stats(arm)
                arms[key].update({"review": stats["stage"] == "review", "judge_calls": stats["judge_calls"],
                                  "retries": stats["retries"], "tokens": stats["tokens"],
                                  "cuad_fp": stats["cuad_fp"] or 0, "cuad_fn": stats["cuad_fn"] or 0})
                verdicts[key].update(stats["verdicts"])
        summary: dict[str, Any] = {"n": len(docs), "dropped_fields": list(drop)}
        for lane, vals in lanes.items():
            pairs = [(c, t) for c, t in zip(vals["c"], vals["t"]) if c is not None and t is not None]
            ci = _ci([t - c for c, t in pairs])
            summary[lane] = {
                "scored": len(pairs),
                "control": statistics.fmean(c for c, _ in pairs) if pairs else None,
                "treatment": statistics.fmean(t for _, t in pairs) if pairs else None,
                "diff": ci[0] if ci else None, "ci95": [ci[1], ci[2]] if ci else None,
            }
        summary["control_counts"], summary["treatment_counts"] = dict(arms["c"]), dict(arms["t"])
        summary["control_verdicts"], summary["treatment_verdicts"] = dict(verdicts["c"]), dict(verdicts["t"])
        out["classes"][cls] = summary
    return out


def render_markdown(report: Mapping[str, Any]) -> str:
    def f(v: Any) -> str:
        return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.3f}" if isinstance(v, float) else str(v)

    lines = [f"Paired report: `{report['control']}` → `{report['treatment']}` ({report['shared_docs']} shared documents)", "",
             "| Class | n | Lane | Control | Treatment | Diff (95% CI) | Review c→t | Judge calls c→t | Retries c→t | Tokens c→t | CUAD FP c→t | CUAD FN c→t |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for cls, s in report["classes"].items():
        c, t = s["control_counts"], s["treatment_counts"]
        for lane in ("all_fields", "without_templated"):
            if lane not in s:
                continue
            q = s[lane]
            ci = q["ci95"] or [None, None]
            lines.append(
                f"| {cls} | {s['n']} | {lane.replace('_', ' ')} | {f(q['control'])} | {f(q['treatment'])} | "
                f"{f(q['diff'])} ({f(ci[0])} to {f(ci[1])}) | {c.get('review', 0)}→{t.get('review', 0)} | "
                f"{c.get('judge_calls', 0)}→{t.get('judge_calls', 0)} | {c.get('retries', 0)}→{t.get('retries', 0)} | "
                f"{c.get('tokens', 0)}→{t.get('tokens', 0)} | {c.get('cuad_fp', 0)}→{t.get('cuad_fp', 0)} | "
                f"{c.get('cuad_fn', 0)}→{t.get('cuad_fn', 0)} |")
    for cls, s in report["classes"].items():
        lines.append(f"\n{cls} judge verdicts: control {s['control_verdicts'] or {}}, treatment {s['treatment_verdicts'] or {}}")
    if report["only_control"] or report["only_treatment"]:
        lines.append(f"\nUnpaired: control only {report['only_control']}, treatment only {report['only_treatment']}")
    if report.get("label_mismatch"):
        lines.append(f"\nExcluded, labels differ between the arms: {report['label_mismatch']}")
    return "\n".join(lines)
