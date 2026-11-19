"""Production parity: what the study's base spec shares with a production slice and where it differs.

The study's results are comparable with the production gate only while the run settings are the
production ones. This module compares the base spec with ``config/runs/production/slice-0100.yaml``
leaf by leaf and names the vendored pipeline and Dojo commits, so a study report can state both.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from mailroom_sandbox.paths import repo_root, vendor_dir

PRODUCTION_SPEC = "config/runs/production/slice-0100.yaml"
_COMMIT = re.compile(r"Exact source commit:\s*`([0-9a-f]{40})`")


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Leaf values of nested mappings by dotted path (lists and scalars are leaves)."""
    if isinstance(value, Mapping) and value:
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: value}


def load_production(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else repo_root() / PRODUCTION_SPEC
    return yaml.safe_load(target.read_text(encoding="utf-8")) or {}


def compare(base: Mapping[str, Any], production: Mapping[str, Any]) -> dict[str, list]:
    """``{"inherited": [(path, value)], "differs": [(path, base, production)]}`` over every leaf path.

    A leaf present on one side only shows ``<unset>`` for the other.
    """
    a, b = flatten(base), flatten(production)
    inherited, differs = [], []
    for path in sorted(set(a) | set(b)):
        left, right = a.get(path, "<unset>"), b.get(path, "<unset>")
        (inherited if left == right else differs).append((path, left) if left == right else (path, left, right))
    return {"inherited": inherited, "differs": differs}


def vendored_commits() -> dict[str, str | None]:
    """The commits of the tracked ``vendor/`` snapshots, from their ``VENDOR.md``."""
    out: dict[str, str | None] = {}
    for name in ("llm-mailroom", "llm-dojo-scoring"):
        meta = vendor_dir() / name / "VENDOR.md"
        match = _COMMIT.search(meta.read_text(encoding="utf-8")) if meta.is_file() else None
        out[name] = match.group(1) if match else None
    return out


def _short(value: Any, limit: int = 80) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def render_parity_md(base: Mapping[str, Any], champion: Mapping[str, Any], *, production: Mapping[str, Any] | None = None,
                     dependency_sources: Mapping[str, Any] | None = None, production_path: str = PRODUCTION_SPEC) -> str:
    """The report's "Production parity" section."""
    production = load_production() if production is None else production
    commits = vendored_commits()
    base_vs = compare(base, production)
    champ_vs = compare(champion, base)
    lines = ["## Production parity", "",
             f"Compared with `{production_path}` (the adopted production configuration).", "",
             "### Pipeline and scoring sources", "",
             f"- vendored llm-mailroom: `{commits['llm-mailroom']}`",
             f"- vendored llm-dojo-scoring: `{commits['llm-dojo-scoring']}`"]
    if dependency_sources:
        for name in ("pipeline", "dojo"):
            row = dependency_sources.get(name) or {}
            lines.append(f"- baseline run lock, {name}: source `{row.get('source')}`, commit `{row.get('commit')}`, "
                         f"tree sha256 `{str(row.get('tree_sha256'))[:16]}`")
    else:
        lines.append("- baseline run lock: not available (no `dependency_sources` in the locked run)")
    lines += ["", f"### Differs from `{production_path}` (the study's base spec)", "",
              "| setting | study base | production |", "|:---|:---|:---|"]
    lines += [f"| `{p}` | {_short(x)} | {_short(y)} |" for p, x, y in base_vs["differs"]] or ["| (none) | | |"]
    lines += ["", f"### Inherited unchanged ({len(base_vs['inherited'])} settings)", ""]
    lines += [f"- `{p}` = {_short(v)}" for p, v in base_vs["inherited"]]
    lines += ["", "### Champion vs the study's base spec (what the kept levers changed)", "",
              "| setting | champion | base |", "|:---|:---|:---|"]
    skip = {"run_id", "job.api_cost_cap_usd", "job.max_wall_seconds", "trace.tags"}
    rows = [(p, x, y) for p, x, y in champ_vs["differs"] if p not in skip]
    lines += [f"| `{p}` | {_short(x)} | {_short(y)} |" for p, x, y in rows] or ["| (none) | | |"]
    return "\n".join(lines) + "\n"
