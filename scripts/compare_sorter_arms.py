#!/usr/bin/env python3
"""Compare the LLM sorter (arm A) with Decisions-API models acting as the sorter (arm B) on the
same documents: class accuracy and macro-F1, subclass and subclass-unit accuracy, calibration,
latency and cost, with paired tests and a Holm-adjusted H5 family (evaluation runbook, SAND-108).
Offline: it reads finished run directories only and makes no model call.

    python scripts/compare_sorter_arms.py --a rb1-r03-sorter-v0-dev \\
        --b rb1-r13b-decision-sorter-luna-dev-look1 --set dev-look1 --volume-docs-per-month 100000 \\
        --experiment-key rb1-r13b --write
    python scripts/compare_sorter_arms.py --a A --b B1 --b B2 --set dev-look1 --json   # + frontier

The first run is the reference (arm A); each ``--b`` is compared with it. Held-out documents are
refused unless ``--confirmatory`` (R70b, sealed run ids ``rb1-r70*``..``rb1-r72*``, a
held-out ``--set``). ``--write`` stores the outputs under the campaign tree, every file named
from the experiment key:

    reports/campaigns/rb1/<key>-sorter-vs-decision/analysis/<key>-sorter-arms.comparison.json
    reports/campaigns/rb1/<key>-sorter-vs-decision/analysis/<key>-sorter-arms.digest.txt
    reports/campaigns/rb1/<key>-sorter-vs-decision/figures/<key>-sorter-arms.frontier.csv
    reports/campaigns/rb1/<key>-sorter-vs-decision/figures/<key>-sorter-arms.<figure>.svg

The figures (``comparison_figures``: total run time, latency, quality differences against the
margins, routing, cost against accuracy) are written with ``--write`` or to ``--figures DIR``.

Exit 0 with a report, 2 when the runs cannot be compared.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

from mailroom_sandbox import sorter_arms
from mailroom_sandbox.paths import repo_root

CAMPAIGN = "rb1"
SLUG = "sorter-vs-decision"
_KEY = re.compile(r"^rb1-[a-z0-9]+$")


def output_dir(key: str, root: Path | None = None) -> Path:
    if not _KEY.match(key):
        raise ValueError(f"experiment key {key!r} must look like rb1-<runbook row>, e.g. rb1-r13b")
    return Path(root or repo_root()) / "reports" / "campaigns" / CAMPAIGN / f"{key}-{SLUG}"


def frontier_csv(report: dict) -> str:
    """One row per arm (cost per 1k docs against class macro-F1 and unit accuracy): the frontier figure's data."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["run_id", "model", "class_macro_f1", "unit_accuracy", "per_1k_docs_usd", "dominated_by"])
    rows = report.get("frontier") or sorter_arms.frontier(report["arms"])
    for r in rows:
        writer.writerow([r["run_id"], r["model"], r["class_macro_f1"], r["unit_accuracy"], r["per_1k_docs_usd"],
                         r["dominated_by"] or ""])
    return buf.getvalue()


def figures(report: dict, refs: list[str], *, set_name: str | None, split_dir: Path | None,
            runs_root: Path | None, confirmatory: bool, allow_mock: bool) -> dict[str, str]:
    """``{name: svg}`` for the report, with per-document latencies and prompt sizes of the compared documents."""
    from mailroom_sandbox import comparison_figures

    arms = [sorter_arms.load_arm(r, runs_root=runs_root) for r in refs]
    ids = sorter_arms.pair(arms, set_name=set_name, split_dir=split_dir or sorter_arms._default_split_dir(),
                           confirmatory=confirmatory, allow_mock=allow_mock)
    latencies = {a.run_id: [float(a.items[i]["latency_ms"]) / 1000.0 for i in ids
                            if isinstance((a.items.get(i) or {}).get("latency_ms"), (int, float))] for a in arms}
    prompt_tokens = {a.run_id: [float(a.items[i]["prompt_tokens"]) for i in ids
                                if isinstance((a.items.get(i) or {}).get("prompt_tokens"), (int, float))] for a in arms}
    return comparison_figures.build(report, latencies, prompt_tokens)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--a", required=True, help="arm A run id or run directory (the LLM sorter, reference)")
    parser.add_argument("--b", required=True, action="append", help="arm B run id or directory; repeat for more arms")
    parser.add_argument("--set", dest="set_name", choices=sorter_arms.SPLIT_SETS,
                        help="restrict both runs to this split set (each must cover all of it)")
    parser.add_argument("--split-dir", type=Path, help="split directory (default: the split the runs drew from)")
    parser.add_argument("--runs-root", type=Path, help="where run ids resolve (default data/runtime/runs)")
    parser.add_argument("--confirmatory", action="store_true",
                        help="the sealed held-out call (R70b): allows held-out documents, once")
    parser.add_argument("--allow-mock", action="store_true", help="accept mock runs (output is labelled simulated)")
    parser.add_argument("--volume-docs-per-month", type=int, help="project monthly cost at this volume")
    parser.add_argument("--margin-macro-f1", type=float, default=sorter_arms.MARGIN_MACRO_F1)
    parser.add_argument("--margin-unit", type=float, default=sorter_arms.MARGIN_UNIT)
    parser.add_argument("--n-boot", type=int, default=sorter_arms.N_BOOT)
    parser.add_argument("--n-perm", type=int, default=sorter_arms.N_PERM)
    parser.add_argument("--seed", type=int, default=sorter_arms.SEED)
    parser.add_argument("--json", action="store_true", help="print the full JSON report instead of the digest")
    parser.add_argument("--out", type=Path, help="also write the JSON report here")
    parser.add_argument("--experiment-key", default="rb1-r13b",
                        help="campaign experiment key the outputs are named from (rb1-r13b dev screen, rb1-r70b held-out)")
    parser.add_argument("--write", action="store_true", help="write the outputs under reports/campaigns/rb1/<key>-sorter-vs-decision/")
    parser.add_argument("--figures", type=Path, metavar="DIR", help="write the comparison figures (SVG) here")
    parser.add_argument("--reports-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.write and args.allow_mock:
        print("compare_sorter_arms: --write stores evidence; mock runs are not evidence", file=sys.stderr)
        return 2
    try:
        report = sorter_arms.compare(
            [args.a, *args.b], set_name=args.set_name, split_dir=args.split_dir, runs_root=args.runs_root,
            confirmatory=args.confirmatory, allow_mock=args.allow_mock, volume=args.volume_docs_per_month,
            margin_macro_f1=args.margin_macro_f1, margin_unit=args.margin_unit, n_boot=args.n_boot,
            n_perm=args.n_perm, seed=args.seed)
        target = output_dir(args.experiment_key, args.reports_root) if args.write else None
    except (sorter_arms.ArmError, ValueError) as exc:
        print(f"compare_sorter_arms: {exc}", file=sys.stderr)
        return 2
    report["experiment_key"] = args.experiment_key
    if args.allow_mock:
        report["simulated"] = True
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    digest = sorter_arms.render(report) + ("\n[SIMULATED: mock runs]" if args.allow_mock else "")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    figs = {}
    if target is not None or args.figures:
        figs = figures(report, [args.a, *args.b], set_name=args.set_name, split_dir=args.split_dir,
                       runs_root=args.runs_root, confirmatory=args.confirmatory, allow_mock=args.allow_mock)
    if args.figures:
        args.figures.mkdir(parents=True, exist_ok=True)
        for name, svg in figs.items():
            (args.figures / f"{args.experiment_key}-sorter-arms.{name}.svg").write_text(svg, encoding="utf-8")
    if target is not None:
        key = args.experiment_key
        (target / "analysis").mkdir(parents=True, exist_ok=True)
        (target / "figures").mkdir(parents=True, exist_ok=True)
        (target / "analysis" / f"{key}-sorter-arms.comparison.json").write_text(text + "\n", encoding="utf-8")
        (target / "analysis" / f"{key}-sorter-arms.digest.txt").write_text(digest + "\n", encoding="utf-8")
        (target / "figures" / f"{key}-sorter-arms.frontier.csv").write_text(frontier_csv(report), encoding="utf-8")
        for name, svg in figs.items():
            (target / "figures" / f"{key}-sorter-arms.{name}.svg").write_text(svg, encoding="utf-8")
        print(f"wrote {target}", file=sys.stderr)
    print(text if args.json else digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
