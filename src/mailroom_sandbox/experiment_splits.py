"""Frozen four-way experiment split for the evaluation runbook (R00).

Builds dev / calibration / held-out / rotation-pool sets over the pinned 3,302-row
corpus, offline, from the Hugging Face cache. The output directory holds one id file
per set plus its complement (``<set>.exclude.ids``), so a run selects a set with the
existing ``dataset.exclude_ids_file`` + ``split: all`` (no spec change), and nested
sequential-look slices of dev (300 / 600 / 900).

Rules (design doc, Splits section):

* Score units: a subclass with ``min_scored``+ documents is its own unit; smaller
  subclasses are scored through their family (``config/splits/families.yaml``); a
  family below ``min_scored`` is a pooled group.
* Dev and held-out take 20 per scored unit (15-19 for units of 30-39 documents),
  at least ``min_pooled_per_set`` per pooled group, and at least one document of
  every rare subclass with 3+ documents.
* Within a unit, draws interleave length bands (``context_window_band``).
* Documents linked by ``matter_id``, ``group_id``, a shared normalized email subject
  (reply/forward prefixes stripped), identical normalized text, and — when present —
  ``message_id`` / ``in_reply_to`` or ``related_document_ids`` form one leak component
  and always land in the same set. On the pinned corpus the last two never fire
  (unique message ids, no ``in_reply_to``, no related ids).
* Held-out prefers the least-exposed documents: never tuned (``test`` split, not on
  the production tuning list), then untuned ``train``, then tuned; dev the reverse.
* Calibration follows the corpus class mix as closely as the remainder allows; the
  rotation pool takes the rest.

Everything is deterministic given the seed; ``audit`` re-derives every check and
every file hash from the manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from mailroom_sandbox.paths import repo_root

REPO_ROOT = repo_root()

SETS = ("dev", "calibration", "heldout", "pool")
DEFAULT_SIZES = {"dev": 900, "calibration": 1000, "heldout": 1000, "pool": 402}
DEV_LOOKS = (300, 600)
BANDS = ("<=4k", "<=16k", "<=32k", ">32k")
DEFAULT_FAMILIES = REPO_ROOT / "config" / "splits" / "families.yaml"
DEFAULT_EXPOSURE = REPO_ROOT / "config" / "production" / "excluded-ids.txt"
DEFAULT_OUT_ROOT = REPO_ROOT / "config" / "splits"
MIX_TOLERANCE_PTS = 5.0
SCHEMA = "mailroom.experiment_split/v1"


class SplitError(ValueError):
    """The corpus or the requested sizes cannot satisfy the split rules."""


@dataclass
class Doc:
    id: str
    doc_class: str
    subclass: str
    band: str
    source_corpus: str
    annotation_method: str
    hf_split: str
    tuned: bool
    links: list[str] = field(default_factory=list)
    unit: str = ""
    unit_kind: str = ""  # subclass | family | pooled
    component: str = ""

    @property
    def never_tuned(self) -> bool:
        return self.hf_split == "test" and not self.tuned

    @property
    def exposure_tier(self) -> int:
        """0 never tuned (test split, not listed), 1 train split but not listed, 2 on the tuning list.

        Held-out takes the lowest tier first; dev takes the highest first, so it
        leaves the least-exposed documents for held-out.
        """
        if self.tuned:
            return 2
        return 0 if self.hf_split == "test" else 1


# ---------------------------------------------------------------- corpus loading


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return [text]
        else:
            return [text] if text else []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v not in (None, "")]
    return []


def load_cached_rows(revision: str | None = None, repo: str | None = None) -> list[dict[str, Any]]:
    """Read the pinned default + ground_truth parquet shards from the local HF cache only.

    Unlike ``corpus.load_hf_rows`` this never lists the remote tree, so it works
    with ``HF_HUB_OFFLINE=1`` once ``sandbox datasets pull`` has filled the cache.
    """
    import huggingface_hub

    from mailroom_sandbox import corpus
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION, HF_DEFAULT_REPO

    corpus._ensure_hf_home()
    repo = repo or HF_DEFAULT_REPO
    revision = revision or FAMILY_HF_REVISION
    out: list[dict[str, Any]] = []
    for split in ("train", "test"):
        shards: dict[str, list[dict[str, Any]]] = {}
        for config in ("default", "ground_truth"):
            name = f"parquet/{config}/{split}/{split}-00000-of-00001.parquet"
            try:
                path = huggingface_hub.hf_hub_download(
                    repo, name, revision=revision, repo_type="dataset", local_files_only=True
                )
            except Exception as exc:  # LocalEntryNotFoundError and friends
                raise SplitError(
                    f"{repo}@{revision[:12]} {name} is not in the local cache; "
                    "run `sandbox datasets pull` once (network) first"
                ) from exc
            shards[config] = corpus._read_parquet(path)
        merged = corpus.merge_default_and_gt(shards["default"], shards["ground_truth"])
        for row in merged:
            row["source_revision"] = revision
            row.setdefault("split", split)
        out.extend(merged)
    # normalize_rows keeps only the scoring columns; the split needs the provenance and
    # link columns too, so carry every raw field the normalized row does not set.
    normalized = corpus.normalize_rows([dict(r) for r in out])
    if len(normalized) != len(out):
        raise SplitError("normalize_rows changed the row count; cannot pair raw and normalized rows")
    for raw, norm in zip(out, normalized):
        if raw.get("filename") != norm.get("filename"):
            raise SplitError(f"row order changed during normalization at {raw.get('filename')!r}")
        for key, value in raw.items():
            if key not in ("doc_text", "prompt"):
                norm.setdefault(key, value)
    return normalized


def read_id_file(path: Path | None) -> set[str]:
    if path is None or not Path(path).is_file():
        return set()
    ids = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


_REPLY_PREFIX = re.compile(r"^\s*(re|fw|fwd)\s*:\s*", re.IGNORECASE)


def _thread_subject(subject: Any) -> str:
    """Normalized email subject: reply/forward prefixes stripped, case and spaces folded.

    The corpus has no resolvable ``in_reply_to`` and unique ``message_id``s, so a shared
    normalized subject is the thread signal. Over-linking only makes components larger
    (conservative); the corpus has 9 such groups of 2-5 documents.
    """
    text = str(subject or "").strip()
    while True:
        stripped = _REPLY_PREFIX.sub("", text)
        if stripped == text:
            break
        text = stripped
    return re.sub(r"\s+", " ", text).strip().lower()


def docs_from_rows(rows: Iterable[dict[str, Any]], exposure: set[str]) -> list[Doc]:
    docs: list[Doc] = []
    for r in rows:
        meta = _as_dict(r.get("metadata"))
        gt = {**_as_dict(r.get("expected_fields")), **_as_dict(r.get("gt_fields"))}
        did = str(r.get("id") or r.get("document_id") or "")
        if not did:
            raise SplitError(f"row without an id: {r.get('filename')!r}")
        band = str(gt.get("context_window_band") or r.get("context_window_band") or "<=4k")
        links: list[str] = []
        for key in ("matter_id", "group_id"):
            if r.get(key):
                links.append(f"{key}:{r[key]}")
        for key in ("normalized_text_sha256",):
            if r.get(key):
                links.append(f"text:{r[key]}")
        if str(r.get("expected_doc_class") or r.get("expected") or "") == "correspondence":
            subject = _thread_subject(meta.get("subject"))
            if len(subject) >= 4:
                links.append(f"subject:{subject}")
        if meta.get("message_id"):
            links.append(f"msg:{str(meta['message_id']).strip()}")
        if meta.get("in_reply_to"):
            links.append(f"msg:{str(meta['in_reply_to']).strip()}")
        for rel in _as_list(r.get("related_document_ids")):
            links.append(f"doc:{rel}")
        links.append(f"doc:{did}")
        docs.append(
            Doc(
                id=did,
                doc_class=str(r.get("expected_doc_class") or r.get("expected") or ""),
                subclass=str(r.get("expected_subclass") or ""),
                band=band if band in BANDS else "<=4k",
                source_corpus=str(r.get("source_corpus") or ""),
                annotation_method=str(r.get("annotation_method") or ""),
                hf_split=str(r.get("split") or ""),
                tuned=did in exposure,
                links=links,
            )
        )
    ids = [d.id for d in docs]
    if len(set(ids)) != len(ids):
        dup = [i for i, n in Counter(ids).items() if n > 1][:5]
        raise SplitError(f"duplicate document ids in the corpus: {dup}")
    return docs


# ------------------------------------------------------------- units, components


def load_families(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    data.setdefault("min_scored", 30)
    data.setdefault("min_pooled_per_set", 10)
    data.setdefault("families", {})
    return data


def assign_units(docs: Sequence[Doc], families: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Give every doc its score unit; return unit -> {kind, n, subclasses}."""
    min_scored = int(families["min_scored"])
    sub_n = Counter((d.doc_class, d.subclass) for d in docs)
    fam_of: dict[tuple[str, str], str] = {}
    for cls, fams in (families.get("families") or {}).items():
        for fam, members in (fams or {}).items():
            for m in members or []:
                fam_of[(cls, str(m))] = f"{cls}/family:{fam}"
    units: dict[str, dict[str, Any]] = {}
    for d in docs:
        key = (d.doc_class, d.subclass)
        if sub_n[key] >= min_scored:
            d.unit, d.unit_kind = f"{d.doc_class}/{d.subclass}", "subclass"
        else:
            d.unit = fam_of.get(key, f"{d.doc_class}/family:unassigned")
            d.unit_kind = "family"
        units.setdefault(d.unit, {"kind": d.unit_kind, "n": 0, "subclasses": set()})
        units[d.unit]["n"] += 1
        units[d.unit]["subclasses"].add(d.subclass)
    for name, u in units.items():
        if u["kind"] == "family" and u["n"] < min_scored:
            u["kind"] = "pooled"
        u["subclasses"] = sorted(u["subclasses"])
    for d in docs:
        d.unit_kind = units[d.unit]["kind"]
    return units


def build_components(docs: Sequence[Doc]) -> dict[str, list[Doc]]:
    """Union-find over shared link keys; component id = smallest member id."""
    parent: dict[str, str] = {d.id: d.id for d in docs}
    known = set(parent)

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            parent[rb] = ra

    owner: dict[str, str] = {}
    for d in docs:
        for key in d.links:
            if key.startswith("doc:"):
                target = key[4:]
                if target in known:
                    union(d.id, target)
                continue
            if key in owner:
                union(d.id, owner[key])
            else:
                owner[key] = d.id
    comps: dict[str, list[Doc]] = defaultdict(list)
    for d in docs:
        root = find(d.id)
        comps[root].append(d)
    for root, members in comps.items():
        cid = min(m.id for m in members)
        for m in members:
            m.component = cid
    return {min(m.id for m in ms): ms for ms in comps.values()}


# ---------------------------------------------------------------------- drawing


def _h(seed: int, *parts: str) -> str:
    return hashlib.sha256("|".join([str(seed), *parts]).encode()).hexdigest()


def _band_interleaved(docs: Sequence[Doc], seed: int, salt: str) -> list[Doc]:
    """Order docs so any prefix is balanced across length band x source corpus strata."""
    by_band: dict[tuple[str, str], list[Doc]] = defaultdict(list)
    for d in docs:
        by_band[(d.band, d.source_corpus)].append(d)
    for b in by_band:
        by_band[b].sort(key=lambda d: _h(seed, salt, d.id))
    # proportional interleave: each doc gets a fractional rank within its band
    ranked = []
    for b, ds in by_band.items():
        n = len(ds)
        for i, d in enumerate(ds):
            ranked.append(((i + 0.5) / n, _h(seed, "tie", d.id), d))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in ranked]


def unit_quota(kind: str, n: int, min_pooled: int) -> int:
    """Per-set quota for dev and held-out."""
    if kind == "pooled":
        return min(min_pooled, n // 2)
    if n >= 40:
        return 20
    return max(min(19, n // 2), min(15, n // 2))


@dataclass
class SplitResult:
    assignment: dict[str, str]
    docs: list[Doc]
    units: dict[str, dict[str, Any]]
    components: dict[str, list[Doc]]
    looks: dict[str, list[str]]
    quotas: dict[str, int]


def build_split(
    docs: list[Doc],
    families: dict[str, Any],
    *,
    seed: int,
    sizes: dict[str, int] | None = None,
) -> SplitResult:
    sizes = dict(sizes or DEFAULT_SIZES)
    if sum(sizes.values()) != len(docs):
        raise SplitError(
            f"set sizes sum to {sum(sizes.values())} but the corpus has {len(docs)} documents"
        )
    units = assign_units(docs, families)
    comps = build_components(docs)
    comp_of = {d.id: d.component for d in docs}
    # a leak component moves as one, so rank it by its least-exposed member
    tier = {d.id: min(m.exposure_tier for m in comps[d.component]) for d in docs}
    min_pooled = int(families["min_pooled_per_set"])
    assignment: dict[str, str] = {}
    filled: Counter[str] = Counter()
    unit_count: dict[str, Counter[str]] = {s: Counter() for s in SETS}
    sub_count: dict[str, Counter[tuple[str, str]]] = {s: Counter() for s in SETS}

    def place(comp_id: str, target: str) -> bool:
        members = comps[comp_id]
        if any(m.id in assignment for m in members):
            return False
        if filled[target] + len(members) > sizes[target]:
            return False
        for m in members:
            assignment[m.id] = target
            unit_count[target][m.unit] += 1
            sub_count[target][(m.doc_class, m.subclass)] += 1
        filled[target] += len(members)
        return True

    by_unit: dict[str, list[Doc]] = defaultdict(list)
    for d in docs:
        by_unit[d.unit].append(d)
    quotas = {u: unit_quota(info["kind"], info["n"], min_pooled) for u, info in units.items()}
    need = sum(quotas.values())
    for target in ("dev", "heldout"):
        if need > sizes[target]:
            raise SplitError(
                f"{target} holds {sizes[target]} documents but the per-unit quotas need {need}; "
                "raise the set size or the family pooling"
            )

    # 1. held-out quotas, never-tuned documents first; 2. dev quotas.
    for target in ("heldout", "dev"):
        for unit in sorted(by_unit):
            pool = by_unit[unit]
            order = _band_interleaved(pool, seed, f"{target}:{unit}")
            # stable sorts keep the band order: held-out takes never-tuned docs first,
            # dev leaves them for held-out
            if target == "heldout":
                order.sort(key=lambda d: tier[d.id])
            else:
                order.sort(key=lambda d: -tier[d.id])
            for d in order:
                if unit_count[target][unit] >= quotas[unit]:
                    break
                place(comp_of[d.id], target)

    # 3. every rare subclass (3+ docs) at least once in dev and held-out
    sub_n = Counter((d.doc_class, d.subclass) for d in docs)
    for target in ("heldout", "dev"):
        for key in sorted(k for k, n in sub_n.items() if n >= 3):
            if sub_count[target][key]:
                continue
            cands = [d for d in docs if (d.doc_class, d.subclass) == key and d.id not in assignment]
            cands.sort(key=lambda d: (tier[d.id] if target == "heldout" else -tier[d.id],
                                      _h(seed, "rare", target, d.id)))
            for d in cands:
                if place(comp_of[d.id], target):
                    break

    # 4. fill held-out (never-tuned first) and dev to size, spreading across units
    strat_n = Counter((d.doc_class, d.source_corpus) for d in docs)
    cls_n = Counter(d.doc_class for d in docs)

    def fill(target: str, prefer_never_tuned: bool) -> None:
        """Greedy fill toward the corpus (class, source) mix, band-balanced within strata."""
        queues: dict[tuple[str, str], list[Doc]] = {}
        per_stratum: dict[tuple[str, str], list[Doc]] = defaultdict(list)
        for d in docs:
            if d.id not in assignment:
                per_stratum[(d.doc_class, d.source_corpus)].append(d)
        for key, ds in per_stratum.items():
            order = _band_interleaved(ds, seed, f"fill:{target}:{key}")
            order.sort(key=lambda d: tier[d.id] if prefer_never_tuned else -tier[d.id])
            queues[key] = order
        have = Counter((d.doc_class, d.source_corpus) for d in docs if assignment.get(d.id) == target)
        while filled[target] < sizes[target]:
            live = [k for k, q in queues.items() if q]
            if not live:
                break
            if prefer_never_tuned:
                best = min(tier[queues[k][0].id] for k in live)
                live = [k for k in live if tier[queues[k][0].id] == best]
            n_next = filled[target] + 1
            cls_have = Counter()
            for (c, _src), v in have.items():
                cls_have[c] += v
            classes = sorted({k[0] for k in live})
            cls = max(classes, key=lambda c: (cls_n[c] / total * n_next - cls_have[c], c))
            within = [k for k in live if k[0] == cls]
            key = max(within, key=lambda k: (strat_n[k] / cls_n[cls] * (cls_have[cls] + 1) - have[k], k))
            d = queues[key].pop(0)
            if d.id in assignment:
                continue
            if place(comp_of[d.id], target):
                for m in comps[comp_of[d.id]]:
                    have[(m.doc_class, m.source_corpus)] += 1

    total = len(docs)
    fill("heldout", prefer_never_tuned=True)
    fill("dev", prefer_never_tuned=False)

    # 5. calibration and pool split the remainder in the same class x length-band mix,
    #    so the pilot pool also holds long documents (R15 input-cap sweep) and
    #    calibration keeps as close to the corpus class mix as dev/held-out allow.
    share = sizes["pool"] / max(1, sizes["pool"] + sizes["calibration"])
    remaining = [d for d in docs if d.id not in assignment]
    strata: dict[tuple[str, str, str], list[Doc]] = defaultdict(list)
    for d in remaining:
        strata[(d.doc_class, d.source_corpus, d.band)].append(d)
    debt = 0.0  # error diffusion across strata keeps the pool total on target
    for key in sorted(strata):
        for d in sorted(strata[key], key=lambda d: _h(seed, "rem", d.id)):
            if d.id in assignment:
                continue
            debt += share
            target = "pool" if debt >= 0.5 else "calibration"
            if target == "pool":
                debt -= 1.0
            if not place(comp_of[d.id], target):
                other = "calibration" if target == "pool" else "pool"
                if not place(comp_of[d.id], other):
                    raise SplitError(f"could not place {d.id}: calibration and pool are full")
    for s in SETS:
        if filled[s] != sizes[s]:
            raise SplitError(f"{s} has {filled[s]} documents, expected {sizes[s]}")

    short = [f"{t}:{u} {unit_count[t][u]}/{q}" for t in ("dev", "heldout")
             for u, q in sorted(quotas.items()) if unit_count[t][u] < q]
    if short:
        raise SplitError(
            "per-unit quotas not met (leak components forced documents elsewhere): "
            + "; ".join(short[:6]) + " — try another --seed or adjust the families"
        )
    looks = nested_looks([d for d in docs if assignment[d.id] == "dev"], seed)
    return SplitResult(assignment, docs, units, comps, looks, quotas)


def nested_looks(dev: Sequence[Doc], seed: int, looks: Sequence[int] = DEV_LOOKS) -> dict[str, list[str]]:
    """Nested stratified prefixes of dev: each look is a prefix of the next."""
    per_unit: dict[str, list[Doc]] = defaultdict(list)
    for d in dev:
        per_unit[d.unit].append(d)
    ranked: list[tuple[float, str, str]] = []
    for unit, ds in per_unit.items():
        order = _band_interleaved(ds, seed, f"look:{unit}")
        for i, d in enumerate(order):
            ranked.append(((i + 0.5) / len(order), _h(seed, "look", d.id), d.id))
    ranked.sort()
    ordered = [t[2] for t in ranked]
    return {f"dev-look{i + 1}": ordered[:n] for i, n in enumerate(looks)}


# --------------------------------------------------------------------- writing


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ids_bytes(ids: Iterable[str], header: str) -> bytes:
    lines = [f"# {header}", "# Generated by `sandbox splits build`; do not hand-edit."]
    lines += sorted(ids)
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_split(
    result: SplitResult,
    out_dir: Path,
    *,
    seed: int,
    revision: str,
    families_path: Path,
    exposure_path: Path | None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    all_ids = {d.id for d in result.docs}
    files: dict[str, str] = {}

    def emit(name: str, ids: set[str], header: str) -> None:
        data = _ids_bytes(ids, header)
        (out_dir / name).write_bytes(data)
        files[name] = _sha(data)

    members = {s: {i for i, t in result.assignment.items() if t == s} for s in SETS}
    for s in SETS:
        emit(f"{s}.ids", members[s], f"{s}: {len(members[s])} documents")
        emit(f"{s}.exclude.ids", all_ids - members[s],
             f"complement of {s}: use as dataset.exclude_ids_file with split: all")
    for look, ids in result.looks.items():
        emit(f"{look}.ids", set(ids), f"{look}: nested stratified prefix of dev ({len(ids)})")
        emit(f"{look}.exclude.ids", all_ids - set(ids), f"complement of {look}")

    by_id = {d.id: d for d in result.docs}
    rows = [
        {"id": i, "set": result.assignment[i], "doc_class": by_id[i].doc_class,
         "subclass": by_id[i].subclass, "unit": by_id[i].unit, "unit_kind": by_id[i].unit_kind,
         "band": by_id[i].band, "component": by_id[i].component, "hf_split": by_id[i].hf_split,
         "tuned": by_id[i].tuned}
        for i in sorted(result.assignment)
    ]
    data = ("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n").encode()
    (out_dir / "assignments.jsonl").write_bytes(data)
    files["assignments.jsonl"] = _sha(data)

    exposure_sha = _sha(Path(exposure_path).read_bytes()) if exposure_path and Path(exposure_path).is_file() else None
    manifest = {
        "schema": SCHEMA,
        "seed": seed,
        "dataset": {"revision": revision, "rows": len(all_ids)},
        "sizes": {s: len(members[s]) for s in SETS},
        "looks": {k: len(v) for k, v in result.looks.items()},
        "inputs": {
            "families": {"path": _rel(families_path), "sha256": _sha(Path(families_path).read_bytes())},
            "exposure": {"path": _rel(exposure_path) if exposure_path else None, "sha256": exposure_sha},
        },
        "units": {u: {"kind": v["kind"], "n": v["n"], "quota": result.quotas[u],
                      "subclasses": v["subclasses"]} for u, v in sorted(result.units.items())},
        "files": dict(sorted(files.items())),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def _rel(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ----------------------------------------------------------------------- audit


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    gate: bool = True  # False = informational, never fails the audit


def _mix(docs: Iterable[Doc], attr: str) -> dict[str, float]:
    c = Counter(getattr(d, attr) for d in docs)
    n = sum(c.values()) or 1
    return {k: 100.0 * v / n for k, v in c.items()}


def _max_gap(a: dict[str, float], b: dict[str, float]) -> tuple[float, str]:
    keys = set(a) | set(b)
    gap, worst = 0.0, ""
    for k in keys:
        g = abs(a.get(k, 0.0) - b.get(k, 0.0))
        if g > gap:
            gap, worst = g, k
    return gap, worst


def audit(out_dir: Path, docs: list[Doc], families: dict[str, Any]) -> list[Check]:
    """Re-derive every split rule from the written files; ``docs`` = fresh corpus load."""
    checks: list[Check] = []
    manifest = json.loads((out_dir / "manifest.json").read_text())

    # file hashes
    bad = [n for n, sha in manifest["files"].items()
           if not (out_dir / n).is_file() or _sha((out_dir / n).read_bytes()) != sha]
    checks.append(Check("file hashes match manifest", not bad, f"mismatched: {bad}" if bad else f"{len(manifest['files'])} files"))
    fam_sha = _sha((REPO_ROOT / manifest["inputs"]["families"]["path"]).read_bytes()) \
        if (REPO_ROOT / str(manifest["inputs"]["families"]["path"])).is_file() else None
    checks.append(Check("families file unchanged since build", fam_sha == manifest["inputs"]["families"]["sha256"],
                        f"sha256 {str(fam_sha)[:12]}"))
    exp = manifest["inputs"].get("exposure") or {}
    exp_path = REPO_ROOT / str(exp.get("path")) if exp.get("path") else None
    exp_sha = _sha(exp_path.read_bytes()) if exp_path and exp_path.is_file() else None
    checks.append(Check("tuning exposure list unchanged since build", exp_sha == exp.get("sha256"),
                        f"sha256 {str(exp_sha)[:12]} ({exp.get('path') or 'none'})"))

    assignment: dict[str, str] = {}
    dup: list[str] = []
    for s in SETS:
        for i in read_id_file(out_dir / f"{s}.ids"):
            if i in assignment:
                dup.append(i)
            assignment[i] = s
    corpus_ids = {d.id for d in docs}
    missing = corpus_ids - set(assignment)
    extra = set(assignment) - corpus_ids
    checks.append(Check("sets disjoint", not dup, f"{len(dup)} ids in two sets"))
    checks.append(Check("sets cover the corpus exactly", not missing and not extra,
                        f"missing {len(missing)}, unknown {len(extra)}, corpus {len(corpus_ids)}"))
    sizes = Counter(assignment.values())
    checks.append(Check("set sizes match manifest", all(sizes[s] == manifest["sizes"][s] for s in SETS),
                        ", ".join(f"{s}={sizes[s]}" for s in SETS)))
    for s in SETS:
        comp = read_id_file(out_dir / f"{s}.exclude.ids")
        ok = comp == corpus_ids - {i for i, t in assignment.items() if t == s}
        checks.append(Check(f"{s}.exclude.ids is the exact complement", ok, f"{len(comp)} ids"))

    # the written split must be exactly what the seed produces (catches a consistent swap)
    try:
        rebuilt = build_split(docs, families, seed=int(manifest["seed"]), sizes=dict(manifest["sizes"]))
        differ = sorted(i for i in rebuilt.assignment if rebuilt.assignment[i] != assignment.get(i))
        looks_ok = all(set(ids) == read_id_file(out_dir / f"{k}.ids") for k, ids in rebuilt.looks.items())
        checks.append(Check("split reproduces from its seed and inputs", not differ and looks_ok,
                            f"{len(differ)} documents differ from a rebuild; looks match: {looks_ok}"
                            + (f"; e.g. {differ[:3]}" if differ else "")))
    except SplitError as exc:
        checks.append(Check("split reproduces from its seed and inputs", False, f"rebuild refused: {exc}"))

    # leak components
    assign_units(docs, families)
    comps = build_components(docs)
    crossing = [cid for cid, ms in comps.items() if len({assignment.get(m.id) for m in ms}) > 1]
    multi = sum(1 for ms in comps.values() if len(ms) > 1)
    checks.append(Check("no leak component spans two sets", not crossing,
                        f"{multi} linked components; crossing: {crossing[:5]}"))

    # looks nested
    dev_ids = {i for i, t in assignment.items() if t == "dev"}
    l1 = read_id_file(out_dir / "dev-look1.ids")
    l2 = read_id_file(out_dir / "dev-look2.ids")
    checks.append(Check("dev looks nested (look1 ⊂ look2 ⊂ dev)", l1 <= l2 <= dev_ids,
                        f"look1={len(l1)} look2={len(l2)} dev={len(dev_ids)}"))

    by_set: dict[str, list[Doc]] = defaultdict(list)
    for d in docs:
        by_set[assignment.get(d.id, "?")].append(d)

    # unit quotas and rare subclasses
    min_pooled = int(families["min_pooled_per_set"])
    units = manifest["units"]
    short = []
    for s in ("dev", "heldout"):
        got = Counter(d.unit for d in by_set[s])
        for u, info in units.items():
            if got[u] < unit_quota(info["kind"], info["n"], min_pooled):
                short.append(f"{s}:{u} {got[u]}/{unit_quota(info['kind'], info['n'], min_pooled)}")
    checks.append(Check("dev/held-out meet per-unit quotas", not short, "; ".join(short[:6]) or
                        f"{sum(1 for u in units.values() if u['kind'] != 'pooled')} scored units, "
                        f"{sum(1 for u in units.values() if u['kind'] == 'pooled')} pooled"))
    sub_n = Counter((d.doc_class, d.subclass) for d in docs)
    absent = []
    for s in ("dev", "heldout"):
        have = {(d.doc_class, d.subclass) for d in by_set[s]}
        absent += [f"{s}:{c}/{sc}" for (c, sc), n in sub_n.items() if n >= 3 and (c, sc) not in have]
    checks.append(Check("every subclass with 3+ docs in dev and held-out", not absent, "; ".join(absent[:6]) or "all present"))

    # mixes: within-class (gate) and raw (informational: oversampling shifts it by design)
    corpus_by_class: dict[str, list[Doc]] = defaultdict(list)
    for d in docs:
        corpus_by_class[d.doc_class].append(d)
    def within_class_gap(sets: Sequence[str], attr: str) -> tuple[float, str]:
        worst = (0.0, "")
        for s in sets:
            for cls, cds in corpus_by_class.items():
                sds = [d for d in by_set[s] if d.doc_class == cls]
                if len(sds) < 20:
                    continue
                gap, key = _max_gap(_mix(sds, attr), _mix(cds, attr))
                if gap > worst[0]:
                    worst = (gap, f"{s}/{cls}/{key} (n={len(sds)})")
        return worst

    for attr in ("source_corpus", "annotation_method"):
        informative = any(len({getattr(d, attr) for d in cds}) > 1 for cds in corpus_by_class.values())
        gap, where = within_class_gap(("dev", "heldout"), attr)
        if not informative:
            checks.append(Check(f"{attr} mix within class (not testable)", True,
                                f"one {attr} per class in this corpus, so the within-class mix is fixed by class",
                                gate=False))
        else:
            checks.append(Check(f"{attr} mix within ±{MIX_TOLERANCE_PTS:g} pts of corpus (dev/held-out, within class)",
                                gap <= MIX_TOLERANCE_PTS, f"max gap {gap:.1f} pts at {where or '-'}"))
        gap, where = within_class_gap(("calibration",), attr)
        checks.append(Check(f"{attr} mix in calibration (within class, informational)", True,
                            f"max gap {gap:.1f} pts at {where or '-'}", gate=False))
        raw = {s: _max_gap(_mix(by_set[s], attr), _mix(docs, attr)) for s in ("dev", "calibration", "heldout")}
        checks.append(Check(f"{attr} mix vs corpus (raw, informational)", True,
                            ", ".join(f"{s} {g:.1f} pts ({k})" for s, (g, k) in raw.items()), gate=False))

    cal_gap = _max_gap(_mix(by_set["calibration"], "doc_class"), _mix(docs, "doc_class"))
    # Informational: dev/held-out quotas (20 per unit) take most contracts and mergers,
    # so calibration cannot match the corpus mix for them; the design accepts global or
    # per-class gates only where a class has enough calibration documents.
    checks.append(Check("calibration class mix vs corpus (informational)", True,
                        f"max gap {cal_gap[0]:.1f} pts ({cal_gap[1]}); within ±{MIX_TOLERANCE_PTS:g}: "
                        f"{'yes' if cal_gap[0] <= MIX_TOLERANCE_PTS else 'no'}", gate=False))

    # length-band balance inside dev/held-out units (informational)
    worst_band = (0.0, "")
    for s in ("dev", "heldout"):
        for u in units:
            uds = [d for d in by_set[s] if d.unit == u]
            cds = [d for d in docs if d.unit == u]
            if len(uds) >= 10:
                gap, key = _max_gap(_mix(uds, "band"), _mix(cds, "band"))
                if gap > worst_band[0]:
                    worst_band = (gap, f"{s}/{u}/{key}")
    checks.append(Check("length-band balance within units (informational)", True,
                        f"max gap {worst_band[0]:.1f} pts at {worst_band[1] or '-'}", gate=False))

    # held-out exposure
    ho = by_set["heldout"]
    never = sum(1 for d in ho if d.never_tuned)
    avail = sum(1 for d in docs if d.never_tuned)
    tuned = sum(1 for d in ho if d.tuned)
    placed_never = sum(1 for d in docs if d.never_tuned and assignment.get(d.id) == "heldout")
    need = min(avail, manifest["sizes"]["heldout"])
    checks.append(Check("held-out takes every never-tuned document", placed_never >= need,
                        f"{never}/{len(ho)} held-out docs never tuned ({avail} available)"))
    comp_tier = {}
    for d in docs:
        comp_tier[d.component] = min(comp_tier.get(d.component, 9), d.exposure_tier)
    unlinked_tuned = [d.id for d in docs if assignment.get(d.id) == "heldout" and d.exposure_tier == 2
                      and comp_tier[d.component] == 2]
    spare_untuned = sum(1 for d in docs if comp_tier[d.component] == 1 and assignment.get(d.id) != "heldout")
    checks.append(Check("held-out holds a tuning-list document only when linked to an untuned one",
                        not unlinked_tuned or spare_untuned == 0,
                        f"{tuned} tuning-list docs in held-out ({len(unlinked_tuned)} not linked to an untuned doc); "
                        f"{spare_untuned} untuned train docs outside it"))
    return checks


def band_counts(docs: Sequence[Doc], assignment: dict[str, str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for s in SETS:
        c = Counter(d.band for d in docs if assignment.get(d.id) == s)
        out[s] = {b: c.get(b, 0) for b in BANDS}
    return out
