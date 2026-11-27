"""Phase 5 part 2: the generated merger tables (``config/extraction/merger_tables.json``).

Everything here comes from the Dojo's merger definitions (``llm_dojo_scoring.schemas.maud_schema``)
plus a few committed choices, and ``scripts/build_merger_tables.py --check`` keeps the file fresh:

* ``subclass_drop``: the consideration-amount field a subclass does not use (``job.merger.subclass_fields``).
  Of ``per_share_cash_amount`` and ``exchange_ratio``, a subclass keeps those its Dojo entity hints
  name; one that names neither keeps both.
* ``groups`` / ``merged_groups`` / ``main_owned``: which read owns each MAUD question, for 1 to 3
  group reads (``job.merger.question_groups``). Every question has exactly one owner.
* ``near_universal``: MAUD questions labelled on at least 90% of the **calibration-set** mergers of
  ``config/splits/runbook-v2/assignments.jsonl``; an unanswered one is a gap-retry target. Dev and
  sealed held-out documents are never read for it.
* ``required_entities`` / ``entity_sections``: entity fields every executed merger agreement states,
  and the section the gap retry reads each from.

Design: docs/design/specs/2026-11-27-phase5-merger-maud-design.md.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from mailroom_sandbox.paths import repo_root, vendored_dojo_src

SCHEMA_ID = "mailroom.merger_tables/v1"
TABLES_PATH = repo_root() / "config" / "extraction" / "merger_tables.json"
ASSIGNMENTS_PATH = repo_root() / "config" / "splits" / "runbook-v2" / "assignments.jsonl"
#: The Hub revision the stage-1 runs draw (config/runs/p4-s1-verify-gov-off.yaml).
DATASET_REVISION = "ff4ca546d4346991628c2616ae014afc15e9fe04"
DATASET_GT = (repo_root() / "data" / "cache" / "hf" / "hub" / "datasets--Lucius-Morningstar--mailroom-dataset"
              / "snapshots" / DATASET_REVISION / "parquet" / "ground_truth")
NEAR_UNIVERSAL_SHARE = 0.90

AMOUNT_FIELDS = ("per_share_cash_amount", "exchange_ratio")
REQUIRED_BASE = ("document_name", "parties", "acquirer", "target", "governing_law", "outside_date")
ENTITY_SECTIONS = {
    "document_name": "preamble", "parties": "preamble", "acquirer": "preamble", "target": "preamble",
    "governing_law": "governing_law", "outside_date": "termination",
    "per_share_cash_amount": "consideration", "exchange_ratio": "consideration",
}
#: Dojo groups whose questions the main (whole-document) read owns.
MAIN_GROUPS = ("General Information", "Knowledge", "Material Adverse Effect", "Remedies")
#: The Dojo's 12-question Deal Protection group, split in two (committed choice).
DEAL_PROTECTION_1 = (
    "No-Shop",
    "Fiduciary exception:  Board determination (no-shop)",
    "Superior Offer Definition",
    "Intervening Event Definition",
    "Tail Period & Acquisition Proposal Details",
    "Breach of No Shop",
)
DEAL_PROTECTION = "Deal Protection and Related Provisions"
GROUP_3 = ("Conditions to Closing", "Operating and Efforts Covenant")


def _ensure_dojo() -> None:
    src = vendored_dojo_src()
    if src is not None and str(src) not in sys.path:
        sys.path.insert(0, str(src))


# --------------------------------------------------------------------------- build


def _drop_table() -> dict[str, list[str]]:
    from llm_dojo_scoring.schemas import maud_schema as ms

    out: dict[str, list[str]] = {}
    for sub in ms.MAUD_CONSIDERATION_SUBCLASSES:
        token = getattr(sub, "token", sub)
        named = {h.name for h in ms.consideration_subclass(token).entity_hints}
        kept = [f for f in AMOUNT_FIELDS if f in named] or list(AMOUNT_FIELDS)
        out[token] = [f for f in AMOUNT_FIELDS if f not in kept]
    return out


def _group_table() -> tuple[dict[str, list[str]], list[str]]:
    from llm_dojo_scoring.schemas.maud_schema import maud_questions

    groups: dict[str, list[str]] = {"1": [], "2": [], "3": []}
    main: list[str] = []
    for q in maud_questions():
        group = q.group.strip()
        if group in MAIN_GROUPS:
            main.append(q.name)
        elif group == DEAL_PROTECTION:
            groups["1" if q.name in DEAL_PROTECTION_1 else "2"].append(q.name)
        elif group in GROUP_3:
            groups["3"].append(q.name)
        else:
            raise ValueError(f"MAUD question {q.name!r} is in an unmapped Dojo group {q.group!r}")
    missing = set(DEAL_PROTECTION_1) - set(groups["1"])
    if missing:
        raise ValueError(f"the Deal Protection split names questions the Dojo lacks: {sorted(missing)}")
    return groups, main


def near_universal_from(rows: Iterable[tuple[str, Mapping[str, Any]]], sets: Mapping[str, str],
                        *, share: float = NEAR_UNIVERSAL_SHARE) -> dict[str, Any]:
    """The near-universal block from ``(doc_id, maud_labels)`` rows; only ``calibration`` documents count."""
    counts: dict[str, int] = {}
    n = 0
    for doc_id, labels in rows:
        if sets.get(doc_id) != "calibration":
            continue
        n += 1
        for question, value in (labels or {}).items():
            if value:
                counts[question] = counts.get(question, 0) + 1
    questions = sorted(q for q, c in counts.items() if n and c / n >= share)
    return {"questions": questions, "calibration_n": n, "counts": dict(sorted(counts.items())), "share": share}


def _calibration_rows() -> Iterable[tuple[str, Mapping[str, Any]]] | None:
    """Merger MAUD labels from the cached ground-truth parquet, or ``None`` when it is not cached."""
    if not DATASET_GT.exists():
        return None
    import pyarrow.parquet as pq

    rows: list[tuple[str, Mapping[str, Any]]] = []
    for split in ("train", "test"):
        path = DATASET_GT / split / f"{split}-00000-of-00001.parquet"
        if not path.exists():
            return None
        table = pq.read_table(path, columns=["document_id", "expected", "gt_fields"]).to_pydict()
        for doc_id, expected, gt in zip(table["document_id"], table["expected"], table["gt_fields"]):
            if "merger" not in str(expected).lower():
                continue
            raw = json.loads(gt or "{}").get("maud_clause_labels") or "{}"
            rows.append((doc_id, json.loads(raw) if isinstance(raw, str) else raw))
    return rows


def _assignment_sets() -> tuple[dict[str, str], str]:
    data = ASSIGNMENTS_PATH.read_bytes()
    sets = {}
    for line in data.decode("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            sets[row["id"]] = row["set"]
    return sets, hashlib.sha256(data).hexdigest()


def build(previous: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    """``(tables, near_universal_rebuilt)``; without the cached dataset the committed block is kept."""
    _ensure_dojo()
    groups, main = _group_table()
    rows = _calibration_rows()
    if rows is None:
        if not previous or "near_universal" not in previous:
            raise RuntimeError(f"the dataset is not cached at {DATASET_GT} and no committed near-universal block exists")
        near, rebuilt = dict(previous["near_universal"]), False
    else:
        sets, split_sha = _assignment_sets()
        near = {**near_universal_from(rows, sets), "split_sha256": split_sha, "dataset_revision": DATASET_REVISION}
        rebuilt = True
    tables = {
        "schema": SCHEMA_ID,
        "subclass_drop": _drop_table(),
        "groups": groups,
        "merged_groups": {"2": {"1": groups["1"] + groups["2"], "2": groups["3"]},
                          "1": {"1": groups["1"] + groups["2"] + groups["3"]}},
        "main_owned": main,
        "near_universal": near,
        "required_entities": list(REQUIRED_BASE),
        "entity_sections": dict(ENTITY_SECTIONS),
    }
    return tables, rebuilt


def render(tables: Mapping[str, Any]) -> str:
    return json.dumps(tables, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- read


@lru_cache(maxsize=1)
def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load() -> dict[str, Any]:
    return _load(str(TABLES_PATH))


def sha256() -> str:
    return hashlib.sha256(TABLES_PATH.read_bytes()).hexdigest()


def dropped_fields(subclass: str | None) -> frozenset[str]:
    return frozenset(load()["subclass_drop"].get(str(subclass or "").strip(), ()))


def group_questions(groups: int) -> dict[str, tuple[str, ...]]:
    if groups not in (1, 2, 3):
        raise ValueError(f"job.merger.groups must be 1 to 3, not {groups!r}")
    data = load()
    table = data["groups"] if groups == 3 else data["merged_groups"][str(groups)]
    return {key: tuple(qs) for key, qs in table.items()}


def owner(question: str, groups: int) -> str:
    """``"main"`` or the group key that owns ``question``."""
    if question in load()["main_owned"]:
        return "main"
    for key, questions in group_questions(groups).items():
        if question in questions:
            return key
    raise KeyError(question)


def near_universal() -> frozenset[str]:
    return frozenset(load()["near_universal"]["questions"])


def required_entities(subclass: str | None) -> tuple[str, ...]:
    dropped = dropped_fields(subclass)
    return (*load()["required_entities"], *(f for f in AMOUNT_FIELDS if f not in dropped))


def entity_section(field: str) -> str | None:
    return load()["entity_sections"].get(field)
