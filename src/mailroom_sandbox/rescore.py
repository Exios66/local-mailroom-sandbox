"""``sandbox rescore``: re-score a finished run against other ground truth, with no model call.

A run keeps every answer it was given (``items.jsonl``, the raw ``pred`` of each document). When
the truth moves after the run (a dataset revision such as v9.1 to v9.3, a label overlay update, a
scorer hotfix), the answers stay valid and only the scores go stale. Re-scoring rebuilds the
truth of the run's own documents from the chosen source and scores the stored answers again with
the scorer the run's task uses, so calibration of a decision model can move to the new truth
without paying for the run twice.

The source run is never written. The result is a derived run directory (default
``data/runtime/runs/<run_id>.rescore-<label>``) in the runtime layout that ``compare_sorter_arms``
and the gold audit read:

* ``spec.lock.json``: the source lock, with ``dataset`` describing the new truth, ``lock_kind``
  ``rescore.lock``, a new ``run_id`` and a ``rescore`` block holding the source run id, the source
  ``dataset`` block and the truth provenance;
* ``dataset.jsonl``: the new truth rows of the scored documents, in item order;
* ``items.jsonl``: the source items, ``score`` re-computed and the first score kept in
  ``score_original``;
* ``scores.json``: run-level means of every numeric per-item score, overall and by class;
* ``rescore.json``: the provenance and the before/after digest that the CLI prints;
* ``events.jsonl``, ``checkpoint.json`` and ``prompt.lock.json`` copied when present.

Truth sources: the lock's own revision (default; isolates scorer drift while the run's overlays
are unchanged, since they apply at their current content), ``--revision`` (a tag
such as ``v9.3`` or a commit; the run's documents are read from that revision's full corpus, not
re-drawn), or ``--dataset-file`` (a local JSONL, for hand-corrected truth). ``--overlays lock``
(default) applies the label overlays the run used, at their current content; ``none`` drops them;
``all`` applies both. A document the new source lacks stops the rescore unless
``--allow-missing``, which leaves it out and lists it, so no stale score sits beside new ones.
"""

from __future__ import annotations

import functools
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OVERLAY_MODES = ("lock", "none", "all")
# Score keys the digest reports when present: the headline of each task family.
HEADLINE_KEYS = (
    "match", "class_correct", "subclass_match", "subclass_correct", "stage_correct",
    "overall_extraction_score", "field_f1", "field_precision", "field_recall",
)
_COPIED = ("events.jsonl", "checkpoint.json", "prompt.lock.json")
# Report-bundle spellings (reports/campaigns/<c>/<study>/<run>/<iter>/) of the runtime files.
_BUNDLE = {
    "spec.lock.json": ("logs", ".spec-lock.json"),
    "items.jsonl": ("traces", ".items.jsonl"),
    "events.jsonl": ("logs", ".events.jsonl"),
    "checkpoint.json": ("logs", ".checkpoint.json"),
    "prompt.lock.json": ("docs", ".prompt-lock.json"),
}


class RescoreError(RuntimeError):
    """A rescore that cannot give trustworthy scores; nothing was written."""


@dataclass
class RunFiles:
    path: Path
    files: dict[str, Path] = field(default_factory=dict)  # runtime name -> where it is

    def get(self, name: str) -> Path | None:
        return self.files.get(name)


def locate(run: str | Path, *, runs_root: Path | None = None) -> RunFiles:
    """A run's files, in the runtime layout or a committed report bundle."""
    path = Path(run)
    if not path.is_dir():
        if runs_root is None:
            from mailroom_sandbox.job.spec import runs_root as _root

            runs_root = _root()
        path = Path(runs_root) / str(run)
    if not path.is_dir():
        raise RescoreError(f"run {run!r}: no run directory at {path}")
    found = RunFiles(path)
    for name in ("spec.lock.json", "items.jsonl", "dataset.jsonl", *_COPIED):
        if (path / name).is_file():
            found.files[name] = path / name
    for name, (sub, suffix) in _BUNDLE.items():
        if name in found.files:
            continue
        hits = sorted((path / sub).glob(f"*{suffix}")) if (path / sub).is_dir() else []
        if len(hits) > 1:
            raise RescoreError(f"{path}: several {sub}/*{suffix} files; name the run directory itself")
        if hits:
            found.files[name] = hits[0]
    for need in ("spec.lock.json", "items.jsonl"):
        if need not in found.files:
            raise RescoreError(f"{path}: no {need} (neither the runtime nor the report-bundle layout)")
    return found


def _jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="\n") as handle:  # text holds U+2028: split on \n only
        return [json.loads(line) for line in handle.read().split("\n") if line.strip()]


def _dump_jsonl(rows: Iterable[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows)


# --------------------------------------------------------------------------- scorers


def scorer_for(lock: Mapping[str, Any]) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]:
    """The per-item scorer the run's task used, as ``score(row, pred)``.

    ``pipeline`` uses the connected-pipeline scorer, ``specialist`` the specialist of each
    document's class, ``isolated`` the sorter and any other registered agent task its own
    ``AgentSpec.score_one``. Tasks whose items are not per-document answers are refused.
    """
    from mailroom_sandbox.eval import agents, primary, runners

    task = str(lock.get("task") or (lock.get("spec_core") or {}).get("task") or "")
    if task == "pipeline":
        def pipeline(row: dict[str, Any], pred: dict[str, Any]) -> dict[str, Any]:
            return runners.pipeline_item_score(row, pred, runners._score_pipeline_extraction(row, pred))
        return pipeline
    if task == "specialist":
        def specialist(row: dict[str, Any], pred: dict[str, Any]) -> dict[str, Any] | None:
            agent = primary.SPECIALISTS.get(primary.row_class(row))
            # A document the new truth moves out of every specialist class has no specialist score.
            return agents.SPECS[agent].score_one(row, pred) if agent in agents.SPECS else None
        return specialist
    name = "sorter" if task == "isolated" else task
    if name in agents.SPECS:
        return agents.SPECS[name].score_one
    # extract, chained, local_vs_api and sorter_vs_modernbert keep run-level scores only: their
    # runners store no per-document answer, so there is nothing to score again.
    raise RescoreError(f"task {task!r} has no per-document scorer to re-run; its run stores no "
                       "per-document answers (supported: pipeline, specialist, isolated and the "
                       "registered agent tasks)")


# --------------------------------------------------------------------------- truth


def _revision_label(revision: str) -> str:
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION, FAMILY_HF_TAG, LEGACY_FAMILY_HF_REVISIONS

    pairs = {FAMILY_HF_TAG: FAMILY_HF_REVISION, **{k: v[0] for k, v in LEGACY_FAMILY_HF_REVISIONS.items()}}
    return next((tag for tag, commit in pairs.items() if revision in (tag, commit)), revision[:12])


def truth_spec(lock: Mapping[str, Any], *, revision: str | None = None, dataset_file: str | Path | None = None,
               overlays: str = "lock"):
    """The ``DatasetSpec`` the new truth is read from."""
    from mailroom_sandbox.job.spec import DatasetSpec, family_tag_commit

    if overlays not in OVERLAY_MODES:
        raise RescoreError(f"--overlays {overlays!r}: expected one of {list(OVERLAY_MODES)}")
    if revision and dataset_file:
        raise RescoreError("give --revision or --dataset-file, not both")
    core = dict((lock.get("spec_core") or {}).get("dataset") or {})
    locked = dict(lock.get("dataset") or {})
    # A derived run records the overlays its truth was built with; "lock" reads those, not the
    # source spec_core, so a rescore with --overlays none stays without them when re-scored again.
    used = (lock.get("rescore") or {}).get("overlays_effective")
    used = used if isinstance(used, Mapping) else core
    interim = overlays == "all" or (overlays == "lock" and bool(used.get("interim_labels")))
    near_gold = overlays == "all" or (overlays == "lock" and bool(used.get("near_gold_labels")))
    # A staged overlay is the merged master of the other two: a run that used one re-scores
    # with that same pinned cut ("lock" or "all"), never with the layers stacked again.
    staged = used.get("staged_overlay") if overlays != "none" else None
    staged = (staged.get("version") if isinstance(staged, Mapping) else staged) or None
    if staged:
        interim = near_gold = False
    if dataset_file:
        return DatasetSpec(provider="file", local_path=str(dataset_file), interim_labels=interim,
                           near_gold_labels=near_gold, staged_overlay=staged)
    if locked.get("metadata", {}).get("source") == "local" or core.get("provider") == "file":
        if not revision:
            raise RescoreError("the run read a local dataset file; give --dataset-file (or --revision for the Hub)")
    target = revision or locked.get("revision_resolved") or locked.get("revision") or core.get("revision") or ""
    return DatasetSpec(repo=core.get("repo") or locked.get("repo") or DatasetSpec().repo,
                       config=core.get("config") or locked.get("config") or "ground_truth",
                       # The run's documents may come from any split: read them all, draw nothing.
                       split="all", revision=family_tag_commit(str(target)) if target else "",
                       interim_labels=interim, near_gold_labels=near_gold, staged_overlay=staged)


# --------------------------------------------------------------------------- digest


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _truth_key(row: Mapping[str, Any] | None) -> tuple[str, str]:
    if not row:
        return ("", "")
    return (str(row.get("expected_doc_class") or ""), str(row.get("expected_subclass") or ""))


def _numeric_moved(old: Any, new: Any) -> bool:
    old, new = old if isinstance(old, Mapping) else {}, new if isinstance(new, Mapping) else {}
    shared = [k for k in old if k in new and _num(old[k]) is not None and _num(new[k]) is not None]
    return any(abs(_num(old[k]) - _num(new[k])) > 1e-12 for k in shared)  # type: ignore[operator]


def _new_keys(item: Mapping[str, Any], *, lost: bool = False) -> list[str]:
    old, new = item.get("score_original"), item.get("score")
    old, new = set(old) if isinstance(old, Mapping) else set(), set(new) if isinstance(new, Mapping) else set()
    return sorted(old - new if lost else new - old)


def digest(items: Sequence[Mapping[str, Any]], old_truth: Mapping[str, Mapping[str, Any]],
           new_truth: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Before/after means of the headline keys, by class too, and what changed in the truth."""
    rescored = [i for i in items if i.get("rescored")]
    metrics: dict[str, dict[str, Any]] = {}
    by_class: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    for key in HEADLINE_KEYS:
        old_vals, new_vals, both = [], [], []
        for it in rescored:
            old, new = _num((it.get("score_original") or {}).get(key)), _num((it.get("score") or {}).get(key))
            old_vals += [old] if old is not None else []
            new_vals += [new] if new is not None else []
            if old is not None and new is not None:
                both.append((old, new))
                by_class[_truth_key(new_truth.get(str(it.get("item_id"))))[0]][key].append((old, new))
        if not old_vals and not new_vals:
            continue
        metrics[key] = {
            "n_before": len(old_vals), "before": sum(old_vals) / len(old_vals) if old_vals else None,
            "n_after": len(new_vals), "after": sum(new_vals) / len(new_vals) if new_vals else None,
            # Items scored on the key both times; their mean delta is the like-for-like change.
            "n_paired": len(both),
            "paired_delta": sum(n - o for o, n in both) / len(both) if both else None,
            "changed": sum(1 for o, n in both if abs(o - n) > 1e-12),
        }
    classes = {cls: {k: {"n": len(v), "before": sum(o for o, _ in v) / len(v), "after": sum(n for _, n in v) / len(v)}
                     for k, v in keys.items()} for cls, keys in sorted(by_class.items())}
    moves: Counter[str] = Counter()
    fields_changed = 0
    if old_truth:
        for doc_id, new in new_truth.items():
            old = old_truth.get(doc_id)
            if old is None:
                continue
            (oc, osub), (nc, nsub) = _truth_key(old), _truth_key(new)
            if oc != nc:
                moves[f"class {oc} -> {nc}"] += 1
            elif osub != nsub:
                moves[f"{nc}: subclass {osub or '-'} -> {nsub or '-'}"] += 1
            if (old.get("expected_fields") or {}) != (new.get("expected_fields") or {}):
                fields_changed += 1
    return {
        "items": len(items),
        "rescored": len(rescored),
        "carried": len(items) - len(rescored),
        # An item whose shared numeric score keys moved; keys only one side has are counted apart.
        "items_changed": sum(1 for it in rescored if _numeric_moved(it.get("score_original"), it.get("score"))),
        "keys_gained": dict(sorted(Counter(k for it in rescored for k in _new_keys(it)).items())),
        "keys_lost": dict(sorted(Counter(k for it in rescored for k in _new_keys(it, lost=True)).items())),
        "metrics": metrics,
        "by_class": classes,
        "truth_changes": {"compared": bool(old_truth), "label_moves": dict(sorted(moves.items())),
                          "documents_with_field_changes": fields_changed},
    }


def run_scores(items: Sequence[Mapping[str, Any]], truth: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Run-level means of every numeric per-item score key, overall and by truth class.

    These are plain means over the items that carry each key. A task runner's own run summary can
    hold other statistics (macro-F1, confidence intervals), which a rescore does not recompute.
    """
    def means(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        vals: dict[str, list[float]] = defaultdict(list)
        for it in rows:
            for key, value in (it.get("score") or {}).items():
                if (num := _num(value)) is not None:
                    vals[key].append(num)
        return {k: {"n": len(v), "mean": sum(v) / len(v)} for k, v in sorted(vals.items())}

    scored = [i for i in items if i.get("ok") and isinstance(i.get("score"), Mapping)]
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for it in scored:
        groups[_truth_key(truth.get(str(it.get("item_id"))))[0]].append(it)
    return {
        "source": "mean of the re-scored per-item scores (sandbox rescore)",
        "items": len(items),
        "scored": len(scored),
        "unscored": len(items) - len(scored),
        "means": means(scored),
        "by_class": {cls: means(rows) for cls, rows in sorted(groups.items())},
    }


# --------------------------------------------------------------------------- rescore


def _fix_ids(locked: Any) -> list[str] | None:
    """The scoring-hotfix ids a lock recorded (``{"fixes": [{"id": ...}]}`` or a plain list)."""
    fixes = locked.get("fixes") if isinstance(locked, Mapping) else locked
    if not isinstance(fixes, list):
        return None
    return sorted({str(f.get("id") if isinstance(f, Mapping) else f) for f in fixes})


def _hub_run(lock: Mapping[str, Any]) -> bool:
    core = (lock.get("spec_core") or {}).get("dataset") or {}
    return core.get("provider", "huggingface") != "file" and (lock.get("dataset") or {}).get(
        "metadata", {}).get("source", "huggingface") == "huggingface"


def _restrict(items: list[dict[str, Any]], ids: Iterable[str] | None) -> list[dict[str, Any]]:
    if ids is None:
        return items
    wanted = {str(i) for i in ids}
    return [it for it in items if str(it.get("item_id")) in wanted]


def _finished_lock(files: RunFiles, *, force: bool) -> dict[str, Any]:
    lock = json.loads(files.files["spec.lock.json"].read_text(encoding="utf-8"))
    checkpoint = files.get("checkpoint.json")
    if checkpoint is not None and not force:
        state = (json.loads(checkpoint.read_text(encoding="utf-8")) or {}).get("state")
        if state == "running":
            run_id = lock.get("run_id") or files.path.name
            raise RescoreError(f"{run_id}: its checkpoint says 'running'; re-score a finished run (or --force)")
    return lock


def _rescore_items(items: Sequence[Mapping[str, Any]], truth: Mapping[str, Mapping[str, Any]],
                   score: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    """Score stored usable answers against available truth, preserving failures and first scores."""
    out_items: list[dict[str, Any]] = []
    for original in items:
        doc_id = str(original.get("item_id"))
        if doc_id not in truth:
            continue
        item = dict(original)
        pred = item.get("pred")
        if item.get("ok") and isinstance(pred, dict):
            fresh = score(truth[doc_id], pred)
            item.setdefault("score_original", item.get("score"))
            item.update(score=fresh, rescored=True)
        out_items.append(item)
    return out_items


def rescore(run: str | Path, *, revision: str | None = None, dataset_file: str | Path | None = None,
            overlays: str = "lock", ids: Iterable[str] | None = None, out: str | Path | None = None,
            allow_missing: bool = False, force: bool = False, dry_run: bool = False,
            runs_root: Path | None = None, truth_loader: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] | None = None,
            ) -> dict[str, Any]:
    """Re-score ``run`` and write the derived run (unless ``dry_run``); return ``rescore.json``."""
    from mailroom_sandbox import corpus
    from mailroom_sandbox import scoring_hotfixes as sh
    from mailroom_sandbox.job.checkpoint import utc_now

    files = locate(run, runs_root=runs_root)
    lock = _finished_lock(files, force=force)
    run_id = str(lock.get("run_id") or files.path.name)
    score = scorer_for(lock)
    items = _restrict(_jsonl(files.files["items.jsonl"]), ids)
    if not items:
        raise RescoreError(f"{run_id}: no items to re-score" + (" in the given ids" if ids is not None else ""))
    order = list(dict.fromkeys(str(it.get("item_id")) for it in items))

    spec = truth_spec(lock, revision=revision, dataset_file=dataset_file, overlays=overlays)
    # Agent scorers can read truth keys outside the corpus row shape (pdf_transcriber's
    # expected_snippet): normalizing them away would score any non-empty answer as a match.
    load = truth_loader or functools.partial(corpus.truth_rows, keep_raw=_agent_truth(lock))
    rows, meta = load(spec, order)
    new_truth = {str(r["id"]): r for r in rows}
    missing = [i for i in order if i not in new_truth]
    if missing and not allow_missing:
        raise RescoreError(f"{run_id}: {len(missing)} of {len(order)} documents are not in the new truth "
                           f"(first {missing[0]}); --allow-missing leaves them out")
    if files.get("dataset.jsonl"):
        old_truth = {str(r.get("id")): r for r in _jsonl(files.files["dataset.jsonl"])}
    elif not dataset_file and _hub_run(lock):
        # A report bundle keeps no dataset.jsonl: rebuild the truth the run was scored on, so the
        # digest still says which labels moved.
        old_rows, _ = load(truth_spec(lock), order)
        old_truth = {str(r["id"]): r for r in old_rows}
    else:
        old_truth = {}

    out_items = _rescore_items(items, new_truth, score)

    label = ("file-" + str(meta.get("sha256") or "")[:12]) if dataset_file else _revision_label(spec.revision or "")
    dest = Path(out) if out else Path(runs_root or _default_root()) / f"{run_id}.rescore-{label}"
    src_dir, dest_dir = files.path.resolve(), dest.resolve()
    if dest_dir == src_dir or src_dir.is_relative_to(dest_dir) or dest_dir.is_relative_to(src_dir):
        # --force removes --out first: a parent of the source would take the source with it.
        raise RescoreError(f"--out {dest} is the source run, contains it or lies inside it; "
                           "a rescore never rewrites its source")
    meta = _with_row_revision(meta, new_truth.values())
    dataset_payload = _dump_jsonl(new_truth[i] for i in order if i in new_truth)
    counts = Counter(f"{r['expected_doc_class']}::{r['expected_subclass']}" for r in new_truth.values())
    report = {
        "run_id": dest.name,
        "source_run": run_id,
        "source_path": str(files.path),
        "created_at": utc_now(),
        "task": lock.get("task"),
        "truth": {**meta, "overlays": overlays, "dataset_file": str(dataset_file) if dataset_file else None},
        "source_dataset": {k: (lock.get("dataset") or {}).get(k) for k in ("revision", "revision_resolved", "sha256", "rows")},
        "scoring_hotfixes": {"run": _fix_ids(lock.get("scoring_hotfixes")), "rescore": sorted(sh.current_ids())},
        "ids_restricted": ids is not None,
        "missing": missing,
        "digest": digest(out_items, old_truth, new_truth),
        "scores": run_scores(out_items, new_truth),
    }
    if dry_run:
        return {**report, "dry_run": True, "out": str(dest)}
    if dest.exists():
        if not force:
            raise RescoreError(f"{dest} exists; --force replaces it")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    new_lock = json.loads(json.dumps(lock))
    new_lock.update({"run_id": dest.name, "lock_kind": "rescore.lock"})
    # A split's sets are drawn per revision (runbook-v1 on v9.1, runbook-v2 on v9.3, and a v1 dev
    # document can be v2 held-out), so the source's split file stays only while the revision does;
    # otherwise readers resolve the split of the new revision, and its held-out checks apply.
    kept = ("strata_actual",) if not _revision_moved(lock.get("dataset") or {}, meta) else ("strata_actual",
                                                                                            "exclude_ids_file")
    new_lock["dataset"] = {
        **{k: v for k, v in (lock.get("dataset") or {}).items() if k not in kept},
        "revision": meta.get("revision"), "revision_resolved": meta.get("revision_resolved"),
        "rows": len(new_truth), "sha256": hashlib.sha256(dataset_payload.encode("utf-8")).hexdigest(),
        "metadata": {k: v for k, v in meta.items() if k not in ("missing", "rows")},
        "strata_actual": dict(sorted(counts.items())),
    }
    new_lock["rescore"] = {"source_run": run_id, "source_dataset": lock.get("dataset"),
                           "source_spec_hash": lock.get("spec_hash"), "overlays": overlays,
                           "overlays_effective": {"interim_labels": bool(spec.interim_labels),
                                                  "near_gold_labels": bool(spec.near_gold_labels),
                                                  # only when set, so locks without one keep their bytes
                                                  **({"staged_overlay": spec.staged_overlay}
                                                     if spec.staged_overlay else {})},
                           "created_at": report["created_at"], "missing": missing}
    (dest / "spec.lock.json").write_text(json.dumps(new_lock, indent=2, ensure_ascii=False, default=str) + "\n",
                                         encoding="utf-8")
    (dest / "dataset.jsonl").write_text(dataset_payload, encoding="utf-8")
    (dest / "items.jsonl").write_text(_dump_jsonl(out_items), encoding="utf-8")
    for name in _COPIED:
        if files.get(name) is not None:
            shutil.copyfile(files.files[name], dest / name)
    (dest / "scores.json").write_text(json.dumps(report["scores"], indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    (dest / "rescore.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                                       encoding="utf-8")
    return {**report, "out": str(dest)}


def _with_row_revision(meta: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """``meta`` with the revision its rows carry, when the source names none (a local truth file).

    Readers check a lock's revision against its rows' ``source_revision``: a local file that says
    "offline" while its rows carry one real revision would be refused, so that revision is used.
    """
    meta = dict(meta)
    if str(meta.get("revision") or "") not in ("", "offline"):
        return meta
    revs = {str(r.get("source_revision")) for r in rows if str(r.get("source_revision") or "") not in ("", "offline")}
    if len(revs) == 1:
        meta["revision"] = meta["revision_resolved"] = next(iter(revs))
    return meta


def _agent_truth(lock: Mapping[str, Any]) -> bool:
    """Whether the task is scored by an agent spec other than the corpus-shaped ones."""
    task = str(lock.get("task") or (lock.get("spec_core") or {}).get("task") or "")
    return task not in ("pipeline", "specialist", "isolated", "sorter")


def _revision_moved(source: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    """Whether the new truth is on another dataset revision than the run (unknown counts as moved)."""
    from mailroom_sandbox.job.spec import family_tag_commit

    def commit(d: Mapping[str, Any]) -> str:
        rev = str(d.get("revision_resolved") or d.get("revision") or "")
        return family_tag_commit(rev) if rev else ""

    old, new = commit(source), commit(meta)
    return not (old and new and old == new)


def _default_root() -> Path:
    from mailroom_sandbox.job.spec import runs_root

    return runs_root()


# --------------------------------------------------------------------------- CLI


def render(report: Mapping[str, Any]) -> str:
    d = report["digest"]
    truth = report["truth"]
    src = report["source_dataset"]
    lines = [
        f"rescore {report['source_run']} -> {report['run_id']}{' (dry run, nothing written)' if report.get('dry_run') else ''}",
        f"  truth: {truth.get('source')} {truth.get('revision_resolved') or truth.get('revision')}"
        f" (was {src.get('revision_resolved') or src.get('revision')}), overlays {truth.get('overlays')}",
        f"  items: {d['items']} ({d['rescored']} re-scored, {d['carried']} carried unscored, "
        f"{d['items_changed']} changed); missing truth: {len(report['missing'])}",
    ]
    if d["truth_changes"]["compared"]:
        moves = d["truth_changes"]["label_moves"]
        lines.append(f"  truth changes: {sum(moves.values())} label moves, "
                     f"{d['truth_changes']['documents_with_field_changes']} documents with field changes")
        lines += [f"    {k}: {v}" for k, v in list(moves.items())[:20]]
    else:
        lines.append("  truth changes: not compared (the source truth is not available)")
    def f(x: float | None) -> str:
        return f"{x:.4f}" if x is not None else "-"

    lines.append(f"  {'metric':<26}{'n':>5}{'before':>9}{'n':>5}{'after':>9}{'paired':>7}{'delta':>9}{'changed':>8}")
    for key, m in d["metrics"].items():
        lines.append(f"  {key:<26}{m['n_before']:>5}{f(m['before']):>9}{m['n_after']:>5}{f(m['after']):>9}"
                     f"{m['n_paired']:>7}{f(m['paired_delta']):>9}{m['changed']:>8}")
    if d["keys_gained"] or d["keys_lost"]:
        lines.append(f"  score keys gained {d['keys_gained'] or '{}'}, lost {d['keys_lost'] or '{}'}")
    run_fixes, now_fixes = report["scoring_hotfixes"]["run"], report["scoring_hotfixes"]["rescore"]
    if run_fixes is not None and run_fixes != now_fixes:
        added, dropped = sorted(set(now_fixes) - set(run_fixes)), sorted(set(run_fixes) - set(now_fixes))
        lines.append(f"  note: scoring hotfixes changed since the run (added {added or 'none'}, dropped "
                     f"{dropped or 'none'}); part of any delta is the scorer, not the truth")
    if not report.get("dry_run"):
        lines.append(f"  wrote {report['out']}")
    return "\n".join(lines)


def register(sub, leaf) -> None:
    parser = sub.add_parser(
        "rescore", parents=[leaf],
        help="re-score a finished run against other ground truth (another revision, overlays or file); no LLM calls",
    )
    parser.add_argument("run", help="run id under data/runtime/runs, a run directory or a report bundle directory")
    parser.add_argument("--revision", default=None,
                        help="dataset revision for the new truth (tag such as v9.3, or a commit; default the run's own)")
    parser.add_argument("--dataset-file", default=None, help="local JSONL holding the new truth rows")
    parser.add_argument("--overlays", choices=OVERLAY_MODES, default="lock",
                        help="label overlays: those the run used (lock, default), none, or all")
    parser.add_argument("--ids-file", default=None, help="re-score only the document ids in this file")
    parser.add_argument("--set", dest="set_name", default=None,
                        help="re-score only the documents of this split set (dev, dev-look1, heldout, ...)")
    parser.add_argument("--split-dir", default=None, help="split directory for --set (default the current split)")
    parser.add_argument("--out", default=None, help="derived run directory (default <runs>/<run_id>.rescore-<label>)")
    parser.add_argument("--allow-missing", action="store_true",
                        help="leave out documents the new truth lacks instead of stopping")
    parser.add_argument("--force", action="store_true", help="replace an existing --out; re-score a running run")
    parser.add_argument("--dry-run", action="store_true", help="compute and print the digest; write nothing")
    parser.add_argument("--json", action="store_true", help="print rescore.json instead of the digest")
    parser.set_defaults(handler=_cli)


def sorter_arms_error() -> type[Exception]:
    from mailroom_sandbox.sorter_arms import ArmError

    return ArmError


def _cli(args) -> int:
    import sys

    from mailroom_sandbox import corpus

    ids: set[str] | None = None
    try:
        if args.ids_file:
            ids = set(corpus.read_id_list(Path(args.ids_file)))
        if args.set_name:
            from mailroom_sandbox import sorter_arms

            in_set = sorter_arms.set_ids(args.set_name, Path(args.split_dir) if args.split_dir else None)
            ids = in_set if ids is None else ids & in_set
        report = rescore(args.run, revision=args.revision, dataset_file=args.dataset_file, overlays=args.overlays,
                         ids=ids, out=args.out, allow_missing=args.allow_missing, force=args.force,
                         dry_run=args.dry_run)
    except (RescoreError, ValueError, FileNotFoundError, sorter_arms_error()) as exc:
        print(f"sandbox rescore: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, default=str) if args.json else render(report))
    return 0
