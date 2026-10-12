"""SAND-042: GPU hardware telemetry sampled inside the Modal serving replica.

The A100 cost cards carried ``gpu utilization % (min/max/n src=serving-replica
nvidia-smi)``, peak util, power draw, temperature and memory used. No L4 card
ever did — ``reports/SAND-37/SAND37_L4_cost_cards.md`` says "nvidia-smi not
sampled", and ``reports/dashboard/gpu_report.py`` recommends sampling it before
the next spend. SAND-042 closes that gap.

The container cannot expose a second HTTP port (Modal allows exactly one
``@modal.web_server`` per function — ``_PartialFunctionParams.update`` raises
"Cannot set `webhook_config` twice"), so the sampler runs *inside* ``serve()``,
appends one JSON line per sample to a Modal Volume, and this module reads that
volume from the operator machine and reduces it to the A100 card's fields.

Reading needs the Modal SDK (the ``[deploy]`` extra) and network. Nothing here
runs on the scoring path: a missing volume, a missing SDK or a missing file all
degrade to ``captured: False`` with a reason, never an exception.
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_log = logging.getLogger("mailroom_sandbox.job.container_telemetry")

SCHEMA = "sandbox.container-telemetry/v1"
DEFAULT_VOLUME = "sandbox-vllm-telemetry"
SRC = "serving-replica nvidia-smi"

# nvidia-smi prints "[N/A]" (or "N/A") for a metric the SKU does not report.
_NA = {"", "n/a", "[n/a]", "na", "[not supported]"}


def _f(value: Any) -> float | None:
    """Parse one nvidia-smi CSV cell, tolerating units and ``[N/A]``."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _NA:
        return None
    for suffix in ("%", "W", "C", "MiB", "MHz"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_nvidia_smi_csv(text: str) -> list[dict[str, Any]]:
    """One nvidia-smi query output → one dict per GPU.

    Expects ``--format=csv,noheader,nounits`` with the column order
    ``index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw``
    (the same query ``tui/pretty_log.py`` uses locally).
    """
    gpus: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        gpus.append(
            {
                "index": parts[0],
                "name": parts[1],
                "utilization_gpu_perc": _f(parts[2]),
                "memory_used_mib": _f(parts[3]),
                "memory_total_mib": _f(parts[4]),
                "temperature_c": _f(parts[5]),
                "power_draw_w": _f(parts[6]),
            }
        )
    return gpus


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    """Sampler JSONL → samples; a malformed line is skipped, never fatal."""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def slice_window(
    samples: Sequence[Mapping[str, Any]], *, start: float | None, end: float | None
) -> list[dict[str, Any]]:
    """Samples whose ``t`` falls inside the run's own scrape window."""
    out: list[dict[str, Any]] = []
    for s in samples:
        t = s.get("t")
        if not isinstance(t, (int, float)):
            continue
        if start is not None and float(t) < float(start):
            continue
        if end is not None and float(t) > float(end):
            continue
        out.append(dict(s))
    return out


def _flat_gpus(samples: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in samples:
        for g in s.get("gpus") or []:
            if isinstance(g, dict):
                out.append(g)
    return out


def _stat(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
        "p95": _p95(values),
        "n": len(values),
    }


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


def summarize_samples(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce a pulled telemetry doc to the A100 cost-card GPU fields.

    ``doc`` is what ``pull`` writes: ``{"samples": [...], "replicas": {...}}``.
    Every field is ``None`` when the metric was never reported, so a card can say
    "not captured" instead of printing a fabricated 0.
    """
    samples = [s for s in (doc.get("samples") or []) if isinstance(s, dict)]
    gpus = _flat_gpus(samples)
    if not gpus:
        return {
            "captured": False,
            "src": SRC,
            "samples": len(samples),
            "reason": doc.get("reason") or "no GPU samples in the telemetry window",
            "errors": list(doc.get("errors") or []),
        }

    def collect(key: str) -> list[float]:
        return [v for v in (_num(g.get(key)) for g in gpus) if v is not None]

    util = collect("utilization_gpu_perc")
    replicas: dict[str, Any] = {}
    for name, rep in sorted((doc.get("replicas") or {}).items()):
        rep_gpus = _flat_gpus(
            [s for s in (rep.get("samples") or []) if isinstance(s, dict)]
        )
        rep_util = [v for v in (_num(g.get("utilization_gpu_perc")) for g in rep_gpus) if v is not None]
        replicas[str(name)] = {
            "samples": len(rep.get("samples") or []),
            "util_mean_perc": statistics.fmean(rep_util) if rep_util else None,
            "util_max_perc": max(rep_util) if rep_util else None,
        }

    return {
        "captured": True,
        "schema": SCHEMA,
        "src": doc.get("src") or SRC,
        "label": doc.get("label"),
        "samples": len(samples),
        "gpus_observed": len(gpus),
        "util_mean_perc": statistics.fmean(util) if util else None,
        "util_min_perc": min(util) if util else None,
        "util_max_perc": max(util) if util else None,
        "util_peak_perc": max(util) if util else None,
        "power_draw_w": _stat(collect("power_draw_w")),
        "temperature_c": _stat(collect("temperature_c")),
        "memory_used_mib": _stat(collect("memory_used_mib")),
        "memory_total_mib": _stat(collect("memory_total_mib")),
        "replicas": replicas,
        "errors": list(doc.get("errors") or []),
    }


def _num(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) else None


# ── volume pull ──────────────────────────────────────────────────────────────


def _read_volume_files(
    label: str, *, volume_name: str = DEFAULT_VOLUME
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """``{replica: samples}`` from ``<label>/<replica>.jsonl`` in the volume.

    The volume is mounted at ``/telemetry`` *inside the container*; from the
    volume's own perspective the sampler's files live at the volume root under
    ``<label>/``. Do not prefix the container mount here.
    """
    import modal  # local import: [deploy] extra, network + auth required

    errors: list[str] = []
    out: dict[str, list[dict[str, Any]]] = {}
    vol = modal.Volume.from_name(volume_name)
    prefix = label.strip("/")

    entries = _listdir(vol, prefix, errors)
    for entry in entries:
        path = str(getattr(entry, "path", "") or "")
        if not path.endswith(".jsonl"):
            continue
        replica = Path(path).name[: -len(".jsonl")]
        try:
            chunks = _read_file(vol, path)
        except Exception as exc:  # noqa: BLE001 — report, never crash the run
            errors.append(f"read {path}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        out[replica] = parse_jsonl(chunks)
    if not entries:
        errors.append(f"no telemetry under {prefix}/ in volume {volume_name!r}")
    return out, errors


def _listdir(vol: Any, prefix: str, errors: list[str]) -> list[Any]:
    try:
        return list(vol.listdir(prefix))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"listdir {prefix}: {type(exc).__name__}: {str(exc)[:120]}")
        return []


def _read_file(vol: Any, path: str) -> str:
    """Drain ``Volume.read_file``.

    ``read_file`` is decorated ``@live_method_gen``, so outside async code it
    returns a *synchronous* generator (the SDK's own docstring iterates it with a
    plain ``for``); an ``async for`` raises "'async for' requires an object with
    __aiter__ method, got generator".
    """
    return b"".join(vol.read_file(path)).decode("utf-8", errors="replace")


def pull(
    label: str,
    *,
    volume_name: str = DEFAULT_VOLUME,
    start: float | None = None,
    end: float | None = None,
) -> dict[str, Any]:
    """Read one cell's telemetry out of the Modal Volume, sliced to the run window."""
    try:
        replicas_raw, errors = _read_volume_files(label, volume_name=volume_name)
    except Exception as exc:  # noqa: BLE001 — no SDK / no auth / volume absent
        return {
            "schema": SCHEMA,
            "label": label,
            "src": SRC,
            "samples": [],
            "replicas": {},
            "errors": [f"{type(exc).__name__}: {str(exc)[:160]}"],
            "reason": (
                "could not read the Modal telemetry volume "
                f"(is the [deploy] extra installed and `modal` authenticated?)"
            ),
        }

    replicas: dict[str, Any] = {}
    flat: list[dict[str, Any]] = []
    for replica, samples in replicas_raw.items():
        windowed = slice_window(samples, start=start, end=end)
        replicas[replica] = {"samples": windowed}
        flat.extend(windowed)
    return {
        "schema": SCHEMA,
        "label": label,
        "src": SRC,
        "volume": volume_name,
        "start": start,
        "end": end,
        "samples": flat,
        "replicas": replicas,
        "errors": errors,
    }
