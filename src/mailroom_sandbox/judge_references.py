"""Phase 4 references: what the correcting judge may read besides the document.

- **The reference pool** (``config/judge/reference-pool-runbook-v2.jsonl``, built by
  ``scripts/build_judge_reference_pool.py``): truth labels of the runbook-v2 ``calibration`` and
  ``pool`` documents only, merged with the scorer's own precedence (``gold_labels.apply_near_gold``)
  so an example never shows a value the run would not be scored against: interim truth labels
  (``data/labels/interim``, ``use_as_truth`` and not ``disputed``), then the near-gold overlay
  (``data/labels/gold-overlay``, the scorer's near-gold layer, manifest-verified) on fields interim
  does not give, and over an interim gate gap fill (SHF-010; an ``original_header`` fill stands).
  Hub ground truth is not read (it needs the dataset): no overlay label carries a Hub value, so a
  Hub-labelled field is left out rather than shown wrong. Those sets are never tested with
  ``references: train_pool`` (preflight refuses the draw), and a drawn document that shares a
  leak component (thread, matter or text) with a pool document is refused too.
- **Examples**: at most two pool documents of the same class and subclass, by doc id, showing
  only the requested fields.
- **Earlier attempts** of this document, and the **guide definitions** for its fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
POOL_PATH = ROOT / "config" / "judge" / "reference-pool-runbook-v2.jsonl"
ASSIGNMENTS = ROOT / "config" / "splits" / "runbook-v2" / "assignments.jsonl"
NEAR_GOLD_DIR = ROOT / "data" / "labels" / "gold-overlay"
INTERIM_DIR = ROOT / "data" / "labels" / "interim"
#: The only sets examples come from (owner decision, spec "References without cheating").
POOL_SETS = frozenset({"calibration", "pool"})
#: Evidence kept per field in the pool: enough to show where a value is, small enough to commit.
EVIDENCE_PER_FIELD = 2
EVIDENCE_CHARS = 240


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _evidence(items: Any) -> list[str]:
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        text = item if isinstance(item, str) else (item.get("text") or item.get("header") or "") if isinstance(
            item, Mapping) else ""
        text = " ".join(str(text).split())
        if text:
            out.append(text[:EVIDENCE_CHARS])
        if len(out) >= EVIDENCE_PER_FIELD:
            break
    return out


def _near_gold_wins(interim_label: Mapping[str, Any]) -> bool:
    """SHF-010 (``gold_labels.supersede_interim_gap_fills``): near-gold replaces an interim gate gap fill."""
    from mailroom_sandbox.gold_labels import INTERIM_BASES_OVER_NEAR_GOLD

    return (interim_label.get("status") == "gap_fill"
            and str(interim_label.get("basis") or "") not in INTERIM_BASES_OVER_NEAR_GOLD)


def build_pool(assignments: Iterable[Mapping[str, Any]], interim: Iterable[Mapping[str, Any]],
               near_gold: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pool rows ``{doc_id, doc_class, subclass, set, component, fields}``, sorted by class and doc id.

    ``near_gold`` holds gold-overlay records (``{doc_id, labels: {field: {value, basis, evidence}}}``).
    """
    sets = {str(row["id"]): row for row in assignments if row.get("set") in POOL_SETS}
    fields: dict[str, dict[str, dict[str, Any]]] = {}
    superseded: dict[str, set[str]] = {}
    for record in interim:
        doc_id = str(record.get("doc_id"))
        if doc_id not in sets:
            continue
        for name, label in (record.get("labels") or {}).items():
            if isinstance(label, Mapping) and label.get("use_as_truth") and label.get("status") != "disputed":
                fields.setdefault(doc_id, {})[name] = {"value": label.get("value"), "source": "interim",
                                                       "evidence": _evidence(label.get("evidence"))}
                if _near_gold_wins(label):
                    superseded.setdefault(doc_id, set()).add(name)
    for record in near_gold:
        doc_id = str(record.get("doc_id"))
        if doc_id not in sets:
            continue
        for name, label in (record.get("labels") or {}).items():
            if not isinstance(label, Mapping) or not str(label.get("basis") or "").startswith("near_gold:"):
                continue
            if name in fields.get(doc_id, {}) and name not in superseded.get(doc_id, set()):
                continue  # an interim label the scorer keeps over near-gold
            fields.setdefault(doc_id, {})[str(name)] = {"value": label.get("value"), "source": "near_gold",
                                                        "evidence": _evidence(label.get("evidence"))}
    rows = []
    for doc_id, named in fields.items():
        assigned = sets[doc_id]
        rows.append({"doc_id": doc_id, "doc_class": str(assigned.get("doc_class") or ""),
                     "subclass": assigned.get("subclass"), "set": assigned["set"],
                     "component": str(assigned.get("component") or doc_id),
                     "fields": {name: named[name] for name in sorted(named)}})
    return sorted(rows, key=lambda r: (r["doc_class"], r["doc_id"]))


def read_sources(classes: Iterable[str] | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """``(assignments, interim, near_gold)`` from the committed files; the overlay must match its manifest."""
    from mailroom_sandbox.gold_labels import near_gold_snapshot

    classes = None if classes is None else list(classes)  # read twice below; a generator would empty
    assignments = _jsonl(ASSIGNMENTS)
    names = sorted(classes or {p.stem for p in INTERIM_DIR.glob("*.jsonl")})
    interim = [r for name in names for r in _jsonl(INTERIM_DIR / f"{name}.jsonl")]
    records, _sha, problems = near_gold_snapshot(NEAR_GOLD_DIR)
    if problems:
        raise ValueError(f"{NEAR_GOLD_DIR}: {'; '.join(problems[:3])}")
    near_gold = [r for _, r in sorted(records.items())
                 if classes is None or str(r.get("doc_class")) in classes]
    return assignments, interim, near_gold


def render(pool: Iterable[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in pool)


def load_pool(path: str | Path | None = None) -> list[dict[str, Any]]:
    return _jsonl(Path(path) if path else POOL_PATH)


def _fit(example: dict[str, Any], max_chars: int) -> dict[str, Any] | None:
    """The example within ``max_chars`` of JSON: evidence dropped first, then trailing fields."""
    if len(json.dumps(example, ensure_ascii=False)) <= max_chars:
        return example
    bare = {**example, "fields": {k: {"value": v["value"]} for k, v in example["fields"].items()}}
    while bare["fields"] and len(json.dumps(bare, ensure_ascii=False)) > max_chars:
        bare["fields"].popitem()
    return bare if bare["fields"] and len(json.dumps(bare, ensure_ascii=False)) <= max_chars else None


def examples(pool: Iterable[Mapping[str, Any]], doc_class: str, subclass: str | None, *, k: int, max_chars: int,
             exclude: Collection[str] = (), fields: Collection[str] | None = None) -> list[dict[str, Any]]:
    """At most ``k`` pool documents of the same class and subclass, by doc id, each within ``max_chars``.

    With ``fields`` (the judge's requested fields), an example shows only those, so a field the
    extraction was not asked for (a subclass drop) never reaches the prompt; one with none is skipped.
    """
    if k <= 0 or not subclass:
        return []
    wanted = None if fields is None else set(fields)
    out: list[dict[str, Any]] = []
    for row in sorted(pool, key=lambda r: str(r.get("doc_id"))):
        if row.get("doc_class") != doc_class or row.get("subclass") != subclass or row.get("doc_id") in exclude:
            continue
        shown = {n: {"value": f.get("value"), "evidence": list(f.get("evidence") or [])}
                 for n, f in (row.get("fields") or {}).items() if wanted is None or n in wanted}
        if not shown:
            continue
        fitted = _fit({"doc_id": row["doc_id"], "subclass": subclass, "fields": shown}, max_chars)
        if fitted is not None:
            out.append(fitted)
        if len(out) >= k:
            break
    return out


def assigned_components(path: Path | None = None) -> dict[str, str]:
    """Doc id → leak component (thread, matter or text cluster) from the split assignments."""
    return {str(r["id"]): str(r.get("component") or r["id"]) for r in _jsonl(path or ASSIGNMENTS)}


def pool_leaks(pool: Iterable[Mapping[str, Any]], drawn: Mapping[str, str]) -> list[str]:
    """Refuse a draw holding a pool document, or one sharing a leak component with the pool."""
    by_component: dict[str, list[str]] = {}
    ids = set()
    for row in pool:
        ids.add(str(row["doc_id"]))
        by_component.setdefault(str(row.get("component") or row["doc_id"]), []).append(str(row["doc_id"]))
    hits = []
    for doc_id, component in sorted(drawn.items()):
        shared = sorted(set(by_component.get(str(component), ())) | ({doc_id} & ids))
        if shared:
            hits.append(f"{doc_id} (component {component}: {', '.join(shared[:3])})")
    if not hits:
        return []
    return [f"judge.references: train_pool: {len(hits)} drawn documents are in the reference pool or share a "
            f"thread, matter or text with it: {'; '.join(hits[:5])}"]


def guide_for(doc_class: str, subclass: str | None) -> dict[str, str]:
    """Field definitions: the curated ``schema_guide`` text, then the subclass field-list guide."""
    from mailroom_sandbox.schema_guide import GUIDE_DESCRIPTIONS

    guide = dict(GUIDE_DESCRIPTIONS.get(doc_class) or {})
    try:
        from mailroom_sandbox.subclass_fields import load_field_lists

        entry = ((load_field_lists().get("classes") or {}).get(doc_class) or {}).get(str(subclass or "")) or {}
    except Exception:  # noqa: BLE001 — no field list: the curated text only
        entry = {}
    for name, text in (entry.get("guide") or {}).items():
        guide.setdefault(str(name), str(text))
    return guide


def attempts_for(state: Mapping[str, Any], *, max_chars: int) -> list[dict[str, Any]]:
    """This document's earlier extraction attempts (not the one under review), newest kept first."""
    history = [e for e in state.get("extraction_attempt_history") or [] if isinstance(e, Mapping)][:-1]
    out: list[dict[str, Any]] = []
    for entry in reversed(history):
        item = {"attempt": entry.get("attempt_no"), "kind": entry.get("kind"),
                "fields": {k: v for k, v in (entry.get("extracted_data") or {}).items()
                           if not str(k).startswith("_") and k != "reasoning"},
                "judge_verdict": entry.get("judge_verdict"), "judge_findings": entry.get("judge_findings")}
        if len(json.dumps([*out, item], ensure_ascii=False, default=str)) > max_chars:
            break
        out.append(item)
    return list(reversed(out))
