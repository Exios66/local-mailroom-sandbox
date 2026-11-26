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

* :func:`show_figure` embeds matplotlib figures as PNG so Agg/demo runs stay visual.

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
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
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
    if os.environ.get("SANDBOX_SKIP_DOTENV"):
        return None
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


def show_figure(fig: Any) -> None:
    """Embed ``fig`` as a PNG in the notebook cell (works with the Agg backend).

    ``plt.show()`` is a no-op under Agg and only warns; ``display(fig)`` often
    yields a text representation. Saving to PNG keeps demo outputs visual.
    """
    import io

    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    try:
        from IPython.display import Image, display

        fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
    finally:
        plt.close(fig)
    display(Image(data=buf.getvalue()))


@contextmanager
def quiet_pipeline_logs():
    """Buffer demo stdout and scope expected warnings, restoring kernel state even on failure."""
    import io
    import logging
    import warnings
    from contextlib import redirect_stdout

    previous = logging.root.manager.disable
    buffer = io.StringIO()
    try:
        with warnings.catch_warnings(), redirect_stdout(buffer):
            logging.disable(logging.WARNING)
            warnings.filterwarnings("ignore", category=RuntimeWarning, module=r".*relations.*")
            yield buffer
    finally:
        logging.disable(previous)


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
    endpoints = endpoints_for(spec, base_url_override=_effective_base_url(spec))
    for url in (endpoints.base_url, endpoints.models_url, endpoints.chat_url):
        parsed = urlsplit(str(url))
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or host not in LOCAL_PROBE_HOSTS:
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


# --------------------------------------------------------------------------- agent fixtures

#: Agent fixture keys that hold a span the agent must reproduce from the row's own text.
AGENT_SNIPPET_KEYS: tuple[str, ...] = ("expected_snippet", "expected")


def _agent_rows(agent: str) -> list[dict[str, Any]]:
    """The agent's prepared rows plus catalog rows the cleaner dropped for empty text."""
    from mailroom_sandbox.prep import clean_agent_rows, load_agent_fixtures

    prepared, _ = clean_agent_rows(agent)
    kept = {row["id"] for row in prepared}
    for raw in load_agent_fixtures(agent):
        row_id = str(raw.get("id") or "").strip()
        if row_id and row_id not in kept and raw.get("subdir") and raw.get("filename"):
            gold = raw.get("expected_fields")
            if isinstance(gold, str):
                try:
                    gold = json.loads(gold)
                except json.JSONDecodeError:
                    gold = {}
            prepared.append({**raw, "id": row_id, "text": "", "expected_fields": gold})
    return prepared


def agent_fixture_grounding(agents: Iterable[str] | None = None) -> list[GroundingFinding]:
    """``gold_field_grounding`` over ``data/fixtures/agents/*.jsonl``.

    A row is checked when it has text: a catalog document (``subdir`` + ``filename``) or
    inline ``text``. Its ``expected_fields`` and its expected snippets (``expected_snippet``,
    ``expected``) must be written in that text. Rows that carry only model output to
    judge (``extracted_data`` with no source document) or a binary ``file`` (image, PDF) have
    no text to ground against and yield no findings. A row whose catalog document is missing
    or empty is checked against empty text, so its gold is reported ungrounded rather than
    skipped.
    Row ids are ``<agent>/<id>``.
    """
    from mailroom_sandbox.paths import fixtures_dir

    if agents is None:
        agents = sorted(p.stem for p in (fixtures_dir() / "agents").glob("*.jsonl"))
    rows: list[dict[str, Any]] = []
    for agent in agents:
        for row in _agent_rows(agent):
            text = row.get("text")
            if not isinstance(text, str) or not text:
                if not (row.get("subdir") and row.get("filename")):
                    continue
                text = ""  # named catalog document is missing or empty: its gold is ungrounded
            gold = dict(row.get("expected_fields") or {})
            gold.update({k: row[k] for k in AGENT_SNIPPET_KEYS if isinstance(row.get(k), str)})
            if gold:
                rows.append({"id": f"{agent}/{row['id']}", "text": text, "expected_fields": gold})
    return gold_field_grounding(rows)


# --------------------------------------------------------------------------- label overlays

#: Label overlays the scoring fixes read as truth: the near-gold overlay (SHF-010 supersedes
#: interim gap fills with it) and the interim overlay (``dataset.interim_labels``).
LABEL_OVERLAYS: tuple[str, ...] = ("gold-overlay", "interim")

NO_EVIDENCE = "no_evidence"
#: A closed label with no quote: its value is in the field's vocabulary, which is all a closed
#: label states without evidence.
IN_VOCABULARY = "in_vocabulary"


@dataclass(frozen=True)
class LabelFinding:
    overlay: str
    doc_id: str
    doc_class: str
    field: str
    value: Any
    status: str  # grounded | ungrounded | in_vocabulary | no_evidence
    basis: str = ""
    reason: str = ""


def _evidence_quotes(label: Mapping[str, Any]) -> list[str]:
    """The quoted text of a label's evidence: span ``text``, an email ``header`` line, or a string."""
    quotes = []
    for item in label.get("evidence") or []:
        if isinstance(item, str):
            quotes.append(item)
        elif isinstance(item, Mapping):
            quote = item.get("text") or item.get("header")
            if isinstance(quote, str):
                quotes.append(quote)
    return [q for q in quotes if q.strip()]


def cached_doc_rows(path: Any = None) -> dict[str, dict[str, Any]]:
    """``{doc_id: row}`` from the pulled Hub corpus (``sandbox datasets pull``), or ``{}``.

    Reads ``datasets.full_corpus_cache_path()`` unless ``path`` is given. Never reaches the
    network: without a pulled cache, labels that need their document stay ``no_evidence``.
    """
    import json
    from pathlib import Path

    from mailroom_sandbox.datasets import full_corpus_cache_path
    from mailroom_sandbox.interim_labels import row_id

    src = Path(path) if path is not None else full_corpus_cache_path()
    if not src.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    # Split on newlines only: JSON strings may hold U+2028 and other separators splitlines() takes.
    for line in src.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            row = json.loads(line)
            if row_id(row):
                rows[row_id(row)] = row
    return rows


def _reviewed_label_status(
    doc_class: str, name: str, label: Mapping[str, Any], quotes: list[str],
    doc_subclass: str | None = None,
) -> tuple[str, str]:
    """A reviewed label, by the review file's rule (``interim_labels``), then its quote if any.

    A reviewed intent (``review_read_message``) is checked by the vocabulary rule alone: the
    review file takes no quote minimum, so an optional quote is not held to the gate's.
    """
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    value, basis = label.get("value"), str(label.get("basis") or "")
    if doc_class == "corporate_record" and doc_subclass is not None:
        ok, reason = gl.evidence_support(doc_class, name, value, quotes, doc_subclass)
        return (GROUNDED, "") if ok else (UNGROUNDED, reason)
    problem = il._review_value_problem(name, value)
    if not problem and basis == "original_header":
        problem = il._header_problem(name, value, label.get("evidence"))
    elif not problem and basis == "review_read_record":
        problem = il._record_quote_problem(value, label.get("evidence"))
    if problem:
        return UNGROUNDED, problem
    if basis == "review_read_message":
        return IN_VOCABULARY, ""  # a reviewed intent: the vocabulary rule; quotes are optional
    if basis != "original_header" and quotes:
        ok, reason = gl.evidence_support(doc_class, name, value, quotes, doc_subclass)
        return (GROUNDED, "") if ok else (UNGROUNDED, reason)
    return (GROUNDED, "") if quotes else (IN_VOCABULARY, "")


def _hub_row_label_status(
    row: Mapping[str, Any], name: str, label: Mapping[str, Any]
) -> tuple[str, str]:
    """An unquoted label against its document's Hub row, by the build's own rule."""
    from mailroom_sandbox import interim_labels as il

    value, basis = label.get("value"), str(label.get("basis") or "")
    if label.get("status") == "correction" and basis.startswith("cuad_"):
        if il.contract_correction(name, value, il._expected(row)) == basis:
            return GROUNDED, ""
        return UNGROUNDED, f"not supported by the row's CUAD spans ({basis})"
    text = row.get("doc_text") if row.get("doc_text") is not None else row.get("text")
    if il.grounded(value, str(text or "")):
        return GROUNDED, ""
    return UNGROUNDED, "value not in the document"


def _check_label(
    record: Mapping[str, Any],
    doc_class: str,
    name: str,
    label: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    """``(status, reason)`` for one populated label, by the rule that admitted it.

    - ``derived``: recomputed from the record's own ``doc_subclass``.
    - a reviewed label (``review``): the review file's rule (``interim_labels``): header lines
      for ``original_header``, the quote for ``review_read_record``, the vocabulary alone for
      intents (``in_vocabulary``).
    - a stored quote: the label gate's value rules (``gold_labels.evidence_support``).
    - no quote, a closed label: the value is in the field's vocabulary (``in_vocabulary``).
    - no quote, the document's Hub row available (``rows``, bound by ``doc_sha256``): the
      build's own rule. A gap fill's every token is in the text (``interim_labels.grounded``);
      a CUAD correction agrees with the row's CUAD spans (``interim_labels.contract_correction``).
    - a gap fill whose stored ``support`` is under the admission threshold is ``ungrounded``
      before any document check: the build requires both the support and the text.
    - otherwise ``no_evidence``.
    """
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    value = label.get("value")
    status = label.get("status")
    sub = record.get("doc_subclass")
    row = rows.get(str(record.get("doc_id") or ""))
    if doc_class == "corporate_record":
        if "doc_subclass" in record and sub is None:
            return UNGROUNDED, "invalid corporate record subclass None"
        if row is not None and il.row_doc_sha(row) == record.get("doc_sha256"):
            row_class, row_sub = row.get("expected_doc_class"), row.get("expected_subclass")
            if (row_class and row_class != doc_class) or (sub is not None and row_sub is not None and sub != row_sub):
                return UNGROUNDED, "record identity differs from bound corpus row"
            if sub is None:
                sub = row_sub
        if sub is not None:
            try:
                gl._corporate_subclass(sub)
            except KeyError as exc:
                return UNGROUNDED, str(exc)
    if status == "derived":
        if doc_class == "corporate_record" and name != "record_type":
            return UNGROUNDED, f"{name} is not a derived corporate field"
        sub = str(sub or "")
        want = sub if label.get("basis") == "cms_subclass" else il.derived_value(doc_class, sub)
        return (
            (GROUNDED, "")
            if value == want
            else (UNGROUNDED, f"{doc_class} subclass {sub!r} derives {want!r}")
        )
    quotes = _evidence_quotes(label)
    if doc_class == "corporate_record":
        # Entity fields must always pass the admission gate, including reviewed labels.
        from llm_dojo_scoring.schemas.corporate_record_schema import SUBCLASS_SCHEMAS

        entities = {entity.key for schema in SUBCLASS_SCHEMAS.values() for entity in schema.entities}
        if name in entities:
            if sub is None or name not in gl.target_fields(doc_class, doc_subclass=sub):
                return UNGROUNDED, f"not a target field of {doc_class}/{sub}"
            types, _, _, _, model = gl._schema_bits(doc_class, sub)
            problem = gl._corporate_value_error(model, name, value, str(types[name]), sub)
            if problem:
                return UNGROUNDED, problem
            if not quotes:
                return NO_EVIDENCE, "no evidence quote"
            if label.get("review"):
                return _reviewed_label_status(doc_class, name, label, quotes, sub)
            ok, reason = gl.evidence_support(doc_class, name, value, quotes, sub)
            return (GROUNDED, "") if ok else (UNGROUNDED, reason)
        elif name not in gl._schema_bits(doc_class)[0]:
            return UNGROUNDED, f"not a target field of {doc_class}/{sub}"
    if label.get("review"):
        return _reviewed_label_status(doc_class, name, label, quotes)
    if quotes:
        ok, reason = gl.evidence_support(doc_class, name, value, quotes)
        return (GROUNDED, "") if ok else (UNGROUNDED, reason)
    allowed = gl._schema_bits(doc_class, sub)[1].get(name)
    if allowed is not None:
        ok = value in allowed
        return (IN_VOCABULARY, "") if ok else (UNGROUNDED, f"out_of_vocabulary: {value!r}")
    support = label.get("support")
    if status == "gap_fill" and isinstance(support, (int, float)) and support < il.SUPPORT_MIN:
        return UNGROUNDED, f"support {support} is under the admission threshold {il.SUPPORT_MIN}"
    if row is not None and il.row_doc_sha(row) == record.get("doc_sha256"):
        return _hub_row_label_status(row, name, label)
    if row is not None:
        return NO_EVIDENCE, "document text changed since the label was read"
    return NO_EVIDENCE, ""


def label_overlay_grounding(
    overlays: Iterable[str] = LABEL_OVERLAYS,
    *,
    root: Any = None,
    rows: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[LabelFinding]:
    """Every populated truth label in the scoring overlays, checked by the rule that admitted it.

    See ``_check_label`` for the rule per kind of label. ``rows`` (``{doc_id: Hub row}``, e.g.
    ``cached_doc_rows()``) lets labels with no stored quote be checked against their document;
    without it they stay ``no_evidence``. Empty values and interim ``disputed`` labels (never
    truth) are not reported.
    """
    import json
    from pathlib import Path

    from mailroom_sandbox.paths import repo_root

    base = Path(root) if root is not None else repo_root() / "data" / "labels"
    rows = rows or {}
    findings: list[LabelFinding] = []
    for overlay in overlays:
        for path in sorted((base / overlay).glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                doc_class = str(record.get("doc_class") or path.stem)
                for name, label in (record.get("labels") or {}).items():
                    if not isinstance(label, Mapping) or label.get("status") == "disputed":
                        continue
                    value = label.get("value")
                    if value is None or value == "" or value == []:
                        continue
                    status, reason = _check_label(record, doc_class, name, label, rows)
                    findings.append(
                        LabelFinding(
                            overlay,
                            str(record.get("doc_id") or ""),
                            doc_class,
                            name,
                            value,
                            status,
                            str(label.get("basis") or ""),
                            reason,
                        )
                    )
    return findings


# --------------------------------------------------------------------------- merged truth

#: Where a scored truth field comes from after the merge (Hub GT -> interim -> near-gold).
HUB = "hub"
INTERIM = "interim"  # an interim truth label in a field the Hub leaves unlabelled
INTERIM_CORRECTION = "interim_correction"  # an interim correction of the Hub value it names
NEAR_GOLD = "near_gold"  # near-gold in a field neither the Hub nor interim labels
NEAR_GOLD_SHF010 = "near_gold_shf010"  # near-gold superseding a conflicting interim gap fill

_NOT_FIELDS = frozenset({"gt_presence", "cuad_clause_labels"})
#: The layer an overlap was settled by.
_WINNER = {
    HUB: HUB,
    INTERIM: INTERIM,
    INTERIM_CORRECTION: INTERIM,
    NEAR_GOLD: NEAR_GOLD,
    NEAR_GOLD_SHF010: NEAR_GOLD,
}


@dataclass(frozen=True)
class TruthField:
    doc_id: str
    doc_class: str
    field: str
    source: str
    value: Any


@dataclass(frozen=True)
class HubConflict:
    """A Hub label an interim gate extraction disagrees with and no rule settled (``disputed``).

    The Hub value stays the truth until a review or CUAD check makes the overlay a ``correction``
    (the clear winner). ``hub_grounded`` / ``overlay_grounded``: whether each value's tokens are in
    the document (``None`` for an empty value or a closed label, which the text cannot settle).
    """

    doc_id: str
    doc_class: str
    field: str
    hub_value: Any
    overlay_value: Any
    support: Any
    hub_grounded: bool | None
    overlay_grounded: bool | None


@dataclass
class TruthMerge:
    """The merged truth of a set of Hub rows, with the precedence problems found on the way."""

    fields: list[TruthField]
    #: ``(interim basis, "agree" | "differ", winner)`` -> count, for every document and field both
    #: the interim truth and near-gold label. The winner is the layer the merged field came from
    #: (``hub``, ``interim`` or ``near_gold``).
    overlaps: dict[tuple[str, str, str], int]
    #: A merge result the precedence rules forbid (an overlay replacing a Hub label other than by
    #: an interim correction, or SHF-010 replacing anything but an interim gate gap fill).
    violations: list[str]
    #: Hub labels an overlay disagrees with and no rule settled, kept as Hub truth for review.
    hub_conflicts: list[HubConflict] = field(default_factory=list)

    def breakdown(self) -> dict[str, dict[str, int]]:
        """``{doc_class: {source: fields}}``."""
        out: dict[str, Counter[str]] = {}
        for f in self.fields:
            out.setdefault(f.doc_class, Counter())[f.source] += 1
        return {cls: dict(c) for cls, c in sorted(out.items())}


def _labelled(exp: Mapping[str, Any]) -> set[str]:
    from mailroom_sandbox.gold_labels import hub_labels

    return {f for f in exp if f not in _NOT_FIELDS and hub_labels(f, exp)}


def _same(a: Any, b: Any) -> bool:
    import json

    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _field_source(
    name: str,
    ilab: Mapping[str, Any],
    hub: Mapping[str, Any],
    final: Mapping[str, Any],
    hub_fields: set[str],
    ifields: set[str],
    nfields: set[str],
    shf010: set[str],
) -> tuple[str, str]:
    """``(source, precedence problem or "")`` of one merged field."""
    if name in shf010:
        if name in hub_fields:
            return NEAR_GOLD_SHF010, "SHF-010 replaced the Hub label"
        if ilab.get("basis") != "gate_accepted_grounded":
            return NEAR_GOLD_SHF010, f"SHF-010 replaced a {ilab.get('basis')} label"
        return NEAR_GOLD_SHF010, ""
    if name in nfields:
        bad = name in hub_fields or name in ifields
        return NEAR_GOLD, "near-gold replaced a label it must not" if bad else ""
    if name in ifields:
        if name not in hub_fields:
            return INTERIM, ""
        ok = ilab.get("status") == "correction"
        return (
            INTERIM_CORRECTION,
            "" if ok else f"an interim {ilab.get('status')} replaced the Hub label",
        )
    if not _same(final.get(name), hub.get(name)):
        return HUB, "the Hub value changed with no overlay recorded"
    return HUB, ""


def _hub_conflicts(row: Mapping[str, Any], ilabels: Mapping[str, Any]) -> list[HubConflict]:
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    doc_id, cls = il.row_id(row), str(row.get("expected_doc_class") or "")
    text = str(row.get("doc_text") or "")
    try:
        closed = gl._schema_bits(cls, row.get("expected_subclass"))[1] if cls else {}
    except KeyError:
        closed = {}  # unknown corporate subtype supplies no reliable vocabulary
    out = []
    for name, lab in sorted(ilabels.items()):
        if lab.get("status") != "disputed":
            continue
        hub_value = gl._parse_json(il._expected(row).get(name))

        def grounded(value: Any, name: str = name) -> bool | None:
            if name in closed or value in (None, "", [], {}):
                return None
            return il.grounded(value, text)

        out.append(
            HubConflict(
                doc_id,
                cls,
                name,
                hub_value,
                lab.get("value"),
                lab.get("support"),
                grounded(hub_value),
                grounded(lab.get("value")),
            )
        )
    return out


def _merge_row(
    row: Mapping[str, Any],
    interim: Mapping[str, Any],
    near: Mapping[str, Any],
    shas: tuple[str, str],
) -> tuple[list[TruthField], Counter[tuple[str, str, str]], list[str]]:
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    doc_id, cls = il.row_id(row), str(row.get("expected_doc_class") or "")
    if row.get("id") != doc_id:
        row = {**row, "id": doc_id}  # a raw Hub row keys on document_id; apply_near_gold on id
    hub = il._expected(row)
    hub_fields = _labelled(hub)
    after_interim = il.apply_overlay(row, interim, overlay_sha=shas[0])
    ifields = set((after_interim.get("interim_labels") or {}).get("fields") or [])
    final_row = gl.apply_near_gold(after_interim, near, overlay_sha=shas[1], interim=interim)
    nfields = set((final_row.get("near_gold_labels") or {}).get("fields") or [])
    shf010 = set((final_row.get("truth_overrides") or {}).get("SHF-010") or {})
    final = il._expected(final_row)
    ilabels = (interim.get(doc_id) or {}).get("labels") or {}
    fields, problems = [], []
    for name in sorted(_labelled(final)):
        source, problem = _field_source(
            name, ilabels.get(name) or {}, hub, final, hub_fields, ifields, nfields, shf010
        )
        if problem:
            problems.append(f"{doc_id}.{name}: {problem}")
        fields.append(TruthField(doc_id, cls, name, source, final.get(name)))
    won = {f.field: f.source for f in fields}
    overlaps: Counter[tuple[str, str, str]] = Counter()
    nlabels = (near.get(doc_id) or {}).get("labels") or {}
    for name in sorted(set(ilabels) & set(nlabels)):
        ilab, nlab = ilabels[name], nlabels[name]
        if not ilab.get("use_as_truth") or not str(nlab.get("basis") or "").startswith(
            "near_gold:"
        ):
            continue
        agree = "agree" if _same(ilab.get("value"), nlab.get("value")) else "differ"
        winner = _WINNER.get(won.get(name, ""), "unlabelled")
        overlaps[(str(ilab.get("basis") or ""), agree, winner)] += 1
    return fields, overlaps, problems


def merged_truth(
    rows: Iterable[Mapping[str, Any]],
    *,
    interim: Mapping[str, Mapping[str, Any]] | None = None,
    near_gold: Mapping[str, Mapping[str, Any]] | None = None,
) -> TruthMerge:
    """Merge Hub rows with the overlays exactly as scoring does and say where each field came from.

    Uses ``interim_labels.apply_overlay`` then ``gold_labels.apply_near_gold`` (SHF-010 included
    while it is current), so the breakdown is the truth a run scores against. ``hub_conflicts``
    lists the Hub labels an overlay disagrees with that no rule settled (interim ``disputed``):
    the Hub value stands until a review or CUAD check makes the overlay the clear winner. ``rows`` are Hub
    rows with their text (``cached_doc_rows().values()``); ``interim`` and ``near_gold`` default to
    the committed overlays. A row whose text no longer matches an overlay's ``doc_sha256`` keeps
    its Hub labels, as at run time.
    """
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    if interim is None:
        interim = il.load_overlay()
    near_sha = "supplied"
    if near_gold is None:
        near_gold, near_sha, problems = gl.near_gold_snapshot()
        if problems:
            raise ValueError(f"near-gold label overlay is inconsistent: {problems[0]}")
    fields: list[TruthField] = []
    overlaps: Counter[tuple[str, str, str]] = Counter()
    violations: list[str] = []
    conflicts: list[HubConflict] = []
    for row in rows:
        f, o, v = _merge_row(row, interim, near_gold, ("supplied", near_sha))
        fields += f
        overlaps.update(o)
        violations += v
        rec = interim.get(il.row_id(row)) or {}
        if rec.get("doc_sha256") == il.row_doc_sha(row):
            conflicts += _hub_conflicts(row, rec.get("labels") or {})
    return TruthMerge(fields, dict(overlaps), violations, conflicts)
