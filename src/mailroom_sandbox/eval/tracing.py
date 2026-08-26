"""Phoenix-first tracing helpers for sandbox runs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mailroom_sandbox.paths import data_dir


def default_tags(*extra: str) -> list[str]:
    tags = ["sandbox", os.environ.get("SANDBOX_PROFILE") or "ollama"]
    mode = os.environ.get("SANDBOX_RUN_MODE") or "local"
    tags.append(mode)
    tags.extend(t for t in extra if t)
    return tags


def tracing_backend() -> str:
    provider = (os.environ.get("OBSERVABILITY_PROVIDER") or "phoenix").lower()
    if provider == "auto":
        if os.environ.get("LANGFUSE_SECRET_KEY"):
            return "langfuse"
        if os.environ.get("BRAINTRUST_API_KEY"):
            return "braintrust"
        if os.environ.get("PHOENIX_TRACING", "enabled").lower() != "disabled":
            return "phoenix"
        return "none"
    return provider


def export_traces(dest: Path | None = None) -> Path:
    """Dump a local trace bookmark file (Phoenix UI is the live viewer).

    Full span export needs a running Phoenix; we write a pointer + env snapshot
    so offline review still knows which sink a run used.
    """
    out = dest or (data_dir() / "traces" / "export.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tracing_backend": tracing_backend(),
        "phoenix_endpoint": os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces"),
        "phoenix_ui": "http://localhost:6006",
        "tags": default_tags(),
        "note": "Inspect live spans in the Phoenix UI. Delete the Phoenix SQLite store to discard a batch.",
    }
    try:
        import httpx

        resp = httpx.get("http://localhost:6006/healthz", timeout=2.0)
        payload["phoenix_health"] = resp.status_code
    except Exception as exc:  # noqa: BLE001 — probe only
        payload["phoenix_health"] = f"unreachable: {exc}"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out
