"""Record the prompts a run actually sends, for the floor's prompt view (``prompts.jsonl``).

``prompt.lock.json`` names the prompt files a run spec pins, but most agents (intake, judge,
arbiter, the classification arbiter, boss) run their code-default prompt, and every request is
also shaped at run time: the JSON schema (with ``job.schema_guide`` descriptions), the sorter
handoff note (HF-028) and the subclass field note. The lock shows none of that. This module
observes each request at the wire seams (``provider_pins`` for chat and LangChain calls,
``decision_backends`` for the Decisions API) and records what was sent.

Two kinds of rows go to the run's sink:

* ``{"kind": "text", "sha256", "role", "chars", "text"}`` once per distinct text in the run:
  a system message, an output schema (``response_format`` / ``tools``), Decisions questions or
  handoff, or a user message. A user message carries the document, so only its first and last
  ``USER_EDGE_CHARS`` are kept (where the handoff and field notes sit), with the omitted span
  marked; ``chars`` is the full length.
* ``{"kind": "call", "doc", "node", "agent", "model", "call_path", "parts": [{"role",
  "sha256", "chars"}]}`` once per request, naming the texts it was built from.

The agent and node come from the read-range context (``job.read_ranges``); a request made
outside a document is recorded with ``doc`` null. Recording never changes or fails a call, and it
is a no-op unless a run has called :func:`activate`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any

_log = logging.getLogger(__name__)

#: Characters kept from each end of a user message (the document sits between them).
USER_EDGE_CHARS = 3000

_LOCK = threading.Lock()
_SINK: Callable[[dict[str, Any]], None] | None = None
_SEEN: set[str] = set()


def activate(sink: Callable[[dict[str, Any]], None] | None, seen: set[str] | None = None) -> None:
    """Send later records to ``sink`` (``None`` turns recording off).

    ``seen`` holds the text hashes the sink already has (a resumed run), so they are not written twice.
    """
    global _SINK
    with _LOCK:
        _SINK = sink
        _SEEN.clear()
        _SEEN.update(seen or ())


def deactivate() -> None:
    """Stop recording."""
    activate(None)


def active() -> bool:
    return _SINK is not None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _content_text(content: Any) -> str:
    """The text of a chat message's ``content`` (a string or a list of typed parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, Mapping):
                if isinstance(part.get("text"), str):
                    out.append(part["text"])
                elif part.get("type"):
                    out.append(f"[{part['type']} part]")
            elif isinstance(part, str):
                out.append(part)
        return "\n".join(out)
    return "" if content is None else str(content)


def user_edges(text: str, edge: int = USER_EDGE_CHARS) -> str:
    """``text`` with its middle replaced by a marker when it is longer than two edges."""
    if len(text) <= 2 * edge:
        return text
    omitted = len(text) - 2 * edge
    return f"{text[:edge]}\n[… {omitted:,} characters omitted (document body) …]\n{text[-edge:]}"


def _context() -> tuple[str | None, str | None, str | None]:
    """``(doc, node, agent)`` of the current request from the read-range context."""
    try:
        from mailroom_sandbox.job import read_ranges

        return read_ranges.current_doc(), read_ranges.current_node(), read_ranges.pending_agent()
    except Exception:  # noqa: BLE001
        return None, None, None


def _emit(parts: list[tuple[str, str, int]], *, model: Any, call_path: str, agent: str | None) -> None:
    sink = _SINK
    if sink is None or not parts:
        return
    doc, node, observed_agent = _context()
    rows: list[dict[str, Any]] = []
    refs = []
    with _LOCK:
        for role, text, chars in parts:
            sha = _sha(text)
            refs.append({"role": role, "sha256": sha, "chars": chars})
            if sha not in _SEEN:
                _SEEN.add(sha)
                rows.append({"kind": "text", "sha256": sha, "role": role, "chars": chars, "text": text})
    rows.append({"kind": "call", "doc": doc, "node": node, "agent": agent or observed_agent,
                 "model": None if model is None else str(model), "call_path": call_path, "parts": refs})
    for row in rows:
        sink(row)


def observe_chat(payload: Mapping[str, Any], *, call_path: str) -> None:
    """Record one chat-completions request (``messages`` plus its output schema, if any)."""
    if _SINK is None:
        return
    try:
        parts: list[tuple[str, str, int]] = []
        for message in payload.get("messages") or ():
            if not isinstance(message, Mapping):
                continue
            role = str(message.get("role") or "user")
            text = _content_text(message.get("content"))
            if role == "user":
                parts.append(("user", user_edges(text), len(text)))
            elif role != "assistant":
                parts.append((role, text, len(text)))
        for key in ("response_format", "tools"):
            if payload.get(key):
                schema = json.dumps(payload[key], sort_keys=True, default=str, ensure_ascii=False)
                parts.append(("schema", schema, len(schema)))
        _emit(parts, model=payload.get("model"), call_path=call_path, agent=None)
    except Exception as exc:  # noqa: BLE001 - recording never fails a call
        _log.debug("prompt capture failed: %s", exc)


def observe_decision(body: Mapping[str, Any], *, agent: str) -> None:
    """Record one Decisions request: its questions and handoff, never the document."""
    if _SINK is None:
        return
    try:
        parts: list[tuple[str, str, int]] = []
        questions = json.dumps(body.get("questions"), sort_keys=True, default=str, ensure_ascii=False)
        parts.append(("questions", questions, len(questions)))
        state = body.get("state")
        if isinstance(state, Mapping):
            handoff = {k: v for k, v in state.items() if k != "document"}
            if handoff:
                text = json.dumps(handoff, sort_keys=True, default=str, ensure_ascii=False)
                parts.append(("handoff", text, len(text)))
        _emit(parts, model=body.get("model"), call_path="decisions", agent=agent)
    except Exception as exc:  # noqa: BLE001 - recording never fails a call
        _log.debug("decision prompt capture failed: %s", exc)
