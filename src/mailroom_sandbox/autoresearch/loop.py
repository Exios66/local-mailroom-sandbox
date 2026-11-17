"""The autoresearch loop: a greedy, config-only search over the lever catalog.

One champion run spec. Each round diagnoses the champion (a weakness table charging lost utility to
node x class), proposes the first untried lever attached to the worst node, runs champion + that ONE
lever on the same frozen draw, scores per-document utility, compares it with the champion by a
stratified paired bootstrap, and keeps or reverts. An append-only ledger records every round. The
loop changes no pipeline code and drives the existing locked-run lifecycle through an ``Executor``.
It stops on budget, on an exhausted catalog, or after N consecutive reverts.

After the baseline the loop runs the identical champion spec once more (``replicate``). The paired difference
between the two baseline runs is the measured noise: the study's effective noise floor is the larger of the
configured ``noise_floor``, the absolute mean difference and the interval's half-width, and no lever may be kept
before the replicate exists. A round the run's own API cap aborts is ``aborted_cap``: not a revert, charged its
full cap.

State, under ``reports/autoresearch/<study>/`` (or ``state_dir``):

``.lock``          an advisory ``flock`` held for the whole of ``step``, ``run`` and ``holdout``: a second process is refused
``ledger.jsonl``   one JSON row per round (and per skipped lever); the loop resumes from it. A paid run is preceded by a
                   ``pending`` row that reserves its cap (counted in the spend until a final row for the same run id)
``key_start.json`` the OpenRouter key's first ``limit_remaining`` reading of the study (the bill-grounded spend guard)
``champion.yaml``  a convenience copy of the current champion's run spec (written before its ledger row; never read back)
``specs/``         every candidate spec that was run (``<run_id>.yaml``); the champion is loaded from here and checked
                   against the ledger row's ``spec_sha256``
``scores/``        per-document utility and cost of every run (``<run_id>.json``)
``weakness.md``    the champion's weakness table
``report.md``      the study report, with a production-parity section
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mailroom_sandbox.autoresearch import diagnose, estimate, keep, levers as lv, scoring
from mailroom_sandbox.paths import repo_root

SCHEMA = "sandbox.autoresearch/v1"
DECIDED = ("keep", "revert", "error", "aborted_cap")


class AutoresearchError(RuntimeError):
    """An operator-facing refusal (missing initials, a bad study file, a draw that overlaps)."""


class LedgerCorruptError(AutoresearchError):
    """A ledger row whose cost cannot be summed (non-finite or not a number): the study stops rather than guess."""


class ExecutionError(AutoresearchError):
    """A candidate run that did not finish; ``run_id`` names its (possibly partial) run directory."""

    def __init__(self, message: str, run_id: str | None = None):
        super().__init__(message)
        self.run_id = run_id


# ---- the study file ----------------------------------------------------------------------------------

class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_usd: float = Field(gt=0, allow_inf_nan=False)
    round_api_cap_usd: float = Field(gt=0, allow_inf_nan=False)
    round_wall_seconds: int = Field(ge=60)
    min_key_remaining_usd: float = Field(default=3.0, ge=0, allow_inf_nan=False)
    # The ceiling for a lever's own round cap (supervisor levers derive theirs from the runtime-bound estimate).
    max_round_cap_usd: float = Field(default=4.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _caps(self) -> "Budget":
        if self.max_round_cap_usd < self.round_api_cap_usd:
            raise ValueError("max_round_cap_usd must be at least round_api_cap_usd")
        return self


class Bootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_boot: int = Field(default=2000, ge=1)
    seed: int = 0
    ci: float = Field(default=0.90, gt=0, lt=1)


class Study(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: str = Field(default=SCHEMA, alias="schema")
    study: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    base_run: str
    levers: str
    budget: Budget
    noise_floor: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    max_consecutive_reverts: int = Field(default=3, ge=1)
    utility: scoring.UtilityWeights = Field(default_factory=scoring.UtilityWeights)
    bootstrap: Bootstrap = Field(default_factory=Bootstrap)
    guard_classes: list[str] | None = None
    estimate_safety: float = Field(default=1.0, ge=0.5, le=10, allow_inf_nan=False)
    cost_goal_tolerance: float = Field(default=0.02, ge=0)
    # Fields that replace the dev draw's dataset fields for the holdout. The holdout always excludes the
    # production list plus every dev document (generated file), so ``{}`` draws the next ranked block.
    holdout_dataset: dict[str, Any] = Field(default_factory=dict)
    state_dir: str | None = None

    _path: Path | None = None
    _mock: bool | None = None

    @field_validator("holdout_dataset")
    @classmethod
    def _holdout_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Only real ``DatasetSpec`` fields: a typo (``sample_sed``) must fail at load, not silently draw the dev block."""
        from mailroom_sandbox.job.spec import DatasetSpec

        unknown = sorted(set(value) - set(DatasetSpec.model_fields))
        if unknown:
            raise ValueError(f"holdout_dataset has unknown dataset field(s) {unknown}; "
                             f"valid fields are {sorted(DatasetSpec.model_fields)}")
        if "exclude_ids_file" in value:
            raise ValueError("holdout_dataset.exclude_ids_file is generated by the holdout (production list + dev ids)")
        return value

    @classmethod
    def load(cls, path: str | Path) -> "Study":
        path = Path(path)
        try:
            study = cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        except (ValueError, yaml.YAMLError) as exc:
            raise AutoresearchError(f"{path}: {exc}") from exc
        if study.schema_name != SCHEMA:
            raise AutoresearchError(f"{path}: unsupported study schema {study.schema_name!r}")
        study._path = path.resolve()
        return study

    def _resolve(self, name: str) -> Path:
        path = Path(name).expanduser()
        if path.is_absolute() or self._path is None:
            return path
        return (self._path.parent / path).resolve()

    @property
    def base_path(self) -> Path:
        return self._resolve(self.base_run)

    @property
    def levers_path(self) -> Path:
        return self._resolve(self.levers)

    @property
    def state_path(self) -> Path:
        if self.state_dir:
            return self._resolve(self.state_dir)       # relative to the study file, like every other path here
        return repo_root() / "reports" / "autoresearch" / self.study

    def base_spec(self) -> dict[str, Any]:
        return yaml.safe_load(self.base_path.read_text(encoding="utf-8")) or {}

    @property
    def mock(self) -> bool:
        """The base run's ``job.mock`` as the validated ``RunSpec`` reads it (never the truthiness of the raw YAML:
        ``mock: "false"`` is a paid run)."""
        if self._mock is None:
            self._mock = bool(lv.validate_spec(self.base_spec(), where="base run spec").job.mock)
        return self._mock


# ---- executors ---------------------------------------------------------------------------------------

class Executor(Protocol):
    """Runs one locked spec file and returns its run directory. ``env`` overrides the process environment."""

    def execute(self, spec_path: Path, *, env: Mapping[str, str] | None = None) -> Path: ...


_OPENROUTER_KEY = re.compile(r"sk-or-[A-Za-z0-9_-]+")
_BEARER = re.compile(r"(?i)bearer\s+\S+")


def scrub(text: str, env: Mapping[str, str] | None = None) -> str:
    """``text`` without the OpenRouter key, any ``sk-or-...`` token or any bearer token that a tool echoed.

    Scrub the WHOLE text, then truncate: a secret that straddles a cut would otherwise survive as a partial.
    """
    key = (os.environ if env is None else env).get("OPENROUTER_API_KEY", "").strip()
    if len(key) >= 6:
        text = text.replace(key, "[redacted]")
    text = _OPENROUTER_KEY.sub("[redacted]", text)
    return _BEARER.sub("Bearer [redacted]", text)


def scrub_tail(text: str, limit: int, env: Mapping[str, str] | None = None) -> str:
    """The last ``limit`` characters of ``text`` after scrubbing all of it (never slice first)."""
    return scrub(text, env)[-limit:]


def scrub_head(text: str, limit: int, env: Mapping[str, str] | None = None) -> str:
    """The first ``limit`` characters of ``text`` after scrubbing all of it (never slice first)."""
    return scrub(text, env)[:limit]


class CliExecutor:
    """The real executor: ``sandbox run preflight`` then ``sandbox run start`` in a child process.

    A paid spec needs ``initials`` (supplied by a human on the command line, never defaulted or invented);
    a mock spec needs none. ``prepare`` runs the preflight alone, which locks the draw and calls no model.
    """

    def __init__(self, *, initials: str | None = None, runner: Callable[..., Any] = subprocess.run,
                 python: str | None = None, timeout_margin: int = 900):
        self.initials = (initials or "").strip().upper() or None
        if self.initials and not re.fullmatch(r"[A-Z]{2,6}", self.initials):
            raise AutoresearchError("initials must be 2-6 letters")
        self._run, self._python, self._margin = runner, python or sys.executable, timeout_margin
        self._prepared: set[str] = set()

    @staticmethod
    def _spec(spec_path: Path) -> dict[str, Any]:
        return yaml.safe_load(Path(spec_path).read_text(encoding="utf-8")) or {}

    def _invoke(self, args: list[str], *, env: Mapping[str, str] | None, timeout: int, run_id: str) -> None:
        merged = {**os.environ, **(env or {})}
        try:
            done = self._run([self._python, "-m", "mailroom_sandbox", *args], cwd=str(repo_root()), env=merged,
                             capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ExecutionError(f"`sandbox {' '.join(args[:2])}` timed out after {timeout}s", run_id) from exc
        if done.returncode != 0:
            tail = scrub_tail((done.stdout or "") + (done.stderr or ""), 1500, merged)
            raise ExecutionError(f"`sandbox {' '.join(args[:2])}` exited {done.returncode}: {tail}", run_id)

    def _check(self, spec: Mapping[str, Any]) -> tuple[str, bool]:
        mock = bool(lv.validate_spec(spec, where="run spec").job.mock)   # the validated value, not raw YAML truthiness
        if not mock and not self.initials:
            raise AutoresearchError("a paid run needs --initials XX (2-6 letters, yours; they are never defaulted)")
        return str(spec.get("run_id") or ""), mock

    def prepare(self, spec_path: Path, *, env: Mapping[str, str] | None = None) -> Path:
        from mailroom_sandbox.job.spec import run_dir

        spec = self._spec(spec_path)
        run_id, _ = self._check(spec)
        self._invoke(["run", "preflight", "--config", str(spec_path)], env=env, timeout=1800, run_id=run_id)
        self._prepared.add(run_id)
        return run_dir(run_id)

    def execute(self, spec_path: Path, *, env: Mapping[str, str] | None = None) -> Path:
        from mailroom_sandbox.job.spec import run_dir

        spec = self._spec(spec_path)
        run_id, mock = self._check(spec)
        if run_id not in self._prepared:
            self.prepare(spec_path, env=env)
        wall = int((spec.get("job") or {}).get("max_wall_seconds") or 3600)
        args = ["run", "start", "--config", str(spec_path)] + ([] if mock else ["--initials", str(self.initials)])
        self._invoke(args, env=env, timeout=wall + self._margin, run_id=run_id)
        return run_dir(run_id)


def openrouter_key_remaining() -> float | None:
    """The OpenRouter key's remaining limit in USD (None for a key with no limit).

    ``GET https://openrouter.ai/api/v1/key`` through ``job.spend.key_headroom``. The key is read from
    ``OPENROUTER_API_KEY`` and never printed or stored; a failure raises with the exception type only.
    """
    from mailroom_sandbox.job.spend import key_headroom

    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        raise AutoresearchError("OPENROUTER_API_KEY is not set: a paid study checks the key's remaining limit first")
    try:
        remaining = key_headroom().get("limit_remaining")
    except Exception as exc:  # noqa: BLE001 - fail closed; never echo what the transport said
        raise AutoresearchError(f"could not read the OpenRouter key's remaining limit ({type(exc).__name__})") from None
    return None if remaining is None else float(remaining)


# ---- the ledger ----------------------------------------------------------------------------------------

class Ledger:
    """Append-only JSONL: one row per round. Rows are never rewritten."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise AutoresearchError(f"{self.path}: unreadable ledger row ({exc.msg})") from exc
        return out

    def append(self, row: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


# ---- pure helpers ----------------------------------------------------------------------------------------

def run_id_for(study: str, round_no: int | str, lever_id: str) -> str:
    """``ar-<study>-r<NN>-<lever id>``, kept a valid run id (letters, digits, ``.``, ``_``, ``-``; at most 64)."""
    head = f"ar-{study}-r{round_no:02d}" if isinstance(round_no, int) else f"ar-{study}-{round_no}"
    tail = lv.slug(lever_id) if lever_id else ""
    return (f"{head}-{tail}" if tail else head)[:64].rstrip("-.")


# Study-level runs, not lever rounds: their rows (and their errors) never count as a revert.
NON_CANDIDATE = ("baseline", "replicate", "holdout")


def consecutive_reverts(rows: list[Mapping[str, Any]]) -> int:
    """Trailing lever rounds that were reverted or errored; a keep resets, a skip or an abort is neutral.

    The baseline, replicate and holdout rows are not lever rounds: an error of theirs is ignored, and the scan
    stops at the baseline or replicate row itself (what came before it belongs to no lever).
    """
    count = 0
    for row in reversed(rows):
        decision = row.get("decision")
        if row.get("lever") in NON_CANDIDATE:
            if decision in ("baseline", "replicate"):
                break
            continue
        if decision in ("revert", "error"):
            count += 1
        elif decision == "keep":
            break
    return count


def _row_usd(row: Mapping[str, Any], field_name: str) -> float:
    """``row[field_name]`` as a finite, non-negative USD amount (absent counts as 0); anything else is a corrupt ledger."""
    raw = row.get(field_name)
    if raw is None or raw == "":
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise LedgerCorruptError(f"ledger row {row.get('seq')} ({row.get('lever')}): {field_name} {raw!r} is not a number; "
                                 "the study cannot sum its spend") from None
    if not math.isfinite(value):
        raise LedgerCorruptError(f"ledger row {row.get('seq')} ({row.get('lever')}): {field_name} is {raw!r}, not a finite "
                                 "number; the study cannot sum its spend")
    return max(0.0, value)


def dangling_reservations(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """``pending`` rows no later final row (any other decision) has resolved by run id: a run that may still be billing."""
    last_final: dict[Any, int] = {}
    for i, row in enumerate(rows):
        if row.get("decision") != "pending" and row.get("run_id"):
            last_final[row["run_id"]] = i
    return [row for i, row in enumerate(rows) if row.get("decision") == "pending" and last_final.get(row.get("run_id"), -1) < i]


def spent_usd(rows: list[Mapping[str, Any]], *, release: str | None = None) -> float:
    """The ledger's spend: each row's cost (clamped to >= 0) plus every dangling ``pending`` reservation at its cap.

    A non-finite or non-numeric cost raises ``LedgerCorruptError``. ``release`` leaves the reservation of that run id
    out (the run that is about to resume under it).
    """
    dangling = {id(r) for r in dangling_reservations(rows)}
    total = 0.0
    for row in rows:
        if row.get("decision") == "pending":
            if id(row) in dangling and row.get("run_id") != release:
                total += _row_usd(row, "reserved_usd")
            continue
        total += _row_usd(row, "cost_usd")
    return total


def _fits(spent: float, cap: float, study_usd: float) -> bool:
    """Whether a round capped at ``cap`` fits the study budget. False for a NaN anywhere (it fails closed)."""
    return bool(spent + cap <= study_usd + 1e-9)


def draw_size(dataset: Mapping[str, Any]) -> int | None:
    """The most documents a dataset spec can draw (strata quotas, then ``limit``), None when it cannot be told."""
    strata = dataset.get("strata") or {}
    totals: list[int] = []
    if "buckets" in strata:
        total = 0
        for bucket in strata.get("buckets") or []:
            subs = bucket.get("sub_buckets") or []
            count = sum(int(sb.get("count") or 0) for sb in subs) if subs else bucket.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                total = -1
                break
            total += count
        if total > 0:
            totals.append(total)
    elif "values" in strata:
        counts = strata.get("counts") or []
        if counts and len(counts) == len(strata["values"]) and all(isinstance(c, int) and c > 0 for c in counts):
            totals.append(sum(counts))
    limit = dataset.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        totals.append(limit)
    return min(totals) if totals else None


def assert_disjoint(dev_ids: set[str], holdout_ids: set[str]) -> None:
    """The holdout draw shares no document with the dev draw (a hard error, never a warning)."""
    overlap = sorted(dev_ids & holdout_ids)
    if overlap:
        raise AutoresearchError(f"holdout overlaps the dev draw on {len(overlap)} document(s): {', '.join(overlap[:5])}")


def propose(weakness: list[diagnose.WeaknessRow], levers: list[lv.Lever], rows: list[Mapping[str, Any]], *,
            catalog: list[lv.Lever] | None = None, env: Mapping[str, str] | None = None,
            budget_remaining: float | None = None, round_cap: float | None = None,
            ) -> tuple[lv.Lever | None, diagnose.WeaknessRow | None]:
    """The first untried, unlocked lever attached to the worst actionable weakness, lowest tier first."""
    tried = lv.settled(rows)   # a lever that errored once is not here: it is proposed again (MAX_ATTEMPTS in all)
    catalog = levers if catalog is None else catalog
    eligible = [(i, item) for i, item in enumerate(levers)
                if item.id not in tried and lv.env_ready(item, env)
                and lv.requirement_met(item, catalog, rows, budget_remaining_usd=budget_remaining, round_cap_usd=round_cap)]
    for row in weakness:
        if not row.actionable:
            continue
        hits = [(item.tier or 0, i, item) for i, item in eligible if row.node in item.nodes and item.covers(row.doc_class)]
        if hits:
            return min(hits, key=lambda h: (h[0], h[1]))[2], row
    return None, None


# ---- the loop ---------------------------------------------------------------------------------------------

@dataclass
class State:
    rows: list[dict[str, Any]]
    champ_row: dict[str, Any] | None = None
    champ_spec: dict[str, Any] | None = None
    champ_scores: scoring.RunScores | None = None

    @property
    def spent(self) -> float:
        return spent_usd(self.rows)

    def spent_for(self, run_id: str | None) -> float:
        """The spend with ``run_id``'s own dangling reservation released: the run about to resume under that id."""
        return spent_usd(self.rows, release=run_id)

    @property
    def replicate(self) -> dict[str, Any] | None:
        """The replicate-baseline row (the champion's identical re-run), if the ledger has one."""
        return next((r for r in self.rows if r.get("decision") == "replicate"), None)

    @property
    def holdout(self) -> dict[str, Any] | None:
        """The holdout row (the champion's one confirmation run), if the ledger has one."""
        return next((r for r in self.rows if r.get("decision") == "holdout"), None)

    @property
    def holdout_stale(self) -> bool:
        """True when a keep changed the champion after the holdout confirmed an earlier one."""
        hold = self.holdout
        return bool(hold and self.champ_row and hold.get("champion_run_id") != self.champ_row.get("run_id"))


@dataclass
class RoundPlan:
    """What a candidate round will run under: its API cap and the estimate behind it."""
    cap: float
    est: estimate.Estimate | None = None

    @property
    def info(self) -> dict[str, Any]:
        out: dict[str, Any] = {"round_cap_usd": self.cap}
        if self.est is not None:
            out["estimate"] = self.est.to_dict()
        return out


@dataclass
class StepResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    stop: str | None = None
    executed: bool = False


class Loop:
    def __init__(self, study: Study, executor: Executor | None, *, key_remaining: Callable[[], float | None] | None = None,
                 env: Mapping[str, str] | None = None, state_dir: Path | None = None, out: Callable[[str], Any] = print,
                 git_head: Callable[[Path], str | None] | None = None, clock: Callable[[], datetime] | None = None):
        self.study = study
        self.executor = executor
        self.env = os.environ if env is None else env
        self.dir = Path(state_dir) if state_dir else study.state_path
        self.ledger = Ledger(self.dir / "ledger.jsonl")
        self.out = out
        self._key_remaining = key_remaining
        self._git_head = git_head or _git_head
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._catalog: lv.Catalog | None = None
        self._base: dict[str, Any] | None = None
        self._warned_key = False
        self._key_info: dict[str, Any] = {}      # the key reading behind the current round (stamped on its ledger rows)
        self._lock_depth = 0
        self._lock_fh: Any = None

    # -- inter-process lock
    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Hold ``<state_dir>/.lock`` (``flock``, non-blocking) for the whole of a mutating command.

        Reentrant within this ``Loop`` (``run`` calls ``step``). A second process (or ``Loop``) on the same state
        directory is refused at once: two loops would race on the ledger, the champion and the budget.
        """
        if self._lock_depth:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        fh = open(self.dir / ".lock", "a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            raise AutoresearchError(f"another autoresearch process holds {self.dir} (its .lock is taken): "
                                    "wait for it to finish, or stop it, before starting another") from None
        except OSError as exc:
            fh.close()
            raise AutoresearchError(f"could not lock {self.dir / '.lock'} ({type(exc).__name__})") from None
        self._lock_fh, self._lock_depth = fh, 1
        try:
            yield
        finally:
            self._lock_depth = 0
            self._lock_fh = None
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()

    # -- inputs
    @property
    def base(self) -> dict[str, Any]:
        if self._base is None:
            self._base = self.study.base_spec()
            lv.validate_spec(self._base, where="base run spec")
        return self._base

    @property
    def catalog(self) -> lv.Catalog:
        if self._catalog is None:
            self._catalog = lv.load_levers(self.study.levers_path)
            problems = lv.validate_catalog(self._catalog, self.base)
            if problems:
                raise AutoresearchError("lever catalog does not fit the base spec:\n  " + "\n  ".join(problems))
        return self._catalog

    def levers(self, rows: list[dict[str, Any]]) -> list[lv.Lever]:
        return lv.all_levers(self.catalog, self.base, rows)

    # -- state
    def state(self) -> State:
        rows = self.ledger.rows()
        state = State(rows=rows)
        champs = [r for r in rows if r.get("decision") in ("baseline", "keep")]
        if champs:
            state.champ_row = champs[-1]
            state.champ_spec = self._champion_spec(state.champ_row)
            state.champ_scores = scoring.RunScores.from_dict(
                json.loads((self.dir / "scores" / f"{state.champ_row['run_id']}.json").read_text(encoding="utf-8")))
        return state

    def _champion_spec(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """The champion's spec: ``specs/<run_id>.yaml`` (written before the run), checked against the row's hash.

        ``champion.yaml`` is only a convenience copy and is never read: a crash between a ledger row and that file
        cannot leave the state inconsistent.
        """
        path = self.dir / "specs" / f"{row['run_id']}.yaml"
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AutoresearchError(f"{path}: the champion's spec is missing ({type(exc).__name__}); "
                                    "the ledger names it as the champion") from None
        if row.get("spec_sha256") and hashlib.sha256(raw).hexdigest() != row["spec_sha256"]:
            raise AutoresearchError(f"{path}: does not match the ledger's spec_sha256 for {row['run_id']}; "
                                    "the champion's spec was edited after its round")
        return yaml.safe_load(raw.decode("utf-8")) or {}

    def _champion_source(self, state: State) -> dict[str, Any] | None:
        return (state.champ_row or {}).get("pipeline_source")

    # -- guards
    def noise_floor(self, state: State) -> float | None:
        """The effective noise floor: the configured one or the replicate's measured one, whichever is larger.

        None until the replicate baseline exists (no lever may be kept before then).
        """
        rep = state.replicate
        if rep is None:
            return None
        measured = float((rep.get("noise") or {}).get("measured_floor") or 0.0)
        return max(float(self.study.noise_floor), measured)

    def class_noise(self, state: State) -> dict[str, float]:
        """Each class's run-to-run swing: the absolute mean paired delta per class between the two baseline runs."""
        rep = state.replicate or {}
        by_class = (rep.get("delta") or {}).get("by_class") or {}
        return {cls: abs(float(d.get("mean") or 0.0)) for cls, d in by_class.items()}

    def _guard(self, state: State, cap: float | None = None, run_id: str | None = None) -> str | None:
        """A stop reason when a round capped at ``cap`` (default: the study's round cap) cannot start.

        ``run_id`` is the run about to start: if the ledger holds a dangling reservation for it (a crash resumed),
        that reservation is released from the sum so the resume is not charged twice. Paid studies also read the
        key: ``key_low`` (remaining - cap under the reserve), ``key_spend`` (the bill itself: the key's drop since the
        study's first reading plus this cap exceeds the study budget; unlike the ledger, it counts what was really billed).
        """
        budget = self.study.budget
        cap = budget.round_api_cap_usd if cap is None else cap
        self._key_info = {}
        if not _fits(state.spent_for(run_id), cap, budget.study_usd):
            return "study_budget"
        if self.study.mock:
            return None
        check = self._key_remaining
        if check is None:
            check = openrouter_key_remaining
        try:
            remaining = check()
        except Exception:  # noqa: BLE001 - fail closed; the message is not echoed (it may name the transport)
            return "key_unreadable"
        if remaining is None:
            self._key_info = {"key_remaining_before": None}
            self._warn_unlimited_key(state)
            return None
        try:
            remaining = float(remaining)
        except (TypeError, ValueError):
            return "key_unreadable"
        if not math.isfinite(remaining):
            return "key_unreadable"
        start = self._key_start(remaining)
        self._key_info = {"key_remaining_before": remaining, "key_remaining_at_start": start}
        if not (remaining - cap >= budget.min_key_remaining_usd):
            return "key_low"
        if not (start - remaining + cap <= budget.study_usd + 1e-9):
            return "key_spend"
        return None

    def _refuse_stale_run_dir(self, state: State, run_id: str) -> None:
        """Refuse a run id whose run directory exists while the ledger has no row for it.

        Run ids repeat across restarts (study, round and lever only), and run directories live under the global runs
        root. A fresh state directory over an old run directory would resume that run and score its stored results as
        new measurements (and charge the round cap for calls never made). Run ids the ledger already records, a
        ``pending`` row included, still resume.
        """
        from mailroom_sandbox.job.spec import run_dir as _run_dir

        existing = _run_dir(run_id)
        if existing.exists() and not any(r.get("run_id") == run_id for r in state.rows):
            raise AutoresearchError(
                f"run directory {existing} already exists but the ledger has no row for {run_id}: refusing to reuse "
                "its stored results as new measurements. Move that directory aside, or give the study a new name")

    def _key_start(self, remaining: float) -> float:
        """The study's first ``limit_remaining`` reading: persisted once (``key_start.json``), then read back."""
        path = self.dir / "key_start.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            value = float(data["key_remaining_at_start"])
            if not math.isfinite(value):
                raise ValueError("not finite")
            return value
        except FileNotFoundError:
            _atomic_write(path, json.dumps({"key_remaining_at_start": remaining, "recorded_at": self._clock().strftime("%Y-%m-%dT%H:%M:%SZ")}))
            return remaining
        except (OSError, ValueError, KeyError, TypeError):
            raise AutoresearchError(f"{path}: unreadable; it holds the key's first reading of this study (the bill-grounded "
                                    "spend guard). Fix it or move it aside to start the study's key accounting again") from None

    def _warn_unlimited_key(self, state: State) -> None:
        """A key with no spend limit cannot bound the study: say so (ledger once, console once per process)."""
        message = ("the OpenRouter key has no spend limit (limit_remaining is null): the key check cannot bound spend, "
                   "so only the study budget does")
        if not self._warned_key:
            self._warned_key = True
            self.out(f"warning: {message}")
        if not any(r.get("decision") == "warning" and r.get("lever") == "key_check" for r in state.rows):
            self._row(state, round=None, lever="key_check", run_id=None, decision="warning", reasons=[message],
                      cost_usd=0.0, goal="quality")

    # -- spec stamping
    def _stamp(self, spec: Mapping[str, Any], *, run_id: str, lever_id: str, cap: float | None = None) -> dict[str, Any]:
        out = copy.deepcopy(dict(spec))
        out["run_id"] = run_id
        job = out.setdefault("job", {})
        job["api_cost_cap_usd"] = self.study.budget.round_api_cap_usd if cap is None else cap
        job["max_wall_seconds"] = self.study.budget.round_wall_seconds
        trace = out.setdefault("trace", {})
        tags = [t for t in (trace.get("tags") or []) if not str(t).startswith("lever:")]   # the champion's own lever tag goes
        for tag in ("autoresearch", self.study.study, f"lever:{lever_id}"):
            if tag not in tags:
                tags.append(tag)
        trace["tags"] = tags
        lv.validate_spec(out, where=f"candidate {run_id}")
        problems = lv.reviewer_errors(out)
        if problems:
            raise AutoresearchError(f"candidate {run_id}: " + "; ".join(problems))
        return out

    def _write_spec(self, spec: Mapping[str, Any], run_id: str) -> tuple[Path, str]:
        path = self.dir / "specs" / f"{run_id}.yaml"
        text = yaml.safe_dump(dict(spec), sort_keys=False)
        _atomic_write(path, text)
        return path, hashlib.sha256(text.encode("utf-8")).hexdigest()

    # -- pipeline source
    def _source_for(self, lever: lv.Lever | None, state: State) -> tuple[dict[str, str], dict[str, Any] | None]:
        """Environment overrides for the round, and the provenance record (None without a custom source)."""
        meta = None
        if lever is not None and lever.pipeline_source is not None:
            meta = {"env": lever.pipeline_source.env, "commit": lever.pipeline_source.commit, "lever": lever.id}
        meta = meta or self._champion_source(state)
        if not meta:
            return {}, None
        raw = str(self.env.get(meta["env"], "")).strip()
        if not raw or not Path(raw).expanduser().is_dir():
            raise AutoresearchError(f"pipeline source: ${meta['env']} is unset or not a directory")
        path = Path(raw).expanduser().resolve()
        head = self._git_head(path)
        if meta.get("commit") and head != meta["commit"]:
            raise AutoresearchError(f"pipeline source: ${meta['env']} is at {head or 'no git HEAD'}, expected {meta['commit']}")
        return {"MAILROOM_SRC": str(path)}, {**meta, "commit_found": head}

    # -- one run
    def _reserve(self, state: State, run_id: str, cap: float, lever_id: str, round_no: int | None, goal: str) -> None:
        """Before a paid child runs: a ``pending`` row that reserves its cap (``spent_usd`` counts it until a final row
        for the same run id supersedes it). A crash after this point leaves the reservation in the ledger, so the next
        process cannot spend the same dollars twice; the resume of the same run id resolves it. Mock studies spend nothing.
        """
        if self.study.mock or any(r.get("run_id") == run_id for r in dangling_reservations(state.rows)):
            return
        self._row(state, round=round_no, lever=lever_id, run_id=run_id, decision="pending", cost_usd=0.0,
                  reserved_usd=round(cap, 6), round_cap_usd=cap, goal=goal,
                  reasons=[f"reserved {cap:g} USD before the run started; the run's own row supersedes it"])

    def _run_one(self, state: State, spec: dict[str, Any], run_id: str, env: Mapping[str, str], *, cap: float,
                 lever_id: str, round_no: int | None = None, goal: str = "quality",
                 ) -> tuple[scoring.RunScores | None, str | None, Path | None, bool]:
        """Reserve, execute and score; ``(scores, error, run_dir, capped)``. A failed run is scored from whatever it wrote.

        ``capped`` is true when the run's own API budget (``job.api_cost_cap_usd``) aborted it.
        """
        spec_path, _ = self._write_spec(spec, run_id)
        self._reserve(state, run_id, cap, lever_id, round_no, goal)
        error: str | None = None
        run_dir: Path | None = None
        try:
            assert self.executor is not None
            run_dir = Path(self.executor.execute(spec_path, env=env or None))
        except ExecutionError as exc:
            error = scrub(str(exc), self.env)
            from mailroom_sandbox.job.spec import run_dir as _run_dir
            run_dir = _run_dir(exc.run_id or run_id)
        scores = None
        try:
            if run_dir is not None and (run_dir / "dataset.jsonl").is_file():
                scores = scoring.score_run(run_dir, self.study.utility)
                _atomic_write(self.dir / "scores" / f"{run_id}.json", json.dumps(scores.to_dict(), indent=1))
        except Exception as exc:  # noqa: BLE001 - an unscorable run is an error row, not a crash of the loop
            error = error or f"scoring failed: {type(exc).__name__}: {scrub_head(str(exc), 300, self.env)}"
        return scores, error, run_dir, _aborted_by_cap(run_dir, error)

    def _row(self, state: State, **fields: Any) -> dict[str, Any]:
        row = {"seq": len(state.rows) + 1, "timestamp": self._clock().strftime("%Y-%m-%dT%H:%M:%SZ"),
               "mock": self.study.mock, "study": self.study.study, **fields}
        if fields.get("run_id") and not self.study.mock:
            for name, value in self._key_info.items():      # the key reading the round's guard took
                row.setdefault(name, value)
        self.ledger.append(row)
        state.rows.append(row)
        return row

    @staticmethod
    def _lock_sources(run_dir: Path | None) -> dict[str, Any] | None:
        try:
            lock = json.loads((Path(run_dir) / "spec.lock.json").read_text(encoding="utf-8"))
            return lock.get("dependency_sources")
        except (OSError, ValueError, TypeError):
            return None

    def _save_champion(self, spec: Mapping[str, Any]) -> None:
        _atomic_write(self.dir / "champion.yaml", yaml.safe_dump(dict(spec), sort_keys=False))

    # -- baseline and replicate
    def ensure_baseline(self, state: State) -> str | None:
        """Run the champion once as round 0 when the ledger has none; a stop reason when a guard refuses."""
        if any(r.get("decision") == "baseline" for r in state.rows):
            return None
        run_id = run_id_for(self.study.study, 0, "baseline")
        self._refuse_stale_run_dir(state, run_id)
        stop = self._guard(state, run_id=run_id)
        if stop:
            return stop
        cap = self.study.budget.round_api_cap_usd
        spec = self._stamp(self.base, run_id=run_id, lever_id="baseline")
        env, source = self._source_for(None, state)
        _, sha = self._write_spec(spec, run_id)
        self.out(f"round 0: baseline champion {run_id}")
        scores, error, run_dir, capped = self._run_one(state, spec, run_id, env, cap=cap, lever_id="baseline", round_no=0)
        if scores is None or error or capped:
            self._row(state, round=0, lever="baseline", run_id=run_id, spec_sha256=sha, decision="error",
                      reasons=[error or ("the baseline run was aborted by its API cap" if capped else "the baseline run wrote no dataset")],
                      cost_usd=_charge(scores, cap, capped, run_dir), run_dir=str(run_dir) if run_dir else None)
            raise AutoresearchError(f"baseline failed: {error or ('aborted by its API cap' if capped else 'no dataset')}")
        self._save_champion(spec)   # before the row: the ledger is the commit point, this file only a copy
        row = self._row(state, round=0, lever="baseline", run_id=run_id, run_dir=str(run_dir), spec_sha256=sha,
                        champion_run_id=None, decision="baseline", reasons=["the champion's own run"],
                        metrics=scores.metrics(), delta=None, usd_per_utility_point=None, goal="quality",
                        cost_usd=_charge(scores, cap, False, run_dir), pipeline_source=source, round_cap_usd=cap,
                        dependency_sources=self._lock_sources(run_dir))
        state.champ_row, state.champ_spec, state.champ_scores = row, spec, scores
        self._write_views(state)
        return None

    def ensure_replicate(self, state: State) -> str | None:
        """Run the baseline's identical spec again (``replicate``) and measure the noise floor from the pair.

        The effective floor is ``max(noise_floor, |mean paired delta|, CI half-width)`` of the two baseline
        runs. No lever may be kept before this row exists. A failed replicate raises (the next call retries it).
        """
        if state.replicate is not None:
            return None
        assert state.champ_row is not None and state.champ_spec is not None and state.champ_scores is not None
        if state.champ_row.get("decision") != "baseline":
            raise AutoresearchError("the replicate must run against the baseline, before any lever is kept")
        run_id = run_id_for(self.study.study, "replicate", "")
        self._refuse_stale_run_dir(state, run_id)
        stop = self._guard(state, run_id=run_id)
        if stop:
            return stop
        cap = self.study.budget.round_api_cap_usd
        base_row, base_scores = state.champ_row, state.champ_scores
        spec = self._stamp(state.champ_spec, run_id=run_id, lever_id="replicate")
        env, source = self._source_for(None, state)
        _, sha = self._write_spec(spec, run_id)
        self.out(f"replicate: the baseline champion again, {run_id}")
        scores, error, run_dir, capped = self._run_one(state, spec, run_id, env, cap=cap, lever_id="replicate")
        common = dict(round=None, lever="replicate", run_id=run_id, run_dir=str(run_dir) if run_dir else None, spec_sha256=sha,
                      champion_run_id=base_row["run_id"], goal="quality", pipeline_source=source, round_cap_usd=cap)
        problem = None
        if scores is None or error or capped:
            problem = error or ("the replicate run was aborted by its API cap" if capped else "the replicate run wrote no dataset")
        elif {d.id for d in scores.docs} != {d.id for d in base_scores.docs}:
            problem = "the replicate drew different documents than the baseline: not the same frozen draw"
        if problem:
            self._row(state, **common, decision="error", reasons=[problem], metrics=scores.metrics() if scores else None,
                      delta=None, cost_usd=_charge(scores, cap, capped, run_dir), dependency_sources=self._lock_sources(run_dir))
            raise AutoresearchError(f"replicate failed: {problem}")
        boot = self.study.bootstrap
        delta = scoring.paired_delta(base_scores.utilities(), scores.utilities(), base_scores.classes(),
                                     n_boot=boot.n_boot, seed=boot.seed, ci=boot.ci)
        half_width = (delta.ci_high - delta.ci_low) / 2.0
        measured = max(abs(delta.mean), half_width)
        effective = max(float(self.study.noise_floor), measured)
        noise = {"configured_floor": float(self.study.noise_floor), "abs_mean_delta": round(abs(delta.mean), 6),
                 "ci_half_width": round(half_width, 6), "measured_floor": round(measured, 6),
                 "effective_floor": round(effective, 6), "n": delta.n, "ci": delta.ci,
                 "measured_round_cost_usd": round(scores.cost_usd, 6),
                 "baseline_round_cost_usd": round(base_scores.cost_usd, 6)}
        self._row(state, **common, decision="replicate", reasons=[
            f"noise floor {effective:.4f}: max(configured {self.study.noise_floor:g}, |mean delta| {abs(delta.mean):.4f}, "
            f"CI half-width {half_width:.4f}) between the two baseline runs"],
            metrics=scores.metrics(), delta=delta.to_dict(), noise=noise, usd_per_utility_point=None,
            cost_usd=_charge(scores, cap, False, run_dir), dependency_sources=self._lock_sources(run_dir))
        self._write_views(state)
        return None

    # -- planning
    def plan(self) -> dict[str, Any]:
        """What the next round would do, without running anything."""
        state = self.state()
        out: dict[str, Any] = {"baseline": bool(state.champ_row), "replicate": state.replicate is not None,
                               "noise_floor": self.noise_floor(state), "spent_usd": round(state.spent, 4),
                               "consecutive_reverts": consecutive_reverts(state.rows)}
        if not state.champ_scores or not state.champ_spec:
            out["next"] = "baseline (the champion's own run), then the replicate (the same run again, to measure noise)"
            return out
        if state.replicate is None:
            out["next"] = "replicate (the baseline run again, to measure noise; no lever is kept before it)"
        weakness = diagnose.weakness_table(state.champ_scores)
        remaining = self.study.budget.study_usd - state.spent
        lever, row = propose(weakness, self.levers(state.rows), state.rows, catalog=self.catalog.levers, env=self.env,
                             budget_remaining=remaining, round_cap=self.study.budget.round_api_cap_usd)
        out.update({"weakness": [r.to_dict() for r in weakness], "weakness_md": diagnose.render_weakness_md(state.champ_scores, weakness),
                    "lever": lever.id if lever else None, "attached_to": row.to_dict() if row else None,
                    "description": lever.description if lever else None})
        return out

    # -- a step
    def step(self) -> StepResult:
        """Run the baseline and replicate if missing, then one candidate round (skipped levers do not count as a round).

        Holds the state directory's inter-process lock for the whole step.
        """
        with self._exclusive():
            return self._step()

    def _step(self) -> StepResult:
        _ = self.catalog   # a catalog that does not fit the base spec is refused before any spend
        state = self.state()
        result = StepResult()
        before = len(state.rows)

        def done(stop: str | None = None, executed: bool = False) -> StepResult:
            result.rows, result.stop, result.executed = state.rows[before:], stop, executed
            return result

        stop = self.ensure_baseline(state) or self.ensure_replicate(state)
        if stop:
            return done(stop)
        if consecutive_reverts(state.rows) >= self.study.max_consecutive_reverts:
            return done("consecutive_reverts")
        assert state.champ_scores is not None and state.champ_spec is not None
        base_cap = self.study.budget.round_api_cap_usd
        while True:
            remaining = self.study.budget.study_usd - state.spent
            weakness = diagnose.weakness_table(state.champ_scores)
            levers = self.levers(state.rows)
            lever, weak = propose(weakness, levers, state.rows, catalog=self.catalog.levers, env=self.env,
                                  budget_remaining=remaining, round_cap=base_cap)
            if lever is None:
                return done("levers_exhausted")
            run_id = run_id_for(self.study.study, self._next_round(state), lever.id)
            if not _fits(state.spent_for(run_id), base_cap, self.study.budget.study_usd):
                return done("study_budget")      # not even a standard round fits
            skipped, plan = self._maybe_skip(state, lever)
            if skipped:
                continue
            stop = self._guard(state, plan.cap, run_id=run_id)
            if stop:
                return done(stop)
            self._candidate_round(state, lever, weak, plan)
            return done(executed=True)

    def _maybe_skip(self, state: State, lever: lv.Lever) -> tuple[dict[str, Any] | None, RoundPlan]:
        """``(row, plan)``: a ledger row when the lever changes nothing, has no usable source, or does not fit its cap.

        The cap decision uses the estimate's runtime bound (what the run's own ``ApiBudget`` will count) against
        the lever's cap: its override, its derived supervisor cap, or the study's round cap. A lever whose cap is
        above the standard one must also be reservable from the remaining study budget (``over_study_budget``).
        """
        assert state.champ_spec is not None and state.champ_scores is not None
        budget = self.study.budget
        plan = RoundPlan(cap=budget.round_api_cap_usd)
        round_no = self._next_round(state)
        run_id = run_id_for(self.study.study, round_no, lever.id)

        def skip(reason: str, **extra: Any) -> tuple[dict[str, Any], RoundPlan]:
            self.out(f"skip {lever.id}: {reason}")
            return self._row(state, round=None, lever=lever.id, run_id=None, decision="skipped", reasons=[reason],
                             cost_usd=0.0, goal=lever.goal, **extra), plan

        try:
            cand = lv.apply_lever(state.champ_spec, lever)
        except lv.LeverError as exc:
            return skip(f"invalid on the current champion: {exc}")
        if cand == state.champ_spec and lever.pipeline_source is None:
            return skip("noop: the champion already has this setting")
        try:
            self._source_for(lever, state)
        except AutoresearchError as exc:
            return skip(str(exc))
        spec = self._stamp(cand, run_id=run_id, lever_id=lever.id)
        safety = self.study.estimate_safety * (lever.estimate_safety or 1.0)
        est = estimate.estimate_round_cost(state.champ_scores, state.champ_spec, spec, safety=safety)
        cap = estimate.round_cap_for(lever, est, base_cap=budget.round_api_cap_usd, max_cap=budget.max_round_cap_usd)
        plan = RoundPlan(cap=cap, est=est)
        if est.unpriced:
            return skip(f"unpriced model(s) {', '.join(est.unpriced)}", **plan.info)
        if est.cap_usd > cap + 1e-9:
            return skip(f"over_round_cap: runtime bound {est.cap_usd:.3f} USD > round cap {cap:g} USD "
                        f"(per-agent estimate {est.usd:.3f} USD)", **plan.info)
        if cap > budget.round_api_cap_usd and not _fits(state.spent_for(run_id), cap, budget.study_usd):
            return skip(f"over_study_budget: the round cap {cap:g} USD cannot be reserved from the remaining "
                        f"{budget.study_usd - state.spent_for(run_id):.3f} USD of the study budget", **plan.info)
        return None, plan

    def _next_round(self, state: State) -> int:
        # A dangling ``pending`` row does not take its round number: the resume of that run gets the same run id back.
        return 1 + max((r["round"] for r in state.rows if isinstance(r.get("round"), int) and r.get("decision") != "pending"),
                       default=0)

    def _candidate_round(self, state: State, lever: lv.Lever, weak: diagnose.WeaknessRow | None, plan: RoundPlan) -> dict[str, Any]:
        assert state.champ_spec is not None and state.champ_scores is not None and state.champ_row is not None
        floor = self.noise_floor(state)
        if floor is None:
            raise AutoresearchError("no lever runs before the replicate baseline has measured the noise floor")
        cap = plan.cap
        round_no = self._next_round(state)
        run_id = run_id_for(self.study.study, round_no, lever.id)
        self._refuse_stale_run_dir(state, run_id)
        spec = self._stamp(lv.apply_lever(state.champ_spec, lever), run_id=run_id, lever_id=lever.id, cap=cap)
        env, source = self._source_for(lever, state)
        _, sha = self._write_spec(spec, run_id)
        where = f" (attached to {weak.node}/{weak.doc_class})" if weak else ""
        self.out(f"round {round_no}: {lever.id}{where} -> {run_id} (cap {cap:g} USD)")
        champ = state.champ_scores
        scores, error, run_dir, capped = self._run_one(state, spec, run_id, env, cap=cap, lever_id=lever.id,
                                                       round_no=round_no, goal=lever.goal)
        common = dict(round=round_no, lever=lever.id, run_id=run_id, run_dir=str(run_dir) if run_dir else None, spec_sha256=sha,
                      champion_run_id=state.champ_row["run_id"], goal=lever.goal, pipeline_source=source,
                      attached_to=weak.to_dict() if weak else None, patch_before={p: lv.lookup(state.champ_spec, p) for p in lever.patch},
                      **plan.info)
        if capped:
            row = self._row(state, **common, decision="aborted_cap", metrics=scores.metrics() if scores else None, delta=None,
                            usd_per_utility_point=None, cost_usd=_charge(scores, cap, True, run_dir),
                            dependency_sources=self._lock_sources(run_dir),
                            reasons=[f"aborted by the run's API cap ({cap:g} USD): no verdict, not a revert; charged the full cap"
                                     + (f" ({error[:200]})" if error else "")])
        elif scores is None or error:
            row = self._row(state, **common, decision="error", reasons=[error or "no dataset written"], metrics=None,
                            delta=None, usd_per_utility_point=None, cost_usd=_charge(scores, cap, False, run_dir),
                            dependency_sources=self._lock_sources(run_dir))
        elif {d.id for d in scores.docs} != {d.id for d in champ.docs}:
            row = self._row(state, **common, decision="error", metrics=scores.metrics(), delta=None, usd_per_utility_point=None,
                            reasons=["the run drew different documents than the champion: not the same frozen draw"],
                            cost_usd=_charge(scores, cap, False, run_dir), dependency_sources=self._lock_sources(run_dir))
        else:
            boot = self.study.bootstrap
            delta = scoring.paired_delta(champ.utilities(), scores.utilities(), champ.classes(),
                                         n_boot=boot.n_boot, seed=boot.seed, ci=boot.ci)
            kept, reasons = keep.decide_keep(champ, scores, delta, goal=lever.goal, noise_floor=floor,
                                             class_noise=self.class_noise(state),
                                             guard_classes=self.study.guard_classes, tolerance=self.study.cost_goal_tolerance)
            if kept:
                self._save_champion(spec)   # before the row: the ledger is the commit point, this file only a copy
            row = self._row(state, **common, decision="keep" if kept else "revert", reasons=reasons, metrics=scores.metrics(),
                            delta=delta.to_dict(), usd_per_utility_point=_round(scoring.usd_per_utility_point(champ, scores, delta.mean)),
                            cost_usd=_charge(scores, cap, False, run_dir), noise_floor=floor, dependency_sources=self._lock_sources(run_dir))
            if kept:
                state.champ_row, state.champ_spec, state.champ_scores = row, spec, scores
        self._write_views(state)
        return row

    # -- the loop
    def run(self, max_rounds: int) -> tuple[list[dict[str, Any]], str]:
        """Run up to ``max_rounds`` candidate rounds; the rows written and why the loop stopped.

        Holds the state directory's inter-process lock for the whole run (each ``step`` re-enters it).
        """
        with self._exclusive():
            rows: list[dict[str, Any]] = []
            executed = 0
            while executed < max_rounds:
                result = self.step()
                rows += result.rows
                executed += int(result.executed)
                if result.stop:
                    return rows, result.stop
            return rows, "max_rounds"

    # -- views
    def _write_views(self, state: State) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if state.champ_scores:
            _atomic_write(self.dir / "weakness.md", diagnose.render_weakness_md(state.champ_scores))
        _atomic_write(self.dir / "report.md", self.render_report(state))

    def render_report(self, state: State | None = None) -> str:
        from mailroom_sandbox.autoresearch.report import render_report

        return render_report(self, state or self.state())

    def status(self) -> dict[str, Any]:
        state = self.state()
        decided = [r for r in state.rows if r.get("decision") in DECIDED]
        message = None
        if not state.rows:
            message = (f"nothing has run yet: no ledger at {self.ledger.path}; "
                       f"`sandbox autoresearch step --study <file>` runs the baseline")
        elif state.champ_row is None:
            message = "no champion yet: the baseline has not succeeded (see the error row in the ledger); `step` retries it"
        hold = state.holdout
        return {"message": message, "study": self.study.study, "rounds": len([r for r in state.rows if isinstance(r.get("round"), int) and r.get("decision") != "pending"]) - 1
                if state.champ_row else 0,
                "kept": [r["lever"] for r in decided if r["decision"] == "keep"],
                "reverted": [r["lever"] for r in decided if r["decision"] == "revert"],
                "errors": [r["lever"] for r in decided if r["decision"] == "error"],
                "aborted_cap": [r["lever"] for r in decided if r["decision"] == "aborted_cap"],
                "replicate": state.replicate is not None, "noise_floor": self.noise_floor(state),
                "warnings": [str((r.get("reasons") or [""])[0]) for r in state.rows if r.get("decision") == "warning"],
                "skipped": [r["lever"] for r in state.rows if r.get("decision") == "skipped"],
                "spent_usd": round(state.spent, 4), "study_usd": self.study.budget.study_usd,
                "consecutive_reverts": consecutive_reverts(state.rows),
                "champion": (state.champ_row or {}).get("run_id"),
                "champion_mean_utility": state.champ_scores.mean_utility if state.champ_scores else None,
                "holdout": hold is not None,
                "holdout_champion": hold.get("champion_run_id") if hold else None,
                "holdout_stale": state.holdout_stale}

    # -- holdout
    def holdout(self) -> dict[str, Any]:
        """Run the champion once on a draw disjoint from the dev draw; refuse a second time.

        Holds the state directory's inter-process lock for the whole holdout.
        """
        with self._exclusive():
            return self._holdout()

    def _holdout(self) -> dict[str, Any]:
        state = self.state()
        if not state.champ_scores or not state.champ_spec or not state.champ_row:
            raise AutoresearchError("no champion yet: run `autoresearch step` first")
        if any(r.get("decision") == "holdout" for r in state.rows):
            raise AutoresearchError("the holdout has been run once already; it is a confirmation, never a tuning set")
        # The champion may run supervisors: its own runtime bound (every token at the dearest API model) can exceed the
        # standard round cap, so the holdout takes the derived cap, and is refused when even the maximum cannot hold it.
        budget = self.study.budget
        est = estimate.estimate_round_cost(state.champ_scores, state.champ_spec, state.champ_spec, safety=self.study.estimate_safety)
        cap = estimate.auto_round_cap(est, base_cap=budget.round_api_cap_usd, max_cap=budget.max_round_cap_usd, tier=3)
        if est.cap_usd > cap + 1e-9:
            raise AutoresearchError(f"holdout refused: the champion's runtime bound {est.cap_usd:.3f} USD exceeds the "
                                    f"largest round cap {cap:g} USD (budget.max_round_cap_usd)")
        run_id = run_id_for(self.study.study, "holdout", "")
        self._refuse_stale_run_dir(state, run_id)
        dev_ids = {d.id for d in state.champ_scores.docs}
        self._check_holdout_size(state.champ_spec, len(dev_ids))
        stop = self._guard(state, cap, run_id=run_id)
        if stop:
            raise AutoresearchError(f"holdout refused: {stop}")
        exclude = self._write_holdout_exclusions(state.champ_spec, dev_ids)
        spec = copy.deepcopy(state.champ_spec)
        spec["dataset"] = {**spec.get("dataset", {}), **self.study.holdout_dataset, "exclude_ids_file": str(exclude)}
        spec = self._stamp(spec, run_id=run_id, lever_id="holdout", cap=cap)
        env, source = self._source_for(None, state)
        spec_path, sha = self._write_spec(spec, run_id)
        assert self.executor is not None
        prepare = getattr(self.executor, "prepare", None)
        if prepare is not None:  # lock the draw first: no model has been called yet
            locked = Path(prepare(spec_path, env=env or None))
            assert_disjoint(dev_ids, _dataset_ids(locked))
        self.out(f"holdout: champion {state.champ_row['run_id']} on {run_id}")
        scores, error, run_dir, capped = self._run_one(state, spec, run_id, env, cap=cap, lever_id="holdout")
        if capped or scores is None or error:
            self._row(state, round=None, lever="holdout", run_id=run_id, run_dir=str(run_dir) if run_dir else None,
                      spec_sha256=sha, decision="aborted_cap" if capped else "error", round_cap_usd=cap,
                      reasons=[error or ("aborted by the run's API cap" if capped else "no dataset written")],
                      cost_usd=_charge(scores, cap, capped, run_dir))
            raise AutoresearchError(f"holdout failed: {error or ('aborted by its API cap' if capped else 'no dataset')}")
        assert_disjoint(dev_ids, {d.id for d in scores.docs})
        gate = _gate_summary(run_dir)
        row = self._row(state, round=None, lever="holdout", run_id=run_id, run_dir=str(run_dir), spec_sha256=sha,
                        champion_run_id=state.champ_row["run_id"], decision="holdout", reasons=["confirmation run of the champion"],
                        metrics=scores.metrics(), delta=None, cost_usd=_charge(scores, cap, False, run_dir), gate=gate,
                        pipeline_source=source, dependency_sources=self._lock_sources(run_dir), goal="quality",
                        dev_ids=len(dev_ids), holdout_ids=len(scores.docs), disjoint=True)
        _atomic_write(self.dir / "holdout.md", self._holdout_md(state, scores, gate))
        self._write_views(state)
        return row

    def _write_holdout_exclusions(self, champ_spec: Mapping[str, Any], dev_ids: set[str]) -> Path:
        """``holdout-excluded-ids.txt``: the production exclusion list plus every dev document."""
        from mailroom_sandbox.job.spec import DatasetSpec

        lines = ["# Holdout exclusion list generated by `sandbox autoresearch holdout`.",
                 f"# Study {self.study.study}: the dev draw's {len(dev_ids)} document ids follow the inherited list.", ""]
        source = DatasetSpec.model_validate(dict(champ_spec.get("dataset") or {})).exclude_ids_path()
        if source is not None:
            if not source.is_file():
                raise AutoresearchError(f"dataset.exclude_ids_file not found: {source}")
            lines += [f"# --- inherited from {source.name} ---", *source.read_text(encoding="utf-8").splitlines(), ""]
        lines += ["# --- dev draw ---", *sorted(dev_ids), ""]
        path = self.dir / "holdout-excluded-ids.txt"
        _atomic_write(path, "\n".join(lines))
        return path

    def _check_holdout_size(self, champ_spec: Mapping[str, Any], dev_n: int) -> None:
        """Refuse a holdout draw larger than twice the dev draw (checked before any spend).

        A holdout that overrides nothing draws the dev draw's own quotas from the remaining block, so it fits by
        construction. An override must say how many documents it draws (strata quotas or ``limit``).
        """
        if not self.study.holdout_dataset:
            return
        merged = {**(champ_spec.get("dataset") or {}), **self.study.holdout_dataset}
        size = draw_size(merged)
        if size is None:
            raise AutoresearchError("holdout refused: holdout_dataset does not say how many documents it draws "
                                    "(strata quotas or a limit); an open draw could take the whole corpus")
        if size > 2 * dev_n:
            raise AutoresearchError(f"holdout refused: holdout_dataset draws {size} documents, more than twice the "
                                    f"{dev_n}-document dev draw ({2 * dev_n} at most)")

    def _holdout_md(self, state: State, scores: scoring.RunScores, gate: Mapping[str, Any] | None) -> str:
        lines = [f"# Holdout: {scores.run_id}", "",
                 f"Champion `{state.champ_row['run_id']}` (lever `{state.champ_row['lever']}`) on {scores.n} documents "
                 "disjoint from the dev draw. Run once; it confirms, it does not tune.", "",
                 f"- mean utility {scores.mean_utility:.3f} (dev {state.champ_scores.mean_utility:.3f})",
                 f"- outcomes {json.dumps(scores.metrics()['outcomes'])}", f"- cost {scores.cost_usd:.4f} USD ({scores.cost_per_doc:.5f} per document)"]
        if gate:
            lines.append(f"- production gate on this slice (no audit trail): {'PASS' if gate['pass'] else 'FAIL'}; "
                         f"pooled {json.dumps(gate['pooled'])}; reasons {gate['reasons']}")
        lines += ["", "## By class", "", "| class | dev | holdout |", "|:---|---:|---:|"]
        dev, hold = state.champ_scores.mean_by_class(), scores.mean_by_class()
        lines += [f"| {c} | {dev.get(c, float('nan')):.3f} | {hold.get(c, float('nan')):.3f} |" for c in sorted(set(dev) | set(hold))]
        return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a temp file in the same directory and ``os.replace``: never a torn file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _charge(scores: scoring.RunScores | None, cap: float, capped: bool, run_dir: Path | None = None) -> float:
    """The ledger cost of a run: what it was billed, never less than what its own budget counted.

    Billed is ``max(scores.cost_usd, api_spend(run_dir))``: the per-agent priced cost of the scored documents, or the
    run's own ``ApiBudget`` view (every item's totals, retried attempts included, plus the usage of documents that
    raised: ``api_spend``), whichever is larger. A round the API cap aborted is charged at least its full cap (only
    spend reaches a cap). A failed round that scored nothing is charged at least the cap when its run directory shows
    that model calls started (``_calls_started``): what it spent is then unknown, and the cap is the most it can have.
    A preflight or config failure, which never reached a model, costs 0. A non-finite figure counts as the cap.
    """
    recorded = scores.cost_usd if scores is not None and scores.n else 0.0
    spend = api_spend(run_dir)
    billed = max(recorded, spend or 0.0)
    if not math.isfinite(billed):
        return round(cap, 6)
    if capped:
        return round(max(cap, billed), 6)
    if scores is not None and scores.n:
        return round(billed, 6)
    return round(max(cap, billed), 6) if _calls_started(run_dir) else 0.0


def _jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    """The JSON objects of a JSONL file; a missing file or an unparseable (torn) line is skipped."""
    out: list[dict[str, Any]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def api_spend(run_dir: Path | None) -> float | None:
    """The USD the run's own ``ApiBudget`` counts for its persisted usage; None when it cannot be priced.

    The budget keeps no counter of its own: on resume the runner rebuilds it from the run directory (``runner._api_budget``),
    so this does the same read: every ``items.jsonl`` row (whose token totals already include the attempts the runner
    retried) plus every ``api_usage_of_failed_document`` event of ``events.jsonl`` (a document that raised after a paid
    call has no item row), priced at the lock's runtime bound (``api_budget.price_bound``: the dearest API model's input
    and output price). A mock run, a run without a lock, or one with an unpriced API model gives None.
    """
    if run_dir is None:
        return None
    from mailroom_sandbox.job.api_budget import FAILED_USAGE_EVENT, spend_estimate

    run_dir = Path(run_dir)
    try:
        lock = json.loads((run_dir / "spec.lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(lock, dict) or (lock.get("job") or {}).get("mock", False):
        return None
    failed = [e.get("detail") for e in _jsonl_dicts(run_dir / "events.jsonl") if e.get("event") == FAILED_USAGE_EVENT]
    records = [*_jsonl_dicts(run_dir / "items.jsonl"), *[d for d in failed if isinstance(d, dict)]]
    try:
        estimate_ = spend_estimate(lock, records)
    except Exception:  # noqa: BLE001 - a usage row the budget cannot read is not a reason to lose the ledger row
        return None
    if estimate_ is None:
        return None
    value = float(estimate_["est_api_usd"])
    return value if math.isfinite(value) else None


def _calls_started(run_dir: Path | None) -> bool:
    """Whether the run's own record shows the job started work: an item row, or a checkpoint past ``prepared``.

    Preflight writes the lock and a ``prepared`` checkpoint and calls no model; ``run start`` replaces it with
    ``running`` before the first document. No run directory (a config failure) or no checkpoint is not started.
    """
    if run_dir is None:
        return False
    run_dir = Path(run_dir)
    try:
        if (run_dir / "items.jsonl").stat().st_size > 0:
            return True
    except OSError:
        pass
    try:
        checkpoint = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(checkpoint, dict) and checkpoint.get("state") in ("running", "paused", "failed", "done")


_CAP_MESSAGE = re.compile(r"api_cost_cap_usd=\S+ reached")


def _aborted_by_cap(run_dir: Path | None, error: str | None) -> bool:
    """Whether the run's own API budget aborted it: its checkpoint says so, else the child's message does."""
    if run_dir is not None:
        try:
            checkpoint = json.loads((Path(run_dir) / "checkpoint.json").read_text(encoding="utf-8"))
            if checkpoint.get("state") == "failed" and (checkpoint.get("last_error") or {}).get("type") == "api_cost_cap":
                return True
        except (OSError, ValueError, AttributeError):
            pass
    return bool(error and _CAP_MESSAGE.search(error))


def _dataset_ids(run_dir: Path) -> set[str]:
    path = Path(run_dir) / "dataset.jsonl"
    if not path.is_file():
        raise AutoresearchError(f"{run_dir}: no dataset.jsonl; cannot check the draw")
    return {str(json.loads(line).get("id")) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _gate_summary(run_dir: Path | None) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    try:
        from mailroom_sandbox.job import gate

        report = gate.gate_report(Path(run_dir), gate.load_bars(), audit=False)
        return {"pass": report["verdict"]["pass"], "reasons": report["verdict"]["reasons"], "pooled": report["pooled"]}
    except Exception:  # noqa: BLE001 - the gate view is informative; scores stand without it
        return None


def _git_head(path: Path) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    head = done.stdout.strip()
    return head if done.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", head) else None
