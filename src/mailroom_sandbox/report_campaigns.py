"""Campaign report tree: file every run's records under ``reports/campaigns/`` (SAND-108).

Layout (the grammar is documented in ``reports/campaigns/README.md``)::

    reports/campaigns/<campaign>/                       rb1/
      README.md, index.jsonl                            campaign index (one row per run iteration)
      <key>-<slug>/                                     rb1-r01-provider-pin-smoke/
        README.md                                       experiment index
        <run_id>/<iNN>/                                 rb1-r01-smoke-qwen3.7-flash/i01/
          README.md, <run_id>-<iNN>.manifest.json
          logs/ traces/ outputs/ report/ analysis/ figures/ docs/

Every generated file except ``README.md`` and ``index.jsonl`` starts with its full key
(``<run_id>-<iNN>.<name>.<ext>``), so one filename identifies campaign, experiment, run and
iteration. The builder reads only run logs (the run store, the experiment log, the served
provider ledger and gate outputs) and writes deterministically: no timestamps of its own,
no absolute paths. Scores are never recomputed here: the headline comes from the run's own
experiment-log record (matched to the locked generation) and cost from the existing serving
renderer; anything missing is shown as missing, never estimated.

An iteration is one locked generation of a run_id: each ``archive-*`` directory a forced
re-lock moved aside (oldest first), then the live store. Relaunches and resumes inside one
generation append to the same items, so they are listed as launches of that iteration.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from mailroom_sandbox.paths import config_dir, data_dir, repo_root

_log = logging.getLogger("mailroom_sandbox.report_campaigns")

SUBDIRS = ("logs", "traces", "outputs", "report", "analysis", "figures", "docs")
COPY_CAP_BYTES = 256 * 1024
DISABLE_ENV = "SANDBOX_CAMPAIGN_REPORTS"
ROOT_ENV = "SANDBOX_CAMPAIGN_REPORTS_DIR"

# ── naming grammar ──────────────────────────────────────────────────────────
CAMPAIGN_RE = re.compile(r"[a-z][a-z0-9]*")
ROW_RE = re.compile(r"[a-z]+[0-9][a-z0-9]*")
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ITERATION_RE = re.compile(r"i(\d{2,})")
RUN_ID_RE = re.compile(
    r"(?P<campaign>[a-z][a-z0-9]*)-(?P<row>[a-z]+[0-9][a-z0-9]*)-(?P<rest>[a-z0-9][a-z0-9._-]*)"
)
_TRAILING_ITER = re.compile(r"-i\d+$")
ARTIFACT_RE = re.compile(
    r"(?P<run_id>[a-z0-9][a-z0-9._-]*?)-(?P<iteration>i\d{2,})\.(?P<name>[a-z0-9][a-z0-9_-]*)\.(?P<ext>[a-z0-9]+)"
)


class CampaignError(ValueError):
    """A run, key or file name outside the campaign grammar or mapping."""


@dataclass(frozen=True)
class RunKey:
    """One run iteration's identity: campaign, row, run_id and iteration number."""

    campaign: str
    row: str
    run_id: str
    iteration: int = 1

    @property
    def experiment(self) -> str:
        return f"{self.campaign}-{self.row}"

    @property
    def iteration_label(self) -> str:
        return format_iteration(self.iteration)

    @property
    def stem(self) -> str:
        return f"{self.run_id}-{self.iteration_label}"

    def artifact(self, name: str, ext: str) -> str:
        """``<run_id>-<iNN>.<name>.<ext>``."""
        return format_artifact(self.run_id, self.iteration, name, ext)


def format_iteration(number: int) -> str:
    if not isinstance(number, int) or number < 1:
        raise CampaignError(f"iteration must be a positive int, got {number!r}")
    return f"i{number:02d}"


def parse_iteration(label: str | int) -> int:
    if isinstance(label, int):
        format_iteration(label)
        return label
    text = str(label).strip()
    if text.isdigit():
        return parse_iteration(int(text))
    match = ITERATION_RE.fullmatch(text)
    if not match or int(match.group(1)) < 1:
        raise CampaignError(f"iteration {label!r} must look like i01")
    return int(match.group(1))


def experiment_key(campaign: str, row: str) -> str:
    if not CAMPAIGN_RE.fullmatch(campaign or "") or not ROW_RE.fullmatch(row or ""):
        raise CampaignError(f"bad campaign/row {campaign!r}/{row!r}")
    return f"{campaign}-{row}"


def parse_run_id(run_id: str) -> RunKey:
    """Split ``<campaign>-<row>-<rest>``; raise CampaignError when it is outside the grammar."""
    text = str(run_id or "")
    match = RUN_ID_RE.fullmatch(text)
    if not match or _TRAILING_ITER.search(text) or len(text) > 64:
        raise CampaignError(
            f"run_id {run_id!r} must be <campaign>-<row>-<rest>, lowercase, at most 64 characters, "
            "not ending in -iNN"
        )
    return RunKey(match["campaign"], match["row"], text)


def format_run_id(campaign: str, row: str, rest: str) -> str:
    return parse_run_id(f"{experiment_key(campaign, row)}-{rest}").run_id


def format_artifact(run_id: str, iteration: int, name: str, ext: str) -> str:
    key = parse_run_id(run_id)
    out = f"{key.run_id}-{format_iteration(iteration)}.{name}.{ext}"
    if parse_artifact(out) != (key.run_id, iteration, name, ext):
        raise CampaignError(f"artifact name {out!r} does not round-trip")
    return out


def parse_artifact(filename: str) -> tuple[str, int, str, str]:
    """``(run_id, iteration, name, ext)`` from ``<run_id>-<iNN>.<name>.<ext>``."""
    match = ARTIFACT_RE.fullmatch(Path(filename).name)
    if not match:
        raise CampaignError(f"{filename!r} is not <run_id>-<iNN>.<name>.<ext>")
    run_id = parse_run_id(match["run_id"]).run_id
    return run_id, parse_iteration(match["iteration"]), match["name"], match["ext"]


# ── campaign mapping ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Experiment:
    campaign: str
    row: str
    slug: str
    phase: str
    title: str

    @property
    def key(self) -> str:
        return f"{self.campaign}-{self.row}"

    @property
    def dirname(self) -> str:
        return f"{self.key}-{self.slug}"


@dataclass(frozen=True)
class Campaign:
    campaign: str
    name: str
    title: str
    experiments: tuple[Experiment, ...]

    def experiment(self, row_or_key: str) -> Experiment:
        want = str(row_or_key).lower()
        for exp in self.experiments:
            if want in (exp.row, exp.key):
                return exp
        raise CampaignError(f"campaign {self.campaign!r} has no experiment {row_or_key!r}")


def campaign_config_path(campaign: str) -> Path:
    return config_dir() / "campaigns" / f"{campaign}.yaml"


def load_campaign(campaign: str) -> Campaign:
    """Load and validate ``config/campaigns/<campaign>.yaml``."""
    if not CAMPAIGN_RE.fullmatch(str(campaign or "")):
        raise CampaignError(f"campaign {campaign!r} must be lowercase letters and digits")
    path = campaign_config_path(campaign)
    if not path.is_file():
        raise CampaignError(f"unknown campaign {campaign!r}: no mapping at config/campaigns/{campaign}.yaml")
    return _load_campaign_text(path.read_text(encoding="utf-8"), str(path))


@lru_cache(maxsize=8)
def _load_campaign_text(text: str, where: str) -> Campaign:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, Mapping) or data.get("schema") != "sandbox.campaign/v1":
        raise CampaignError(f"{where}: schema must be sandbox.campaign/v1")
    cid = str(data.get("campaign") or "")
    if not CAMPAIGN_RE.fullmatch(cid):
        raise CampaignError(f"{where}: bad campaign id {cid!r}")
    rows: list[Experiment] = []
    seen: set[str] = set()
    for raw in data.get("experiments") or []:
        row, slug = str(raw.get("row") or ""), str(raw.get("slug") or "")
        if not ROW_RE.fullmatch(row) or not SLUG_RE.fullmatch(slug) or row in seen:
            raise CampaignError(f"{where}: bad or duplicate experiment row {raw!r}")
        seen.add(row)
        rows.append(Experiment(cid, row, slug, str(raw.get("phase") or ""), str(raw.get("title") or "")))
    return Campaign(cid, str(data.get("name") or cid), str(data.get("title") or cid), tuple(rows))


def experiment_for_run(run_id: str) -> tuple[Campaign, Experiment, RunKey]:
    key = parse_run_id(run_id)
    camp = load_campaign(key.campaign)
    return camp, camp.experiment(key.row), key


# ── paths API (for scripts writing into the tree) ───────────────────────────
def campaigns_root() -> Path:
    env = os.environ.get(ROOT_ENV, "").strip()
    return Path(env).expanduser() if env else repo_root() / "reports" / "campaigns"


@dataclass(frozen=True)
class ExperimentPaths:
    dir: Path
    key: str

    @property
    def analysis(self) -> Path:
        return self.dir / "analysis"

    @property
    def figures(self) -> Path:
        return self.dir / "figures"

    def file(self, name: str, ext: str, subdir: str | None = None) -> Path:
        """``<dir>[/<subdir>]/<key>.<name>.<ext>``."""
        base = self.dir / subdir if subdir else self.dir
        return base / f"{self.key}.{name}.{ext}"


@dataclass(frozen=True)
class RunPaths:
    """Where one run iteration's records live. Attributes are the seven subfolders."""

    key: RunKey
    experiment: ExperimentPaths
    root: Path

    @property
    def stem(self) -> str:
        return self.key.stem

    def __getattr__(self, name: str) -> Path:
        if name in SUBDIRS:
            return self.root / name
        raise AttributeError(name)

    def file(self, subdir: str, name: str, ext: str) -> Path:
        """``<root>/<subdir>/<run_id>-<iNN>.<name>.<ext>``."""
        if subdir not in SUBDIRS:
            raise CampaignError(f"subdir {subdir!r} not in {SUBDIRS}")
        return self.root / subdir / self.key.artifact(name, ext)

    def mkdirs(self) -> "RunPaths":
        for sub in SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        return self


def experiment_paths(key: str, *, root: Path | None = None) -> ExperimentPaths:
    campaign, _, row = str(key).partition("-")
    exp = load_campaign(campaign).experiment(row)
    base = (root or campaigns_root()) / exp.campaign / exp.dirname
    return ExperimentPaths(base, exp.key)


def campaign_paths(run_id: str, iteration: int | str | None = None, *, root: Path | None = None,
                   runs_dir: Path | None = None) -> RunPaths:
    """Tree paths for ``run_id``. ``iteration=None`` picks the store's latest (i01 without a store)."""
    _camp, exp, key = experiment_for_run(run_id)
    if iteration is None:
        store_dir = (runs_dir or default_runs_dir()) / run_id
        found = discover_iterations(store_dir, run_id) if store_dir.is_dir() else []
        number = found[-1].number if found else 1
    else:
        number = parse_iteration(iteration)
    key = RunKey(key.campaign, key.row, key.run_id, number)
    epaths = experiment_paths(exp.key, root=root)
    return RunPaths(key, epaths, epaths.dir / run_id / key.iteration_label)


def default_runs_dir() -> Path:
    return data_dir() / "runtime" / "runs"


# ── run-store reading (strictly read-only) ──────────────────────────────────
def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse JSONL, skipping a torn or bad line (never truncates the file)."""
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _logical(path: Path) -> str:
    """Machine-independent path: relative to the data dir as ``data/...`` or to the repo."""
    path = Path(path)
    for base, prefix in ((data_dir(), "data"), (repo_root(), "")):
        try:
            rel = path.resolve().relative_to(Path(base).resolve()).as_posix()
        except ValueError:
            continue
        return f"{prefix}/{rel}" if prefix else rel
    return f"<external>/{path.name}"


def _tree_rel(path: Path, root: Path | None) -> str:
    """``reports/campaigns/...`` style path for messages (relative to the campaigns root)."""
    base = root or campaigns_root()
    try:
        return "reports/campaigns/" + Path(path).relative_to(base).as_posix()
    except ValueError:
        return _logical(path)


@dataclass
class Generation:
    """One iteration: a locked generation's files (live store or an archive dir)."""

    number: int
    dir: Path
    run_id: str
    archived: bool
    run_store_dir: Path = field(default=Path("."))

    @property
    def label(self) -> str:
        return format_iteration(self.number)

    def path(self, name: str) -> Path:
        return self.dir / name

    @property
    def lock(self) -> dict[str, Any] | None:
        lock = _read_json(self.path("spec.lock.json"))
        return lock if isinstance(lock, dict) else None

    @property
    def checkpoint(self) -> dict[str, Any] | None:
        cp = _read_json(self.path("checkpoint.json"))
        return cp if isinstance(cp, dict) else None

    def events(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path("events.jsonl"))

    def items(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path("items.jsonl"))


def discover_iterations(store_dir: Path, run_id: str | None = None) -> list[Generation]:
    """Archived generations (oldest first) then the live store, numbered i01, i02, ..."""
    store_dir = Path(store_dir)
    run_id = run_id or store_dir.name
    found: list[tuple[Path, bool]] = []
    for archive in sorted(p for p in store_dir.glob("archive-*") if p.is_dir()):
        if (archive / "spec.lock.json").is_file() or (archive / "items.jsonl").is_file():
            found.append((archive, True))
    if (store_dir / "spec.lock.json").is_file():
        found.append((store_dir, False))
    return [Generation(i, d, run_id, archived, store_dir) for i, (d, archived) in enumerate(found, 1)]


class _ReadOnlyStore:
    """Duck-typed RunStore view over one generation for the existing renderers.

    It never creates directories and ``load_items`` never truncates a torn tail.
    """

    _FILES = {"lock_path": "spec.lock.json", "prompt_lock_path": "prompt.lock.json",
              "dataset_path": "dataset.jsonl", "items_path": "items.jsonl",
              "checkpoint_path": "checkpoint.json", "events_path": "events.jsonl",
              "nodes_path": "nodes.jsonl", "cold_boot_path": "cold_boot.json"}
    _READ_ONLY = ("dataset_rows", "dataset_sha256")

    def __init__(self, gen: Generation):
        from mailroom_sandbox.job.checkpoint import RunStore

        self._gen = gen
        self.dir = gen.dir
        self.run_id = gen.run_id
        for attr, name in self._FILES.items():
            setattr(self, attr, gen.dir / name)
        # A RunStore shell without __init__ (which would mkdir) for its pure dataset readers.
        self._rs = RunStore.__new__(RunStore)
        self._rs.__dict__.update({"dir": self.dir, "run_id": self.run_id,
                                  **{a: getattr(self, a) for a in self._FILES}})

    def events(self):
        return self._gen.events()

    def read_lock(self):
        return self._gen.lock

    def read_checkpoint(self):
        return self._gen.checkpoint

    def read_prompt_lock(self):
        return _read_json(self.prompt_lock_path)

    def read_cold_boot(self):
        return _read_json(self.cold_boot_path)

    def spec_hash(self):
        return (self._gen.lock or {}).get("spec_hash")

    def load_items(self):
        return self._gen.items()

    def __getattr__(self, name):
        # Only RunStore's pure dataset readers are delegated; every writer stays unreachable.
        if name in self._READ_ONLY:
            return getattr(self._rs, name)
        raise AttributeError(f"read-only store view has no {name}")


# ── builder ─────────────────────────────────────────────────────────────────
@dataclass
class BuildOptions:
    root: Path | None = None
    runs_dir: Path | None = None
    experiment_log: Path | None = None
    served_logs: tuple[Path, ...] = ()
    copy_cap: int = COPY_CAP_BYTES


def _dump_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n"


def _csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: _cell(row.get(c)) for c in columns})
    return buf.getvalue()


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return value


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _ref(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return {"path": _logical(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _experiment_log_record(gen: Generation, log_path: Path | None) -> dict[str, Any] | None:
    """The run's own experiment-log record for this generation (latest match), or None."""
    from mailroom_sandbox.job.evidence import record_matches

    lock = gen.lock
    if not lock or not log_path or not Path(log_path).is_file():
        return None
    state = (gen.checkpoint or {}).get("state") or "done"
    store = _ReadOnlyStore(gen)
    match = None
    for rec in _read_jsonl(Path(log_path)):
        if rec.get("run_id") not in (None, gen.run_id):
            continue
        try:
            if record_matches(rec, store, lock, state=state):
                match = rec
        except Exception:  # noqa: BLE001 - a malformed legacy record is not evidence
            continue
    return match


def _served_rows(gen: Generation, logs: Iterable[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lock = gen.lock or {}
    rows: list[dict[str, Any]] = []
    sources = []
    for path in sorted({Path(p) for p in logs if Path(p).is_file()}):
        sources.append(_ref(path))
        for row in _read_jsonl(path):
            if row.get("run_id") == gen.run_id and row.get("spec_hash") == lock.get("spec_hash"):
                rows.append(row)
    # Two generations can share a spec_hash: keep rows recorded inside this one's launch window
    # (second resolution; ledger stamps are ``YYYY-MM-DDTHH:MM:SSZ``, event stamps ISO-8601).
    window = _event_window(gen)
    if window and window[0]:
        lo, hi = window[0][:19], (window[1] or "")[:19]
        rows = [r for r in rows if not r.get("recorded_at")
                or (lo <= str(r["recorded_at"])[:19] and (not hi or str(r["recorded_at"])[:19] <= hi))]
    return rows, [s for s in sources if s]


def _event_window(gen: Generation) -> tuple[str | None, str | None] | None:
    events = gen.events()
    if not events:
        return None
    starts = [e.get("ts") for e in events if e.get("event") in ("start", "resume") and e.get("ts")]
    ends = [e.get("ts") for e in events if e.get("event") in ("done", "failed", "paused", "yielded",
                                                                "cost_cap_abort") and e.get("ts")]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _launches(gen: Generation) -> list[dict[str, Any]]:
    return [{"event": e.get("event"), "ts": e.get("ts")} for e in gen.events()
            if e.get("event") in ("start", "resume")]


def default_served_logs(key: RunKey) -> list[Path]:
    paths = sorted((data_dir() / "runtime" / key.experiment).glob("served-*.jsonl"))
    env = os.environ.get("SANDBOX_SERVED_LOG", "").strip()
    if env:
        paths.append(Path(env))
    return paths


def _serving_record(gen: Generation) -> tuple[dict[str, Any] | None, str | None]:
    from mailroom_sandbox.job import metrics

    try:
        return metrics.serving_record_from_store(_ReadOnlyStore(gen)), None  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - shown as a caveat, never as a number
        return None, f"serving record unavailable: {type(exc).__name__}: {str(exc)[:160]}"


def _pred_row(item: Mapping[str, Any]) -> dict[str, Any]:
    pred = item.get("pred") if isinstance(item.get("pred"), dict) else {}
    expected = item.get("expected")
    return {
        "item_id": item.get("item_id"),
        "index": item.get("index"),
        "ok": item.get("ok"),
        "expected": expected if not isinstance(expected, dict) else json.dumps(expected, sort_keys=True),
        "doc_type": pred.get("doc_type") if pred else (item.get("predicted") or item.get("pred")),
        "subclass": (pred.get("subclass") or pred.get("doc_subclass")) if pred else None,
        "stage": pred.get("stage") if pred else None,
        "latency_ms": item.get("latency_ms"),
        "prompt_tokens": item.get("prompt_tokens"),
        "completion_tokens": item.get("completion_tokens"),
        "error": item.get("error"),
    }


def _score_rows(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    keys: set[str] = set()
    rows = []
    for item in items:
        score = item.get("score") if isinstance(item.get("score"), dict) else {}
        flat = {k: v for k, v in score.items() if isinstance(v, (int, float, str, bool)) or v is None}
        keys.update(flat)
        rows.append({"item_id": item.get("item_id"), "ok": item.get("ok"), **flat})
    return rows, ["item_id", "ok", *sorted(keys)]


def _stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Stats layer on item rows that carry their own truth; a sanity read, not the headline."""
    from mailroom_sandbox import experiment_stats as st

    pairs = []
    for item in items:
        row = _pred_row(item)
        if isinstance(item.get("expected"), str) and row["doc_type"] and isinstance(row["doc_type"], str):
            pairs.append((item["expected"], row["doc_type"]))
    if not pairs:
        return {"applicable": False,
                "note": "items.jsonl rows carry no per-item truth; use the run scorer's scores in metrics.json"}
    truth, pred = [t for t, _ in pairs], [p for _, p in pairs]
    correct = [t == p for t, p in pairs]
    labels = sorted(set(truth) | set(pred))
    confusion = {t: {p: sum(1 for a, b in pairs if a == t and b == p) for p in labels} for t in labels}
    return {
        "applicable": True,
        "source": "mailroom_sandbox.experiment_stats on items.jsonl expected vs predicted doc_type",
        "n": len(pairs),
        "accuracy": sum(correct) / len(correct),
        "macro_f1": st.macro_f1(truth, pred),
        "brier_null_floor": st.brier_null_floor(correct),
        "labels": labels,
        "confusion": confusion,
        "paired_tests": "McNemar / paired permutation need two arms; see the experiment's analysis/",
    }


def _figures(stem: str, items: list[dict[str, Any]], scores: Mapping[str, Any] | None) -> tuple[dict[str, str], str | None]:
    """Deterministic SVG figures; returns ``{filename_suffix_name: svg_text}``."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        return {}, f"figures skipped: matplotlib unavailable ({type(exc).__name__})"
    out: dict[str, str] = {}
    with matplotlib.rc_context({"svg.hashsalt": stem, "svg.fonttype": "none", "font.size": 9}):
        lat = [float(i["latency_ms"]) / 1000.0 for i in items if isinstance(i.get("latency_ms"), (int, float))]
        if lat:
            fig, ax = plt.subplots(figsize=(5, 3))
            ax.hist(lat, bins=min(20, max(5, len(lat) // 2)), color="#4c72b0")
            ax.set_xlabel("latency per document (s)")
            ax.set_ylabel("documents")
            ax.set_title(f"{stem} latency")
            fig.tight_layout()
            buf = io.StringIO()
            fig.savefig(buf, format="svg", metadata={"Date": None, "Creator": None})
            plt.close(fig)
            out["latency"] = buf.getvalue()
        per_class = (((scores or {}).get("task") or {}).get("per_class")) if isinstance(scores, Mapping) else None
        if isinstance(per_class, Mapping) and per_class:
            names = sorted(per_class)
            vals = [float((per_class[n] or {}).get("f1") or 0.0) for n in names]
            fig, ax = plt.subplots(figsize=(5, 3))
            ax.barh(names, vals, color="#55a868")
            ax.set_xlim(0, 1)
            ax.set_xlabel("F1 (run scorer)")
            ax.set_title(f"{stem} per-class F1")
            fig.tight_layout()
            buf = io.StringIO()
            fig.savefig(buf, format="svg", metadata={"Date": None, "Creator": None})
            plt.close(fig)
            out["per-class-f1"] = buf.getvalue()
    return out, None


def _status(gen: Generation) -> str:
    return str((gen.checkpoint or {}).get("state") or ("prepared" if gen.lock else "unlocked"))


def _headline(scores: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(scores, Mapping):
        return {}
    keys = ("accuracy", "exact_match", "overall_extraction_score", "schema_valid_rate", "n", "error_count")
    head = {k: scores.get(k) for k in keys if scores.get(k) is not None}
    task = scores.get("task") if isinstance(scores.get("task"), Mapping) else {}
    for k in ("f1_macro", "doc_type_accuracy"):
        if task.get(k) is not None:
            head[k] = task[k]
    return head


def render_run(gen: Generation, paths: RunPaths, opts: BuildOptions) -> dict[str, str]:
    """All files for one iteration as ``{relative_path: text}`` (pure; nothing written)."""
    lock = gen.lock or {}
    stem = paths.stem
    files: dict[str, str] = {}
    cp = gen.checkpoint or {}
    items = gen.items()
    job = lock.get("job") if isinstance(lock.get("job"), dict) else {}
    mock = bool(job.get("mock")) or (lock.get("engine") or {}).get("kind") == "replay" or "replay" in lock
    caveats: list[str] = []
    if mock:
        caveats.append("MOCK or replay run: simulated output, never cite its scores, tokens or cost as evidence.")
    if gen.archived:
        caveats.append(f"Archived generation ({gen.dir.name}): superseded by a forced re-lock of the same run_id.")
    status = _status(gen)
    if status != "done":
        caveats.append(f"Run state is `{status}`, not `done`: results are partial.")
    failed = sum(1 for i in items if i.get("ok") is False)
    if failed:
        caveats.append(f"{failed} of {len(items)} documents failed (ok=false); they are in outputs/ with their error.")

    def rel(sub: str, name: str, ext: str) -> str:
        return f"{sub}/{paths.key.artifact(name, ext)}"

    # logs/
    log_refs: dict[str, Any] = {}
    for name, src in (("spec-lock", "spec.lock.json"), ("checkpoint", "checkpoint.json"),
                      ("prompt-lock", "prompt.lock.json"), ("events", "events.jsonl")):
        path = gen.path(src)
        if not path.is_file():
            continue
        ext = "jsonl" if src.endswith(".jsonl") else "json"
        if path.stat().st_size <= opts.copy_cap:
            files[rel("logs" if name != "prompt-lock" else "docs", name, ext)] = path.read_text(encoding="utf-8")
        else:
            log_refs[name] = _ref(path)
    nodes = _read_jsonl(gen.path("nodes.jsonl"))
    if nodes:
        counts: dict[str, dict[str, int]] = {}
        for row in nodes:
            node = str(row.get("node"))
            st = str(row.get("status"))
            counts.setdefault(node, {}).setdefault(st, 0)
            counts[node][st] += 1
        files[rel("logs", "nodes-digest", "json")] = _dump_json(
            {"source": _ref(gen.path("nodes.jsonl")), "rows": len(nodes), "by_node_status": counts})
    spend = _read_json(gen.run_store_dir / "spend-authorization.json") if not gen.archived else None
    if isinstance(spend, dict) and spend.get("generation_id") in (None, lock.get("generation_id")):
        files[rel("logs", "spend-authorization", "json")] = _dump_json({
            "source": _ref(gen.run_store_dir / "spend-authorization.json"),
            "signed": bool(spend.get("initials")),
            "signed_at": spend.get("signed_at"),
            "budget": spend.get("budget"),
            "generation_id": spend.get("generation_id"),
            "fingerprint": spend.get("fingerprint"),
            "note": "digest only; the signer's initials stay in the run store",
        })
    served, served_sources = _served_rows(gen, opts.served_logs or default_served_logs(paths.key))
    served_digest: dict[str, Any] = {"sources": served_sources, "rows": len(served)}
    if served:
        by: dict[str, int] = {}
        for row in served:
            k = f"{row.get('requested_model')} | {row.get('served_model')} | {row.get('served_provider')} | {row.get('status')}"
            by[k] = by.get(k, 0) + 1
        served_digest["by_requested_served_provider_status"] = dict(sorted(by.items()))
        served_digest["mismatch_rows"] = sum(1 for r in served if r.get("mismatch"))
    else:
        caveats.append("No served-provider ledger rows for this generation (SANDBOX_SERVED_LOG unset or not found).")
    files[rel("logs", "served-digest", "json")] = _dump_json(served_digest)
    if log_refs:
        files[rel("logs", "large-logs", "json")] = _dump_json(log_refs)

    # traces/
    trace_refs: dict[str, Any] = {}
    items_path = gen.path("items.jsonl")
    if items_path.is_file():
        if items_path.stat().st_size <= opts.copy_cap:
            files[rel("traces", "items", "jsonl")] = items_path.read_text(encoding="utf-8")
        else:
            trace_refs["items"] = _ref(items_path)
    for name, src in (("nodes", gen.path("nodes.jsonl")), ("dataset", gen.path("dataset.jsonl"))):
        if src.is_file():
            trace_refs[name] = _ref(src)
    from mailroom_sandbox.job.otel import local_trace_path

    spans = local_trace_path(gen.run_id) if not gen.archived else None
    if spans is not None and spans.is_file():
        trace_refs["spans"] = _ref(spans)
    for pack in sorted((data_dir() / "runtime" / "exports").glob(f"*/*_{gen.run_id}.zip")) if not gen.archived else []:
        trace_refs[f"trace-pack:{pack.parent.name}"] = _ref(pack)
    files[rel("traces", "traces", "json")] = _dump_json({
        "copy_cap_bytes": opts.copy_cap,
        "note": "files over the cap (and every dataset, span mirror and trace pack) are referenced by path + sha256, not copied",
        "references": trace_refs,
    })

    # outputs/
    files[rel("outputs", "predictions", "csv")] = _csv(
        [_pred_row(i) for i in items],
        ["item_id", "index", "ok", "expected", "doc_type", "subclass", "stage", "latency_ms",
         "prompt_tokens", "completion_tokens", "error"])
    score_rows, score_cols = _score_rows(items)
    files[rel("outputs", "item-scores", "csv")] = _csv(score_rows, score_cols)

    # analysis/
    record = _experiment_log_record(gen, opts.experiment_log)
    scores = record.get("scores") if isinstance(record, dict) else None
    if record is None:
        caveats.append("No experiment-log record matches this generation: headline scores are not recorded "
                       "(never recomputed here).")
    serving, serving_err = _serving_record(gen) if items else (None, "no items.jsonl rows")
    if serving_err:
        caveats.append(serving_err)
    elif serving and serving.get("cost_basis"):
        caveats.append(f"Cost basis is `{serving.get('cost_basis')}` (from the serving renderer), not a provider invoice.")
    metrics_doc = {
        "scores": scores,
        "scores_source": "experiment log record matched to this generation" if record else None,
        "serving": serving,
        "serving_source": "mailroom_sandbox.job.metrics.serving_record_from_store" if serving else None,
    }
    files[rel("analysis", "metrics", "json")] = _dump_json(metrics_doc)
    stats = _stats(items)
    files[rel("analysis", "stats", "json")] = _dump_json(stats)
    if stats.get("applicable"):
        labels = stats["labels"]
        files[rel("analysis", "confusion", "csv")] = _csv(
            [{"truth": t, **stats["confusion"][t]} for t in labels], ["truth", *labels])

    # figures/
    figs, fig_err = _figures(stem, items, scores)
    for name, svg in figs.items():
        files[rel("figures", name, "svg")] = svg
    if fig_err:
        caveats.append(fig_err)

    # docs/
    config_path = config_dir() / "runs" / f"{gen.run_id}.yaml"
    config_ref = _ref(config_path)
    if config_ref:
        files[rel("docs", "config", "yaml")] = config_path.read_text(encoding="utf-8")
        caveats.append("docs/ config is the committed config today; the spec lock in logs/ is authoritative.")
    if lock.get("spec_core") is not None:
        files[rel("docs", "spec-core", "json")] = _dump_json(lock.get("spec_core"))
    files[rel("docs", "caveats", "md")] = "\n".join(
        [f"# Caveats — `{stem}`", "", *(f"- {c}" for c in caveats or ["None recorded."]), ""])

    # report/
    from mailroom_sandbox.job.checkpoint import generation_identity

    window = _event_window(gen) or (None, None)
    identity = generation_identity(lock) if lock else {}
    engine = lock.get("engine") if isinstance(lock.get("engine"), dict) else {}
    report = {
        "schema": "sandbox.campaign-run-report/v1",
        "campaign": paths.key.campaign,
        "experiment": paths.key.experiment,
        "run_id": gen.run_id,
        "iteration": paths.key.iteration_label,
        "status": status,
        "mock": mock,
        "archived": gen.archived,
        "task": lock.get("task"),
        "profile": lock.get("profile"),
        "model": engine.get("model"),
        "spec_hash": lock.get("spec_hash"),
        "generation_id": lock.get("generation_id"),
        "lock_sha256": identity.get("lock_sha256"),
        "dataset": {k: (lock.get("dataset") or {}).get(k) for k in ("repo", "revision", "config", "split", "limit", "sha256")},
        "dependency_sources": lock.get("dependency_sources"),
        "git": lock.get("git"),
        "started": window[0],
        "finished": window[1],
        "launches": _launches(gen),
        "items": {"total": len(items), "ok": sum(1 for i in items if i.get("ok") is not False), "failed": failed},
        "checkpoint": {k: cp.get(k) for k in ("state", "cursor", "total", "last_error")},
        "headline": _headline(scores),
        "headline_source": "experiment log" if record else None,
        "cost": {k: (serving or {}).get(k) for k in ("estimated_cost_usd", "cost_per_document", "cost_basis",
                                                   "wall_seconds", "prompt_tokens", "completion_tokens")},
        "caveats": caveats,
        "config": config_ref,
    }
    files[rel("report", "report", "json")] = _dump_json(report)
    files[rel("report", "report", "md")] = _render_report_md(report, paths)
    files["README.md"] = _render_run_readme(report, paths, sorted(files))
    manifest = {"schema": "sandbox.campaign-manifest/v1", "stem": stem,
                "files": {p: hashlib.sha256(t.encode("utf-8")).hexdigest() for p, t in sorted(files.items())}}
    files[f"{stem}.manifest.json"] = _dump_json(manifest)
    return files


def _render_report_md(report: Mapping[str, Any], paths: RunPaths) -> str:
    head = report.get("headline") or {}
    cost = report.get("cost") or {}
    lines = [f"# Run report — `{paths.stem}`", ""]
    if report.get("mock"):
        lines += ["> **MOCK / replay run. Simulated output; not evidence.**", ""]
    lines += [
        "| | |", "| --- | --- |",
        f"| campaign / experiment | `{report['campaign']}` / `{report['experiment']}` |",
        f"| run_id / iteration | `{report['run_id']}` / `{report['iteration']}` |",
        f"| status | **{report['status']}** |",
        f"| task / model | `{report.get('task')}` / `{report.get('model')}` |",
        f"| spec_hash | `{report.get('spec_hash')}` |",
        f"| started → finished | {_fmt(report.get('started'))} → {_fmt(report.get('finished'))} |",
        f"| documents ok / failed / total | {report['items']['ok']} / {report['items']['failed']} / {report['items']['total']} |",
        "", "## Headline (run scorer, from the experiment log)", "",
    ]
    if head:
        lines += ["| metric | value |", "| --- | --- |", *(f"| {k} | {_fmt(v)} |" for k, v in sorted(head.items()))]
    else:
        lines.append("Not recorded: no experiment-log record matches this generation. Nothing is recomputed here.")
    lines += ["", "## Cost and serving (serving renderer)", "", "| metric | value |", "| --- | --- |",
              *(f"| {k} | {_fmt(v, 6)} |" for k, v in cost.items()), "", "## Caveats", "",
              *(f"- {c}" for c in report.get("caveats") or ["None recorded."]), ""]
    return "\n".join(lines)


_SUB_HELP = {
    "logs": "spec lock, checkpoint, events, node and served-ledger digests, spend authorization digest",
    "traces": "item rows (size-capped) and path + sha256 references to large raw data",
    "outputs": "per-document predictions and per-item scores (CSV)",
    "report": "this run's report (md + json)",
    "analysis": "metrics (run scorer + serving), stats layer, confusion matrix",
    "figures": "SVG figures",
    "docs": "config copy, spec core, prompt lock, caveats; gate results (`<stem>.<gate>-gate.json`)",
}


def _render_run_readme(report: Mapping[str, Any], paths: RunPaths, names: list[str]) -> str:
    deps = report.get("dependency_sources") or {}
    ds = report.get("dataset") or {}
    launches = ", ".join(f"{x.get('event')} {x.get('ts')}" for x in report.get("launches") or []) or "—"
    lines = [
        f"# `{paths.stem}`", "",
        f"Campaign `{report['campaign']}`, experiment `{report['experiment']}`, run `{report['run_id']}`, "
        f"iteration `{report['iteration']}`. Generated by `sandbox report build --run {report['run_id']}` "
        "from the run logs; do not edit by hand.", "",
    ]
    if report.get("mock"):
        lines += ["> **MOCK / replay run. Simulated output; not evidence.**", ""]
    lines += [
        "## How to read this run", "",
        f"1. Start with [report/{paths.key.artifact('report', 'md')}](report/{paths.key.artifact('report', 'md')}).",
        f"2. Check [docs/{paths.key.artifact('caveats', 'md')}](docs/{paths.key.artifact('caveats', 'md')}) before quoting a number.",
        "3. Per-document rows are in `outputs/`; the locked inputs are in `logs/`.", "",
        "| | |", "| --- | --- |",
        f"| status | **{report['status']}** |",
        f"| config | `{(report.get('config') or {}).get('path') or 'not committed'}` |",
        f"| spec_hash | `{report.get('spec_hash')}` |",
        f"| generation_id | `{report.get('generation_id')}` |",
        f"| lock sha256 | `{report.get('lock_sha256')}` |",
        f"| dataset | `{ds.get('repo')}` @ `{ds.get('revision')}` ({ds.get('config')}/{ds.get('split')}, limit {ds.get('limit')}) sha256 `{ds.get('sha256')}` |",
        f"| git | `{json.dumps(report.get('git'), sort_keys=True) if report.get('git') else '—'}` |",
        f"| launches | {launches} |",
        "", "## dependency_sources", "", "| dependency | source | version | commit | tree sha256 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name in sorted(deps):
        d = deps[name] or {}
        lines.append(f"| {name} | {d.get('source')} | {d.get('version')} | `{d.get('commit')}` | `{d.get('tree_sha256')}` |")
    if not deps:
        lines.append("| — | not recorded in the lock | | | |")
    lines += ["", "## Where everything is", "", "| folder | holds | files |", "| --- | --- | --- |"]
    for sub in SUBDIRS:
        own = [n.split("/", 1)[1] for n in names if n.startswith(sub + "/")]
        lines.append(f"| `{sub}/` | {_SUB_HELP[sub]} | {', '.join(f'[{n}]({sub}/{n})' for n in own) or '—'} |")
    lines.append("")
    return "\n".join(lines)


def _write_owned(dest: Path, files: Mapping[str, str], *, check: bool, manifest_name: str) -> list[str]:
    """Write (or, with check, compare) owned files; remove files the old manifest owned. Returns stale paths."""
    stale: list[str] = []
    old = _read_json(dest / manifest_name)
    old_owned = set((old or {}).get("files") or {}) if isinstance(old, dict) else set()
    for relpath, text in sorted(files.items()):
        path = dest / relpath
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != text:
            stale.append(relpath)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    for relpath in sorted(old_owned - set(files)):
        path = dest / relpath
        if path.is_file():
            stale.append(relpath)
            if not check:
                path.unlink()
    if not check:
        for sub in SUBDIRS:
            (dest / sub).mkdir(parents=True, exist_ok=True)
    return stale


def build_run(run_id: str, iteration: int | str | None = None, *, check: bool = False,
              opts: BuildOptions | None = None) -> dict[str, Any]:
    """Build (or check) every iteration of ``run_id`` (or just one), then refresh the indexes."""
    opts = opts or BuildOptions()
    if opts.experiment_log is None:
        from mailroom_sandbox.eval.experiment_log import jsonl_path

        opts.experiment_log = jsonl_path()
    camp, _exp, _key = experiment_for_run(run_id)
    store_dir = (opts.runs_dir or default_runs_dir()) / run_id
    gens = discover_iterations(store_dir, run_id) if store_dir.is_dir() else []
    if not gens:
        raise CampaignError(f"run {run_id!r} has no locked generation under {store_dir}")
    if iteration is not None:
        want = parse_iteration(iteration)
        gens = [g for g in gens if g.number == want]
        if not gens:
            raise CampaignError(f"run {run_id!r} has no iteration {format_iteration(want)}")
    result: dict[str, Any] = {"run_id": run_id, "iterations": [], "stale": []}
    for gen in gens:
        paths = campaign_paths(run_id, gen.number, root=opts.root)
        files = render_run(gen, paths, opts)
        stale = _write_owned(paths.root, files, check=check, manifest_name=f"{paths.stem}.manifest.json")
        where = _tree_rel(paths.root, opts.root)
        result["iterations"].append({"iteration": gen.label, "path": where, "files": len(files)})
        result["stale"] += [f"{where}/{p}" for p in stale]
    idx = build_campaign(camp.campaign, check=check, root=opts.root)
    result["stale"] += idx["stale"]
    return result


# ── indexes ─────────────────────────────────────────────────────────────────
def _iteration_reports(exp_dir: Path) -> list[dict[str, Any]]:
    reports = []
    for path in sorted(exp_dir.glob("*/i*/report/*.report.json")):
        data = _read_json(path)
        if isinstance(data, dict) and data.get("schema") == "sandbox.campaign-run-report/v1":
            data = dict(data)
            data["_dir"] = path.parent.parent
            reports.append(data)
    return reports


def _gate_files(exp_dir: Path) -> list[tuple[str, Path, Any]]:
    out = []
    for path in sorted(exp_dir.rglob("*-gate.json")):
        data = _read_json(path)
        ok = data.get("ok") if isinstance(data, dict) else None
        out.append((path.relative_to(exp_dir).as_posix(), path, ok))
    return out


def _configs_for(exp: Experiment) -> list[Path]:
    return sorted((config_dir() / "runs").glob(f"{exp.key}-*.yaml"))


def _other_records(exp_dir: Path) -> list[str]:
    """Experiment-level files (sheets, digests, comparisons) outside the run folders."""
    out: list[str] = []
    for folder in (exp_dir, exp_dir / "analysis", exp_dir / "figures"):
        if folder.is_dir():
            out += [p.relative_to(exp_dir).as_posix() for p in sorted(folder.iterdir())
                    if p.is_file() and p.name != "README.md" and not p.name.endswith("-gate.json")]
    return out


def _experiment_status(exp: Experiment, reports: list[dict[str, Any]], configs: list[Path],
                       gates: list[tuple[str, Path, Any]], exp_dir: Path | None = None) -> str:
    if reports:
        states: dict[str, int] = {}
        for r in reports:
            states[str(r.get("status"))] = states.get(str(r.get("status")), 0) + 1
        return ", ".join(f"{n} {s}" for s, n in sorted(states.items()))
    if gates:
        oks = [ok for _n, _p, ok in gates]
        return "gate passed" if all(ok is True for ok in oks) else "gate not passed"
    if configs:
        return f"{len(configs)} config(s), no runs built"
    if exp_dir is not None and _other_records(exp_dir):
        return "records only (no runs)"
    return "no runs"


def _render_experiment_readme(camp: Campaign, exp: Experiment, exp_dir: Path, reports: list[dict[str, Any]],
                              configs: list[Path], gates: list[tuple[str, Path, Any]]) -> str:
    lines = [
        f"# `{exp.key}` — {exp.title}", "",
        f"Campaign [`{camp.campaign}`](../README.md) ({camp.name}), phase {exp.phase}. "
        "Generated by `sandbox report build`; do not edit by hand.", "",
        f"Status: **{_experiment_status(exp, reports, configs, gates, exp_dir)}**", "",
        "## Configs", "",
    ]
    lines += [f"- `{_logical(c)}`" for c in configs] or ["- none committed"]
    lines += ["", "## Runs", ""]
    if reports:
        lines += ["| run_id | iteration | status | n ok/total | headline | started | link |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in reports:
            rel = r["_dir"].relative_to(exp_dir).as_posix()
            head = r.get("headline") or {}
            head_txt = ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(head.items()) if k != "n") or "not recorded"
            mock = " (MOCK)" if r.get("mock") else ""
            lines.append(f"| `{r['run_id']}` | {r['iteration']} | {r['status']}{mock} | "
                         f"{r['items']['ok']}/{r['items']['total']} | {head_txt} | {_fmt(r.get('started'))} | "
                         f"[{rel}]({rel}/README.md) |")
    else:
        lines.append("No run iterations built yet.")
    if gates:
        lines += ["", "## Gate results", "", "| file | ok |", "| --- | --- |"]
        lines += [f"| [{name}]({name}) | {ok} |" for name, _p, ok in gates]
    others = _other_records(exp_dir)
    if others:
        lines += ["", "## Other records in this folder", ""] + [f"- [{n}]({n})" for n in others]
    lines.append("")
    return "\n".join(lines)


def build_campaign(campaign: str, *, check: bool = False, root: Path | None = None) -> dict[str, Any]:
    """Rebuild ``README.md`` + ``index.jsonl`` for a campaign and each experiment folder that exists.

    Reads only the built tree and committed configs, so it runs without any run store.
    """
    camp = load_campaign(campaign)
    base = (root or campaigns_root()) / camp.campaign
    files: dict[str, str] = {}
    index_rows: list[dict[str, Any]] = []
    table: list[str] = []
    for exp in camp.experiments:
        exp_dir = base / exp.dirname
        configs = _configs_for(exp)
        reports = _iteration_reports(exp_dir) if exp_dir.is_dir() else []
        gates = _gate_files(exp_dir) if exp_dir.is_dir() else []
        if exp_dir.is_dir() or configs:
            files[f"{exp.dirname}/README.md"] = _render_experiment_readme(camp, exp, exp_dir, reports, configs, gates)
            link = f"[{exp.dirname}]({exp.dirname}/README.md)"
        else:
            link = f"`{exp.dirname}`"
        for r in reports:
            index_rows.append({
                "campaign": camp.campaign, "experiment": exp.key, "run_id": r["run_id"],
                "iteration": r["iteration"], "path": r["_dir"].relative_to(base).as_posix(),
                "status": r.get("status"), "spec_hash": r.get("spec_hash"),
                "started": r.get("started"), "finished": r.get("finished"),
            })
        table.append(f"| {exp.phase} | `{exp.key}` | {exp.title} | {_experiment_status(exp, reports, configs, gates, exp_dir)} | {link} |")
    files["README.md"] = "\n".join([
        f"# Campaign `{camp.campaign}` — {camp.name}", "",
        f"{camp.title}. Campaign ID `{camp.campaign}` (full name `{camp.name}`); mapping in "
        f"`config/campaigns/{camp.campaign}.yaml`. Generated by `sandbox report build --campaign {camp.campaign}`; "
        "do not edit by hand. Naming grammar: [../README.md](../README.md).", "",
        "Machine-readable index: [index.jsonl](index.jsonl) (one row per run iteration).", "",
        "| phase | key | experiment | status | folder |", "| --- | --- | --- | --- | --- |", *table, "",
    ])
    files["index.jsonl"] = "".join(json.dumps(r, sort_keys=True) + "\n" for r in index_rows)
    stale = []
    for relpath, text in sorted(files.items()):
        path = base / relpath
        if (path.read_text(encoding="utf-8") if path.is_file() else None) != text:
            stale.append(_tree_rel(path, root))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    return {"campaign": camp.campaign, "files": len(files), "stale": stale}


# ── runner hook ─────────────────────────────────────────────────────────────
def _skip_lock(lock: Mapping[str, Any]) -> bool:
    """The hook files real runs only; mock runs are built on request with ``sandbox report build``."""
    return bool((lock.get("job") or {}).get("mock"))


def maybe_build_campaign_reports(store: Any) -> dict[str, Any] | None:
    """Runner hook: build the finished run's tree. Best-effort; never raises.

    Skips run_ids outside the campaign grammar, mock runs, and ``SANDBOX_CAMPAIGN_REPORTS=0``.
    """
    try:
        if os.environ.get(DISABLE_ENV, "1").strip().lower() in ("0", "false", "no", "off"):
            return None
        run_id = str(getattr(store, "run_id", "") or "")
        try:
            experiment_for_run(run_id)
        except CampaignError:
            return None
        if _skip_lock(store.read_lock() or {}):
            return None
        return build_run(run_id, opts=BuildOptions(runs_dir=Path(store.dir).parent))
    except Exception:  # noqa: BLE001 - a report failure must never fail or alter the run
        _log.warning("campaign report build failed for %s", getattr(store, "run_id", "?"), exc_info=True)
        return None


def copy_into(paths: RunPaths, subdir: str, name: str, src: Path) -> Path:
    """Copy ``src`` into the tree as ``<subdir>/<stem>.<name>.<src ext>`` (for gate scripts)."""
    dest = paths.file(subdir, name, src.suffix.lstrip(".") or "txt")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest
