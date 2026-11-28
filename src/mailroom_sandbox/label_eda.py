"""Read-only EDA over the merged label truth: coverage, gaps, row pulls and where to label next.

Everything here reads committed files only (no network, no model call):

- the label-repaired release (``reports/datasets/mailroom-dataset-v9.3-label-repaired/``), whose
  provenance CSV is one row per (document, field) target cell with the chosen value, its presence,
  the source that won the vote and every source's vote. It already merges the Hub, the interim
  overlay, the near-gold catalog, reviewed subclass corrections and the owner's decisions;
- the near-gold catalog (``data/labels/gold/*.jsonl``) and the interim overlay
  (``data/labels/interim/*.jsonl``) for the raw label records behind a cell;
- the runbook-v2 split assignments (``config/splits/runbook-v2/assignments.jsonl``);
- optionally a production slice draw, made by the same ``prepare_subset`` the runs use, from the
  cached corpus (``data/cache/``).

Each cell gets a **tier**, from what production scoring does with it:

- ``gate``: a gated class's field the gate counts toward ``min_labelled`` and the headline scores;
- ``unit``: a contract or merger entity field. Those rows are gated and headlined on CUAD / MAUD,
  so an entity label is scored in the suite F1 only (and stands in for an empty CUAD universe);
- ``reported``: a field of a class that is reported but not gated (merger);
- ``unscored``: a field the Dojo does not score, a templated field the gate drops (corporate and
  correspondence ``keywords`` / ``subject_matter``), or a field the subclass registry
  (``config/extraction/subclass_schemas.json``) marks ``not_applicable`` for the document's
  subclass (corporate ``filing_number`` on an indenture or bylaws). Labeling these moves nothing.

The CLI is ``scripts/label_eda.py``; see ``docs/label-eda.md``.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Collection, Iterable, Iterator, Mapping, Sequence

from mailroom_sandbox.paths import repo_root

RELEASE_DIR = Path("reports/datasets/mailroom-dataset-v9.3-label-repaired")
STEM = "mailroom_dataset_v9.3_label_repaired"
SPLITS = Path("config/splits/runbook-v2/assignments.jsonl")
REGISTRY = Path("config/extraction/subclass_schemas.json")
GOLD_DIR = Path("data/labels/gold")
INTERIM_DIR = Path("data/labels/interim")
UNIT_CLASSES = frozenset({"contract", "merger_agreement"})
LABELED = frozenset({"populated", "documented_absence"})
TIERS = ("gate", "unit", "reported", "unscored")
#: Cells the gate counts as labelled: a stated value (a documented absence is truth, not a label).
_GATE_LABEL = "populated"


@dataclass(frozen=True)
class Doc:
    doc_id: str
    doc_class: str
    subclass: str
    hub_subclass: str
    split: str
    chars: int


@dataclass
class Cell:
    doc_id: str
    doc_class: str
    subclass: str
    split: str
    field: str
    tier: str
    presence: str
    value: str
    chosen_source: str
    agreeing_sources: str
    rule: str
    conflict: bool
    needs_human: bool
    evidence: str = ""
    votes: str = ""

    @property
    def labeled(self) -> bool:
        return self.presence in LABELED

    def as_dict(self, *, evidence: bool = False, votes: bool = False) -> dict[str, Any]:
        out = {k: getattr(self, k) for k in ("doc_id", "doc_class", "subclass", "split", "field", "tier",
                                             "presence", "value", "chosen_source", "rule", "conflict",
                                             "needs_human")}
        if evidence:
            out["evidence"] = self.evidence
        if votes:
            out["votes"] = self.votes
        return out


@dataclass
class Labels:
    """The release joined to splits and tiers. ``cells`` is every target cell."""

    docs: dict[str, Doc]
    cells: list[Cell]
    gated: tuple[str, ...]
    min_labelled: int
    release: Path = field(default_factory=Path)

    def by_doc(self) -> dict[str, list[Cell]]:
        out: dict[str, list[Cell]] = defaultdict(list)
        for c in self.cells:
            out[c.doc_id].append(c)
        return out


# --------------------------------------------------------------------------- loading

def _csv_rows(path: Path) -> Iterator[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:  # not splitlines(): values may hold U+2028
        return [json.loads(line) for line in fh if line.strip()]


@lru_cache(maxsize=None)
def _scored(doc_class: str) -> frozenset[str] | None:
    from mailroom_sandbox.job.gate import scored_fields

    return scored_fields(doc_class)


def not_applicable(root: Path | None = None) -> frozenset[tuple[str, str, str]]:
    """``(class, subclass, field)`` the subclass registry marks ``not_applicable``."""
    path = (root or repo_root()) / REGISTRY
    if not path.is_file():
        return frozenset()
    reg = json.loads(path.read_text(encoding="utf-8"))["classes"]
    return frozenset((cls, sub, fld) for cls, cv in reg.items() for sub, sv in (cv.get("subclasses") or {}).items()
                     for fld, fv in (sv.get("fields") or {}).items() if fv.get("effective_status") == "not_applicable")


def tier(doc_class: str, fld: str, gated: Sequence[str], *, subclass: str = "",
         na: Collection[tuple[str, str, str]] = ()) -> str:
    """What production scoring does with a labelled ``fld`` on a ``doc_class`` row (see module doc)."""
    from mailroom_sandbox.job.pair_report import TEMPLATED_FIELDS

    scored = _scored(doc_class)
    if (fld in TEMPLATED_FIELDS.get(doc_class, ()) or (scored is not None and fld not in scored)
            or (doc_class, subclass, fld) in na):
        return "unscored"
    if doc_class in UNIT_CLASSES:
        return "unit" if doc_class in gated else "reported"
    return "gate" if doc_class in gated else "reported"


def load(root: Path | None = None, release: Path | None = None) -> Labels:
    """Read the release, the split assignments and the gate bars into :class:`Labels`."""
    from mailroom_sandbox.job.gate import load_bars

    root = root or repo_root()
    rel = root / (release or RELEASE_DIR)
    bars = load_bars()
    na = not_applicable(root)
    split = {r["id"]: r.get("set") or "" for r in _read_jsonl(root / SPLITS)} if (root / SPLITS).is_file() else {}
    docs: dict[str, Doc] = {}
    for r in _csv_rows(rel / f"{STEM}.csv"):
        docs[r["document_id"]] = Doc(r["document_id"], r["doc_class"], r.get("subclass") or "",
                                     r.get("subclass_hub_v9_3") or "", split.get(r["document_id"], ""),
                                     int(r.get("char_count") or 0))
    cells = []
    for r in _csv_rows(rel / f"{STEM}_label_provenance.csv"):
        if r["field"] == "subclass":
            continue
        d = docs.get(r["document_id"])
        cells.append(Cell(
            doc_id=r["document_id"], doc_class=r["doc_class"], subclass=d.subclass if d else "",
            split=d.split if d else "", field=r["field"],
            tier=tier(r["doc_class"], r["field"], bars.gated, subclass=d.subclass if d else "", na=na),
            presence=r["presence"] or "unlabeled", value=r["value"], chosen_source=r["chosen_source"],
            agreeing_sources=r["agreeing_sources"], rule=r["rule"], conflict=r["conflict"] == "True",
            needs_human=r["needs_human"] == "True", evidence=r["evidence"], votes=r["votes"]))
    return Labels(docs, cells, tuple(bars.gated), bars.min_labelled, rel)


def cache_path(root: Path | None = None, revision: str | None = None) -> Path:
    """The cached corpus ``ground_truth_all.jsonl`` for a family revision (the production pin by default)."""
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION, family_tag_commit

    root = root or repo_root()
    commit = family_tag_commit(revision or FAMILY_HF_REVISION)
    return root / "data/cache" / f"Lucius-Morningstar__mailroom-dataset__{commit[:12]}" / "ground_truth_all.jsonl"


def slice_ids(name: str, root: Path | None = None) -> list[str]:
    """Document ids a production slice draws, by the runs' own ``prepare_subset`` on the cached corpus.

    The draw ignores label overlays (they never change which documents are drawn). Raises
    ``FileNotFoundError`` without the cached ``ground_truth_all.jsonl``.
    """
    import tempfile

    from mailroom_sandbox.corpus import prepare_subset
    from mailroom_sandbox.job.spec import load_run_spec

    root = root or repo_root()
    spec = load_run_spec(root / "config/runs/production" / f"{name}.yaml").dataset
    cache = cache_path(root, spec.revision)
    if not cache.is_file():
        raise FileNotFoundError(f"{cache} is not cached (sandbox datasets pull)")
    ds = spec.model_copy(update={"provider": "file", "local_path": str(cache), "interim_labels": False,
                                 "near_gold_labels": False, "staged_overlay": None})
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "draw.jsonl"
        prepare_subset(ds, dest)
        return [r["id"] for r in _read_jsonl(dest)]


# --------------------------------------------------------------------------- selection

@dataclass
class Filter:
    doc_ids: frozenset[str] | None = None
    doc_class: str | None = None
    subclass: str | None = None
    split: str | None = None
    fields: frozenset[str] | None = None
    tiers: frozenset[str] | None = None
    presence: frozenset[str] | None = None
    source: str | None = None
    rule: str | None = None
    needs_human: bool = False
    conflict: bool = False

    def doc_ok(self, d: Doc) -> bool:
        """The document-level part of the filter (ids, class, subclass, split)."""
        return ((self.doc_ids is None or d.doc_id in self.doc_ids)
                and (self.doc_class is None or d.doc_class == self.doc_class)
                and (self.subclass is None or d.subclass.lower() == self.subclass.lower())
                and (self.split is None or d.split == self.split))

    def __call__(self, c: Cell) -> bool:
        return ((self.doc_ids is None or c.doc_id in self.doc_ids)
                and (self.doc_class is None or c.doc_class == self.doc_class)
                and (self.subclass is None or c.subclass.lower() == self.subclass.lower())
                and (self.split is None or c.split == self.split)
                and (self.fields is None or c.field in self.fields)
                and (self.tiers is None or c.tier in self.tiers)
                and (self.presence is None or c.presence in self.presence)
                and (self.source is None or self.source in c.agreeing_sources.split("|")
                     or c.chosen_source == self.source)
                and (self.rule is None or c.rule == self.rule)
                and (not self.needs_human or c.needs_human)
                and (not self.conflict or c.conflict))


def select(labels: Labels, flt: Filter) -> list[Cell]:
    return [c for c in labels.cells if flt(c)]


# --------------------------------------------------------------------------- summaries

def coverage(cells: Iterable[Cell], by: Sequence[str]) -> list[dict[str, Any]]:
    """Completeness grouped by ``by`` (any of doc_class, subclass, field, split, tier, chosen_source)."""
    groups: dict[tuple, Counter] = defaultdict(Counter)
    docs: dict[tuple, set] = defaultdict(set)
    for c in cells:
        key = tuple(getattr(c, k) for k in by)
        g = groups[key]
        g["cells"] += 1
        g[c.presence] += 1
        g["labeled"] += c.labeled
        g["needs_human"] += c.needs_human
        g["conflict"] += c.conflict
        docs[key].add(c.doc_id)
    out = []
    for key, g in sorted(groups.items()):
        out.append({**dict(zip(by, key)), "docs": len(docs[key]), "cells": g["cells"], "labeled": g["labeled"],
                    "completeness": round(g["labeled"] / g["cells"], 4) if g["cells"] else 1.0,
                    "populated": g["populated"], "absent": g["documented_absence"],
                    "unlabeled": g["unlabeled"], "disputed": g["disputed_unresolved"],
                    "needs_human": g["needs_human"]})
    return out


def gate_labelled(cells: Iterable[Cell]) -> int:
    """The gate's labelled count for one document's ``gate`` cells (stated values only)."""
    return sum(1 for c in cells if c.tier == "gate" and c.presence == _GATE_LABEL)


def unscorable(labels: Labels, flt: Filter) -> list[dict[str, Any]]:
    """Gated non-unit documents below ``min_labelled`` stated gate labels, with their open gate fields.

    An approximation of ``gate.labelled_count`` from the release (before SHF-015 / SHF-019 drops,
    which only lower it), so every document listed is unscorable on the release truth too.
    """
    out = []
    for doc_id, cells in sorted(labels.by_doc().items()):
        d = labels.docs.get(doc_id)
        if d is None or d.doc_class not in labels.gated or d.doc_class in UNIT_CLASSES:
            continue
        mine = [c for c in cells if flt(c)]
        if not mine:
            continue
        n = gate_labelled(cells)
        if n < labels.min_labelled:
            out.append({"doc_id": doc_id, "doc_class": d.doc_class, "subclass": d.subclass, "split": d.split,
                        "gate_labelled": n, "open_gate_fields": sorted(c.field for c in cells
                                                                       if c.tier == "gate" and not c.labeled)})
    return out


def unit_unscorable(labels: Labels, flt: Filter, root: Path | None = None) -> list[dict[str, Any]] | None:
    """Gated unit-class documents (contract: CUAD) below ``min_labelled``, by ``gate.labelled_count``.

    The gate counts a contract's CUAD clause labels, which the release does not carry, so this reads
    the cached corpus row (the Hub CUAD map, before overlays) and counts it with the production
    function. ``None`` without the cached corpus.
    """
    from mailroom_sandbox.job.gate import labelled_count

    want = {d.doc_id: d for d in labels.docs.values()
            if d.doc_class in labels.gated and d.doc_class in UNIT_CLASSES and flt.doc_ok(d)}
    if not want:
        return []
    cache = cache_path(root)
    if not cache.is_file():
        return None
    out = []
    for row in _read_jsonl(cache):
        d = want.get(row.get("id"))
        if d is None:
            continue
        n = labelled_count(row, d.doc_class)
        if n < labels.min_labelled:
            out.append({"doc_id": d.doc_id, "doc_class": d.doc_class, "subclass": d.subclass, "split": d.split,
                        "gate_labelled": n, "open_gate_fields": ["cuad_clause_labels"]})
    return sorted(out, key=lambda r: r["doc_id"])


def gaps(cells: Iterable[Cell], *, top: int = 30) -> list[dict[str, Any]]:
    """Unlabeled or disputed cells grouped by (class, subclass, field), most first."""
    count: Counter = Counter()
    docs: dict[tuple, list[str]] = defaultdict(list)
    for c in cells:
        if c.labeled:
            continue
        key = (c.doc_class, c.subclass, c.field, c.tier)
        count[key] += 1
        docs[key].append(c.doc_id)
    return [{"doc_class": k[0], "subclass": k[1], "field": k[2], "tier": k[3], "open_cells": n,
             "example_docs": sorted(docs[k])[:3]} for k, n in count.most_common(top)]


def focus(labels: Labels, flt: Filter, *, top: int = 25) -> dict[str, Any]:
    """Where label work moves production numbers most, in order.

    1. gated documents below ``min_labelled`` (unscorable: every label there adds a scored document;
       a contract counts its CUAD labels, read from the cached corpus when it is present);
    2. open ``gate`` cells, by (class, subclass, field);
    3. open ``unit`` and ``reported`` cells (suite F1 and reported classes only);
    4. the human queue: disputed values and ``needs_human`` cells to settle.
    ``unscored`` cells are left out on purpose.
    """
    cells = select(labels, flt)
    open_ = [c for c in cells if not c.labeled]
    units = unit_unscorable(labels, flt)
    return {
        "scope": {"cells": len(cells), "docs": len({c.doc_id for c in cells})},
        "1_unscorable_docs": unscorable(labels, flt) + (units or []),
        "unit_class_count": ("skipped: gated contract documents are counted on their CUAD labels, which "
                             "need the cached corpus (sandbox datasets pull)") if units is None
                            else "contract documents counted on their CUAD labels in the cached corpus",
        "2_gate_gaps": gaps([c for c in open_ if c.tier == "gate"], top=top),
        "3_suite_and_reported_gaps": gaps([c for c in open_ if c.tier in ("unit", "reported")], top=top),
        "4_human_queue": {"disputed": sum(c.presence == "disputed_unresolved" for c in cells),
                          "needs_human": sum(c.needs_human for c in cells)},
        "skipped_unscored_open_cells": sum(c.tier == "unscored" for c in open_),
    }


def doc_card(labels: Labels, doc_id: str, root: Path | None = None) -> dict[str, Any]:
    """Every cell of one document, with its votes, plus the raw near-gold and interim records."""
    root = root or repo_root()
    d = labels.docs.get(doc_id)
    if d is None:
        raise KeyError(f"{doc_id} is not in the release")
    cells = sorted((c for c in labels.cells if c.doc_id == doc_id), key=lambda c: (TIERS.index(c.tier), c.field))
    return {"doc": vars(d), "gate_labelled": gate_labelled(cells), "min_labelled": labels.min_labelled,
            "cells": [c.as_dict(evidence=True, votes=True) for c in cells],
            "near_gold_records": catalog_records(root, doc_ids={doc_id}),
            "interim_records": interim_records(root, doc_ids={doc_id})}


# --------------------------------------------------------------------------- raw label stores

def catalog_records(root: Path | None = None, *, doc_ids: Iterable[str] | None = None, doc_class: str | None = None,
                    fields: Iterable[str] | None = None, status: str | None = None) -> list[dict[str, Any]]:
    """Near-gold catalog records (``data/labels/gold``), filtered."""
    root = root or repo_root()
    ids = set(doc_ids) if doc_ids is not None else None
    flds = set(fields) if fields is not None else None
    out = []
    for path in sorted((root / GOLD_DIR).glob("*.jsonl")):
        if doc_class and path.stem != doc_class:
            continue
        for r in _read_jsonl(path):
            if ((ids is None or r.get("doc_id") in ids) and (flds is None or r.get("field") in flds)
                    and (status is None or r.get("status") == status)):
                out.append({"store": "near_gold", "doc_class": path.stem, **r})
    return out


def interim_records(root: Path | None = None, *, doc_ids: Iterable[str] | None = None,
                    doc_class: str | None = None, fields: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Interim overlay records (``data/labels/interim``), one per labelled field, filtered."""
    root = root or repo_root()
    ids = set(doc_ids) if doc_ids is not None else None
    flds = set(fields) if fields is not None else None
    out = []
    for path in sorted((root / INTERIM_DIR).glob("*.jsonl")):
        if doc_class and path.stem != doc_class:
            continue
        for r in _read_jsonl(path):
            if ids is not None and r.get("doc_id") not in ids:
                continue
            for fld, lab in sorted((r.get("labels") or {}).items()):
                if flds is None or fld in flds:
                    out.append({"store": "interim", "doc_class": path.stem, "doc_id": r.get("doc_id"),
                                "field": fld, **(lab if isinstance(lab, Mapping) else {"value": lab})})
    return out


def source_mix(cells: Iterable[Cell]) -> list[dict[str, Any]]:
    """Which source won the labelled cells, by class (how much truth rests on the Hub alone)."""
    mix: dict[str, Counter] = defaultdict(Counter)
    for c in cells:
        if c.labeled:
            mix[c.doc_class][c.chosen_source] += 1
    return [{"doc_class": k, "labeled": sum(v.values()), **dict(v.most_common())} for k, v in sorted(mix.items())]
