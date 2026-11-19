#!/usr/bin/env python3
"""Build the rb1 R13b document-form positive controls (offline, deterministic).

The R13b smoke showed reviewer_decisions 4.0.0 parking intact documents as fragments or
bundles; 4.0.1 narrows those criteria. Narrowing is only safe if the question still parks
the real thing, and the corpus has no labelled fragments or bundles, so this script derives
them from the locked smoke rows: cut and joined copies whose correct ``document_form`` is
known by construction, plus intact copies as negative controls.

    python scripts/rb1_build_form_controls.py \\
        --source data/runtime/runs/rb1-r13b-smoke20-decision-sorter-luna/dataset.jsonl \\
        --out data/runtime/rb1-r13b/form-controls.jsonl

With ``--check-run <run dir>`` it instead scores a finished run on those rows: each control's
``document_form`` answer and park decision against the expected form (exit 1 on any miss).

Each output row keeps the dataset row shape (``id``, ``doc_text``, ``expected_doc_class``,
``expected_subclass``, ``source_revision``) and adds ``expected_document_form``,
``control`` (how it was made) and ``derived_from``. Prints a digest and the file's sha256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# (control id, recipe, source doc ids, expected document_form)
CONTROLS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("CTRL-signature-page", "tail", ("DOC-d8df0ba021e7d19d",), "fragment_or_excerpt"),
    ("CTRL-title-and-toc", "head", ("DOC-52f9a5be69429299",), "fragment_or_excerpt"),
    ("CTRL-cut-mid-sentence", "cut", ("DOC-be1eccde5bae9c82",), "fragment_or_excerpt"),
    ("CTRL-claim-plus-email", "join", ("DOC-bf518ec27ab190de", "DOC-6775dc31dac37ceb"), "multiple_documents"),
    ("CTRL-charter-plus-medicare", "join", ("DOC-59d072355f2c3b14", "DOC-d460ba48aced73ea"), "multiple_documents"),
    ("CTRL-intact-claim-file", "whole", ("DOC-68d0e23b4cfcaeb8",), "complete_instrument"),
    ("CTRL-intact-merger-with-amendment", "whole", ("DOC-d8df0ba021e7d19d",), "complete_instrument"),
)

HEAD_CHARS = 4_000      # title page plus table of contents of a long merger agreement
TAIL_CHARS = 1_800      # the closing signature page only
CUT_FRACTION = 0.4      # keep the first 40% and stop inside a sentence


def _cut_mid_sentence(text: str) -> str:
    at = int(len(text) * CUT_FRACTION)
    space = text.find(" ", at)
    end = space if space > 0 else at
    # Step back past a sentence end so the excerpt cannot finish on a full stop.
    while end > 0 and text[end - 1] in ".;:!?":
        end -= 1
    return text[:end]


def build(rows: dict[str, dict]) -> list[dict]:
    out = []
    for cid, recipe, sources, form in CONTROLS:
        missing = [s for s in sources if s not in rows]
        if missing:
            raise SystemExit(f"{cid}: source rows missing from --source: {missing}")
        first = rows[sources[0]]
        texts = [rows[s]["doc_text"] for s in sources]
        if recipe == "tail":
            text = texts[0][-TAIL_CHARS:]
        elif recipe == "head":
            text = texts[0][:HEAD_CHARS]
        elif recipe == "cut":
            text = _cut_mid_sentence(texts[0])
        elif recipe == "join":
            text = "\n\n".join(texts)
        else:
            text = texts[0]
        out.append({
            "id": cid,
            "doc_text": text,
            "expected_doc_class": first.get("expected_doc_class"),
            "expected_subclass": first.get("expected_subclass"),
            "source_revision": first.get("source_revision"),
            "expected_document_form": form,
            "control": recipe,
            "derived_from": list(sources),
        })
    return out


def check_run(run_dir: Path, controls: Path) -> int:
    """Score a finished run on the controls: the form answer and whether the document was parked.

    Expected forms come from the controls file: run preparation keeps only the dataset row
    fields, so the locked ``dataset.jsonl`` no longer carries ``expected_document_form``.
    """
    expected = {}
    for line in controls.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            expected[row["id"]] = row.get("expected_document_form")
    misses = 0
    for line in (run_dir / "items.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        want = expected.get(item.get("item_id"))
        if want is None:
            continue
        pred = item.get("pred") or {}
        got, parked = pred.get("document_form"), bool(pred.get("abstained") or pred.get("route_to_human"))
        ok = got == want and parked == (want != "complete_instrument")
        misses += not ok
        print(f"{'ok  ' if ok else 'MISS'} {item['item_id']:36} want {want:20} got {str(got):20} parked={parked}")
    print(f"{len(expected) - misses}/{len(expected)} controls correct")
    return 1 if misses else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, help="a locked run's dataset.jsonl")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--check-run", type=Path, help="score a finished controls run directory instead")
    ap.add_argument("--controls", type=Path, default=Path("data/runtime/rb1-r13b/form-controls.jsonl"),
                    help="controls file holding the expected forms (with --check-run)")
    args = ap.parse_args(argv)
    if args.check_run:
        return check_run(args.check_run, args.controls)
    if not (args.source and args.out):
        ap.error("--source and --out are required to build")
    rows = {}
    for line in args.source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["id"]] = row
    controls = build(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, sort_keys=True) + "\n" for r in controls)
    args.out.write_text(payload, encoding="utf-8")
    for r in controls:
        print(f"{r['id']:36} {r['expected_document_form']:20} {len(r['doc_text']):>7} chars  from {','.join(r['derived_from'])}")
    print(f"{len(controls)} controls -> {args.out} sha256 {hashlib.sha256(payload.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
