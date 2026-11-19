"""The sealed held-out set of an experiment split (evaluation runbook R70-R72, SAND-108).

A run selects a split set with ``dataset.exclude_ids_file: config/splits/<split>/<set>.exclude.ids``.
Held-out is unsealed once, in the confirmatory rows, so preflight (and ``run start``, which
re-runs it) refuses:

* a **sealed draw**, an exclusion file named ``heldout.exclude.ids``, unless the run id is on the
  sealed convention (``rb1-r70*`` .. ``rb1-r72*``; the older ``runbook-r7*`` prefix too) **and** the shell sets
  ``SANDBOX_UNSEAL_HELDOUT`` to exactly that run id (a per-run, human-set unseal);
* a **leak**: any other draw through a split's exclusion file whose prepared rows hold a
  held-out id of that split (a mis-pointed or stale exclusion file).

Draws that do not use a split's exclusion files (older ``split: test`` configs) are not touched.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

UNSEAL_ENV = "SANDBOX_UNSEAL_HELDOUT"
SEALED_RUN_ID = re.compile(r"^(rb1|runbook)-r7[0-2][a-z]?(-|$)")
SEALED_FILE = "heldout.exclude.ids"
HELDOUT_IDS = "heldout.ids"


def _exclude_path(spec: Any) -> Path | None:
    dataset = getattr(spec, "dataset", None)
    try:
        return dataset.exclude_ids_path() if dataset is not None else None
    except Exception:  # noqa: BLE001 - a bad path is the dataset check's error, not this one
        return None


def is_sealed_draw(spec: Any) -> bool:
    path = _exclude_path(spec)
    return path is not None and path.name == SEALED_FILE


def seal_errors(spec: Any, run_id: str) -> list[str]:
    """Why this spec may not draw the sealed held-out set (empty when it may, or does not)."""
    if not is_sealed_draw(spec):
        return []
    errs = []
    if not SEALED_RUN_ID.match(run_id or ""):
        errs.append(f"run {run_id!r} draws the sealed held-out set; only the confirmatory rows may "
                    "(run ids rb1-r70* .. rb1-r72*)")
    if os.environ.get(UNSEAL_ENV, "") != run_id:
        errs.append(f"held-out is sealed: set {UNSEAL_ENV}={run_id} in this shell to unseal it for this run only "
                    "(the owner's step at R70; held-out is read once)")
    return errs


def _heldout_ids(split_dir: Path) -> set[str]:
    path = split_dir / HELDOUT_IDS
    if not path.is_file():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


def leak_errors(spec: Any, row_ids: Iterable[str]) -> list[str]:
    """A non-sealed draw through a split's exclusion file that still holds held-out documents."""
    path = _exclude_path(spec)
    if path is None or path.name == SEALED_FILE:
        return []
    heldout = _heldout_ids(path.parent)
    if not heldout:
        return []
    leaked = sorted(set(map(str, row_ids)) & heldout)
    if not leaked:
        return []
    return [f"{len(leaked)} prepared rows are sealed held-out documents of {path.parent.name} (e.g. {leaked[0]}); "
            f"{path.name} does not exclude them"]
