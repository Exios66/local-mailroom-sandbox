"""Shared bootstrap and checks for the offline notebooks in ``notebooks/``.

The notebooks are a guided, network-free tour of the sandbox: environment setup,
fixture preparation, a mock smoke run and a read-only look at the experiment log.
This module keeps their first cell identical and their side effects predictable:

* :func:`find_repo_root` finds the checkout from any kernel working directory.
  Jupyter starts a kernel in the notebook's own folder (``notebooks/``), so a
  ``Path.cwd()`` root, or a relative ``MAILROOM_BASE_DIR=./data`` from ``.env``,
  would otherwise point at ``notebooks/`` and scatter run stores there.
* :func:`bootstrap` pins ``SANDBOX_ROOT`` and an absolute ``MAILROOM_BASE_DIR``,
  forces mock mode and no trace sink unless told otherwise, then activates an
  offline profile.
* :func:`experiment_log_redirect` sends records from notebook evals to a
  notebook-only log under ``data/runtime/notebooks/`` instead of
  ``reports/experiment_log.jsonl``, so mock rows never mix with real runs.
* :func:`check_prepared_artifacts` re-reads what ``prepare_offline_datasets``
  wrote and reports every invariant it breaks.

* :func:`gold_field_grounding` checks that every extractive gold value in
  ``data/fixtures/manifest.csv`` is written in its fixture text, so a gold block
  copied onto the wrong row is caught before a live extraction eval scores it.

Nothing here launches paid or live work.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mailroom_sandbox import paths

OFFLINE_PROFILE = "ollama"
"""Default notebook profile: the offline fallback, which needs no deployed endpoint."""

LOG_ENV = "SANDBOX_NOTEBOOK_LOG"
"""Experiment-log target for notebook evals: unset for the notebook log, ``reports``
for the real ``reports/experiment_log.jsonl``, or any other value as a file path."""

OBSERVABILITY_ENV = "SANDBOX_NOTEBOOK_OBSERVABILITY"
"""Trace sink for notebook runs; defaults to ``none`` so a mock run never needs Langfuse."""


def _is_checkout(path: Path) -> bool:
    return (
        (path / "pyproject.toml").is_file()
        and (path / "config").is_dir()
        and (path / "src" / "mailroom_sandbox").is_dir()
    )


def find_repo_root(start: Path | None = None) -> Path:
    """Return the sandbox checkout that contains ``start`` (default: the working directory).

    A valid ``SANDBOX_ROOT`` wins. Otherwise walk up from ``start``; if no ancestor is a
    checkout, fall back to :func:`mailroom_sandbox.paths.repo_root` (the installed package).
    """
    env = os.environ.get("SANDBOX_ROOT")
    if env and _is_checkout(Path(env).expanduser()):
        return Path(env).expanduser().resolve()
    here = (start or Path.cwd()).expanduser().resolve()
    for candidate in (here, *here.parents):
        if _is_checkout(candidate):
            return candidate
    return paths.repo_root()


def _absolute_base_dir(root: Path) -> Path:
    raw = os.environ.get("MAILROOM_BASE_DIR")
    base = Path(raw).expanduser() if raw else root / "data"
    if not base.is_absolute():
        base = root / base
    return base.resolve()


@dataclass(frozen=True)
class NotebookContext:
    """Where a notebook session reads and writes; print it as the first output."""

    root: Path
    profile: str
    mock: bool
    observability: str
    data_dir: Path
    prepared_dir: Path
    experiment_log: Path

    def as_dict(self) -> dict[str, Any]:
        def show(path: Path) -> str:
            try:
                return str(path.relative_to(self.root))
            except ValueError:
                return str(path)

        return {
            "root": str(self.root),
            "profile": self.profile,
            "mock": self.mock,
            "observability": self.observability,
            "data_dir": show(self.data_dir),
            "prepared_dir": show(self.prepared_dir),
            "experiment_log": show(self.experiment_log),
        }


def notebook_log_path(root: Path | None = None) -> Path:
    """Resolve the experiment log notebook evals append to (see :data:`LOG_ENV`)."""
    root = root or find_repo_root()
    raw = (os.environ.get(LOG_ENV) or "").strip()
    if raw == "reports":
        return root / "reports" / "experiment_log.jsonl"
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else root / path
    return _absolute_base_dir(root) / "runtime" / "notebooks" / "experiment_log.jsonl"


def bootstrap(
    profile: str | None = None,
    *,
    mock: bool = True,
    observability: str | None = None,
    create_dotenv: bool = True,
    activate_profile: bool = True,
) -> NotebookContext:
    """Prepare this kernel for offline sandbox work and describe where it writes.

    ``profile`` falls back to ``SANDBOX_PROFILE`` from the kernel's own environment
    (read *before* ``.env`` loads, so Compose's setting applies but ``.env``'s
    ``modal-vllm`` default does not), then to :data:`OFFLINE_PROFILE`.
    """
    root = find_repo_root()
    os.environ["SANDBOX_ROOT"] = str(root)
    base = _absolute_base_dir(root)
    os.environ["MAILROOM_BASE_DIR"] = str(base)
    profile = profile or os.environ.get("SANDBOX_PROFILE") or OFFLINE_PROFILE
    if mock:
        os.environ["SANDBOX_RUN_MODE"] = "mock"
    sink = observability or os.environ.get(OBSERVABILITY_ENV) or "none"
    os.environ["OBSERVABILITY_PROVIDER"] = sink
    if sink == "none":
        os.environ.setdefault("PHOENIX_TRACING", "disabled")
    # The vendored pipeline logs every graph node at INFO; a notebook only needs warnings.
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    if create_dotenv:
        from mailroom_sandbox.prep import ensure_dotenv_from_example

        ensure_dotenv_from_example()
    if activate_profile:
        from mailroom_sandbox.runtime import activate

        activate(profile)
        # activate() loads .env without overriding, but keep the notebook's choices explicit.
        os.environ["OBSERVABILITY_PROVIDER"] = sink
        os.environ["MAILROOM_BASE_DIR"] = str(base)
        _configure_pipeline_logging()

    return NotebookContext(
        root=root,
        profile=profile,
        mock=mock,
        observability=sink,
        data_dir=base,
        prepared_dir=base / "runtime" / "prepared",
        experiment_log=notebook_log_path(root),
    )


def _configure_pipeline_logging() -> bool:
    """Apply ``LOG_LEVEL`` to the vendored pipeline's structlog setup; False if unavailable.

    Without this, an in-process eval prints every graph node's debug event into the cell,
    because only the pipeline's own entry points call ``setup_logging``.
    """
    try:
        from pipeline.logging import setup_logging
    except ImportError:
        return False
    setup_logging(level=os.environ.get("LOG_LEVEL") or "WARNING")
    return True


@contextmanager
def experiment_log_redirect(path: Path | None = None) -> Iterator[Path]:
    """Point ``mailroom_sandbox.eval.experiment_log`` at ``path`` for the block.

    ``path`` defaults to :func:`notebook_log_path`. The real paths are restored on exit,
    even when the block raises.
    """
    from mailroom_sandbox.eval import experiment_log

    target = Path(path) if path is not None else notebook_log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    original_jsonl, original_md = experiment_log.jsonl_path, experiment_log.md_path
    experiment_log.jsonl_path = lambda: target  # type: ignore[assignment]
    experiment_log.md_path = lambda: target.with_suffix(".md")  # type: ignore[assignment]
    try:
        yield target
    finally:
        experiment_log.jsonl_path = original_jsonl  # type: ignore[assignment]
        experiment_log.md_path = original_md  # type: ignore[assignment]


# Controlled labels: a classification of the document, not a span in it.
CATEGORICAL_FIELDS: frozenset[str] = frozenset({"communication_type", "merger_consideration"})

GROUNDED = "grounded"
UNGROUNDED = "ungrounded"
CATEGORICAL = "categorical"
NON_TEXT = "non_text"

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class GroundingFinding:
    row_id: str
    field: str
    value: Any
    status: str


def _norm(text: str) -> str:
    return _WS.sub(" ", text).casefold().strip()


def _values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def gold_field_grounding(
    rows: Iterable[Mapping[str, Any]] | None = None,
    *,
    categorical: Iterable[str] = CATEGORICAL_FIELDS,
) -> list[GroundingFinding]:
    """One finding per gold value (per item for list fields).

    ``rows`` are cleaned manifest rows (``id``, ``text``, ``expected_fields`` as
    a dict), as ``prep.clean_manifest_rows`` returns; the default loads them.
    A string value is ``grounded`` when it appears in the row text, ignoring
    case and whitespace runs. Fields in ``categorical`` and non-string values
    (numbers, booleans) are reported but not checked.
    """
    if rows is None:
        from mailroom_sandbox.prep import clean_manifest_rows

        rows, _ = clean_manifest_rows()
    skip = frozenset(categorical)
    findings: list[GroundingFinding] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        text = _norm(str(row.get("text") or ""))
        for name, value in (row.get("expected_fields") or {}).items():
            for item in _values(value):
                if name in skip:
                    status = CATEGORICAL
                elif not isinstance(item, str):
                    status = NON_TEXT
                else:
                    needle = _norm(item)
                    status = GROUNDED if needle and needle in text else UNGROUNDED
                findings.append(GroundingFinding(row_id, name, item, status))
    return findings


def ungrounded(findings: Iterable[GroundingFinding]) -> list[GroundingFinding]:
    """The findings whose extractive value is not in the fixture text."""
    return [f for f in findings if f.status == UNGROUNDED]


def _resolve(root: Path, rel: str) -> Path:
    path = Path(rel)
    return path if path.is_absolute() else root / path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_prepared_artifacts(manifest: dict[str, Any], root: Path | None = None) -> list[str]:
    """Re-read every prepared artifact named in ``manifest`` and list broken invariants.

    ``manifest`` is the ``prep_manifest.json`` content (or the summary that
    ``prepare_offline_datasets`` returns). An empty list means every check passed:
    files exist, row counts match, ids are unique, fixture rows carry text and a class,
    the balanced slice has exactly one row per fixture class, and the fingerprint
    recomputes from the fixture rows.
    """
    from mailroom_sandbox.datasets import dataset_fingerprint

    root = root or find_repo_root()
    problems: list[str] = []
    artifacts = manifest.get("artifacts") or {}
    counts = manifest.get("counts") or {}
    loaded: dict[str, list[dict[str, Any]]] = {}

    named = [(key, artifacts.get(key)) for key in ("fixtures", "hf", "sorter_pilot_balanced")]
    named += [(f"agents/{a}", rel) for a, rel in sorted((artifacts.get("agents") or {}).items())]
    for key, rel in named:
        if not rel:
            problems.append(f"{key}: no artifact path in manifest")
            continue
        path = _resolve(root, str(rel))
        if not path.is_file():
            problems.append(f"{key}: missing file {rel}")
            continue
        try:
            rows = _read_jsonl(path)
        except json.JSONDecodeError as exc:
            problems.append(f"{key}: invalid JSONL ({exc.msg} at line {exc.lineno})")
            continue
        loaded[key] = rows
        if key.startswith("agents/"):
            expected = (counts.get("agents") or {}).get(key.split("/", 1)[1])
        else:
            expected = counts.get(key)
        if expected is not None and expected != len(rows):
            problems.append(f"{key}: manifest count {expected} != {len(rows)} rows on disk")
        ids = [row.get("id") for row in rows]
        duplicates = sorted({str(i) for i in ids if ids.count(i) > 1})
        if duplicates:
            problems.append(f"{key}: duplicate ids {duplicates}")

    fixtures = loaded.get("fixtures")
    if fixtures is not None:
        for row in fixtures:
            if not row.get("text") or not row.get("expected_doc_class"):
                problems.append(f"fixtures: row {row.get('id', '?')} lacks text or expected_doc_class")
        fingerprint = dataset_fingerprint(
            [
                {"id": r["id"], "filename": r["filename"], "expected_doc_class": r["expected_doc_class"]}
                for r in fixtures
            ]
        )
        if manifest.get("fingerprint") and fingerprint != manifest["fingerprint"]:
            problems.append(f"fingerprint: manifest {manifest['fingerprint']} != recomputed {fingerprint}")
        balanced = loaded.get("sorter_pilot_balanced")
        if balanced is not None:
            classes = [r.get("expected_doc_class") for r in balanced]
            if len(set(classes)) != len(classes):
                problems.append("sorter_pilot_balanced: more than one row for a class")
            if set(classes) != {r.get("expected_doc_class") for r in fixtures}:
                problems.append("sorter_pilot_balanced: classes differ from the fixture classes")
    return problems
