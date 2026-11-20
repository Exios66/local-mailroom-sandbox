#!/usr/bin/env python3
"""Execute the offline tour notebooks and write output-bearing demo copies.

Source notebooks under ``notebooks/0*.ipynb`` stay output-free (CI structure
gate). Demo copies with executed cells land in ``notebooks/demos/``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = sorted((ROOT / "notebooks").glob("0*.ipynb"))
DEMOS = ROOT / "notebooks" / "demos"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEMOS, help="directory for executed demos")
    args = parser.parse_args()

    import nbformat
    from nbclient import NotebookClient

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="notebook-demos-") as tmp:
        tmp_path = Path(tmp)
        os.environ["MAILROOM_BASE_DIR"] = str(tmp_path / "data")
        os.environ["SANDBOX_NOTEBOOK_LOG"] = str(tmp_path / "log" / "experiment_log.jsonl")
        os.environ["SANDBOX_NOTEBOOK_LOG_VIEW"] = str(tmp_path / "log" / "experiment_log.jsonl")
        os.environ["MPLBACKEND"] = "Agg"
        os.environ["SANDBOX_NOTEBOOK_OBSERVABILITY"] = "none"
        os.environ["SANDBOX_SKIP_DOTENV"] = "1"
        os.environ.pop("SANDBOX_PROFILE", None)
        os.environ.pop("SANDBOX_NOTEBOOK_PROBE", None)

        summary = []
        for path in NOTEBOOKS:
            nb = nbformat.read(path, as_version=4)
            client = NotebookClient(
                nb,
                timeout=300,
                kernel_name="python3",
                resources={"metadata": {"path": str(path.parent)}},
            )
            client.execute()
            dest = out / path.name
            nbformat.write(nb, dest)
            code = [c for c in nb.cells if c.cell_type == "code"]
            empty = [c.get("id") for c in code if not c.get("outputs")]
            errors = []
            for c in code:
                for o in c.get("outputs") or []:
                    if o.get("output_type") == "error":
                        errors.append(f"{c.get('id')}:{o.get('ename')}")
            summary.append(
                {
                    "notebook": path.name,
                    "code_cells": len(code),
                    "empty_output_ids": empty,
                    "errors": errors,
                }
            )
            try:
                shown = dest.resolve().relative_to(ROOT.resolve())
            except ValueError:
                shown = dest
            print(f"wrote {shown} ({len(code)} code cells)", flush=True)
            if empty:
                print(f"  WARN empty outputs: {empty}", flush=True)
            if errors:
                print(f"  ERRORS: {errors}", flush=True)
                return 1

        (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
