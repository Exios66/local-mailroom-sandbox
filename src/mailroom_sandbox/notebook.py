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
copied onto the wrong row (parties that are not in the document) is caught
before a live extraction eval scores against it. Network-free.

A value is first matched literally (case and whitespace runs ignored). Gold is
often stored in a canonical form the document does not use verbatim, so a value
that fails the literal match is then compared in canonical form:

- ``date``: a full calendar date (``2024-01-15``) against every date the text
  writes (``January 15, 2024``, ``15th day of January, 2024``, ``1/15/2024``).
- ``number``: an amount or number (``2500000``, ``"$2.5M"``, ``5000000.0``)
  against every amount the text writes (``$2,500,000``, ``2.5 million``).
- ``numeral``: spelled-out numbers read as digits on both sides, so
  ``3 years`` matches ``three (3) years`` and ``thirty days`` matches ``30 days``.
- ``alias``: a canonical abbreviation in ``ALIASES`` (``SEC``) against its written
  forms (``Securities Exchange Act``).

Matches never split a word or number at an alphanumeric edge: ``3 years`` is not
grounded by ``13 years`` and ``SEC`` is not grounded by ``SECTION``.

Those matches are ``grounded_normalized`` with the ``form`` that matched, so
they stay distinguishable from literal ones.

Nothing here launches paid or live work.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from mailroom_sandbox import paths
from mailroom_sandbox.gold_labels import parse_dates

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

    A valid ``SANDBOX_ROOT`` wins. Otherwise walk up from ``start``, then from the installed
    package; an invalid ``SANDBOX_ROOT`` is never returned. With no checkout anywhere, the
    working directory.
    """
    env = os.environ.get("SANDBOX_ROOT")
    if env and _is_checkout(Path(env).expanduser()):
        return Path(env).expanduser().resolve()
    here = (start or Path.cwd()).expanduser().resolve()
    package = Path(paths.__file__).resolve()
    for candidate in (here, *here.parents, *package.parents):
        if _is_checkout(candidate):
            return candidate
    return Path.cwd()


def _dotenv_value(name: str) -> str | None:
    """``name`` from the first ``.env`` file that sets it, in the order ``activate()`` loads them."""
    try:
        from dotenv import dotenv_values

        files = paths.dotenv_files()
    except Exception:  # noqa: BLE001 — no python-dotenv or no checkout: nothing to read
        return None
    for candidate in files:
        value = dotenv_values(candidate).get(name)
        if value:
            return value
    return None


def _absolute_base_dir(root: Path) -> Path:
    # The kernel's environment wins, then .env, as activate() would load it: pinning the variable
    # before activate() runs must not hide a base dir that only .env sets.
    raw = os.environ.get("MAILROOM_BASE_DIR") or _dotenv_value("MAILROOM_BASE_DIR")
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
GROUNDED_NORMALIZED = "grounded_normalized"
UNGROUNDED = "ungrounded"
CATEGORICAL = "categorical"
NON_TEXT = "non_text"

DATE_FORM = "date"
NUMBER_FORM = "number"
NUMERAL_FORM = "numeral"
ALIAS_FORM = "alias"

# Canonical abbreviations the extraction prompts ask for, and the written forms that
# ground them. Keep this short and explicit: every entry widens what counts as grounded.
# "SEC": the compliance prompt names it as the regulatory_body; a 10-K states its
# regulator through the Act it is filed under ("Securities Exchange Act of 1934").
ALIASES: dict[str, tuple[str, ...]] = {
    "sec": ("securities and exchange commission", "securities exchange act"),
}

_WS = re.compile(r"\s+")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_TOKENS = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec|day|of|the)\b\.?|\d+(?:st|nd|rd|th)?|[\s,./-]",
    re.I,
)
_SCALE = {
    "k": Decimal(10**3),
    "thousand": Decimal(10**3),
    "m": Decimal(10**6),
    "mm": Decimal(10**6),
    "million": Decimal(10**6),
    "b": Decimal(10**9),
    "bn": Decimal(10**9),
    "billion": Decimal(10**9),
}
_AMOUNT = re.compile(
    r"(?<![\w.\-\u2212])([-\u2212]?)\$?\s?([-\u2212]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(k|thousand|mm|m|million|bn|b|billion)?(?![\w])",
    re.I,
)
_AMOUNT_ONLY = re.compile(
    r"\s*([-\u2212]?)\s*(?:usd|us\$|\$)?\s*([-\u2212]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(k|thousand|mm|m|million|bn|b|billion)?\s*(?:usd|dollars)?\s*",
    re.I,
)
_UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORD_NUM = {w: i for i, w in enumerate(_UNITS)} | _TENS
_NUM_WORDS = re.compile(
    r"\b(?:("
    + "|".join(_TENS)
    + r")[\s-]("
    + "|".join(_UNITS[1:10])
    + r")|("
    + "|".join(sorted(_WORD_NUM, key=len, reverse=True))
    + r"))\b"
)


@dataclass(frozen=True)
class GroundingFinding:
    row_id: str
    field: str
    value: Any
    status: str
    form: str = ""  # which canonical form matched, for ``grounded_normalized``


def _norm(text: str) -> str:
    return _WS.sub(" ", text).casefold().strip()


def _contains(haystack: str, needle: str) -> bool:
    """``needle`` in ``haystack`` without splitting a word or number at an alphanumeric edge.

    ``3 years`` is not in ``13 years`` and ``Delaware`` is not in ``Delawarean``;
    an edge that is punctuation (``Inc.``) matches as a plain substring.
    """
    head = r"(?<!\w)" if needle[:1].isalnum() else ""
    tail = r"(?!\w)" if needle[-1:].isalnum() else ""
    return re.search(head + re.escape(needle) + tail, haystack) is not None


def _values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _dates(text: str) -> set[str]:
    """Every full calendar date ``text`` writes, as ISO strings."""
    found = parse_dates(text)
    for y, m, d in _ISO_DATE.findall(text):
        try:
            found.add(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            continue
    return found


def _gold_date(value: str) -> str | None:
    """The one full date ``value`` states, as ISO, when ``value`` is only a date.

    A sentence that mentions a date ("signed on 1/2/2024 by both") is not a date
    value and falls through to the literal and numeral checks.
    """
    if _DATE_TOKENS.sub("", value):
        return None
    dates = _dates(value)
    return next(iter(dates)) if len(dates) == 1 else None


def _amount(sign: str, sign2: str, whole: str, frac: str | None, scale: str | None) -> Decimal:
    value = Decimal(whole.replace(",", "") + (frac or "")) * _SCALE.get(
        (scale or "").casefold(), Decimal(1)
    )
    return -value if (sign or sign2) else value


def _amounts(text: str) -> set[Decimal]:
    """Every number or amount ``text`` writes, scaled (``2.5 million`` is 2500000.0)."""
    return {_amount(*m.groups()) for m in _AMOUNT.finditer(text)}


def _gold_amount(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        try:
            return Decimal(repr(value))  # the shortest repr, not the binary expansion
        except InvalidOperation:  # nan / inf
            return None
    m = _AMOUNT_ONLY.fullmatch(value) if isinstance(value, str) else None
    return _amount(*m.groups()) if m else None


def _numerals(text: str) -> str:
    """Spelled-out numbers as digits; ``three (3)`` collapses to ``3``."""

    def word(m: re.Match[str]) -> str:
        if m.group(3):
            return str(_WORD_NUM[m.group(3)])
        return str(_TENS[m.group(1)] + _WORD_NUM[m.group(2)])

    text = _NUM_WORDS.sub(word, _norm(text))
    return re.sub(r"\b(\d+)\s*\(\s*\1\s*\)", r"\1", text)


def _normalized_form(item: Any, raw_text: str, text: str) -> str | None:
    """The canonical form under which ``item`` is written in the text, if any."""
    if isinstance(item, str):
        iso = _gold_date(item)
        if iso is not None:
            return DATE_FORM if iso in _dates(raw_text) else None
    amount = _gold_amount(item)
    if amount is not None and amount in _amounts(raw_text):
        return NUMBER_FORM
    if isinstance(item, str):
        if any(_contains(text, alias) for alias in ALIASES.get(_norm(item), ())):
            return ALIAS_FORM
        needle = _numerals(item)
        if needle and _contains(_numerals(text), needle):
            return NUMERAL_FORM
    return None


def gold_field_grounding(
    rows: Iterable[Mapping[str, Any]] | None = None,
    *,
    categorical: Iterable[str] = CATEGORICAL_FIELDS,
) -> list[GroundingFinding]:
    """One finding per gold value (per item for list fields).

    ``rows`` are cleaned manifest rows (``id``, ``text``, ``expected_fields`` as
    a dict), as ``prep.clean_manifest_rows`` returns; the default loads them.
    A string value is ``grounded`` when it appears in the row text, ignoring
    case and whitespace runs, and ``grounded_normalized`` when it appears only
    in a canonical form (see the module docstring). Numbers are matched by
    value. Fields in ``categorical`` are reported but not checked, and so are
    values with no text form (booleans, ``None``, objects).
    """
    if rows is None:
        from mailroom_sandbox.prep import clean_manifest_rows

        rows, _ = clean_manifest_rows()
    skip = frozenset(categorical)
    findings: list[GroundingFinding] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        raw_text = str(row.get("text") or "")
        text = _norm(raw_text)
        for name, value in (row.get("expected_fields") or {}).items():
            for item in _values(value):
                form = ""
                if name in skip:
                    status = CATEGORICAL
                elif isinstance(item, str) and _norm(item) and _contains(text, _norm(item)):
                    status = GROUNDED
                elif not isinstance(item, (str, int, float)) or isinstance(item, bool):
                    status = NON_TEXT
                elif isinstance(item, str) and not _norm(item):
                    status = UNGROUNDED
                else:
                    form = _normalized_form(item, raw_text, text) or ""
                    status = GROUNDED_NORMALIZED if form else UNGROUNDED
                findings.append(GroundingFinding(row_id, name, item, status, form))
    return findings


def ungrounded(findings: Iterable[GroundingFinding]) -> list[GroundingFinding]:
    """The findings whose extractive value is not in the fixture text."""
    return [f for f in findings if f.status == UNGROUNDED]


#: Hosts a notebook probe may call: this machine and the Compose services of the offline stack.
LOCAL_PROBE_HOSTS: frozenset[str] = frozenset(
    {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal", "ollama", "vllm", "llamacpp"}  # nosec B104 -- hosts a probe connects to; nothing binds here
)


def probe_refusal(profile: str) -> str | None:
    """Why notebook 01 must not probe ``profile`` (None when its endpoint is local).

    ``health_check`` sends a real chat completion, so a profile that resolves to a remote endpoint
    (OpenRouter, a deployed Modal app) would spend from a notebook. Only a local or Compose
    endpoint is probed; run ``sandbox health --profile <name>`` for anything else.
    """
    from urllib.parse import urlsplit

    from mailroom_sandbox.health import _effective_base_url, missing_modal_endpoint
    from mailroom_sandbox.overlay import load_profile
    from mailroom_sandbox.providers import endpoints_for

    spec = load_profile(profile)
    if missing_modal_endpoint(spec):
        return f"profile {profile!r} has no endpoint configured"
    url = endpoints_for(spec, base_url_override=_effective_base_url(spec)).base_url
    host = (urlsplit(str(url)).hostname or "").lower()
    if host not in LOCAL_PROBE_HOSTS:
        return f"profile {profile!r} resolves to {host or url!r}, not a local endpoint"
    return None


def _resolve(root: Path, rel: str) -> Path:
    path = Path(rel)
    return path if path.is_absolute() else root / path


def _read_jsonl(path: Path) -> list[Any]:
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
        objects = [row for row in rows if isinstance(row, dict)]
        if len(objects) != len(rows):
            problems.append(f"{key}: {len(rows) - len(objects)} line(s) are not JSON objects")
        rows = objects
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
            if not row.get("id") or not row.get("filename"):
                problems.append(f"fixtures: row {row.get('id', '?')} lacks id or filename")
            if not row.get("text") or not row.get("expected_doc_class"):
                problems.append(f"fixtures: row {row.get('id', '?')} lacks text or expected_doc_class")
        fingerprint = dataset_fingerprint(
            [
                {"id": r.get("id"), "filename": r.get("filename"), "expected_doc_class": r.get("expected_doc_class")}
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
