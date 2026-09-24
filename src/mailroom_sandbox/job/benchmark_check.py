"""Loud reproducibility checks for Modal L4 Qwen specialist benchmarks.

Fails closed when the Modal account / GPU posture / pins look wrong so a
cold-start tomorrow morning does not burn credits on a misconfigured deploy.
No secrets are printed — only profile names and path presence.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from mailroom_sandbox.job.spec import (
    FAMILY_CORPUS_SIZE,
    FAMILY_HF_REVISION,
    HF_DEFAULT_REPO,
    RunSpec,
)
from mailroom_sandbox.modernbert import feeder_status

# Hermes Agent Gmail workspace profile (more credits). Never commit tokens —
# only the profile *name* belongs in docs / this check.
HERMES_MODAL_PROFILE = "hermes-agent-jjb"

BENCHMARK_EXPECTED = {
    "model": "Qwen/Qwen3-8B",
    "gpu": "L4",
    "image_tag": "v0.29.0",
    "max_containers": 1,
    "min_containers": 0,
    "scaledown_seconds": 600,
    "concurrency": 4,
    "profile": "modal-vllm",
    "app": "sandbox-vllm",
    "revision": FAMILY_HF_REVISION,
    "repo": HF_DEFAULT_REPO,
}


def _read_modal_toml() -> str | None:
    path = Path.home() / ".modal.toml"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def active_modal_profile_name() -> str | None:
    """Parse ``~/.modal.toml`` for the section with ``active = true``.

    Does not return or log token values.
    """
    text = _read_modal_toml()
    if not text:
        return None
    # Prefer CLI when available (fast-fail if hung — we only use toml parse).
    current: str | None = None
    active: str | None = None
    for line in text.splitlines():
        m = re.match(r"^\[([^\]]+)\]\s*$", line)
        if m:
            current = m.group(1).strip()
            continue
        if current and re.match(r"^active\s*=\s*true\b", line.strip(), re.I):
            active = current
    return active


def _modal_cli_ok() -> dict[str, Any]:
    if not shutil.which("modal"):
        return {"ok": False, "reason": "modal CLI not on PATH — pip install -e '.[deploy]'"}
    try:
        proc = subprocess.run(
            ["modal", "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": f"modal --version failed: {exc}"}
    if proc.returncode != 0:
        return {"ok": False, "reason": f"modal --version rc={proc.returncode}"}
    return {"ok": True, "version": (proc.stdout or proc.stderr or "").strip()}


def check_benchmark_posture(
    *,
    spec: RunSpec | None = None,
    require_hermes: bool = True,
    require_modernbert: bool = False,
) -> dict[str, Any]:
    """Inventory Ready / Missing / Blocked for L4 Qwen specialist runs.

    ``ok`` is True only when there are zero ``errors`` (warnings allowed).
    """
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {
        "expected": dict(BENCHMARK_EXPECTED),
        "family_corpus_size": FAMILY_CORPUS_SIZE,
        "hermes_profile_name": HERMES_MODAL_PROFILE,
    }

    cli = _modal_cli_ok()
    checks["modal_cli"] = cli
    if not cli.get("ok"):
        errors.append(str(cli.get("reason")))

    profile = active_modal_profile_name()
    checks["active_modal_profile"] = profile
    if profile is None:
        errors.append(
            "~/.modal.toml missing or has no active profile — run "
            f"`modal profile activate {HERMES_MODAL_PROFILE}` "
            "(Hermes Agent Gmail account)"
        )
    elif require_hermes and profile != HERMES_MODAL_PROFILE:
        errors.append(
            f"active Modal profile is {profile!r}, expected Hermes "
            f"{HERMES_MODAL_PROFILE!r} — "
            f"`modal profile activate {HERMES_MODAL_PROFILE}` "
            "(do not commit tokens; ~/.modal.toml stays local)"
        )

    # Env posture (names only).
    env_bits = {
        "SANDBOX_PROFILE": os.environ.get("SANDBOX_PROFILE"),
        "MODAL_VLLM_MODEL": os.environ.get("MODAL_VLLM_MODEL"),
        "MODAL_VLLM_GPU": os.environ.get("MODAL_VLLM_GPU"),
        "MODAL_VLLM_IMAGE_TAG": os.environ.get("MODAL_VLLM_IMAGE_TAG"),
        "MODAL_VLLM_MAX_CONTAINERS": os.environ.get("MODAL_VLLM_MAX_CONTAINERS"),
        "MODAL_VLLM_SCALEDOWN_SECONDS": os.environ.get("MODAL_VLLM_SCALEDOWN_SECONDS"),
        "VLLM_BASE_URL_set": bool((os.environ.get("VLLM_BASE_URL") or "").strip()),
        "VLLM_API_KEY_set": bool((os.environ.get("VLLM_API_KEY") or "").strip()),
        "HF_TOKEN_set": bool((os.environ.get("HF_TOKEN") or "").strip()),
        "MODAL_TOKEN_ID_set": bool((os.environ.get("MODAL_TOKEN_ID") or "").strip()),
    }
    checks["env"] = env_bits
    if env_bits.get("MODAL_VLLM_GPU") and env_bits["MODAL_VLLM_GPU"] != "L4":
        warnings.append(
            f"MODAL_VLLM_GPU={env_bits['MODAL_VLLM_GPU']!r} — specialist suite pins L4"
        )
    if env_bits.get("MODAL_VLLM_MODEL") and env_bits["MODAL_VLLM_MODEL"] != BENCHMARK_EXPECTED["model"]:
        warnings.append(
            f"MODAL_VLLM_MODEL={env_bits['MODAL_VLLM_MODEL']!r} — "
            f"expected {BENCHMARK_EXPECTED['model']}"
        )

    if spec is not None:
        spec_errs = _check_spec_pins(spec)
        errors.extend(spec_errs["errors"])
        warnings.extend(spec_errs["warnings"])
        checks["spec"] = {
            "run_id": spec.run_id,
            "task": spec.task,
            "profile": spec.profile,
            "model": spec.engine.model,
            "gpu": spec.engine.modal.gpu if spec.engine.modal else None,
            "image_tag": spec.engine.modal.image_tag if spec.engine.modal else None,
            "concurrency": spec.job.concurrency,
            "revision": spec.effective_revision(),
            "sample_seed": spec.dataset.sample_seed,
            "limit": spec.dataset.limit,
        }

    mb = feeder_status()
    checks["modernbert"] = {
        "ok": mb.get("ok"),
        "mailroom_ml_src": mb.get("mailroom_ml_src"),
        "modernbert_model_path": mb.get("modernbert_model_path"),
    }
    if require_modernbert and not mb.get("ok"):
        errors.append(
            "ModernBERT feeder incomplete — set MAILROOM_ML_SRC + "
            "MODERNBERT_MODEL_PATH (see sandbox modernbert status)"
        )
    elif not mb.get("ok"):
        warnings.append(
            "ModernBERT feeder not resolved (optional for specialist extract "
            "suite; required for sorter_vs_modernbert live)"
        )

    ok = len(errors) == 0
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "markdown": _format_md(ok, errors, warnings, checks),
    }


def _check_spec_pins(spec: RunSpec) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    exp = BENCHMARK_EXPECTED
    if spec.profile != exp["profile"]:
        errors.append(f"spec.profile={spec.profile!r} expected {exp['profile']!r}")
    if spec.engine.model != exp["model"]:
        errors.append(f"spec.engine.model={spec.engine.model!r} expected {exp['model']!r}")
    modal = spec.engine.modal
    if modal is None:
        errors.append("spec.engine.modal missing — specialist suite requires Modal L4 pins")
    else:
        if modal.gpu.split(":")[0] != exp["gpu"]:
            errors.append(f"modal.gpu={modal.gpu!r} expected {exp['gpu']!r}")
        if modal.image_tag != exp["image_tag"]:
            errors.append(f"modal.image_tag={modal.image_tag!r} expected {exp['image_tag']!r}")
        if modal.max_containers != exp["max_containers"]:
            errors.append(
                f"modal.max_containers={modal.max_containers} expected {exp['max_containers']}"
            )
        if modal.scaledown_seconds != exp["scaledown_seconds"]:
            warnings.append(
                f"modal.scaledown_seconds={modal.scaledown_seconds} "
                f"(benchmark default {exp['scaledown_seconds']})"
            )
        if modal.app != exp["app"]:
            warnings.append(f"modal.app={modal.app!r} (default {exp['app']!r})")
    if spec.job.concurrency != exp["concurrency"]:
        errors.append(
            f"job.concurrency={spec.job.concurrency} expected {exp['concurrency']} "
            "(DMR-072: 1 starves continuous batching; >4 piles at 1×L4 proxy)"
        )
    if spec.job.concurrency < 2:
        errors.append("job.concurrency must be >= 2 for L4 throughput benchmarks")
    rev = spec.effective_revision()
    if rev != exp["revision"]:
        errors.append(f"dataset revision={rev!r} expected pin {exp['revision']!r}")
    if spec.dataset.repo and spec.dataset.repo != exp["repo"]:
        warnings.append(f"dataset.repo={spec.dataset.repo!r}")
    if spec.dataset.sample_seed is None:
        warnings.append("dataset.sample_seed unset — strata draws may be non-reproducible")
    return {"errors": errors, "warnings": warnings}


def _format_md(
    ok: bool,
    errors: list[str],
    warnings: list[str],
    checks: Mapping[str, Any],
) -> str:
    lines = [
        f"## Benchmark preflight — {'READY' if ok else 'BLOCKED'}",
        "",
        f"- Modal profile: `{checks.get('active_modal_profile')}` "
        f"(Hermes expected: `{checks.get('hermes_profile_name')}`)",
        f"- Family corpus size pin: {checks.get('family_corpus_size')}",
    ]
    if checks.get("spec"):
        s = checks["spec"]
        lines.append(
            f"- Spec: run_id={s.get('run_id')} task={s.get('task')} "
            f"model={s.get('model')} gpu={s.get('gpu')} "
            f"concurrency={s.get('concurrency')} revision={s.get('revision')}"
        )
    mb = checks.get("modernbert") or {}
    lines.append(
        f"- ModernBERT: ok={mb.get('ok')} path={mb.get('modernbert_model_path')}"
    )
    if errors:
        lines += ["", "### Errors (must fix)"]
        lines.extend(f"- {e}" for e in errors)
    if warnings:
        lines += ["", "### Warnings"]
        lines.extend(f"- {w}" for w in warnings)
    return "\n".join(lines)
