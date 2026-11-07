#!/usr/bin/env python3
"""Validate a new sorter prompt against the saved V14 pass, scored on the verified targets.

Two steps, no model call in either:

``inputs`` writes ``data/runtime/handoff/<split>-sorter-errors.jsonl`` (the dataset rows the
``sorter-v15-qwen-*`` run specs read): every document the saved pass got wrong against the
verified targets (class, or subclass with the class right), plus a seeded control sample of
documents it got right, stratified by class, so a fix that breaks a right answer shows up.
Document text comes from the locked ``dataset.jsonl`` of any run over the same split.

``score`` compares a finished run of the new prompt with the saved pass on the same
documents: per document fixed / broken / still wrong / still right, for class and subclass,
grouped by the V14 error pattern. Writes ``reports/sorter-handoff/<run>.compare.json``.

    python scripts/compare_sorter_prompt.py --split train inputs \\
        --dataset-run reviewer-calibration-luna-decisions-v3.1.0-train
    sandbox run start --config config/runs/sorter-v15-qwen-train-errors.yaml --initials XX
    python scripts/compare_sorter_prompt.py --split train score --run sorter-v15-qwen-train-errors

``--prime --current-labels DIR`` keeps only documents with the highest-quality labels before any
selection (see ``prime_targets``): the verified target must agree with the published ground truth
in ``DIR`` (a ``parquet/ground_truth`` directory of the current Hub release), its status must be a
label (as published, normalized, or corrected by two independent sources), class and subclass
must both be scored, a contract's subclass must come from CUAD (expert-curated) rather than the
SEC EX-10 exhibit-title heuristic, a document the saved pass mis-classed must have its label
confirmed by a corpus rule or the reviewer, a confident reviewer (p >= 0.9) must not dispute the
class or subclass, and a corporate record's subclass (an EDGAR exhibit heuristic) must be
confirmed by its title line or the reviewer with neither naming another subclass. ``inputs``
writes the draw to ``<file>.selection.json``; ``score`` grades exactly that draw.

``--sample`` is the controlled, cheaper set: every class error the saved pass made (the
cross-class confusions), then per target class/subclass stratum a seeded draw of
``--sample-errors`` subclass errors and ``--sample-controls`` right answers, so every subclass
is tested and none dominates. It writes ``<split>-sorter-sample.jsonl`` and scores the same
draw. ``--corpus-cache`` takes the document text from the sandbox's pinned corpus cache
instead of a run's dataset.jsonl (the text is the same in every v9.x release).

    python scripts/compare_sorter_prompt.py --split train --sample inputs \
        --corpus-cache data/cache/Lucius-Morningstar__mailroom-dataset__bc9eab280044/ground_truth_all.jsonl
    python scripts/compare_sorter_prompt.py --split train --sample score --run sorter-condensed-v1-qwen-train-sample
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re
from pathlib import Path

from mailroom_sandbox.paths import repo_root

HANDOFF = "sorter-qwen3.7-flash"
CONTROL_PER_CLASS = 40
SAMPLE_ERRORS_PER_STRATUM = 3
SAMPLE_CONTROLS_PER_STRATUM = 2


def _lines(path: Path) -> list[dict]:
    """JSONL rows split on newline only (document text holds U+2028 and other separators)."""
    with path.open(encoding="utf-8", newline="\n") as handle:
        return [json.loads(line) for line in handle.read().split("\n") if line.strip()]


def _targets(root: Path, name: str, split: str) -> dict[str, dict]:
    return {row["id"]: row for row in _lines(root / "data" / "handoff" / name / f"{split}.targets.jsonl")}


def _norm_contract(value):
    from llm_dojo_scoring.equivalences import normalize_subtype

    return normalize_subtype(value) if value else value


def pattern(target: dict) -> str | None:
    """The V14 error a target row shows, or None when the saved pass was right (or unscored)."""
    if not target.get("use_for_class"):
        return None
    if not target.get("sorter_class_correct"):
        return f"class {target['target_doc_class']} -> {target['sorter_doc_type']}"
    if target.get("use_for_subclass") and target.get("sorter_subclass_correct") is False:
        return f"subclass {target['target_doc_class']}/{target['target_subclass']} -> {target['sorter_doc_subclass']}"
    return None


def select(targets: dict[str, dict], *, control_per_class: int = CONTROL_PER_CLASS, seed: int = 42) -> dict[str, str]:
    """Document id -> why it is in the validation set (an error pattern, or ``control``)."""
    chosen = {doc_id: p for doc_id, t in targets.items() if (p := pattern(t))}
    right: dict[str, list[str]] = collections.defaultdict(list)
    for doc_id, t in sorted(targets.items()):
        if doc_id not in chosen and t.get("use_for_class") and t.get("use_for_subclass"):
            right[t["target_doc_class"]].append(doc_id)
    rng = random.Random(seed)
    for cls in sorted(right):
        for doc_id in rng.sample(right[cls], min(control_per_class, len(right[cls]))):
            chosen[doc_id] = "control"
    return chosen


PRIME_STATUSES = ("label", "label_normalized", "corrected")
CUAD_SOURCE = "theatticusproject/cuad"


def _patch_rules():
    """The rules that built the targets (``CONTRACT_KEYS``, ``label_confirmed``), one definition."""
    import importlib.util

    path = Path(__file__).resolve().parent / "patch_sorter_handoff.py"
    spec = importlib.util.spec_from_file_location("patch_sorter_handoff", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def current_labels(directory: Path) -> dict[str, dict]:
    """filename -> {class, subclass, source} from a published ``parquet/ground_truth`` directory."""
    import pyarrow.parquet as pq

    keys = _patch_rules().CONTRACT_KEYS
    out = {}
    for path in sorted(Path(directory).glob("*/*.parquet")):
        for r in pq.read_table(path, columns=["filename", "expected", "expected_subclass",
                                              "annotation_source"]).to_pylist():
            sub = r["expected_subclass"]
            if r["expected"] == "contract" and sub:
                sub = keys.get(re.sub(r"[^a-z]+", "_", sub.lower()).strip("_"), sub)
            out[r["filename"]] = {"class": r["expected"], "subclass": sub, "source": r["annotation_source"]}
    if not out:
        raise SystemExit(f"compare_sorter_prompt: no ground_truth parquet under {directory}")
    return out


REVIEWER_MIN_P = 0.9


def _reviewer_verdict(t: dict) -> str | None:
    """``agrees`` / ``disputes`` for a confident reviewer answer, else None."""
    r = t.get("reviewer_evidence") or {}
    if not r or (r.get("p") or 0) < REVIEWER_MIN_P:
        return None
    same = r.get("doc_type") == t["target_doc_class"] and r.get("doc_subclass") == t["target_subclass"]
    return "agrees" if same else "disputes"


def prime_targets(targets: dict[str, dict], current: dict[str, dict],
                  texts: dict[str, str]) -> tuple[dict[str, dict], dict[str, int]]:
    """Targets whose labels are the highest quality, and the excluded count per reason."""
    rules = _patch_rules()
    kept, dropped = {}, collections.Counter()
    for doc_id, t in targets.items():
        now = current.get(t["filename"])
        title = rules._title_class(texts.get(doc_id) or "") if t.get("target_doc_class") == "corporate_record" else None
        review = _reviewer_verdict(t) if t.get("target_doc_class") else None
        if t.get("target_status") not in PRIME_STATUSES:
            why = f"status {t.get('target_status')}"
        elif not (t.get("use_for_class") and t.get("use_for_subclass")):
            why = "class or subclass not scored"
        elif now is None or (now["class"], now["subclass"]) != (t["target_doc_class"], t["target_subclass"]):
            why = "target disagrees with the published label"
        elif t["target_doc_class"] == "contract" and now["source"] != CUAD_SOURCE:
            why = "contract subclass from the EX-10 exhibit-title heuristic"
        elif not t.get("sorter_class_correct") and not rules.label_confirmed(t.get("target_evidence") or []):
            why = "class error with an unconfirmed label"
        elif review == "disputes":
            why = "the reviewer disputes the label"
        elif t["target_doc_class"] == "corporate_record" and title not in (None, ("corporate_record", t["target_subclass"])):
            why = "corporate subclass disputed by the title line"
        elif t["target_doc_class"] == "corporate_record" and title is None and review != "agrees":
            why = "corporate subclass unverified (no title rule or reviewer confirms it)"
        else:
            kept[doc_id] = t
            continue
        dropped[why] += 1
    return kept, dict(sorted(dropped.items()))


def stratum(target: dict) -> str:
    return f"{target['target_doc_class']}/{target['target_subclass']}"


def select_sample(targets: dict[str, dict], *, errors_per_stratum: int = SAMPLE_ERRORS_PER_STRATUM,
                  controls_per_stratum: int = SAMPLE_CONTROLS_PER_STRATUM, seed: int = 42) -> dict[str, str]:
    """The controlled set: every class error, then per target stratum a seeded draw of subclass
    errors and of right answers. Document id -> why it is in the set (pattern or ``control``)."""
    chosen: dict[str, str] = {}
    errors: dict[str, list[str]] = collections.defaultdict(list)
    right: dict[str, list[str]] = collections.defaultdict(list)
    for doc_id, t in sorted(targets.items()):
        p = pattern(t)
        if p and p.startswith("class "):
            chosen[doc_id] = p
        elif p:
            errors[stratum(t)].append(doc_id)
        elif t.get("use_for_class") and t.get("use_for_subclass"):
            right[stratum(t)].append(doc_id)
    rng = random.Random(seed)
    for key in sorted(set(errors) | set(right)):
        for doc_id in rng.sample(errors[key], min(errors_per_stratum, len(errors[key]))):
            chosen[doc_id] = pattern(targets[doc_id])
        for doc_id in rng.sample(right[key], min(controls_per_stratum, len(right[key]))):
            chosen[doc_id] = "control"
    return chosen


def _targets_for(args: argparse.Namespace, root: Path, texts: dict[str, str]) -> tuple[dict[str, dict], dict]:
    targets = _targets(root, args.name, args.split)
    if not args.prime:
        return targets, {}
    if not args.current_labels:
        raise SystemExit("compare_sorter_prompt: --prime needs --current-labels")
    directory = Path(args.current_labels)
    kept, dropped = prime_targets(targets, current_labels(directory), texts)
    marker = directory.parent.parent / ".hub_revision"  # written by Mailroom-Corpus-EDA's download
    revision = marker.read_text(encoding="utf-8").strip() if marker.is_file() else "unknown"
    return kept, {"prime": {"kept": len(kept), "of": len(targets), "excluded": dropped,
                            "labels_revision": revision}}


def _chosen(args: argparse.Namespace, targets: dict[str, dict]) -> dict[str, str]:
    if args.sample:
        return select_sample(targets, errors_per_stratum=args.sample_errors,
                             controls_per_stratum=args.sample_controls, seed=args.seed)
    return select(targets, control_per_class=args.control_per_class, seed=args.seed)


def _dataset_path(root: Path, args: argparse.Namespace) -> Path:
    name = ("prime-" if args.prime else "") + ("sample" if args.sample else "errors")
    return root / "data" / "runtime" / "handoff" / f"{args.split}-sorter-{name}.jsonl"


def _selection_path(dataset: Path) -> Path:
    return dataset.with_suffix(".selection.json")


def cmd_inputs(args: argparse.Namespace) -> int:
    root = repo_root()
    rows: dict[str, dict] = {}
    sources = [root / "data" / "runtime" / "runs" / rid / "dataset.jsonl" for rid in args.dataset_run or ()]
    sources += [Path(args.corpus_cache)] if args.corpus_cache else []
    for path in sources:
        for row in _lines(path):
            rows.setdefault(row["id"], row)
    targets, quality = _targets_for(args, root, {k: r.get("doc_text") or "" for k, r in rows.items()})
    chosen = _chosen(args, targets)
    missing = sorted(set(chosen) - set(rows))
    if missing:
        print(f"compare_sorter_prompt: {len(missing)} selected documents are not in the dataset runs given")
        return 1
    out = _dataset_path(root, args)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(rows[doc_id], ensure_ascii=False, sort_keys=True) + "\n" for doc_id in sorted(chosen))
    out.write_text(text, encoding="utf-8")
    sha = hashlib.sha256(text.encode()).hexdigest()
    _selection_path(out).write_text(json.dumps({"dataset_sha256": sha, "chosen": chosen, **quality},
                                               indent=2, sort_keys=True) + "\n", encoding="utf-8")
    why = collections.Counter("control" if p == "control" else p.split(" ", 1)[0] for p in chosen.values())
    chars = sum(len(rows[doc_id].get("doc_text") or "") for doc_id in chosen)
    strata = len({stratum(targets[doc_id]) for doc_id in chosen})
    print(json.dumps({"file": str(out.relative_to(root)), "documents": len(chosen), "strata": strata,
                      "by_reason": dict(why), **quality,
                      "sha256": hashlib.sha256(text.encode()).hexdigest(), "doc_chars": chars}, indent=2))
    return 0


def _run_answers(root: Path, run_id: str) -> dict[str, dict]:
    out = {}
    for item in _lines(root / "data" / "runtime" / "runs" / run_id / "items.jsonl"):
        pred = item.get("pred") or {}
        if item.get("ok") and not item.get("error") and pred.get("doc_type"):
            sub = pred.get("doc_subclass") or pred.get("contract_subtype")
            out[str(item["item_id"])] = {"doc_type": pred["doc_type"],
                                         "doc_subclass": _norm_contract(sub) if pred["doc_type"] == "contract" else sub}
    return out


def compare(targets: dict[str, dict], chosen: dict[str, str], answers: dict[str, dict]) -> dict:
    """Class and subclass outcome of the new prompt against the saved pass, per V14 pattern."""
    tally: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    totals = collections.Counter()
    for doc_id, why in sorted(chosen.items()):
        t = targets[doc_id]
        new = answers.get(doc_id)
        if new is None:
            tally[why]["no_answer"] += 1
            totals["no_answer"] += 1
            continue
        for level in ("class", "subclass"):
            if level == "class":
                if not t.get("use_for_class"):
                    continue
                before, after = bool(t["sorter_class_correct"]), new["doc_type"] == t["target_doc_class"]
            else:
                if not t.get("use_for_subclass"):
                    continue
                before = bool(t["sorter_subclass_correct"])
                after = new["doc_type"] == t["target_doc_class"] and new["doc_subclass"] == t["target_subclass"]
            outcome = {(False, True): "fixed", (True, False): "broken",
                       (False, False): "still_wrong", (True, True): "still_right"}[(before, after)]
            tally[why][f"{level}_{outcome}"] += 1
            totals[f"{level}_{outcome}"] += 1
            totals[f"{level}_scored"] += 1
            totals[f"{level}_right_before"] += before
            totals[f"{level}_right_after"] += after
    return {"documents": len(chosen), "answered": sum(doc_id in answers for doc_id in chosen),
            "totals": dict(totals), "by_pattern": {k: dict(v) for k, v in sorted(tally.items())}}


def cmd_score(args: argparse.Namespace) -> int:
    root = repo_root()
    targets = _targets(root, args.name, args.split)
    if args.prime or args.sample:
        path = _selection_path(_dataset_path(root, args))
        if not path.is_file():
            raise SystemExit(f"compare_sorter_prompt: {path} missing; run inputs with the same flags first")
        saved = json.loads(path.read_text(encoding="utf-8"))
        chosen = saved["chosen"]
        quality = {k: v for k, v in saved.items() if k == "prime"} | {"dataset_sha256": saved["dataset_sha256"]}
    else:
        chosen, quality = _chosen(args, targets), {}
    answers = _run_answers(root, args.run)
    extra = sorted(set(answers) - set(chosen))
    if extra:
        print(f"compare_sorter_prompt: run {args.run} answered {len(extra)} documents outside this "
              f"selection; check --sample and its counts match the inputs the run used")
        return 1
    result = {"run_id": args.run, "baseline": f"data/handoff/{args.name}/{args.split}.targets.jsonl", **quality,
              **compare(targets, chosen, answers)}
    out = root / "reports" / "sorter-handoff" / f"{args.run}.compare.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["totals"], indent=2, sort_keys=True))
    print(f"wrote {out.relative_to(root)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default=HANDOFF, help="saved sorter pass under data/handoff/")
    parser.add_argument("--split", default="train")
    parser.add_argument("--control-per-class", type=int, default=CONTROL_PER_CLASS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prime", action="store_true", help="only the highest-quality labels (see above)")
    parser.add_argument("--current-labels", help="published parquet/ground_truth dir for --prime")
    parser.add_argument("--sample", action="store_true", help="the controlled per-stratum set (see above)")
    parser.add_argument("--sample-errors", type=int, default=SAMPLE_ERRORS_PER_STRATUM,
                        help="subclass errors drawn per target stratum")
    parser.add_argument("--sample-controls", type=int, default=SAMPLE_CONTROLS_PER_STRATUM,
                        help="right answers drawn per target stratum")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_in = sub.add_parser("inputs", help="write the validation dataset rows")
    text = p_in.add_mutually_exclusive_group(required=True)
    text.add_argument("--dataset-run", action="append",
                      help="run whose locked dataset.jsonl holds the document text (repeatable)")
    text.add_argument("--corpus-cache", help="pinned full-corpus JSONL (data/cache/.../ground_truth_all.jsonl)")
    p_sc = sub.add_parser("score", help="compare a finished run with the saved pass")
    p_sc.add_argument("--run", required=True)
    args = parser.parse_args()
    return cmd_inputs(args) if args.cmd == "inputs" else cmd_score(args)


if __name__ == "__main__":
    raise SystemExit(main())
