"""``sandbox pain-points``: per-document pain-point composites and per-experiment breakdowns.

Reads one or more finished ``task: pipeline`` runs and, with no model call, scores every
document's stored answer on the two client pain-point composites (``eval/pain_points.py``,
profile ``amfam-v1``): classification and entity extraction, 0 to 4 penalty points per document,
lower is better. It then breaks the points down by experiment (each run is one experiment,
named by its run id or a ``LABEL=RUN`` argument) and by any other key the run lock carries,
with a percentile-bootstrap 95% interval per group, and compares every experiment with a
baseline on the documents both scored (paired per-document differences).

Each document is scored with the current scorer and scoring hotfixes, exactly as a pipeline run
scores it now (``eval/runners.py``: ``_score_pipeline_extraction`` and the subclass check), so
runs made before the composites existed get them too. Truth rows come from the run's
``dataset.jsonl``; a committed report bundle has none, so its truth is rebuilt from the locked
dataset revision (``rescore.truth_spec``) or read from ``--dataset-file``.

Breakdown keys: ``experiment`` (the label), ``run_id``, ``doc_class`` (the truth class),
``model`` (the lock's engine model), ``profile``, ``prompt`` (the default prompt's
name@version) and ``mock`` (``true`` for a mock run, whose points are never model evidence:
``docs/critical-regressions.md`` row 8).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

#: Group keys read from the run (``doc_class`` is read from each document's truth).
GROUP_KEYS = ("experiment", "run_id", "doc_class", "model", "profile", "prompt", "mock")


class PainPointsError(ValueError):
    """A run cannot be scored on the composites (wrong task, no truth, a duplicate label)."""


def _jsonl(path: Path) -> list[dict[str, Any]]:
    # Split on "\n" only: splitlines() also breaks on U+2028 / U+2029 inside JSON strings (rescore._jsonl).
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def _finished_lock(files) -> tuple[dict[str, Any], str]:
    from mailroom_sandbox.job.checkpoint import TERMINAL_STATES

    lock = json.loads(files.files["spec.lock.json"].read_text(encoding="utf-8"))
    if not isinstance(lock, dict):
        raise PainPointsError(f"{files.path}: invalid spec.lock.json object")
    checkpoint = files.get("checkpoint.json")
    if checkpoint is None:
        return lock, "unverified (no checkpoint)"
    cp = json.loads(checkpoint.read_text(encoding="utf-8"))
    if not isinstance(cp, dict):
        raise PainPointsError(f"{files.path}: invalid checkpoint.json object")
    state = cp.get("state")
    if state not in TERMINAL_STATES:
        raise PainPointsError(f"{files.path}: checkpoint is {state!r}; score a finished pipeline run")
    expected = _checkpoint_identity(lock, cp, files.path)
    for key in ("run_id", "spec_hash", "generation_id"):
        if expected.get(key) and cp.get(key) != expected[key]:
            raise PainPointsError(f"{files.path}: checkpoint {key} differs from the locked generation")
    return lock, state


def _checkpoint_identity(lock: dict[str, Any], cp: dict[str, Any], path: Path) -> dict[str, Any]:
    expected = lock
    if lock.get("lock_kind") == "rescore.lock" and cp.get("run_id") != lock.get("run_id"):
        # Legacy derived runs copied their source checkpoint; validate its recorded source identity.
        source = lock.get("rescore") or {}
        expected = {"run_id": source.get("source_run"), "spec_hash": source.get("source_spec_hash"),
                    "generation_id": lock.get("generation_id")}
        if not expected["run_id"]:
            raise PainPointsError(f"{path}: derived checkpoint has no recorded source identity")
    return expected


def _truth_by_id(rows: Iterable[dict[str, Any]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        doc_id = str(row.get("id") or "")
        if not doc_id or doc_id in out:
            raise PainPointsError(f"truth has a missing or duplicate document id: {doc_id!r}")
        out[doc_id] = row
    return out


def run_groups(lock: Mapping[str, Any], label: str) -> dict[str, str]:
    """The breakdown labels a run lock carries (every value a string)."""
    engine = lock.get("engine") or {}
    prompt = (lock.get("prompt") or {}).get("default") or {}
    prompt_label = str(prompt.get("name") or prompt.get("label") or "default")
    if prompt.get("version"):
        prompt_label += f"@{prompt['version']}"
    return {
        "experiment": label,
        "run_id": str(lock.get("run_id") or label),
        "model": str(engine.get("model") or "unknown"),
        "profile": str(lock.get("profile") or "unknown"),
        "prompt": prompt_label,
        "mock": "true" if (lock.get("job") or {}).get("mock") else "false",
    }


def _truth(files, lock: Mapping[str, Any], order: Sequence[str], dataset_file: str | Path | None,
           truth_loader: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] | None,
           ) -> tuple[dict[str, dict], dict[str, Any]]:
    """``{doc_id: truth row}``: the run's dataset.jsonl, a local file, or the locked revision."""
    from mailroom_sandbox import rescore

    if dataset_file is None and files.get("dataset.jsonl"):
        blob = files.files["dataset.jsonl"].read_bytes()
        actual = hashlib.sha256(blob).hexdigest()
        expected = (lock.get("dataset") or {}).get("sha256")
        if not expected or actual != expected:
            raise PainPointsError(f"{files.path}: locked dataset sha256 missing or mismatched; "
                                  "restore dataset.jsonl or explicitly select new truth with --dataset-file")
        rows = [json.loads(line) for line in blob.decode("utf-8").split("\n") if line.strip()]
        return _truth_by_id(rows), {"source": "locked dataset.jsonl", "sha256": actual}
    if truth_loader is None:
        from mailroom_sandbox import corpus

        truth_loader = corpus.truth_rows
    rows, meta = truth_loader(rescore.truth_spec(lock, dataset_file=dataset_file), list(order))
    return _truth_by_id(rows), meta


def documents_for_run(run: str | Path, *, label: str | None = None, dataset_file: str | Path | None = None,
                      runs_root: Path | None = None,
                      truth_loader: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] | None = None,
                      ) -> tuple[list[Any], dict[str, Any]]:
    """Every scored document of one finished pipeline run, and the run's provenance.

    A document whose item failed (``ok`` false, an item or result error) keeps its failure, so it
    scores ``pipeline_failure`` rather than leaving the denominator. A document the truth lacks is
    counted under ``missing_truth`` and left out; a run with none in the truth is refused.
    """
    from mailroom_sandbox import rescore
    from mailroom_sandbox.eval import pain_points, runners, scoring

    try:
        files = rescore.locate(run, runs_root=runs_root)
    except rescore.RescoreError as exc:
        raise PainPointsError(str(exc)) from exc
    lock, state = _finished_lock(files)
    if lock.get("task") != "pipeline":
        raise PainPointsError(f"{run}: task {lock.get('task')!r}; the composites score pipeline runs only "
                              "(they need the final stage: archived or review)")
    run_id = str(lock.get("run_id") or files.path.name)
    # The Dojo strips group labels, so the label is stripped here too: "A" and " A " are one experiment.
    label = (label if label is not None else run_id).strip()
    if not label:
        raise PainPointsError(f"{run}: blank experiment label")
    groups = run_groups(lock, label)
    # A retried item appears more than once: the last line is the one the run kept (job/pair_report.py).
    latest = {str(it.get("item_id")): it for it in _jsonl(files.files["items.jsonl"])}
    order = list(latest)
    truth, truth_meta = _truth(files, lock, order, dataset_file, truth_loader)
    docs: list[Any] = []
    missing: list[str] = []
    for doc_id, item in latest.items():
        row = truth.get(doc_id)
        if row is None:
            missing.append(doc_id)
            continue
        pred = item.get("pred") if isinstance(item.get("pred"), dict) else {}
        error = item.get("error") or pred.get("error") or (None if item.get("ok", True) else "item not ok")
        result = {**pred, "error": error} if error else dict(pred)
        scored = runners._score_pipeline_extraction(row, result)
        sub = scoring.subclass_correct(row.get("expected_doc_class"), row.get("expected_subclass"),
                                       result.get("doc_type"), scoring.predicted_subclass(result))
        docs.append(pain_points.document(row, result, scored, subclass_ok=None if sub is None else bool(sub[1]),
                                         doc_id=doc_id, groups=groups))
    if not docs:
        raise PainPointsError(f"{run_id}: none of its {len(order)} documents is in the truth")
    return docs, {"run_id": run_id, "label": groups["experiment"], "path": str(files.path),
                  "documents": len(docs), "missing_truth": missing, "groups": groups,
                  "state": state, "locked_rows": (lock.get("dataset") or {}).get("rows"), "truth": truth_meta}


def parse_run_args(args: Iterable[str]) -> list[tuple[str, str | None]]:
    """``RUN`` or ``LABEL=RUN`` arguments -> ``[(run, label or None)]``."""
    out: list[tuple[str, str | None]] = []
    for arg in args:
        label, sep, run = arg.partition("=")
        out.append((run, label) if sep and label and run and not Path(arg).exists() else (arg, None))
    return out


def report(runs: Sequence[tuple[str, str | None]], *, by: Sequence[str] = ("experiment",),
           baseline: str | None = None, dataset_file: str | Path | None = None, n_boot: int = 2000,
           seed: int = 0, runs_root: Path | None = None,
           truth_loader: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] | None = None,
           ) -> dict[str, Any]:
    """Per-document points, run totals, breakdowns by ``by`` and paired comparisons with ``baseline``."""
    from mailroom_sandbox.eval import pain_points

    unknown = [k for k in by if k not in GROUP_KEYS]
    if unknown:
        raise PainPointsError(f"--by {','.join(unknown)}: expected keys from {', '.join(GROUP_KEYS)}")
    if not runs:
        raise PainPointsError("give at least one run")
    core, source = pain_points.core()
    docs: list[Any] = []
    provenance: list[dict[str, Any]] = []
    for run, label in runs:
        run_docs, meta = documents_for_run(run, label=label, dataset_file=dataset_file, runs_root=runs_root,
                                           truth_loader=truth_loader)
        if any(p["label"] == meta["label"] for p in provenance):
            raise PainPointsError(f"two runs share the experiment label {meta['label']!r}; name them LABEL=RUN")
        docs.extend(run_docs)
        provenance.append(meta)
    labels = [p["label"] for p in provenance]
    baseline = baseline.strip() if baseline is not None else None
    if baseline is not None and baseline not in labels:
        raise PainPointsError(f"--baseline {baseline!r}: not one of the experiments {labels}")
    per_run = {p["label"]: core.score_run([d for d in docs if d.groups["experiment"] == p["label"]])
               for p in provenance}
    out: dict[str, Any] = {
        "profile": core.DEFAULT_SCALE.profile,
        "source": source,
        "simulated": [p["label"] for p in provenance if p["groups"]["mock"] == "true"],
        "runs": provenance,
        "per_run": per_run,
        "breakdown": core.breakdown(docs, by=tuple(by), n_boot=n_boot, seed=seed),
        "documents": [core.score_document(d) for d in docs],
    }
    if baseline is not None and len(labels) > 1:
        out["compare"] = core.compare(docs, by="experiment", baseline=baseline, n_boot=n_boot, seed=seed)
    return out


def _fmt(value: Any, places: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{places}f}"


def _ci(block: Mapping[str, Any]) -> str:
    ci = block.get("ci")
    return "—" if not ci else f"[{_fmt(ci.get('lo'))}, {_fmt(ci.get('hi'))}]"


def _top(reasons: Mapping[str, int], n: int = 3) -> str:
    hits = sorted(((c, r) for r, c in reasons.items() if c), key=lambda t: (-t[0], t[1]))[:n]
    return ", ".join(f"{r} {c}" for c, r in hits) or "—"


def render(rep: Mapping[str, Any]) -> str:
    """The report as Markdown: provenance, one breakdown table per composite, comparisons."""
    lines = [f"# Pain-point composites ({rep['profile']})", "",
             "Penalty points per document, 0 (correct and complete) to 4 (needless human review). "
             "Lower is better; `score` is 1 - mean / 4.", "",
             f"Scorer: {rep['source']}."]
    if rep.get("simulated"):
        lines += ["", f"**Simulated (mock) runs, never model evidence:** {', '.join(rep['simulated'])}."]
    lines += ["", "| Experiment | Run | State | Documents | Locked rows | Missing truth |",
              "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {p['label']} | {p['run_id']} | {p['state']} | {p['documents']} | "
              f"{p['locked_rows'] if p['locked_rows'] is not None else 'unknown'} | {len(p['missing_truth'])} |"
              for p in rep["runs"]]
    by = rep["breakdown"]["by"]
    for composite in ("classification", "extraction"):
        lines += ["", f"## {composite.capitalize()}", "",
                  "| " + " | ".join(by) + " | n | mean points | 95% CI | score | top reasons |",
                  "| " + " | ".join("---" for _ in by) + " | --- | --- | --- | --- | --- |"]
        for group in rep["breakdown"]["groups"]:
            block = group[composite]
            lines.append("| " + " | ".join(str(group["key"][k]) for k in by)
                         + f" | {block['n']} | {_fmt(block['mean'])} | {_ci(block)} | {_fmt(block['score'])}"
                         + f" | {_top(block['reasons'])} |")
    comparison = rep.get("compare")
    if comparison:
        lines += ["", f"## Paired comparison with `{comparison['baseline']}`", "",
                  "Delta is candidate minus baseline on the documents both scored: positive means more "
                  "penalty (worse).", "",
                  "| Composite | Candidate | Paired n | Baseline mean | Candidate mean | Delta | 95% CI |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for composite in ("classification", "extraction"):
            for row in comparison[composite]:
                lines.append(f"| {composite} | {row['candidate']} | {row['n_paired']} | {_fmt(row['baseline_mean'])}"
                             f" | {_fmt(row['candidate_mean'])} | {_fmt(row['delta'])} | {_ci(row)} |")
    return "\n".join(lines) + "\n"


def register(sub, leaf) -> None:
    parser = sub.add_parser(
        "pain-points", parents=[leaf],
        help="score finished pipeline runs on the pain-point composites, per document and per experiment; no LLM calls",
    )
    parser.add_argument("runs", nargs="+", metavar="RUN",
                        help="run id under data/runtime/runs, a run or report-bundle directory, or LABEL=RUN")
    parser.add_argument("--by", default="experiment",
                        help=f"comma-separated breakdown keys from {', '.join(GROUP_KEYS)} (default experiment)")
    parser.add_argument("--baseline", default=None, help="experiment label to compare every other run with (paired)")
    parser.add_argument("--dataset-file", default=None, help="local JSONL truth (for report bundles, or new truth)")
    parser.add_argument("--documents", default=None, help="write every document's points and reasons to this JSONL")
    parser.add_argument("--out", default=None, help="write the full report JSON to this file")
    parser.add_argument("--n-boot", type=int, default=2000, help="bootstrap resamples per interval (default 2000)")
    parser.add_argument("--seed", type=int, default=0, help="bootstrap seed (default 0)")
    parser.add_argument("--json", action="store_true", help="print the report JSON instead of Markdown")
    parser.set_defaults(handler=_cli)


def _cli(args) -> int:
    import sys

    from mailroom_sandbox import rescore

    try:
        rep = report(parse_run_args(args.runs), by=[k.strip() for k in args.by.split(",") if k.strip()],
                     baseline=args.baseline, dataset_file=args.dataset_file, n_boot=args.n_boot, seed=args.seed)
    except (ValueError, rescore.RescoreError, FileNotFoundError) as exc:
        print(f"sandbox pain-points: {exc}", file=sys.stderr)
        return 2
    if args.documents:
        Path(args.documents).write_text("".join(json.dumps(d, default=str) + "\n" for d in rep["documents"]),
                                        encoding="utf-8")
    if args.out:
        Path(args.out).write_text(json.dumps(rep, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(rep, indent=2, default=str) if args.json else render(rep), end="" if not args.json else "\n")
    return 0
