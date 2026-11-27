"""Committed per-subclass extraction field lists (phase 3, X1: "narrow and extend").

Derived from the label registry ``config/extraction/subclass_schemas.json`` by
:func:`build_field_lists` and committed as ``config/extraction/subclass_extraction_fields.json``.
Runs hash the committed file into their lock and never rebuild it. Every (class,
subclass) in the registry gets an entry:

* ``drop``: class-schema fields the vendored Dojo does not score as a value for the subclass
  (status ``not_applicable``, ``absent_from_dojo`` or ``documented_absent``), unless a dev,
  calibration or pool label gives the field a value there (the registry's ``valued_by_set``):
  the scorer counts a labeled value, so dropping it would turn a hit into a miss. The status
  comes from the Dojo field map, not from labels.
* ``add``: fields outside the class schema with dev, calibration or pool labels whose Dojo
  status is an extraction status (not ``not_applicable``, ``label_task``,
  ``pending_annotation`` or ``absent_from_dojo``).
* ``guide``: the labeling-guide text for kept and added fields that have one.

A subclass's own ``output_schema_fields`` (when the registry records one) replaces the
class's for that subclass.

Held-out labels never shape a list: only the ``dev``, ``calibration`` and ``pool`` counts
are read. Regenerate with ``python scripts/build_subclass_fields.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from mailroom_sandbox.subclass_schemas import DEFAULT_OUT as REGISTRY_PATH

FIELDS_PATH = REGISTRY_PATH.with_name("subclass_extraction_fields.json")
SCHEMA_ID = "mailroom.subclass_extraction_fields/v1"

#: Label sets a schema may be drawn from. ``heldout`` is deliberately absent.
SCHEMA_SETS = ("dev", "calibration", "pool")
_NOT_EXTRACTION = frozenset({"not_applicable", "label_task", "pending_annotation", "absent_from_dojo"})
#: Dojo statuses under which a field is never scored as a value for the subclass.
UNSCORED_FOR_SUBCLASS = frozenset({"not_applicable", "absent_from_dojo", "documented_absent"})


def _canonical_sha256(registry: Mapping[str, Any]) -> str:
    text = json.dumps(registry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _schema_count(entry: Mapping[str, Any], key: str) -> int:
    by_set = entry.get(key) or {}
    return sum(int(by_set.get(name) or 0) for name in SCHEMA_SETS)


def _subclass_lists(fields: Mapping[str, Any], output_fields: set[str]) -> dict[str, Any]:
    drop: list[str] = []
    add: dict[str, dict[str, str]] = {}
    guide: dict[str, str] = {}
    for name in sorted(fields):
        entry = fields[name]
        status = entry.get("dojo_status")
        if name in output_fields:
            if status in UNSCORED_FOR_SUBCLASS and _schema_count(entry, "valued_by_set") <= 0:
                drop.append(name)
                continue
        elif status in _NOT_EXTRACTION or _schema_count(entry, "labeled_by_set") <= 0:
            continue
        else:
            add[name] = {"type": str(entry.get("type") or "text")}
        text = entry.get("guide")
        if isinstance(text, str) and text.strip():
            guide[name] = text
    return {"drop": drop, "add": add, "guide": guide}


def build_field_lists(registry: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the per-subclass field lists from a label registry document."""
    classes: dict[str, dict[str, Any]] = {}
    for cls in sorted(registry.get("classes") or {}):
        entry = registry["classes"][cls]
        output_fields = set(entry.get("output_schema_fields") or ())
        subclasses = entry.get("subclasses") or {}
        classes[cls] = {
            sub: _subclass_lists(subclasses[sub].get("fields") or {},
                                 set(output_fields if subclasses[sub].get("output_schema_fields") is None
                                     else subclasses[sub]["output_schema_fields"]))
            for sub in sorted(subclasses)
        }
    return {"schema": SCHEMA_ID, "registry_sha256": _canonical_sha256(registry), "classes": classes}


def render(lists: Mapping[str, Any]) -> str:
    """The committed file's exact text."""
    return json.dumps(lists, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_field_lists(path: Path | None = None) -> dict[str, Any]:
    """Read the committed field lists (``FIELDS_PATH`` at call time by default)."""
    return json.loads((path or FIELDS_PATH).read_text(encoding="utf-8"))


def field_lists_sha256(path: Path | None = None) -> str:
    """sha256 of the committed file's bytes: the value a run lock records."""
    return hashlib.sha256((path or FIELDS_PATH).read_bytes()).hexdigest()


def read_field_lists(path: Path | None = None) -> tuple[dict[str, Any], str]:
    """The committed lists and the sha256 of the very bytes they were parsed from (one read)."""
    data = (path or FIELDS_PATH).read_bytes()
    return json.loads(data.decode("utf-8")), hashlib.sha256(data).hexdigest()
