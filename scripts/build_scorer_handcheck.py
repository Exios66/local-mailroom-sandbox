#!/usr/bin/env python3
"""Build the R02 scorer hand-check sheet: 20 dev documents, perturbed predictions (offline).

    HF_HUB_OFFLINE=1 python scripts/build_scorer_handcheck.py [--draft]

Truth is the pinned Hub corpus at the split's revision (``config/splits/runbook-v1/manifest.json``)
with the interim and near-gold overlays, read from the local HF cache exactly as a run with
``interim_labels: true`` and ``near_gold_labels: true`` prepares it. The sorter answers are the
saved real v0 pass in ``data/handoff/sorter-qwen3.7-flash`` (checked per document against the
truth row's ``content_sha256``); the extractions are the truth perturbed in known ways
(``mailroom_sandbox.scorer_handcheck``). Writes to ``reports/campaigns/rb1/rb1-r02-scorer-handcheck/``:

* ``rb1-r02.sheet.csv``: one row per check with truth, prediction and an empty ``hand_score``;
  ``--draft`` pre-fills the rows the labeling guide and the documented scorer rules settle,
  marked ``hand_scored_by=agent-draft`` (a person must still confirm every row);
* ``rb1-r02.cases.jsonl``: the replayable prediction per document (no document text);
* ``rb1-r02.provenance.json``: label commit named by the runbook (e90ac8b9) and the label files changed
  since, overlay fingerprints, the vendored Dojo pin, dataset revision, split and sorter-pass hashes.

A sheet holding any person's score is never overwritten without ``--force``.
``--rows FILE`` reads prepared rows (``dataset.jsonl`` shape) instead of the HF cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mailroom_sandbox import scorer_handcheck as hc
from mailroom_sandbox.paths import repo_root

DEFAULT_SPLIT = Path("config/splits/runbook-v1")
DEFAULT_PASS = Path("data/handoff/sorter-qwen3.7-flash")
DEFAULT_OUT = Path("reports/campaigns/rb1/rb1-r02-scorer-handcheck")


def _sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rel(path: Path, root: Path) -> str:
    """A repo-relative path for the record (never an absolute home path)."""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return Path(path).name


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _ids(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def dataset_spec(split_dir: Path, revision: str):
    from mailroom_sandbox.job.spec import DatasetSpec

    return DatasetSpec(split="all", revision=revision, draw="ranked",
                       exclude_ids_file=str(split_dir / "dev.exclude.ids"),
                       interim_labels=True, near_gold_labels=True)


def load_truth(split_dir: Path, rows_file: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Dev truth rows and their provenance: from ``rows_file`` or prepared from the HF cache."""
    manifest = json.loads((split_dir / "manifest.json").read_text(encoding="utf-8"))
    revision = manifest["dataset"]["revision"]
    if rows_file is not None:
        rows = hc.read_jsonl(rows_file)
        meta: dict[str, Any] = {"source": "rows_file", "path": _rel(rows_file, repo_root()), "sha256": _sha_file(rows_file),
                                "revision": revision}
    else:
        from mailroom_sandbox import corpus

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dataset.jsonl"
            prepared = corpus.prepare_subset(dataset_spec(split_dir, revision), dest)
            rows = hc.read_jsonl(dest)
        meta = {"source": "huggingface_cache", "sha256": prepared["sha256"], **prepared["metadata"]}
    dev = set(_ids(split_dir / "dev.ids"))
    rows = [r for r in rows if str(r.get("id")) in dev]
    return rows, meta


def provenance(root: Path, split_dir: Path, pass_dir: Path, truth_meta: dict[str, Any], bars: Any,
               n_cases: int, per_class: int = hc.PER_CLASS) -> dict[str, Any]:
    from mailroom_sandbox import gold_labels, interim_labels
    from mailroom_sandbox.cli import _VENDOR_PINS

    import llm_dojo_scoring

    head = _git(root, "rev-parse", "HEAD")
    changed = _git(root, "diff", "--name-only", hc.LABELS_COMMIT, "HEAD", "--", "data/labels")
    dojo = next((p for p in _VENDOR_PINS if p[0] == "llm-dojo-scoring"), None)
    pass_manifest = json.loads((pass_dir / "manifest.json").read_text(encoding="utf-8")) \
        if (pass_dir / "manifest.json").is_file() else {}
    return {
        "schema": hc.SCHEMA,
        "documents": n_cases,
        "selection": {"seed": hc.SEED, "per_class": per_class, "classes": list(hc.CLASSES),
                      "roles": list(hc.ROLES), "profiles": list(hc.PROFILES), "routes": hc.ROUTES},
        "labels": {
            "runbook_named_commit": hc.LABELS_COMMIT,
            "note": "the runbook's 'field scorer @ e90ac8b9' names a gold-label commit; the scorer is the Dojo pin",
            "checkout_head": head,
            "label_files_changed_since_named_commit": changed.splitlines() if changed else ([] if changed == "" else None),
            "interim_overlay_sha256": interim_labels.overlay_fingerprint(),
            "near_gold_overlay_sha256": gold_labels.near_gold_snapshot()[1],
        },
        "scorer": {
            "dojo_vendor_pin": dojo[1] if dojo else None,
            "dojo_package_version": getattr(llm_dojo_scoring, "__version__", None),
            "entry_points": ["mailroom_sandbox.eval.agents._score_class",
                             "mailroom_sandbox.eval.agents._score_extract (Dojo suite, CUAD, MAUD)",
                             "mailroom_sandbox.experiment_splits.unit_correct",
                             "mailroom_sandbox.job.gate.doc_status",
                             "mailroom_sandbox.eval.scoring.score_classification (Dojo sorter suite)"],
        },
        "dataset": truth_meta,
        "split": {"dir": _rel(split_dir, root), "dev_ids_sha256": _sha_file(split_dir / "dev.ids"),
                  "assignments_sha256": _sha_file(split_dir / "assignments.jsonl")},
        "sorter_pass": {"dir": _rel(pass_dir, root), "model": pass_manifest.get("model"),
                        "dataset_revision": pass_manifest.get("dataset_revision"),
                        "content_sha256_checked_per_document": True,
                        "files": {p.name: _sha_file(p) for p in sorted(pass_dir.glob("*.jsonl"))
                                  if not p.name.endswith(".targets.jsonl")}},
        "bars": {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(bars).items()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split-dir", type=Path, default=None)
    ap.add_argument("--sorter-pass", type=Path, default=None)
    ap.add_argument("--rows", type=Path, default=None, help="prepared dev rows (JSONL) instead of the HF cache")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--draft", action="store_true", help="pre-fill settled rows as agent-draft hand scores")
    ap.add_argument("--force", action="store_true", help="overwrite a sheet that holds a person's scores")
    ap.add_argument("--per-class", type=int, default=hc.PER_CLASS, help="documents per class (the gate uses 4)")
    args = ap.parse_args(argv)
    root = repo_root()
    split_dir = args.split_dir or root / DEFAULT_SPLIT
    pass_dir = args.sorter_pass or root / DEFAULT_PASS
    out = args.out or root / DEFAULT_OUT

    sheet_path = out / hc.SHEET_FILE
    if sheet_path.is_file() and not args.force:
        scored = hc.human_scored(hc.read_sheet(sheet_path))
        if scored:
            print(f"refusing: {sheet_path} holds {len(scored)} row(s) a person scored; pass --force to replace",
                  file=sys.stderr)
            return 2

    from mailroom_sandbox.experiment_splits import load_unit_table
    from mailroom_sandbox.job.gate import load_bars

    rows, truth_meta = load_truth(split_dir, args.rows)
    table = load_unit_table(split_dir)
    bars = load_bars()
    cases = [hc.perturb(c) for c in hc.select_docs(rows, hc.load_sorter_pass(pass_dir), table,
                                                    min_labelled=bars.min_labelled, per_class=args.per_class)]
    sheet = hc.sheet_rows(cases, table, draft=args.draft, gated=bars.gated)

    out.mkdir(parents=True, exist_ok=True)
    hc.write_sheet(sheet, sheet_path)
    (out / hc.CASES_FILE).write_text("".join(json.dumps(hc.case_record(c), ensure_ascii=False, sort_keys=True) + "\n"
                                             for c in cases), encoding="utf-8")
    prov = provenance(root, split_dir, pass_dir, truth_meta, bars, len(cases), args.per_class)
    (out / hc.PROVENANCE_FILE).write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    filled = sum(1 for r in sheet if r["hand_score"])
    print(f"documents {len(cases)}  sheet rows {len(sheet)}  agent-draft filled {filled}  blank {len(sheet) - filled}")
    for c in cases:
        print(f"  {c.doc_id}  {c.doc_class:<17} {str(c.row.get('expected_subclass')):<28} {c.role:<15} "
              f"{c.profile:<10} sorter={c.pred_class}/{c.pred_subclass}")
    changed = prov["labels"]["label_files_changed_since_named_commit"]
    print(f"labels: runbook names {hc.LABELS_COMMIT[:8]}; {len(changed or [])} label file(s) changed since "
          f"(truth is HEAD {str(prov['labels']['checkout_head'])[:8]} with overlays)")
    print(f"scorer: Dojo vendor pin {str(prov['scorer']['dojo_vendor_pin'])[:12]} "
          f"(package {prov['scorer']['dojo_package_version']})")
    print(f"wrote {sheet_path}, {out / hc.CASES_FILE}, {out / hc.PROVENANCE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
