"""Sandbox hotfixes over the vendored llm-mailroom snapshot, until upstream catches up.

``vendor/`` stays byte-identical to its pin (``tests/test_vendor_drift.py``), so a fix the
experiments need before the owning repo ships it is installed here, at activation, as a
wrapper around one vendored function. Each hotfix is bound to the exact source of the
function it wraps:

- the target's ``inspect.getsource`` sha256 must equal ``source_sha256``. After a vendor
  refresh changes the function, the hotfix is not applied and its status is ``stale``:
  ``sandbox run preflight`` fails until the hotfix is re-validated against the new code or
  retired because upstream shipped the fix.
- every run lock records the hotfix set (``dependency_sources.describe()["hotfixes"]``): ids,
  target fingerprints and the sha256 of this module, so results name the code that scored them.

Add a hotfix only for pipeline behavior an experiment depends on, with a test, an upstream
issue or PR in ``upstream`` and the CHANGELOG entry. Never patch scoring here: the scorer is
the Dojo pin. See ``docs/vendor-hotfixes.md``.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_log = logging.getLogger("mailroom_sandbox.vendor_hotfixes")

_MARK = "_sandbox_hotfix"


@dataclass(frozen=True)
class Hotfix:
    id: str
    module: str
    attr: str
    source_sha256: str  # sha256 of inspect.getsource(<vendored target>) the fix was written against
    upstream: str
    summary: str
    install: Callable[[Any, Callable[..., Any]], Callable[..., Any]]


def corporate_record_type_for(subclass: Any) -> str | None:
    """The Hub ``record_type`` a corporate-record subclass implies (Dojo ``corporate_record_schema``).

    The sorter catalog has eleven corporate subclasses, the Hub ``record_type`` inventory five;
    Dojo maps each subclass onto one (indenture, board_resolution, officer_certificate and
    subsidiary_list are ``other``; charter_amendment and certificate_of_formation are
    ``articles_of_incorporation``). Unknown tokens map to nothing.
    """
    from langchain_agents.doc_inventories import sorter_subclass_catalog  # type: ignore
    from llm_dojo_scoring.schemas import corporate_record_schema as crs

    token = str(subclass or "").strip().lower()
    if token not in sorter_subclass_catalog("corporate_record"):
        return None
    return crs.subclass_schema(token).record_type or None


def _install_record_type_from_subclass(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def enrich_extraction(extracted: dict | None = None, *, doc_type: str | None = None,
                          extract_class: str | None = None, subtype: str | None = None) -> dict:
        out = original(extracted, doc_type=doc_type, extract_class=extract_class, subtype=subtype)
        # Upstream backfills a null record_type from the subclass only when the subclass is one
        # of the five Hub tokens; the other six corporate subclasses left it null.
        if str(doc_type or "") == "corporate_record" and subtype and not out.get("record_type"):
            token = corporate_record_type_for(subtype)
            if token:
                out["record_type"] = token
        return out

    return enrich_extraction


HOTFIXES: tuple[Hotfix, ...] = (
    Hotfix(
        id="HF-001",
        module="langchain_agents.doc_inventories",
        attr="enrich_extraction",
        source_sha256="a9986cab125fc26e76d36de77ccd4a18d0537f5fa93f6ce146e9389186d20a90",
        upstream="Exios66/llm-mailroom (issue pending)",
        summary="corporate_record: a null record_type is filled from every corporate subclass "
                "through Dojo's subclass -> record_type map, not only the five Hub tokens",
        install=_install_record_type_from_subclass,
    ),
)

_STATUS: dict[str, str] = {}


def _source_sha(obj: Any) -> str:
    return hashlib.sha256(inspect.getsource(inspect.unwrap(obj)).encode("utf-8")).hexdigest()


def module_sha256() -> str:
    """sha256 of this module: the hotfix code identity a run lock records."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def apply_hotfixes(hotfixes: tuple[Hotfix, ...] = HOTFIXES) -> dict[str, str]:
    """Install every hotfix whose target still matches (idempotent); ``{id: status}``.

    Status is ``applied``, ``stale`` (the vendored target changed, so the fix was not
    installed) or ``unavailable`` (the vendored module cannot be imported here).
    """
    for fix in hotfixes:
        try:
            module = importlib.import_module(fix.module)
        except Exception as exc:  # noqa: BLE001 — optional (pipeline extra)
            _log.debug("%s: %s unavailable: %s", fix.id, fix.module, exc)
            _STATUS[fix.id] = "unavailable"
            continue
        current = getattr(module, fix.attr)
        if getattr(current, _MARK, None) == fix.id:
            _STATUS[fix.id] = "applied"
            continue
        if _source_sha(current) != fix.source_sha256:
            _log.warning("%s not applied: vendored %s.%s changed since the hotfix was written "
                         "(re-validate it or retire it)", fix.id, fix.module, fix.attr)
            _STATUS[fix.id] = "stale"
            continue
        wrapped = fix.install(module, current)
        setattr(wrapped, _MARK, fix.id)
        setattr(module, fix.attr, wrapped)
        _STATUS[fix.id] = "applied"
        _log.info("%s applied: %s", fix.id, fix.summary)
    return {fix.id: _STATUS[fix.id] for fix in hotfixes}


def describe() -> dict[str, Any]:
    """Portable hotfix identity for run locks: module sha and each fix's target fingerprint."""
    return {
        "module_sha256": module_sha256(),
        "fixes": [{"id": f.id, "target": f"{f.module}.{f.attr}", "source_sha256": f.source_sha256}
                  for f in HOTFIXES],
    }


def stale() -> list[str]:
    """Hotfixes whose vendored target no longer matches (after :func:`apply_hotfixes`)."""
    status = apply_hotfixes()
    return [i for i, s in status.items() if s == "stale"]
