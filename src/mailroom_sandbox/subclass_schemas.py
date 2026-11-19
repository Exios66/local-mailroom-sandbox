"""Per-subclass extraction schemas graded against the truth runs actually score (R00+).

The vendored Dojo registry (``llm_dojo_scoring.schemas.extraction_schemas``) gives every
class and subtype its fields and a status, but the status is frozen from the Hub v9
lineage: fields that now carry repaired truth (the interim overlay, the near-gold
overlay) still read ``pending_annotation``. Prompt iteration and readiness reports that
trust it either skip labeled fields or spend effort on fields nothing can score.

This module rebuilds each (class, subclass) schema from the truth stack a run uses —
Hub ground truth, then ``data/labels/interim`` truth labels, then
``data/labels/gold-overlay`` near-gold labels (``corpus.prepare_subset`` precedence) —
and records per field:

* ``type`` and ``dojo_status`` (vendored), ``in_output_schema`` (the pipeline's pydantic
  model asks for it), ``applicable`` (the corporate subclass schema's core fields);
* ``truth``: labeled documents by source, and by runbook set when a split is given;
* ``effective_status``: ``scored`` (truth present), ``derived`` (truth from the subtype,
  CUAD or MAUD labels), ``documented_absent``, ``label_task``, ``not_applicable`` or
  ``no_truth``;
* ``verdict`` for iteration: ``iterate`` (at least ``MIN_DEV`` labeled dev documents),
  ``thin`` (fewer), ``constant`` (one value or role covers >= 95% of labels: state the
  rule in the prompt, do not iterate on it), ``fixed`` (documented absence or a label
  task), ``no_truth`` / ``not_applicable`` (never worth prompt tokens or a round);
* ``guide``: the labeling-guide convention the labels follow.

``problems`` lists mismatches that must be repaired before scoring: truth on a field the
model cannot emit, a closed-vocabulary label outside the pipeline's vocabulary, or a
corporate ``record_type`` label that contradicts its subclass. ``sandbox schemas check``
fails on any of them and on a stale committed file.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from mailroom_sandbox.paths import repo_root

SCHEMA = "mailroom.subclass_schemas/v1"
REPO_ROOT = repo_root()
DEFAULT_OUT = REPO_ROOT / "config" / "extraction" / "subclass_schemas.json"
GUIDE = REPO_ROOT / "docs" / "gold-labels" / "LABELING_GUIDE.md"
DEFAULT_SPLIT = REPO_ROOT / "config" / "splits" / "runbook-v1"
CLASSES = ("contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim")
SETS = ("dev", "calibration", "heldout", "pool")
MIN_DEV = 20
CONSTANT_SHARE = 0.95
_SKIP_OUTPUT = {"reasoning", "confidence"}
_GUIDE_SECTIONS = {"Correspondence fields": "correspondence", "Corporate record fields": "corporate_record",
                   "Contract fields": "contract"}


class SchemaError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_guide(path: Path = GUIDE) -> dict[str, dict[str, str]]:
    """``{class: {field: convention}}`` from the guide's per-class field tables."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    cls = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cls = _GUIDE_SECTIONS.get(line[3:].strip())
            continue
        m = re.match(r"^\| `([a-z_]+)` \| ([^|]+) \| (.+) \|\s*$", line)
        if cls and m:
            out[cls][m.group(1)] = f"{m.group(2).strip()}: {m.group(3).strip()}"
    return dict(out)


def closed_vocabularies() -> dict[tuple[str, str], frozenset[str]]:
    from langchain_agents import doc_inventories as di

    from mailroom_sandbox.schema_guide import ROLES

    return {
        ("correspondence", "urgency"): frozenset({"routine", "time-sensitive", "urgent", "critical"}),
        ("correspondence", "communication_type"): frozenset(di.CORRESPONDENCE_TYPES) | {"other"},
        ("corporate_record", "record_type"): frozenset(di.CORPORATE_RECORD_TYPES),
        ("insurance_claim", "claim_type"): frozenset(di.INSURANCE_PRODUCT_LINES),
        ("insurance_claim", "coverage_determination"): frozenset({"approved", "denied", "partial", "pending"}),
        ("insurance_claim", "cms_source_table"): frozenset(di.CMS_CLAIM_TABLES),
        ("contract", "party_roles"): frozenset(ROLES),
    }


def _value(raw: Any) -> Any:
    if isinstance(raw, str) and raw[:1] in "[{":
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def truth_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rows with the interim and near-gold overlays merged, as a run with both flags sees them."""
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    iov, isha = il.load_overlay(), il.overlay_fingerprint()
    gov, gsha, problems = gl.near_gold_snapshot()
    if problems:
        raise SchemaError(f"near-gold overlay is inconsistent: {problems[0]}")
    return [gl.apply_near_gold(il.apply_overlay(r, iov, overlay_sha=isha), gov, overlay_sha=gsha) for r in rows]


def _subclass_of(cls: str, raw: Any) -> str:
    from llm_dojo_scoring.schemas.corpus import normalize_corpus_subclass

    if cls == "contract":
        from langchain_agents.doc_inventories import normalize_sorter_subclass

        return normalize_sorter_subclass(cls, raw) or "other"
    return normalize_corpus_subclass(cls, raw) or "other"


def _read_sets(split_dir: Path | None) -> tuple[dict[str, str], str | None]:
    if not split_dir or not (split_dir / "assignments.jsonl").is_file():
        return {}, None
    data = (split_dir / "assignments.jsonl").read_bytes()
    sets = {}
    for line in data.decode("utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            sets[rec["id"]] = rec["set"]
    return sets, _sha(data)


def _dominant(values: list[Any]) -> dict[str, Any] | None:
    if len(values) < MIN_DEV:
        return None
    items = [str(i) for v in values if isinstance(v, list) for i in v]
    if items and all(": " in i for i in items):  # '<party>: <role>' lists: grade the role
        roles = Counter(i.rsplit(": ", 1)[1].strip().lower() for i in items)
        role, n = roles.most_common(1)[0]
        return {"kind": "role", "value": role, "share": round(n / len(items), 3)}
    keys = Counter(json.dumps(v if not isinstance(v, list) or v else [], sort_keys=True) for v in values)
    val, n = keys.most_common(1)[0]
    return {"kind": "value", "value": json.loads(val), "share": round(n / len(values), 3)}


def _effective_status(dojo_status: str, applicable: bool, labeled: int) -> str:
    if dojo_status == "not_applicable" or not applicable:
        return "not_applicable"
    if dojo_status in ("documented_absent", "label_task"):
        return dojo_status
    if dojo_status == "derived" and labeled == 0:
        return "derived"
    return "scored" if labeled else "no_truth"


def _verdict(eff: str, dominant: Mapping[str, Any] | None, dev_n: int | None, *, has_truth: bool = True) -> str:
    if eff in ("no_truth", "not_applicable"):
        return eff
    if eff in ("documented_absent", "label_task"):
        return "fixed"
    if dominant and dominant["share"] >= CONSTANT_SHARE:
        return "constant"
    if dev_n is not None and dev_n < MIN_DEV:
        return "thin"
    return "iterate" if has_truth else "no_truth"


def _dev_rows(docs: Iterable[Mapping[str, Any]], sets: Mapping[str, str]) -> int:
    return sum(1 for r in docs if sets.get(str(r.get("id"))) == "dev")


@dataclass
class _Subclass:
    """One (class, subclass) cell being graded, with the problems list it reports into."""

    cls: str
    sub: str
    docs: list[Mapping[str, Any]]
    dojo: Any
    corp: Any
    output_fields: list[str]
    sets: Mapping[str, str]
    vocab: Mapping[tuple[str, str], frozenset[str]]
    problems: list[dict[str, Any]]
    labeled: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    by_set: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    values: dict[str, list[Any]] = field(default_factory=lambda: defaultdict(list))

    @property
    def entities(self) -> dict[str, Any]:
        return {e.key: e for e in self.corp.entities} if self.corp else {}

    @property
    def names(self) -> list[str]:
        return list(dict.fromkeys([*self.output_fields, *self.dojo.fields]))

    def _problem(self, kind: str, name: str, doc_id: Any, values: list[Any], source: str) -> None:
        self.problems.append({"kind": kind, "class": self.cls, "subclass": self.sub, "field": name,
                              "doc_id": doc_id, "values": values, "source": source})

    def _check_vocabulary(self, name: str, val: Any, doc_id: Any, src: str) -> None:
        allowed = self.vocab.get((self.cls, name))
        bad = [v for v in (val if isinstance(val, list) else [val]) if v not in (None, "")]
        if name == "party_roles":
            bad = [v.rsplit(": ", 1)[-1].strip().lower() for v in bad]
        bad = [v for v in bad if allowed is not None and v not in allowed]
        if bad:
            self._problem("label_outside_vocabulary", name, doc_id, bad[:3], src)

    def tally(self, gl: Any, il: Any) -> None:
        """Count every labeled field by truth source and set; report vocabulary and record-type problems."""
        names = self.names
        for r in self.docs:
            exp = il._expected(r)
            interim = set((r.get("interim_labels") or {}).get("fields") or [])
            near = set((r.get("near_gold_labels") or {}).get("fields") or [])
            for name in names:
                if not gl.hub_labels(name, exp):
                    continue
                src = "interim" if name in interim else "near_gold" if name in near else "hub"
                self.labeled[name][src] += 1
                self.by_set[name][self.sets.get(str(r.get("id")), "unassigned")] += 1
                val = _value(exp.get(name))
                self.values[name].append(val)
                self._check_vocabulary(name, val, r.get("id"), src)
            corp = self.corp
            if corp and exp.get("record_type") and str(_value(exp["record_type"])) != corp.record_type:
                self._problem("record_type_contradicts_subclass", "record_type", r.get("id"),
                              [_value(exp["record_type"]), corp.record_type],
                              "interim" if "record_type" in interim else "hub")

    def field_entry(self, name: str, guide: Mapping[str, str], crs: Any) -> dict[str, Any]:
        entities, sets, docs = self.entities, self.sets, self.docs
        fs = self.dojo.fields.get(name)
        dstatus = fs.status if fs else "absent_from_dojo"
        n = sum(self.labeled[name].values())
        in_output = name in self.output_fields
        applicable = True
        if self.corp and name not in entities:
            applicable = name in self.corp.core_applicable or name not in crs.CORE_FIELDS
        eff = _effective_status(dstatus, applicable, n)
        if eff == "derived":
            truth_n, dev_n = len(docs), (_dev_rows(docs, sets) if sets else None)
        else:
            truth_n, dev_n = n, (self.by_set[name].get("dev", 0) if sets else None)
        dominant = _dominant(self.values[name]) if eff == "scored" else None
        verdict = _verdict(eff, dominant, dev_n, has_truth=bool(truth_n))
        if n and not in_output and name not in entities and eff == "scored":
            self._problem("truth_not_in_output_schema", name, None, [n], "any")
        entry: dict[str, Any] = {
            "type": fs.field_type if fs else None,
            "dojo_status": dstatus,
            "effective_status": eff,
            "verdict": verdict,
            "in_output_schema": in_output,
            "truth": dict(sorted(self.labeled[name].items())),
            "labeled": n,
        }
        if sets:
            entry["labeled_by_set"] = {s: self.by_set[name].get(s, 0) for s in SETS}
        if dominant:
            entry["dominant"] = dominant
        if name in entities:
            e = entities[name]
            entry["entity"] = {"description": e.description, "where": e.where, "required": e.required}
        if name in guide:
            entry["guide"] = guide[name]
        return entry

    def entry(self, guide: Mapping[str, str], crs: Any) -> dict[str, Any]:
        fields = {name: self.field_entry(name, guide, crs) for name in self.names}
        sub_entry: dict[str, Any] = {
            "rows": len(self.docs),
            "fields": fields,
            "verdicts": dict(sorted(Counter(f["verdict"] for f in fields.values()).items())),
        }
        if self.sets:
            sub_entry["rows_by_set"] = {s: sum(1 for r in self.docs if self.sets.get(str(r.get("id"))) == s)
                                        for s in SETS}
        if self.dojo.salient:
            sub_entry["salient"] = list(self.dojo.salient)
        if self.corp:
            sub_entry.update(record_type=self.corp.record_type, intent=self.corp.intent, notes=self.corp.notes)
        return sub_entry


def build_registry(rows: list[Mapping[str, Any]], *, revision: str, split_dir: Path | None = DEFAULT_SPLIT,
                   guide_path: Path = GUIDE) -> dict[str, Any]:
    """The graded per-subclass schemas for ``rows`` (already overlay-merged by :func:`truth_rows`)."""
    from llm_dojo_scoring.schemas import corporate_record_schema as crs
    from llm_dojo_scoring.schemas.extraction_schemas import extraction_schema, extraction_subtypes
    from schemas.documents import get_extraction_schema

    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    guide = parse_guide(guide_path)
    vocab = closed_vocabularies()
    sets, split_sha = _read_sets(split_dir)
    problems: list[dict[str, Any]] = []

    by_sub: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        cls = str(r.get("expected_doc_class") or "")
        if cls in CLASSES:
            by_sub[(cls, _subclass_of(cls, r.get("expected_subclass")))].append(r)

    classes: dict[str, Any] = {}
    for cls in CLASSES:
        output_fields = [f for f in get_extraction_schema(cls).model_fields if f not in _SKIP_OUTPUT]
        subtypes = list(extraction_subtypes(cls))
        subtypes += sorted({s for (c, s) in by_sub if c == cls} - set(subtypes))
        subs: dict[str, Any] = {}
        class_values: dict[str, list[Any]] = defaultdict(list)
        for sub in subtypes:
            cell = _Subclass(cls, sub, by_sub.get((cls, sub), []), extraction_schema(cls, sub),
                             crs.subclass_schema(sub) if cls == "corporate_record" else None,
                             output_fields, sets, vocab, problems)
            cell.tally(gl, il)
            subs[sub] = cell.entry(guide.get(cls, {}), crs)
            for name in cell.names:
                class_values[name].extend(cell.values[name])
        classes[cls] = {"output_schema_fields": output_fields, "subclasses": subs,
                        "fields": _class_rollup(cls, subs, sets, by_sub, class_values)}
    problems.sort(key=lambda p: (p["kind"], p["class"], p["subclass"], p["field"], str(p["doc_id"])))
    return _registry_document(classes, problems, revision=revision, guide_path=guide_path, split_sha=split_sha)


def _registry_document(classes: dict[str, Any], problems: list[dict[str, Any]], *, revision: str,
                       guide_path: Path, split_sha: str | None) -> dict[str, Any]:
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    repairs = sorted(
        {(c, f, e["dojo_status"]) for c, ce in classes.items() for f, e in ce["fields"].items()
         if e["dojo_status"] == "pending_annotation" and e["effective_status"] == "scored"})
    return {
        "schema": SCHEMA,
        "inputs": {
            "dataset_revision": revision,
            "interim_overlay_sha256": il.overlay_fingerprint(),
            "near_gold_overlay_sha256": gl.near_gold_fingerprint(),
            "labeling_guide_sha256": _sha(guide_path.read_bytes()),
            "split_assignments_sha256": split_sha,
            "min_dev": MIN_DEV,
            "constant_share": CONSTANT_SHARE,
        },
        "classes": classes,
        "status_conflicts": [{"class": c, "field": f, "labeled_but_not_applicable": e["truth_ignored_not_applicable"]}
                             for c, ce in classes.items() for f, e in ce["fields"].items()
                             if e.get("truth_ignored_not_applicable")],
        "untruthed_output_fields": {c: [f for f in ce["output_schema_fields"]
                                        if ce["fields"].get(f, {}).get("verdict") in ("no_truth", None)]
                                    for c, ce in classes.items()},
        "status_repairs": [{"class": c, "field": f, "dojo_status": d, "effective_status": "scored"}
                           for c, f, d in repairs],
        "problems": problems,
    }


def _rollup_entry(name: str, entries: list[Mapping[str, Any]], dev: int | None,
                  values: list[Any], sets: Mapping[str, str]) -> dict[str, Any]:
    live = [e for e in entries if e["effective_status"] != "not_applicable"]
    statuses = Counter(e["effective_status"] for e in live) or Counter({"not_applicable": 1})
    truth: Counter = Counter()
    by_set: Counter = Counter()
    for e in live:
        truth.update(e["truth"])
        by_set.update(e.get("labeled_by_set") or {})
    eff = "scored" if any(e["effective_status"] == "scored" for e in live) else statuses.most_common(1)[0][0]
    if eff != "derived" or not sets:
        dev = by_set.get("dev", 0) if sets else None
    dominant = _dominant(values) if eff == "scored" else None
    entry = {"effective_status": eff, "verdict": _verdict(eff, dominant, dev),
             "dojo_status": entries[0]["dojo_status"], "in_output_schema": entries[0]["in_output_schema"],
             "truth": dict(sorted(truth.items())), "labeled": sum(truth.values()),
             "subclasses_with_truth": sum(1 for e in live if e["labeled"])}
    if dominant:
        entry["dominant"] = dominant
    ignored = sum(sum(e["truth"].values()) for e in entries if e["effective_status"] == "not_applicable")
    if ignored:
        entry["truth_ignored_not_applicable"] = ignored
    if sets:
        entry["labeled_by_set"] = {s: by_set.get(s, 0) for s in SETS}
    guide = next((e["guide"] for e in entries if "guide" in e), None)
    if guide:
        entry["guide"] = guide
    return entry


def _class_rollup(cls: str, subs: Mapping[str, Any], sets: Mapping[str, str],
                  by_sub: Mapping[tuple[str, str], list], values: Mapping[str, list[Any]]) -> dict[str, Any]:
    """Class-level view of each field: truth summed over subclasses, verdict on the class's dev n."""
    class_dev = sum(_dev_rows(docs, sets) for (c, _s), docs in by_sub.items() if c == cls) if sets else None
    names = list(dict.fromkeys(f for se in subs.values() for f in se["fields"]))
    return {name: _rollup_entry(name, [se["fields"][name] for se in subs.values() if name in se["fields"]],
                                class_dev, values.get(name) or [], sets)
            for name in names}


def load_corpus_rows(revision: str | None = None) -> tuple[list[dict[str, Any]], str]:
    from mailroom_sandbox import corpus
    from mailroom_sandbox.corpus import FAMILY_HF_REVISION, DatasetSpec

    rev = revision or FAMILY_HF_REVISION
    try:
        rows = corpus.normalize_rows(corpus.load_hf_rows(DatasetSpec(provider="huggingface", revision=rev,
                                                                     split="all")))
    except Exception as exc:  # noqa: BLE001
        raise SchemaError(f"corpus {rev[:12]} is not readable ({exc}); run `sandbox datasets pull` first") from exc
    return rows, rev


def render(registry: Mapping[str, Any]) -> bytes:
    return (json.dumps(registry, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def summary_rows(registry: Mapping[str, Any], *, cls: str | None = None, sub: str | None = None,
                 verdict: str | None = None) -> list[tuple[str, str, str, dict[str, Any]]]:
    out = []
    for c, centry in registry["classes"].items():
        if cls and c != cls:
            continue
        for s, sentry in centry["subclasses"].items():
            if sub and s != sub:
                continue
            for f, fentry in sentry["fields"].items():
                if verdict and fentry["verdict"] != verdict:
                    continue
                out.append((c, s, f, fentry))
    return out
