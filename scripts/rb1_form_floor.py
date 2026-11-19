#!/usr/bin/env python3
"""Calibration-split document-form controls and the park-floor fit (rb1 R13b, offline).

Question set 4.0.1 parks a document when its ``document_form`` answer is a human form. On the
dev-look1 smoke it parked 4 intact documents, each with 0.55-0.79 of the form probability on
human forms, while every intact document it passed sat at 0.47 or below. A probability floor
might separate them, but those numbers are in-sample, so the floor is fitted here on the
calibration split instead, from two runs:

1. ``intact`` run: real calibration documents drawn per class (config
   ``rb1-r13b-formcal-intact-decision-luna-v4.0.1``). Each is taken as a complete instrument.
2. ``defects`` run: copies of those same documents made defective by construction
   (``build``): a closing signature page alone, an opening title page alone, the text cut
   mid-sentence (fragments), and two documents of different classes joined (bundles).
   A cut lands in an email's newest message, never its quoted history, and a closing window
   that opens an instrument of its own (an addendum, exhibit, schedule) is skipped: both
   would leave a complete document labelled as a defect (draw 1 had four).

``exclude`` writes the exclude-ids file for a fresh draw (a split complement plus the
documents already used), so a question-set change is judged on rows it was not written from.

    python scripts/rb1_form_floor.py build \\
        --source data/runtime/runs/rb1-r13b-formcal-intact-decision-luna-v4.0.1/dataset.jsonl \\
        --out data/runtime/rb1-r13b/formcal-defects.jsonl
    python scripts/rb1_form_floor.py fit \\
        --intact-run data/runtime/runs/rb1-r13b-formcal-intact-decision-luna-v4.0.1 \\
        --defects-run data/runtime/runs/rb1-r13b-formcal-defects-decision-luna-v4.0.1 \\
        --defects data/runtime/rb1-r13b/formcal-defects.jsonl

``fit`` reads ``document_form_human_mass`` (recorded by decide since PR #356) and prints, for
each candidate floor, how many defects would pass to extraction (misarchive risk) and how many
intact documents would be parked (excess review). It recommends the highest floor that lets
no defect through, and lists the defects and parked intact documents nearest the cut.

Caveat: an "intact" calibration document is assumed complete; the corpus has no form labels.
An intact document parked with high human mass may be a real defect, so ``fit`` lists them
for a look before any floor ships.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path

HEAD_CHARS = 4_000      # opening title page / first page only
TAIL_CHARS = 1_800      # closing signature page only
CUT_FRACTION = 0.4      # keep the first 40% and stop inside a sentence
MIN_TAIL = 3 * TAIL_CHARS
MIN_HEAD = 3 * HEAD_CHARS
MIN_CUT = 800           # shorter texts get no fragment copy (a cut would be a few words)
JOINS_PER_CLASS = 4
SEED = 20261119
FLOORS = tuple(round(0.40 + 0.05 * i, 2) for i in range(12))  # 0.40 .. 0.95
# Where quoted or forwarded mail history begins. A cut inside that history leaves the newest
# message whole, which is a complete email, not a fragment (draw 1: three such "defects").
HISTORY = re.compile(r"-{2,}\s*Original Message\s*-{2,}|-{3,}\s*Forwarded by|>>>"
                     r"|\bFrom:\s[^\n]{0,80}?(?:\bSent:|\d{1,2}/\d{1,2}/\d{2,4})|\bwrote:\s|(?:^|\n)\s*>", re.I)
HISTORY_MIN_WORDS = 3    # fewer words before a match: the message's own header, not history
# A closing window that opens a new instrument of its own (draw 1: the last 1,800 characters
# of an endorsement agreement were a whole signed addendum) is complete, not a fragment.
OPENS_INSTRUMENT = re.compile(r"\b(?:ADDENDUM|AMENDMENT|EXHIBIT|SCHEDULE|ANNEX|APPENDIX)\b")
SIGNATURE_CAPTION = re.compile(r"\[?SIGNATURE PAGES? TO [^\]\n]*\]?", re.I)


def cut_mid_sentence(text: str) -> str:
    at = int(len(text) * CUT_FRACTION)
    space = text.find(" ", at)
    end = space if space > 0 else at
    while end > 0 and text[end - 1] in ".;:!?":  # never finish on a sentence end
        end -= 1
    return text[:end]


def newest_message(text: str) -> str:
    """The text before any quoted or forwarded history (all of it when there is none)."""
    for m in HISTORY.finditer(text):
        # when unsure, call it history: a shorter newest message only means fewer fragments
        if len(text[:m.start()].split()) >= HISTORY_MIN_WORDS:
            return text[:m.start()]
    return text


def fragment(row: dict, recipe: str) -> str | None:
    text = row.get("doc_text") or ""
    if recipe == "tail" and len(text) >= MIN_TAIL:
        tail = text[-TAIL_CHARS:]
        return None if OPENS_INSTRUMENT.search(SIGNATURE_CAPTION.sub(" ", tail)) else tail
    if recipe == "head" and len(text) >= MIN_HEAD:
        return text[:HEAD_CHARS]
    if recipe == "cut":
        newest = newest_message(text)  # cut inside the newest message, never inside its history
        return cut_mid_sentence(newest) if len(newest) >= MIN_CUT else None
    return None


def _row(cid: str, text: str, first: dict, form: str, recipe: str, sources: list[str]) -> dict:
    return {"id": cid, "doc_text": text,
            "expected_doc_class": first.get("expected_doc_class"),
            "expected_subclass": first.get("expected_subclass"),
            "source_revision": first.get("source_revision"),
            "expected_document_form": form, "control": recipe, "derived_from": sources,
            # a bundle of different documents has no one true class; its labels are placeholders
            "class_label_scored": recipe != "join"}


def build(rows: list[dict], seed: int = SEED) -> list[dict]:
    """One fragment per source document (the first eligible recipe in a rotating order) plus
    ``JOINS_PER_CLASS`` bundles per class, each joined to a document of another class."""
    rows = sorted(rows, key=lambda r: r["id"])
    rng = random.Random(seed)
    order = ("tail", "head", "cut")
    out: list[dict] = []
    for row in rows:
        # rotate over the fragments made so far, so short documents skipped cannot bias the mix
        for k in range(len(order)):
            recipe = order[(len(out) + k) % len(order)]
            text = fragment(row, recipe)
            if text is not None:
                out.append(_row(f"CAL-{recipe}-{row['id'][4:]}", text, row, "fragment_or_excerpt",
                                recipe, [row["id"]]))
                break
    by_class: dict[str, list[dict]] = {}
    for row in rows:
        by_class.setdefault(str(row.get("expected_doc_class")), []).append(row)
    for cls in sorted(by_class):
        others = [r for r in rows if str(r.get("expected_doc_class")) != cls]
        if not others:
            continue
        for a in rng.sample(by_class[cls], min(JOINS_PER_CLASS, len(by_class[cls]))):
            b = rng.choice(others)
            out.append(_row(f"CAL-join-{a['id'][4:]}-{b['id'][4:]}",
                            f"{a['doc_text']}\n\n{b['doc_text']}", a, "multiple_documents", "join",
                            [a["id"], b["id"]]))
    return out


def exclude(base: Path, used: list[Path]) -> str:
    """An exclude-ids file: ``base`` (a split complement) plus every id in the ``used`` datasets,
    so a fresh calibration draw cannot reuse documents a question-set change was written from."""
    from mailroom_sandbox.corpus import parse_id_list

    ids = set(parse_id_list(base.read_text(encoding="utf-8")))
    seen = sorted({r["id"] for p in used for r in _jsonl(p)})
    head = [f"# {base.parent.name}/{base.name} plus the {len(seen)} documents of:"] + [f"#   {p.parent.name}/{p.name}" for p in used]
    head.append("# Generated by scripts/rb1_form_floor.py exclude; do not hand-edit.")
    return "\n".join(head + sorted(ids | set(seen))) + "\n"


def _jsonl(path: Path) -> list[dict]:
    # split on physical newlines only: str.splitlines() also breaks on U+2028/U+2029 inside text
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").split("\n") if line.strip()]


def _identity(run_dir: Path) -> dict:
    """What a fit must hold constant across the two runs: models and the exact question set."""
    lock = json.loads((run_dir / "spec.lock.json").read_text(encoding="utf-8"))
    reviewer = lock.get("reviewer") or {}
    qset = json.dumps(reviewer.get("question_set"), sort_keys=True).encode()
    return {"engine_model": (lock.get("engine") or {}).get("model"), "reviewer_model": reviewer.get("model"),
            "question_set_sha256": hashlib.sha256(qset).hexdigest()}


def _check_provenance(intact_run: Path, defects_run: Path, defects: Path) -> None:
    a, b = _identity(intact_run), _identity(defects_run)
    if a != b:
        raise SystemExit(f"cannot fit: the runs differ in model or question set: {a} vs {b}")
    lock = json.loads((defects_run / "spec.lock.json").read_text(encoding="utf-8"))
    locked = ((lock.get("dataset") or {}).get("metadata") or {}).get("sha256")
    actual = hashlib.sha256(defects.read_bytes()).hexdigest()
    if locked != actual:
        raise SystemExit(f"cannot fit: {defects} (sha256 {actual[:12]}) is not the file the defects run "
                         f"locked (sha256 {str(locked)[:12]})")


def _masses(run_dir: Path) -> dict[str, tuple[float | None, bool]]:
    """``{item_id: (human mass, parked)}``; mass is None when the run did not record it.

    The run must cover its locked ``dataset.jsonl`` exactly once per row: a partial or
    re-run directory would bias the negatives (or positives) the floor is fitted on.
    """
    out: dict[str, tuple[float | None, bool]] = {}
    locked = [r["id"] for r in _jsonl(run_dir / "dataset.jsonl")]
    items = _jsonl(run_dir / "items.jsonl")
    ids = [i.get("item_id") for i in items]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    missing = sorted(set(locked) - set(ids))
    extra = sorted(set(ids) - set(locked), key=str)
    if dupes or missing or extra:
        raise SystemExit(f"cannot fit: {run_dir.name} has {len(missing)} locked rows without a result "
                         f"{missing[:5]}, {len(dupes)} duplicated results {dupes[:5]} and {len(extra)} "
                         f"results outside its locked dataset {extra[:5]}")
    for item in items:
        pred = item.get("pred") or {}
        mass = pred.get("document_form_human_mass")
        out[item["item_id"]] = (float(mass) if isinstance(mass, (int, float)) else None,
                                bool(pred.get("abstained") or pred.get("route_to_human")))
    return out


def read_ids(path: Path | None) -> set[str]:
    """One id per line, ``#`` comments ignored (the format of the split ``.ids`` files)."""
    if path is None:
        return set()
    return {ln.split("#", 1)[0].strip() for ln in path.read_text(encoding="utf-8").splitlines()} - {""}


def auroc(pos: list[float], neg: list[float]) -> float:
    """P(a defect's human mass > an intact document's), ties counted half: how well mass ranks."""
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def _expected(defects: Path, misbuilt: set[str]) -> dict[str, str]:
    """Defect rows minus copies a reading found to be complete documents after all."""
    rows = {r["id"]: r["expected_document_form"] for r in _jsonl(defects)}
    unknown = sorted(misbuilt - set(rows))
    if unknown:
        raise SystemExit(f"cannot fit: {len(unknown)} mis-built ids are not in {defects.name} {unknown[:5]}")
    return {i: f for i, f in rows.items() if i not in misbuilt}


def fit(intact_run: Path, defects_run: Path, defects: Path, misbuilt: set[str] | None = None) -> dict:
    _check_provenance(intact_run, defects_run, defects)
    intact = _masses(intact_run)
    expected = _expected(defects, misbuilt or set())
    got = _masses(defects_run)
    missing = sorted(set(expected) - set(got))
    rows = [("intact", i, m) for i, (m, _) in intact.items()]
    rows += [(expected[i], i, got[i][0]) for i in expected if i in got]
    unrecorded = sorted(i for _, i, m in rows if m is None)
    if missing or unrecorded:
        raise SystemExit(f"cannot fit: {len(missing)} defect rows have no result "
                         f"{missing[:5]}, {len(unrecorded)} results have no human mass {unrecorded[:5]}")
    pos = sorted(m for kind, _, m in rows if kind != "intact")
    neg = sorted(m for kind, _, m in rows if kind == "intact")
    if not pos or not neg:  # an empty side makes every floor look free
        raise SystemExit(f"cannot fit: {len(pos)} defects and {len(neg)} intact results; both must be non-empty")
    table = []
    for floor in FLOORS:
        table.append({"floor": floor,
                      "defects_passed": sum(m < floor for m in pos),
                      "intact_parked": sum(m >= floor for m in neg)})
    safe = [t for t in table if t["defects_passed"] == 0]
    best = max(safe, key=lambda t: t["floor"]) if safe else None
    return {"n_defects": len(pos), "n_intact": len(neg), "n_misbuilt": len(misbuilt or ()),
            "auroc": auroc(pos, neg), "table": table, "recommended": best,
            "lowest_defect": [(i, k, m) for k, i, m in sorted((r for r in rows if r[0] != "intact"),
                                                              key=lambda r: r[2])[:8]],
            "highest_intact": [(i, m) for _, i, m in sorted((r for r in rows if r[0] == "intact"),
                                                            key=lambda r: -r[2])[:8]],
            "current_parks": {"intact_parked": sum(p for _, (_, p) in intact.items()),
                              "defects_passed": sum(not got[i][1] for i in expected if i in got)}}


def sign_test_p(wins: int, losses: int) -> float:
    """One-sided exact sign test: P(at least ``wins`` of ``wins + losses`` discordant pairs go one
    way if each pair were a coin flip). Ties (concordant pairs) carry no information."""
    n = wins + losses
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / 2 ** n if n else 1.0


# The draw-2 decision rule, fixed before any draw-2 run (docs/rb1-r13b-smoke-review.md). A side
# "improves" when its discordant pairs favour the candidate; leaks (a defect reaching
# extraction) are the costlier error, so they get the stricter conditions.
MIN_NET = 3          # at least this many more documents fixed than broken on the improving side
ALPHA = 0.05         # one-sided exact sign test on that side's discordant pairs
INTACT_SLACK = 1     # defects improve: the intact side may lose at most this many, net


def _side(base: dict[str, bool], cand: dict[str, bool], bad_when: bool) -> dict:
    """Paired outcome on one side: ``bad_when`` is the park state that is an error there."""
    if set(base) != set(cand):
        raise SystemExit(f"cannot compare: the two runs cover different rows "
                         f"({len(set(base) ^ set(cand))} differ)")
    fixed = sorted(i for i in base if base[i] == bad_when and cand[i] != bad_when)
    broken = sorted(i for i in base if base[i] != bad_when and cand[i] == bad_when)
    return {"n": len(base), "errors_base": sum(v == bad_when for v in base.values()),
            "errors_cand": sum(v == bad_when for v in cand.values()), "fixed": fixed, "broken": broken,
            "net": len(fixed) - len(broken), "p_better": sign_test_p(len(fixed), len(broken)),
            "p_worse": sign_test_p(len(broken), len(fixed))}


def decide(defects: dict, intact: dict) -> str:
    if defects["p_worse"] < ALPHA or intact["p_worse"] < ALPHA:
        return "reject"
    if defects["net"] >= MIN_NET and defects["p_better"] < ALPHA and intact["net"] >= -INTACT_SLACK:
        return "adopt"
    if intact["net"] >= MIN_NET and intact["p_better"] < ALPHA and defects["net"] >= 0:
        return "adopt"
    return "inconclusive"


def compare(base: tuple[Path, Path], cand: tuple[Path, Path], defects: Path,
            misbuilt: set[str] | None = None) -> dict:
    """Paired comparison of two question sets on the same intact rows and the same defect file."""
    for intact_run, defects_run in (base, cand):
        _check_provenance(intact_run, defects_run, defects)
    locked = [hashlib.sha256((run / "dataset.jsonl").read_bytes()).hexdigest() for run in (base[0], cand[0])]
    if locked[0] != locked[1]:
        raise SystemExit("cannot compare: the intact runs locked different rows")
    a, b = _identity(base[0]), _identity(cand[0])
    if a["question_set_sha256"] == b["question_set_sha256"] or a["reviewer_model"] != b["reviewer_model"]:
        raise SystemExit(f"cannot compare: need the same model and two different question sets: {a} vs {b}")
    expected = _expected(defects, misbuilt or set())
    parks = [{i: p for i, (_, p) in _masses(run).items()} for run in (base[0], cand[0], base[1], cand[1])]
    d_base, d_cand = ({i: p[i] for i in expected} for p in parks[2:])
    intact = _side(parks[0], parks[1], bad_when=True)      # an intact document parked
    defect = _side(d_base, d_cand, bad_when=False)        # a defect passed to extraction
    return {"intact": intact, "defects": defect, "decision": decide(defect, intact),
            "n_misbuilt": len(misbuilt or ())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the defect controls from a locked dataset.jsonl")
    b.add_argument("--source", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--seed", type=int, default=SEED)
    e = sub.add_parser("exclude", help="write an exclude-ids file: a split complement plus used documents")
    e.add_argument("--base", type=Path, required=True)
    e.add_argument("--used", type=Path, nargs="+", required=True)
    e.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("fit", help="tabulate candidate floors from the two finished runs")
    f.add_argument("--intact-run", type=Path, required=True)
    f.add_argument("--defects-run", type=Path, required=True)
    f.add_argument("--defects", type=Path, required=True)
    f.add_argument("--misbuilt", type=Path, help="ids of defect copies a reading found complete")
    c = sub.add_parser("compare", help="paired decision between two question sets (draw-2 rule)")
    c.add_argument("--base-intact", type=Path, required=True)
    c.add_argument("--base-defects", type=Path, required=True)
    c.add_argument("--cand-intact", type=Path, required=True)
    c.add_argument("--cand-defects", type=Path, required=True)
    c.add_argument("--defects", type=Path, required=True)
    c.add_argument("--misbuilt", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        rows = build(_jsonl(args.source), seed=args.seed)
        payload = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["control"]] = counts.get(r["control"], 0) + 1
        print(f"{len(rows)} defect controls {dict(sorted(counts.items()))} -> {args.out} "
              f"sha256 {hashlib.sha256(payload.encode()).hexdigest()}")
        return 0
    if args.cmd == "exclude":
        args.out.write_text(exclude(args.base, args.used), encoding="utf-8")
        print(f"wrote {args.out}")
        return 0
    if args.cmd == "compare":
        res = compare((args.base_intact, args.base_defects), (args.cand_intact, args.cand_defects),
                      args.defects, read_ids(args.misbuilt))
        for side, what in (("defects", "defects passed"), ("intact", "intact parked")):
            r = res[side]
            print(f"{side} (n={r['n']}): {what} {r['errors_base']} -> {r['errors_cand']}; "
                  f"fixed {len(r['fixed'])}, broken {len(r['broken'])}, net {r['net']:+d}, "
                  f"p(better) {r['p_better']:.3f}, p(worse) {r['p_worse']:.3f}")
            print(f"  fixed: {', '.join(r['fixed']) or '-'}\n  broken: {', '.join(r['broken']) or '-'}")
        print(f"{res['n_misbuilt']} reviewed mis-built defects excluded; decision: {res['decision'].upper()} "
              f"(rule: net >= {MIN_NET} and one-sided sign test p < {ALPHA} on the improving side; "
              f"defects improving may cost at most {INTACT_SLACK} intact park, intact improving may cost "
              f"no leak; reject on a significant loss on either side)")
        return 0
    res = fit(args.intact_run, args.defects_run, args.defects, read_ids(args.misbuilt))
    print(f"{res['n_defects']} defects ({res['n_misbuilt']} reviewed mis-built excluded), "
          f"{res['n_intact']} intact; AUROC of human mass {res['auroc']:.3f}; question set as run: "
          f"{res['current_parks']['intact_parked']} intact parked, "
          f"{res['current_parks']['defects_passed']} defects passed")
    print(f"{'floor':>6} {'defects passed':>15} {'intact parked':>14}")
    for t in res["table"]:
        print(f"{t['floor']:>6.2f} {t['defects_passed']:>15} {t['intact_parked']:>14}")
    rec = res["recommended"]
    print(f"recommended floor: {rec['floor']:.2f} ({rec['intact_parked']} intact parked)" if rec
          else "no zero-leak floor in range: every floor lets a defect through (see AUROC for how well mass ranks)")
    print("lowest-mass defects:", ", ".join(f"{i} {k} {m:.2f}" for i, k, m in res["lowest_defect"]))
    print("highest-mass intact:", ", ".join(f"{i} {m:.2f}" for i, m in res["highest_intact"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
