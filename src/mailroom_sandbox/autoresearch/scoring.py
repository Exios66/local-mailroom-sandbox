"""Per-document utility, cost by role, and the paired comparison of two runs on the same draw.

Everything here is offline and deterministic: it reads a finished run directory (through the
production gate's per-document outcomes) and never calls a model.

Utility of one document, from its gate outcome (weights are configurable per study):

=====================  =========================================================
``correct_archive``    its extraction score (Dojo ``overall_extraction_score``)
``unscorable_archive`` ``unscorable`` weight, 0 by default (no gold to score against)
``review``             ``review`` weight, -0.25 by default
``wrong_archive``      ``wrong_archive`` weight, -1.0 by default
``crashed``            ``crashed`` weight, -1.0 by default
``judge_error``        ``judge_error`` weight, -1.0 by default (checked first)
=====================  =========================================================

A wrong archive is the gate's: archived under the wrong class, or archived with an extraction
score under the quality bar (0.90 by default). The step from 0.90 to -1.0 is deliberate (a wrong
archive costs more than an honest review) and it makes the utility of a single document jumpy;
the paired bootstrap is what tells a real change from that noise.

Cost. ``items.jsonl`` carries per-document totals and, for pipeline runs made after the per-agent
split was persisted, ``usage_by_agent`` (``{agent: {calls, prompt_tokens, completion_tokens,
models}}``). With the split each agent is priced at the model it recorded (``metrics.call_cost``,
tiered); a decisions reviewer bills input tokens only. Without it (older runs) only the totals
exist: the whole document is priced at the run's engine model and ``cost_by_role`` has the single
key ``unsplit``, so the oversight share is unknown (``None``). Mock runs record token counts for
mock calls; their cost is an arithmetic artefact, useful only for exercising the loop.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

SCHEMA = "sandbox.autoresearch.scores/v1"

#: Agents by role. ``classification_arbiter`` is a node of the ``arbiter`` agent, not an agent key.
OVERSIGHT_AGENTS = frozenset({"judge", "arbiter", "boss"})
REVIEWER_AGENTS = frozenset({"sorter_reviewer"})
WORKER_AGENTS = frozenset({"sorter", "intake", "pdf_transcriber", "image_extractor", "relations", "gmail_triage"})
ROLES = ("worker", "oversight", "reviewer", "other")


def role_of(agent: str) -> str:
    """``worker`` (sorter, intake, the specialists), ``oversight`` (judge, arbiter, boss), ``reviewer`` or ``other``."""
    if agent in OVERSIGHT_AGENTS:
        return "oversight"
    if agent in REVIEWER_AGENTS:
        return "reviewer"
    if agent in WORKER_AGENTS or agent.endswith("_specialist"):
        return "worker"
    return "other"


class UtilityWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review: float = -0.25
    wrong_archive: float = -1.0
    crashed: float = -1.0
    judge_error: float = -1.0
    unscorable: float = 0.0


def doc_utility(status: Mapping[str, Any], weights: UtilityWeights) -> float:
    """The utility of one gate document status (see the module table)."""
    if status.get("judge_error"):
        return weights.judge_error
    outcome = status.get("outcome")
    if outcome == "correct_archive":
        return min(1.0, max(0.0, float(status.get("score") or 0.0)))
    return {"unscorable_archive": weights.unscorable, "review": weights.review,
            "wrong_archive": weights.wrong_archive, "crashed": weights.crashed}.get(str(outcome), weights.crashed)


# ---- run scores -------------------------------------------------------------------------------------

@dataclass
class DocScore:
    id: str
    doc_class: str
    outcome: str
    utility: float
    cause: str = ""
    archived_class: str | None = None
    reviewer_doc_type: str | None = None
    judge_error: bool = False
    crash_node: str | None = None
    doc_chars: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    cost_by_role: dict[str, float] = field(default_factory=dict)
    usage_by_agent: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class RunScores:
    run_id: str
    run_dir: str
    docs: list[DocScore]
    price_model: str | None = None
    split_available: bool = False
    unpriced: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.docs)

    def utilities(self) -> dict[str, float]:
        return {d.id: d.utility for d in self.docs}

    def classes(self) -> dict[str, str]:
        return {d.id: d.doc_class for d in self.docs}

    @property
    def mean_utility(self) -> float:
        return math.fsum(d.utility for d in self.docs) / self.n if self.n else 0.0

    def mean_by_class(self) -> dict[str, float]:
        groups: dict[str, list[float]] = {}
        for d in self.docs:
            groups.setdefault(d.doc_class, []).append(d.utility)
        return {cls: math.fsum(v) / len(v) for cls, v in sorted(groups.items())}

    def count(self, outcome: str) -> int:
        return sum(1 for d in self.docs if d.outcome == outcome)

    @property
    def wrong_archives(self) -> int:
        return self.count("wrong_archive")

    @property
    def cost_usd(self) -> float:
        return math.fsum(d.cost_usd for d in self.docs)

    @property
    def cost_per_doc(self) -> float:
        return self.cost_usd / self.n if self.n else 0.0

    def cost_by_role(self) -> dict[str, float]:
        """Total USD by role over the run (``unsplit`` when per-agent usage was not recorded)."""
        out: dict[str, float] = {}
        for d in self.docs:
            for role, usd in d.cost_by_role.items():
                out[role] = out.get(role, 0.0) + usd
        return out

    @property
    def oversight_cost_share(self) -> float | None:
        """Oversight USD over worker USD (None without the per-agent split or without worker cost)."""
        by_role = self.cost_by_role()
        if not self.split_available or not by_role.get("worker"):
            return None
        return by_role.get("oversight", 0.0) / by_role["worker"]

    def agent_usage(self) -> dict[str, dict[str, Any]]:
        """Tokens by agent over the run: ``{agent: {calls, prompt_tokens, completion_tokens, models}}``."""
        out: dict[str, dict[str, Any]] = {}
        for d in self.docs:
            for agent, slot in d.usage_by_agent.items():
                acc = out.setdefault(agent, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "models": []})
                acc["calls"] += int(slot.get("calls") or 0)
                acc["prompt_tokens"] += int(slot.get("prompt_tokens") or 0)
                acc["completion_tokens"] += int(slot.get("completion_tokens") or 0)
                acc["models"] = sorted({*acc["models"], *(slot.get("models") or [])})
        return out

    def metrics(self) -> dict[str, Any]:
        """The ledger's metrics block."""
        from mailroom_sandbox import scoring_hotfixes as sh

        by_role = self.cost_by_role()
        return {
            "n": self.n, "mean_utility": round(self.mean_utility, 6),
            "mean_utility_by_class": {k: round(v, 6) for k, v in self.mean_by_class().items()},
            "outcomes": {o: self.count(o) for o in ("correct_archive", "wrong_archive", "review", "unscorable_archive", "crashed")},
            "wrong_archives": self.wrong_archives,
            "cost_usd": round(self.cost_usd, 6), "cost_per_doc": round(self.cost_per_doc, 6),
            "cost_by_role": {k: round(v, 6) for k, v in by_role.items()},
            "oversight_cost_share": None if self.oversight_cost_share is None else round(self.oversight_cost_share, 4),
            "cost_split": "by_agent" if self.split_available else "totals_only",
            "price_model": self.price_model, "unpriced": self.unpriced,
            # Utility reads the gate outcomes, which score the hotfixed headline (docs/scoring-hotfixes.md).
            "headline_basis": sh.headline_basis(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "run_id": self.run_id, "run_dir": self.run_dir, "price_model": self.price_model,
                "split_available": self.split_available, "unpriced": self.unpriced,
                "docs": [asdict(d) for d in self.docs]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunScores":
        if data.get("schema") != SCHEMA:
            raise ValueError(f"unsupported scores schema {data.get('schema')!r}")
        return cls(run_id=data["run_id"], run_dir=data["run_dir"], price_model=data.get("price_model"),
                   split_available=bool(data.get("split_available")), unpriced=list(data.get("unpriced") or []),
                   docs=[DocScore(**d) for d in data["docs"]])


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a torn tail line of a live run
    return rows


def _engine_model(run_dir: Path) -> str | None:
    try:
        lock = json.loads((run_dir / "spec.lock.json").read_text(encoding="utf-8"))
        return str((lock.get("engine") or {}).get("model") or "") or None
    except (OSError, ValueError):
        return None


def agent_cost(agent_slot: Mapping[str, Any], fallback_model: str | None) -> tuple[float | None, str | None]:
    """USD of one agent's usage slot and the model it was priced at.

    Priced at the model the slot recorded; several models (a retry on another route) take the dearest.
    ``fallback_model`` (the run's engine model) prices only a slot that recorded NO model; the ``mock`` model
    is free. A recorded model with no price is never swapped for the engine's price: ``(None, model)`` when none of the recorded models
    is priced (see ``unpriced_models`` for the recorded models that are not).
    """
    from mailroom_sandbox.job.metrics import call_cost

    prompt, completion = agent_slot.get("prompt_tokens") or 0, agent_slot.get("completion_tokens") or 0
    calls = max(1, int(agent_slot.get("calls") or 1))
    models = [str(m) for m in agent_slot.get("models") or [] if m] or ([fallback_model] if fallback_model else [])
    priced = [(0.0 if m == "mock" else c, m) for m in models if (c := call_cost(m, prompt, completion, calls=calls)) is not None or m == "mock"]
    if not priced:
        return None, models[0] if models else None
    return max(priced)


def unpriced_models(agent_slot: Mapping[str, Any]) -> list[str]:
    """The models an agent's slot RECORDED that have no price (they are reported, never repriced)."""
    from mailroom_sandbox.job.metrics import call_cost

    return sorted(str(m) for m in agent_slot.get("models") or [] if m and m != "mock" and call_cost(str(m), 1, 1) is None)


def _crash_nodes(run_dir: Path) -> dict[str, str]:
    """The node each document last started and never finished, from ``nodes.jsonl`` (optional telemetry)."""
    open_node: dict[str, tuple[str, str | None]] = {}
    for rec in _jsonl(run_dir / "nodes.jsonl"):
        doc = str(rec.get("doc"))
        if rec.get("status") == "running":
            open_node[doc] = (str(rec.get("node")), rec.get("agent"))
        elif rec.get("status") == "done" and doc in open_node and open_node[doc][0] == rec.get("node"):
            del open_node[doc]
    return {doc: f"{node}|{agent or ''}" for doc, (node, agent) in open_node.items()}


def score_run(run_dir: Path | str, weights: UtilityWeights | None = None, *, bars: Any = None,
              price_model: str | None = None) -> RunScores:
    """Utility and cost of every document of a finished (or partial) run directory.

    ``bars`` defaults to ``config/production/bars.yaml``; ``price_model`` defaults to the run's
    engine model (the price of any agent that recorded no model, and of totals-only items).
    """
    from mailroom_sandbox.job import gate
    from mailroom_sandbox.job.metrics import call_cost

    run_dir = Path(run_dir)
    weights = weights or UtilityWeights()
    report = gate.gate_report(run_dir, bars or gate.load_bars(), audit=False)
    items: dict[str, dict[str, Any]] = {str(r.get("item_id")): r for r in _jsonl(run_dir / "items.jsonl")}
    rows = {str(r.get("id")): r for r in _jsonl(run_dir / "dataset.jsonl")}
    crash = _crash_nodes(run_dir)
    price_model = price_model or _engine_model(run_dir)
    unpriced: set[str] = set()
    split = False
    docs: list[DocScore] = []
    for status in report["docs"]:
        doc_id = str(status["id"])
        item, row = items.get(doc_id) or {}, rows.get(doc_id) or {}
        pred = item.get("pred") or {}
        usage = item.get("usage_by_agent") if isinstance(item.get("usage_by_agent"), dict) else {}
        by_role: dict[str, float] = {}
        if usage:
            split = True
            for agent, slot in usage.items():
                unpriced.update(unpriced_models(slot))
                usd, model = agent_cost(slot, price_model)
                if usd is None:
                    unpriced.add(str(model))
                    continue
                by_role[role_of(agent)] = by_role.get(role_of(agent), 0.0) + usd
        elif item.get("prompt_tokens") is not None or item.get("completion_tokens") is not None:
            usd = call_cost(price_model, item.get("prompt_tokens") or 0, item.get("completion_tokens") or 0,
                            calls=int(item.get("llm_calls") or 1))
            if usd is None:
                unpriced.add(str(price_model))
            else:
                by_role["unsplit"] = usd
        docs.append(DocScore(
            id=doc_id, doc_class=str(status["class"]), outcome=str(status["outcome"]), cause=str(status.get("cause") or ""),
            utility=doc_utility(status, weights), archived_class=status.get("archived_class"),
            reviewer_doc_type=(str(pred.get("reviewer_doc_type")).strip().lower() if pred.get("reviewer_doc_type") else None),
            judge_error=bool(status.get("judge_error")), crash_node=crash.get(doc_id) if status["outcome"] == "crashed" else None,
            doc_chars=len(str(row.get("doc_text") or row.get("text") or "")), tokens=int(status.get("tokens") or 0),
            cost_usd=math.fsum(by_role.values()), cost_by_role=by_role, usage_by_agent=dict(usage)))
    return RunScores(run_id=run_dir.name, run_dir=str(run_dir), docs=docs, price_model=price_model,
                     split_available=split, unpriced=sorted(unpriced))


# ---- paired comparison ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class PairedDelta:
    n: int
    mean: float
    ci_low: float
    ci_high: float
    ci: float
    n_boot: int
    seed: int
    by_class: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {"n": self.n, "mean": round(self.mean, 6), "ci_low": round(self.ci_low, 6), "ci_high": round(self.ci_high, 6),
                "ci": self.ci, "n_boot": self.n_boot, "seed": self.seed,
                "by_class": {k: {m: round(v, 6) for m, v in d.items()} for k, d in self.by_class.items()}}


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return math.nan
    pos = q * (len(sorted_values) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def paired_delta(champ: Mapping[str, float], cand: Mapping[str, float], by_class: Mapping[str, str], *,
                 n_boot: int = 2000, seed: int = 0, ci: float = 0.90) -> PairedDelta:
    """Mean paired utility difference ``cand - champ`` with a stratified percentile bootstrap interval.

    ``champ`` and ``cand`` map document id to utility; only ids in both count (the same frozen draw
    has the same ids, and the loop refuses a run that does not). The bootstrap resamples the paired
    differences with replacement inside each class, keeping every class's size, so a class-rich draw
    cannot swing the interval; ``ci`` is the two-sided level (0.90 = 5th to 95th percentile). A
    ``random.Random(seed)`` makes the interval reproducible.
    """
    if not 0.0 < ci < 1.0:
        raise ValueError("ci must be in (0, 1)")
    if n_boot < 1:
        raise ValueError("n_boot must be >= 1")
    ids = sorted(set(champ) & set(cand))
    strata: dict[str, list[float]] = {}
    for doc_id in ids:
        strata.setdefault(by_class.get(doc_id, "unknown"), []).append(cand[doc_id] - champ[doc_id])
    n = len(ids)
    if not n:
        return PairedDelta(0, math.nan, math.nan, math.nan, ci, n_boot, seed, {})
    mean = math.fsum(x for v in strata.values() for x in v) / n
    rng = random.Random(seed)
    groups = [v for _, v in sorted(strata.items())]
    boots = []
    for _ in range(n_boot):
        total = 0.0
        for diffs in groups:
            k = len(diffs)
            total += math.fsum(diffs[rng.randrange(k)] for _ in range(k))
        boots.append(total / n)
    boots.sort()
    alpha = (1.0 - ci) / 2.0
    return PairedDelta(n, mean, _quantile(boots, alpha), _quantile(boots, 1.0 - alpha), ci, n_boot, seed,
                       {cls: {"n": float(len(v)), "mean": math.fsum(v) / len(v)} for cls, v in sorted(strata.items())})


def usd_per_utility_point(champ: RunScores, cand: RunScores, delta_mean: float, *, point: float = 0.01) -> float | None:
    """Extra USD per document for each ``point`` (0.01) of mean utility gained; None when utility did not rise.

    ``(cand cost per doc - champ cost per doc) / (delta_mean / point)``. Negative means the candidate
    is both better and cheaper.
    """
    if not delta_mean or delta_mean <= 0 or not math.isfinite(delta_mean):
        return None
    return (cand.cost_per_doc - champ.cost_per_doc) / (delta_mean / point)
