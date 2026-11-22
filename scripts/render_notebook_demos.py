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
BINARY_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
                "image/bmp", "image/tiff", "application/pdf", "application/octet-stream"}


def _path_aliases(source: str) -> set[Path]:
    paths = {Path(source), Path(source).resolve()}
    if sys.platform == "darwin":
        for name in ("tmp", "var"):
            short = Path("/") / name
            canonical = Path("/") / "private" / name
            for path in tuple(paths):
                for prefix, alternate in ((short, canonical), (canonical, short)):
                    if path.is_relative_to(prefix):
                        paths.add(alternate / path.relative_to(prefix))
    return paths


def sanitize_demo_outputs(nb, replacements: dict[str, str]) -> None:
    """Replace machine paths in executed output, leaving source and binary image data intact."""
    aliases = {str(path): portable for source, portable in replacements.items() for path in _path_aliases(source)}
    ordered = sorted(aliases.items(), key=lambda item: -len(item[0]))

    def clean(value):
        if isinstance(value, str):
            for source, portable in ordered:
                value = value.replace(source, portable)
            return value
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: item if key in BINARY_MIMES or key.startswith(("audio/", "video/")) else clean(item)
                    for key, item in value.items()}
        return value

    for cell in nb["cells"]:
        if cell.get("outputs"):
            cell["outputs"] = clean(cell["outputs"])


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
            client.km = client.create_kernel_manager()
            kernel_executable = client.km.format_kernel_cmd()[0]
            client.execute()
            sanitize_demo_outputs(nb, {str(ROOT): "/demo/checkout", str(tmp_path): "/demo/runtime",
                                       str(Path.home()): "/demo/home", sys.executable: "/demo/python",
                                       kernel_executable: "/demo/python"})
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
