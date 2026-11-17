"""The lever catalog: one config change each, applied to a run spec as a dotted-path patch.

A lever is ``{id, node, classes, description, patch}``. ``patch`` maps dotted spec paths to
values (``agent_models.sorter: <model>``); a ``null`` value deletes the key. Applying a patch
deep-copies the spec, and the result is validated with the real ``RunSpec`` model, so a typo in a
path or a value fails when the catalog is loaded, not three rounds into a paid study.

Optional fields:

- ``node``: the weakness node(s) the lever attaches to (a name or a list). The proposer only
  tries a lever against a node that lost utility.
- ``requires_env``: an environment variable that must be set, else the loop skips the lever.
- ``tier`` / ``group``: an ordering ladder. Within one weakness the proposer tries the lowest tier first.
- ``requires``: a list of alternatives, any one of which unlocks the lever; each alternative is a
  mapping of conditions that must all hold. Conditions, over the ledger so far:

  ``kept: {group, tier}``                a lever of that group/tier was kept
  ``all_reverted_positive: {group, tier}``  every tried lever of that group/tier was reverted, at least one was
                                          tried and each had a positive mean delta
  ``kept_lever: <id>``                   that lever was kept
  ``budget_multiple: N``                 the remaining study budget is at least N round caps

- ``goal``: ``quality`` (default) or ``cost``. A cost lever is kept when it is not worse and is cheaper.
- ``round_cap_usd``: an explicit ``job.api_cost_cap_usd`` for this lever's round (clamped to the study's
  ``max_round_cap_usd``). ``round_cap_auto: true`` derives it instead: the runtime-bound estimate x 1.2 rounded up
  to $0.25 (never below the study's round cap, never above ``max_round_cap_usd``), or a per-tier default
  (1.5 / 3 / 4 USD) while the champion has no token measurement. Supervisor levers use ``round_cap_auto``.
- ``estimate_safety``: a factor on the pre-run cost estimate for a lever that adds model calls (multiplied
  with the study's ``estimate_safety``).
- ``pipeline_source``: ``{env, commit}``, a lever that runs the round with another pipeline source
  tree (``MAILROOM_SRC`` is set for that run's process only, to the path in the environment
  variable ``env``). The tree's git ``HEAD`` must equal ``commit`` when given. The run lock records
  the tree's sha256 (``dependency_sources.pipeline``), which the ledger copies. The spec is unchanged,
  so ``patch`` may be empty; ``requires_env`` defaults to ``env``.

``placements`` derive cost levers from a kept lever: for every kept lever of ``group``, one lever
per subset of roles that keep the winner. The derived patch is absolute and comes from the winner's own
ledger row, never from the champion's current state: roles it keeps are set to the WINNER's own patch values,
roles it restores are set to the values the champion had just before the winner was kept (``patch_before``
in the row; the base spec's value for a row without it). A winner that a later kept lever of the same group
has superseded on the placement's role paths derives nothing.
"""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA = "sandbox.autoresearch.levers/v1"
# A study compares candidates on one frozen draw: a lever may not move the draw, the run id or the
# mock switch (those belong to the study, which sets them per round).
FORBIDDEN_ROOTS = frozenset({"dataset", "run_id", "schema", "task", "target"})
FORBIDDEN_PATHS = frozenset({"job.mock", "job.mode", "job.max_wall_seconds", "job.api_cost_cap_usd"})
CONDITIONS = frozenset({"kept", "all_reverted_positive", "kept_lever", "budget_multiple"})


class LeverError(ValueError):
    """A lever that is malformed, patches a path it may not, or yields an invalid run spec."""


class PipelineSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    env: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class Lever(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._@+-]*$", max_length=80)
    node: str | list[str]
    classes: str | list[str] = "all"
    description: str = Field(min_length=1)
    patch: dict[str, Any] = Field(default_factory=dict)
    pipeline_source: PipelineSource | None = None
    requires_env: str | None = None
    tier: int | None = Field(default=None, ge=1)
    group: str | None = None
    requires: list[dict[str, Any]] = Field(default_factory=list)
    goal: str = "quality"
    round_cap_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    round_cap_auto: bool = False
    estimate_safety: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @field_validator("classes")
    @classmethod
    def _classes(cls, value: str | list[str]) -> str | list[str]:
        if value == "all":
            return value
        if isinstance(value, str) or not value:
            raise ValueError("classes must be 'all' or a non-empty list of document classes")
        return value

    @field_validator("goal")
    @classmethod
    def _goal(cls, value: str) -> str:
        if value not in ("quality", "cost"):
            raise ValueError("goal must be 'quality' or 'cost'")
        return value

    @field_validator("patch")
    @classmethod
    def _patch(cls, value: dict[str, Any]) -> dict[str, Any]:
        for path in value:
            parts = path.split(".")
            if not path or any(not p for p in parts):
                raise ValueError(f"patch path {path!r} is not a dotted path")
            if parts[0] in FORBIDDEN_ROOTS or path in FORBIDDEN_PATHS:
                raise ValueError(f"patch path {path!r} is set by the study, not by a lever")
        return value

    @field_validator("requires")
    @classmethod
    def _requires(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for alternative in value:
            unknown = set(alternative) - CONDITIONS
            if not alternative or unknown:
                raise ValueError(f"requires alternative {alternative!r}: conditions are {sorted(CONDITIONS)}")
        return value

    @model_validator(mode="after")
    def _ladder(self) -> "Lever":
        if self.tier is not None and not self.group:
            raise ValueError("a lever with a tier needs a group")
        if not self.patch and self.pipeline_source is None:
            raise ValueError("a lever needs a patch or a pipeline_source")
        if self.pipeline_source is not None and self.requires_env is None:
            self.requires_env = self.pipeline_source.env
        if self.round_cap_usd is not None and self.round_cap_auto:
            raise ValueError("a lever sets round_cap_usd or round_cap_auto, not both")
        return self

    @property
    def nodes(self) -> list[str]:
        return [self.node] if isinstance(self.node, str) else list(self.node)

    def covers(self, doc_class: str) -> bool:
        return self.classes == "all" or doc_class in self.classes


class Placement(BaseModel):
    """Derive cost levers from every kept lever of ``group``: the winner on a subset of ``roles``."""
    model_config = ConfigDict(extra="forbid")

    group: str
    roles: list[str] = Field(min_length=2)
    keep_on: list[list[str]] = Field(min_length=1)
    path: str = "agent_routes.{role}"

    @model_validator(mode="after")
    def _subsets(self) -> "Placement":
        for subset in self.keep_on:
            if not subset or set(subset) - set(self.roles) or set(subset) == set(self.roles):
                raise ValueError(f"keep_on {subset!r} must be a proper, non-empty subset of {self.roles}")
        return self


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: str = Field(default=SCHEMA, alias="schema")
    levers: list[Lever] = Field(min_length=1)
    placements: list[Placement] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> "Catalog":
        ids = [lever.id for lever in self.levers]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate lever ids {dupes}")
        if self.schema_name != SCHEMA:
            raise ValueError(f"unsupported levers schema {self.schema_name!r}")
        return self


def load_levers(path: str | Path) -> Catalog:
    """Load and shape-check a lever catalog (``apply`` and ``validate_catalog`` check it against a spec)."""
    path = Path(path)
    try:
        return Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (ValueError, yaml.YAMLError) as exc:
        raise LeverError(f"{path}: {exc}") from exc


def apply_patch(spec: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """A deep copy of ``spec`` with every dotted path of ``patch`` set; a ``None`` value deletes the key.

    Missing (or ``null``) intermediate mappings are created. A path through a scalar is an error.
    """
    out = copy.deepcopy(dict(spec))
    for path, value in patch.items():
        *parents, leaf = path.split(".")
        node: dict[str, Any] = out
        for key in parents:
            child = node.get(key)
            if child is None:
                if value is None:
                    node = {}  # deleting under a missing parent: nothing to do
                    break
                child = node[key] = {}
            if not isinstance(child, dict):
                raise LeverError(f"patch path {path!r}: {key!r} is {type(child).__name__}, not a mapping")
            node = child
        else:
            if value is None:
                node.pop(leaf, None)
            else:
                node[leaf] = copy.deepcopy(value)
    return out


def validate_spec(spec: Mapping[str, Any], *, where: str = "spec"):
    """The ``RunSpec`` of a spec dict; any validation error is a ``LeverError`` naming ``where``."""
    from pydantic import ValidationError

    from mailroom_sandbox.job.spec import RunSpec

    try:
        return RunSpec.model_validate(dict(spec))
    except (ValidationError, ValueError) as exc:
        first = exc.errors()[0] if isinstance(exc, ValidationError) and exc.errors() else None
        detail = f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}" if first else str(exc)
        raise LeverError(f"{where}: {' '.join(detail.split())}") from exc


def apply_lever(spec: Mapping[str, Any], lever: Lever) -> dict[str, Any]:
    """``spec`` patched by ``lever`` and validated as a ``RunSpec``."""
    patched = apply_patch(spec, lever.patch)
    validate_spec(patched, where=f"lever {lever.id}")
    return patched


def env_ready(lever: Lever, env: Mapping[str, str] | None = None) -> bool:
    """Whether the lever's ``requires_env`` variable (if any) is set to a non-blank value."""
    if not lever.requires_env:
        return True
    return bool((os.environ if env is None else env).get(lever.requires_env, "").strip())


# ---- ordering ---------------------------------------------------------------------------------

def _tried(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """The latest decided ledger row per lever id (skips, warnings, the baseline and the replicate excluded)."""
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if row.get("decision") in ("keep", "revert", "error", "aborted_cap"):
            out[str(row.get("lever"))] = row
    return out


def requirement_met(lever: Lever, catalog: Sequence[Lever], rows: Sequence[Mapping[str, Any]], *,
                    budget_remaining_usd: float | None = None, round_cap_usd: float | None = None) -> bool:
    """Whether ``lever`` is unlocked by the ledger ``rows`` (always true without ``requires``)."""
    if not lever.requires:
        return True
    tried = _tried(rows)

    def in_group(group: str, tier: int | None) -> list[Lever]:
        return [item for item in catalog if item.group == group and (tier is None or item.tier == tier)]

    def holds(name: str, arg: Any) -> bool:
        if name == "kept":
            return any(tried.get(item.id, {}).get("decision") == "keep" for item in in_group(arg["group"], arg.get("tier")))
        if name == "kept_lever":
            return tried.get(str(arg), {}).get("decision") == "keep"
        if name == "all_reverted_positive":
            # Every lever of the tier must have been decided: reverted, or aborted by its API cap (an aborted
            # run has no verdict and does not block the ladder). A skipped one, over the round cap or a no-op,
            # cannot be run and does not block it either; an error is not a decision. Every revert needs a
            # positive mean delta; an aborted round carries none.
            skipped = {str(r.get("lever")) for r in rows if r.get("decision") == "skipped"}
            members = [item for item in in_group(arg["group"], arg.get("tier")) if item.id not in skipped or item.id in tried]
            if not members or any(item.id not in tried for item in members):
                return False
            done = [tried[item.id] for item in members]
            if any(row.get("decision") not in ("revert", "aborted_cap") for row in done):
                return False
            return all((row.get("delta") or {}).get("mean", 0.0) > 0 for row in done if row.get("decision") == "revert")
        if name == "budget_multiple":
            if budget_remaining_usd is None or not round_cap_usd:
                return False
            return budget_remaining_usd >= float(arg) * float(round_cap_usd)
        raise LeverError(f"unknown condition {name!r} on lever {lever.id}")  # pragma: no cover - validated at load

    return any(all(holds(name, arg) for name, arg in alternative.items()) for alternative in lever.requires)


def derive_placements(catalog: Catalog, base_spec: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[Lever]:
    """Cost levers for every kept lever of a placement group: the winner on a subset of its roles.

    The patch is absolute, derived from the winner's own patch and its ledger row, never from the
    champion's current state (which later keeps and kept placements have moved):

    - a role in the subset is set to the WINNER's own value at the role's path;
    - a role left out is set to the value the champion had just before the winner was kept
      (``patch_before`` of the winner's row), else the BASE spec's value; deleted when there was none.

    The winner must be kept and not superseded: a later kept lever of the same group that patches any of
    the placement's role paths replaces the winner's routes, so its placements would put the old winner
    back. The derived lever requires its winner to be kept.
    """
    positions: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for pos, row in enumerate(rows):
        if row.get("decision") in ("keep", "revert", "error", "aborted_cap"):
            positions[str(row.get("lever"))] = (pos, row)
    kept = {lever_id: found for lever_id, found in positions.items() if found[1].get("decision") == "keep"}
    out: list[Lever] = []
    for placement in catalog.placements:
        paths = {role: placement.path.format(role=role) for role in placement.roles}
        for winner in catalog.levers:
            if winner.group != placement.group or winner.id not in kept:
                continue
            pos, win_row = kept[winner.id]
            superseded = any(other.id != winner.id and other.group == placement.group and other.id in kept
                             and kept[other.id][0] > pos and set(other.patch) & set(paths.values())
                             for other in catalog.levers)
            if superseded:
                continue
            before = win_row.get("patch_before") if isinstance(win_row.get("patch_before"), Mapping) else {}
            for subset in placement.keep_on:
                restore = [role for role in placement.roles if role not in subset]
                patch: dict[str, Any] = {}
                for role in subset:
                    if paths[role] in winner.patch:
                        patch[paths[role]] = copy.deepcopy(winner.patch[paths[role]])
                for role in restore:
                    path = paths[role]
                    patch[path] = copy.deepcopy(before[path]) if path in before else lookup(base_spec, path)
                out.append(Lever(
                    id=f"{winner.id}@{'+'.join(subset)}", node=list(placement.roles), classes="all", goal="cost",
                    description=f"{winner.id} on {'+'.join(subset)} only; {', '.join(restore)} back to the routing before {winner.id}",
                    patch=patch, group=f"{placement.group}-placement", tier=1,
                    requires=[{"kept_lever": winner.id}],
                    round_cap_usd=winner.round_cap_usd, round_cap_auto=winner.round_cap_auto))
    return out


def lookup(spec: Mapping[str, Any], path: str) -> Any:
    """A deep copy of the value at a dotted ``path`` of ``spec`` (None when any step is missing)."""
    node: Any = spec
    for key in path.split("."):
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return copy.deepcopy(node)


def all_levers(catalog: Catalog, base_spec: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[Lever]:
    """The catalog's levers plus the placement levers the ledger has unlocked."""
    return [*catalog.levers, *derive_placements(catalog, base_spec, rows)]


def validate_catalog(catalog: Catalog, base_spec: Mapping[str, Any]) -> list[str]:
    """Every problem of ``catalog`` against ``base_spec``: invalid patched specs, dead patches, unknown requires.

    A paid (non-mock) study also refuses a base or patched spec whose reviewer is not a Decisions-API model on
    the ``decisions`` backend (``reviewer_errors``). Empty when the catalog is sound. Does not touch the
    network or any environment variable.
    """
    problems: list[str] = []
    problems.extend(f"base spec: {msg}" for msg in reviewer_errors(base_spec))
    ids = {lever.id for lever in catalog.levers}
    groups = {(lever.group, lever.tier) for lever in catalog.levers}
    for lever in catalog.levers:
        try:
            patched = apply_lever(base_spec, lever)
        except LeverError as exc:
            problems.append(str(exc))
            continue
        if patched == dict(base_spec) and lever.pipeline_source is None:
            problems.append(f"lever {lever.id}: the patch changes nothing in the base spec")
        problems.extend(f"lever {lever.id}: {msg}" for msg in context_errors(patched))
        problems.extend(f"lever {lever.id}: {msg}" for msg in reviewer_errors(patched))
        for alternative in lever.requires:
            for name, arg in alternative.items():
                if name == "kept_lever" and arg not in ids:
                    problems.append(f"lever {lever.id}: requires unknown lever {arg!r}")
                if name in ("kept", "all_reverted_positive") and (arg.get("group"), arg.get("tier")) not in groups:
                    problems.append(f"lever {lever.id}: requires {name} of an empty group/tier {arg!r}")
    return problems


# ---- the reviewer is a Decisions-API model, or the chat reviewer the baseline omits ---------------------

def reviewer_errors(spec: Mapping[str, Any]) -> list[str]:
    """Why a paid study may not run ``spec``'s reviewer (empty for a mock study or an absent block).

    The baseline has no ``reviewer`` block, so the taxonomy's chat ``sorter_reviewer`` runs, and that stays
    allowed. A reviewer block that is present must be the OpenRouter Decisions API: backend ``decisions``, a
    pinned model of ``config/decision_models.yaml``, and no ``allow_chat_model`` escape hatch. The ``jev``,
    ``local``, ``api`` and ``mock`` backends are refused.
    """
    from mailroom_sandbox.decision_backends import is_decisions_model

    if bool((spec.get("job") or {}).get("mock", True)):
        return []
    block = spec.get("reviewer")
    if not block:
        return []
    errors: list[str] = []
    if block.get("backend") != "decisions":
        errors.append(f"reviewer backend {block.get('backend')!r} is refused in a paid study: "
                      "decision models run only on the OpenRouter Decisions endpoint (backend decisions)")
    if block.get("allow_chat_model"):
        errors.append("reviewer allow_chat_model is refused in a paid study: the reviewer is a Decisions-API model")
    if not is_decisions_model(block.get("model")):
        errors.append(f"reviewer model {block.get('model')!r} is not a Decisions-API model of config/decision_models.yaml")
    return errors


# ---- reviewer input vs the model's context -------------------------------------------------------

# Conservative sizing: 0.25 tokens per character (the measured fit is 0.2073) plus the question text.
TOKENS_PER_CHAR = 0.25
QUESTION_TOKENS = 4000


def reviewer_request_tokens(max_input_chars: int) -> int:
    """Upper estimate of one Decisions request: the document capped at ``max_input_chars`` plus the questions."""
    return int(max_input_chars * TOKENS_PER_CHAR) + QUESTION_TOKENS


def context_errors(spec: Mapping[str, Any]) -> list[str]:
    """Reviewer (and gate) requests that cannot fit the Decisions model's context.

    The input cap of a reviewer is its question set's ``max_input_chars``: the spec has no per-run
    override, so a model with a small window needs a question set that caps lower.
    """
    from mailroom_sandbox.decision_backends import decision_model, load_question_set

    errors: list[str] = []
    for block, label in ((spec.get("reviewer") or {}, "reviewer"), (spec.get("extraction_gate") or {}, "extraction_gate")):
        model, stem = block.get("model"), block.get("questions")
        row = decision_model(model)
        if not row or not stem or (label == "reviewer" and block.get("backend") != "decisions"):
            continue
        try:
            chars = int(load_question_set(str(stem)).get("max_input_chars") or 0)
        except Exception as exc:  # noqa: BLE001 - reported, not raised: the catalog check lists every problem
            errors.append(f"{label} question set {stem!r}: {exc}")
            continue
        need, window = reviewer_request_tokens(chars), row.get("context_length") or 0
        if window and need > window:
            errors.append(f"{label} {model}: question set {stem} sends up to ~{need:,} tokens "
                          f"(max_input_chars {chars:,}), over its {window:,}-token context")
    return errors


def slug(text: str, *, limit: int = 40) -> str:
    """A lever id as a run-id fragment: letters, digits, dot, underscore and hyphen only."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:limit] or "lever"
