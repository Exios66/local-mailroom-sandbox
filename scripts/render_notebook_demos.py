#!/usr/bin/env python3
"""Execute the offline tour notebooks and write output-bearing demo copies.

Source notebooks under ``notebooks/0*.ipynb`` stay output-free (CI structure
gate). Demo copies with executed cells land in ``notebooks/demos/``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = sorted((ROOT / "notebooks").glob("0*.ipynb"))
DEMOS = ROOT / "notebooks" / "demos"
BINARY_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
                "image/bmp", "image/tiff", "application/pdf", "application/octet-stream"}
# Parent for the render's TemporaryDirectory: a private, uniquely named mkdtemp folder, so a
# fixed parent carries no predictable-path risk; it is short so paths fit display widths.
SHORT_TEMP_BASE = "/tmp"  # nosec B108 -- parent of a private mkdtemp folder, not a fixed file
# Pandas truncates long cells ("/var/folders/...") before sanitization sees them, so a
# truncated machine path would no longer match its replacement and would leak.
KERNEL_SETUP = (
    "try:\n"
    "    import pandas as _demo_pd\n"
    "    _demo_pd.set_option('display.max_colwidth', None)\n"
    "    del _demo_pd\n"
    "except ImportError:\n"
    "    pass"
)


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
            # NotebookNode is a dict subclass required by nbformat's writer; retain it.
            for key, item in value.items():
                if key not in BINARY_MIMES and not key.startswith(("audio/", "video/")):
                    value[key] = clean(item)
            return value
        return value

    for cell in nb["cells"]:
        if cell.get("outputs"):
            cell["outputs"] = clean(cell["outputs"])


_ELLIPSIS = re.compile(r"\.\.\.|\u2026")
# A machine path starts a token: "/src" inside the portable "/demo/checkout/src/..." is not one.
_PATH_START = r"(?<![\w.~-])"


def find_path_leaks(nb, markers: list[str], truncatable: list[str] = ()) -> list[str]:
    """Return ``cell-id:marker`` for each sanitized output that still holds a machine path.

    A cell can truncate a path itself (for example ``pd.set_option("display.max_colwidth", 80)``),
    so no sanitization rule matches it; this check refuses to publish such a demo. ``markers`` are
    prefixes that must never appear; ``truncatable`` are full paths whose elided form (a prefix of
    at least two components, spaces allowed, followed by ``...``) must not appear either.
    """
    needles = sorted({str(alias) for marker in markers for alias in _path_aliases(marker)}, key=len, reverse=True)
    patterns = [(needle, re.compile(_PATH_START + re.escape(needle))) for needle in needles]
    fulls = sorted({str(alias) for path in truncatable for alias in _path_aliases(path)})
    leaks = []

    def elided(text):
        for match in _ELLIPSIS.finditer(text):
            end = match.start()
            for full in fulls:
                # the longest prefix of ``full`` that the text ends with just before the ellipsis
                k = next((k for k in range(min(len(full), end), 0, -1) if text.startswith(full[:k], end - k)), 0)
                if k and full[:k].count("/") >= 2 and not re.match(r"[\w.~-]", text[end - k - 1: end - k] or " "):
                    return full[:k] + "..."
        return None

    def texts(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from texts(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in BINARY_MIMES and not key.startswith(("audio/", "video/")):
                    yield from texts(item)

    for cell in nb["cells"]:
        for text in texts(cell.get("outputs") or []):
            hit = next((needle for needle, pattern in patterns if pattern.search(text)), None) or elided(text)
            if hit:
                leaks.append(f"{cell.get('id')}:{hit}")
                break
    return leaks


def _short_temp_base() -> str | None:
    """Prefer a writable ``/tmp`` over macOS's long ``$TMPDIR`` so paths fit display widths;
    ``None`` (the platform default) when ``/tmp`` is missing or not writable."""
    base = Path(SHORT_TEMP_BASE)
    usable = os.name == "posix" and base.is_dir() and os.access(base, os.W_OK | os.X_OK)
    return SHORT_TEMP_BASE if usable else None


def leak_markers(tmp_path: Path) -> list[str]:
    """Path prefixes that must not survive sanitization: home, the render temp folders and the
    checkout's parent (a cell may shorten the checkout path before its full prefix can match)."""
    markers = [str(Path.home()), str(tmp_path.parent / "notebook-demos-")]
    parent = ROOT.resolve().parent
    if parent != Path(parent.anchor):
        markers.append(str(parent))
    return markers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEMOS, help="directory for executed demos")
    args = parser.parse_args()

    import nbformat
    from nbclient import NotebookClient

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="notebook-demos-", dir=_short_temp_base()) as tmp:
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
                extra_arguments=[f"--IPKernelApp.exec_lines={json.dumps([KERNEL_SETUP])}"],
            )
            client.km = client.create_kernel_manager()
            kernel_executable = client.km.format_kernel_cmd()[0]
            client.execute()
            sanitize_demo_outputs(nb, {str(ROOT): "/demo/checkout", str(tmp_path): "/demo/runtime",
                                       str(Path.home()): "/demo/home", sys.executable: "/demo/python",
                                       kernel_executable: "/demo/python"})
            leaks = find_path_leaks(nb, leak_markers(tmp_path), [str(ROOT), str(Path.home()), str(tmp_path)])
            if leaks:
                print(f"  ERRORS: unsanitized machine paths in {path.name}: {leaks}", flush=True)
                return 1
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
