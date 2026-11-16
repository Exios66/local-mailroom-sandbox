"""Markdown rendering of a production slice gate report (``gate.md``); pure, no I/O.

``render_markdown(report)`` takes the dict ``gate.gate_report`` returns, optionally with a ``step_up``
block (``gate_compare.step_up``) or a ``rerun`` block (``gate_compare.rerun``) and a ``thresholds`` block (``gate_compare.threshold_evidence``) added
by the CLI. The first line is the verdict: ``PASS`` or ``FAIL — <reasons>``. Archive links are rendered
relative to the checkout root (``data/archive/...``), so no home path reaches the Markdown; the JSON
report keeps the real paths.
"""
from __future__ import annotations

from pathlib import PurePath
from typing import Any, Mapping

from mailroom_sandbox.job.pair_report import render_markdown as render_paired


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _verdict_line(verdict: Mapping[str, Any]) -> str:
    return "PASS" if verdict["pass"] else "FAIL — " + "; ".join(verdict["reasons"])


def _rel(path: str | None) -> str | None:
    """``data/archive/...`` for a path inside a checkout's data dir; the bare name otherwise."""
    if not path:
        return None
    parts = PurePath(path).parts
    for i in range(len(parts) - 1):
        if parts[i] == "data" and parts[i + 1] in ("archive", "traces", "runtime"):
            return "/".join(parts[i:])
    return PurePath(path).name


def _class_table(report: Mapping[str, Any]) -> list[str]:
    lines = ["| Class | Gated | n | Review rate | Wrong-archive rate | Scorable / unscorable | Tokens/doc |",
             "|---|---|---|---|---|---|---|"]
    for cls, c in report["classes"].items():
        lines.append(f"| {cls} | {'yes' if c['gated'] else 'no'} | {c['n']} | {_pct(c['review_rate'])} | "
                     f"{_pct(c['wrong_archive_rate'])} | {c['scorable']} / {c['unscorable']} | "
                     f"{_pct(c['tokens_per_doc'])} |")
    return lines


def _pooled_line(report: Mapping[str, Any]) -> str:
    p, bars = report["pooled"], report["bars"]
    return (f"Pooled over the gated classes: review rate {_pct(p['review_rate'])} (Wilson 95% upper "
            f"{_pct(p['review_upper95'])}, bar {bars['review_max']:g}); wrong-archive rate "
            f"{_pct(p['wrong_archive_rate'])} (Wilson 95% upper {_pct(p['wrong_archive_upper95'])}, bar "
            f"{bars['wrong_archive_max']:g}); scorable {p['scorable']}, unscorable {p['unscorable']}; "
            f"crashes {p['crashes']}, judge_error {p['judge_errors']}.")


def _audit_lines(report: Mapping[str, Any]) -> list[str]:
    audit = report.get("audit")
    if audit is None:
        return ["Audit trail: skipped."]
    n = report["n"]
    archived = sum(1 for d in report["docs"] if d["stage"] == "archived")
    linked_archives = sum(1 for d in report["docs"] if d["stage"] == "archived" and (audit["archives"] or {}).get(d["id"]))
    linked_spans = sum(1 for v in (audit["span_ids"] or {}).values() if v)
    mirror = "present" if audit["span_mirror"] else "absent or unreadable"
    return [f"Audit trail ({'ok' if audit['ok'] else 'FAILED'}): span mirror {mirror}; "
            f"{linked_spans}/{n} documents linked to a span, {n - len(audit['missing_nodes'])}/{n} to a node log, "
            f"{linked_archives}/{archived} archived documents to an archive; "
            f"missing: spans {len(audit['missing_spans'])}, nodes {len(audit['missing_nodes'])}, "
            f"archives {len(audit['missing_archive'])}."]


def _bucket_table(report: Mapping[str, Any]) -> list[str]:
    buckets = report["buckets"]
    if not buckets:
        return ["No review, wrong-archive or crashed documents."]
    lines = ["| Cause | Count | Document (archive) | Span |", "|---|---|---|---|"]
    for cause, bucket in buckets.items():
        for i, doc in enumerate(bucket["docs"]):
            archive = _rel(doc.get("archive"))
            link = f"[{doc['id']}]({archive})" if archive else f"{doc['id']} (no archive)"
            span = f"`{doc['span_id']}`" if doc.get("span_id") else "—"
            lines.append(f"| {cause if i == 0 else ''} | {bucket['count'] if i == 0 else ''} | {link} | {span} |")
    return lines


def _rerun_lines(rerun: Mapping[str, Any]) -> list[str]:
    before, after = rerun["prev_pooled"], rerun["next_pooled"]
    lines = ["## Re-run (paired, same slice)", "",
             f"`{rerun['prev']}` → `{rerun['next']}`: {rerun['shared_docs']} shared documents"
             f"{'' if rerun['same_documents'] else ' (the runs drew DIFFERENT documents)'}. Kept only when not worse.", "",
             f"Re-run verdict: {_verdict_line(rerun['verdict'])}", "",
             "| Pooled (gated) | earlier | re-run |", "|---|---|---|"]
    for key in ("wrong_archive_rate", "review_rate", "crashes", "judge_errors"):
        old, new = before.get(key), after.get(key)
        fmt = _pct if key.endswith("_rate") else str
        lines.append(f"| {key} | {fmt(old)} | {fmt(new)} |")
    lines += ["", render_paired(rerun["shared_paired"])]
    return lines


def _step_up_lines(step: Mapping[str, Any]) -> list[str]:
    new = step["new_docs_gate"]
    lines = ["## Step-up", "",
             f"`{step['prev']}` → `{step['next']}`: {len(step['new_docs'])} new documents, slices "
             f"{'nest' if step['nested'] else 'DO NOT nest'}. The step-up verdict is read on the new documents only.", "",
             f"Step-up verdict: {_verdict_line(step['verdict'])}", "", _pooled_line(new), ""]
    lines += _class_table(new)
    lines += ["", "Shared documents (diagnostic, does not decide the verdict):", "",
              render_paired(step["shared_paired"])]
    return lines


def _thresholds_lines(ev: Mapping[str, Any]) -> list[str]:
    lines = ["## Threshold evidence", "",
             f"Replay of \"archived with extraction_confidence < t goes to the judge\" (offline; {ev['label']}).", "",
             "| Scope | Archived | No confidence | t | Extra judged | Wrong archives caught (upper bound) | Correct archives disturbed |",
             "|---|---|---|---|---|---|---|"]
    for scope, block in (("pooled", ev["pooled"]), *ev["classes"].items()):
        for i, (t, row) in enumerate(block["thresholds"].items()):
            lead = f"| {scope} | {block['archived']} | {block['no_confidence']} " if i == 0 else "| | | "
            lines.append(f"{lead}| {float(t):.2f} | {row['extra_judged']} | {row['wrong_archives_caught_upper_bound']} | "
                         f"{row['correct_archives_disturbed']} |")
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    """The gate report as Markdown: verdict first, then classes, pooled line, audit, buckets, optional sections."""
    verdict = report["verdict"]
    lines = [_verdict_line(verdict), "", f"# Slice gate: `{report['run_id']}` ({report['n']} documents)", ""]
    if verdict.get("warnings"):
        lines += ["## Warnings", "", *[f"- {w}" for w in verdict["warnings"]], ""]
    bars = report["bars"]
    lines += ["## Classes", "", *_class_table(report), "", _pooled_line(report), "",
              f"Bars: quality {bars['quality']:g}, wrong-archive max {bars['wrong_archive_max']:g}, review max "
              f"{bars['review_max']:g}; per-class bars apply from n={bars['per_class_from_n']} "
              f"(this slice: {report['n']}).", "",
              "## Audit", "", *_audit_lines(report), "",
              "## Buckets", "", *_bucket_table(report)]
    if report.get("step_up"):
        lines += ["", *_step_up_lines(report["step_up"])]
    if report.get("rerun"):
        lines += ["", *_rerun_lines(report["rerun"])]
    if report.get("thresholds"):
        lines += ["", *_thresholds_lines(report["thresholds"])]
    return "\n".join(lines) + "\n"
