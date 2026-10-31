"""Decision-model backends for the Lane A reviewer.

A backend is a plain callable, ``backend(doc_text, doc_types, subclass_catalogs)
-> DecisionAnswer`` (``agents.decision_backend.DecisionBackend`` in the vendored
llm-mailroom). The graph never builds one; the sandbox does, and registers it.

* ``jev_backend`` asks Jev (TypeSafe, through Pydantic AI) two pick-one
  questions: ``doc_type`` and an optional ``doc_subclass``.
* ``local_backend`` runs the ``sorter_reviewer`` agent on the run's own serving
  route, so no document text leaves it. This is the only live path for
  correspondence.
* ``mock_backend`` answers from a fixed table, for offline runs and tests.

Pydantic AI is an optional dependency (``pip install -e ".[decision]"``). It is
imported inside the call path, so offline installs keep working. The family
types (``DecisionAnswer``) are imported lazily too, after
``mailroom_sandbox.runtime.activate`` has put the mailroom source on ``sys.path``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal, Mapping, Optional

if TYPE_CHECKING:  # family types are imported lazily: activate() must run first
    from agents.decision_backend import DecisionBackend
    from pipeline.decision_review import DecisionAnswer

# Jev picks from at most this many options in one question; a 256th is a 400.
MAX_CHOICE_OPTIONS = 255

DEFAULT_MAX_INPUT_CHARS = 12000

# A tuned cutoff is tied to one model version, so only a versioned id is allowed.
_VERSIONED_JEV = re.compile(r"^jev-\d+(\.\d+)+$")

_GOAL = "Classify one document from its text."
_DOC_TYPE_QUESTION = "Which document type is this text?"
_DOC_SUBCLASS_QUESTION = "Which subclass of the document type best fits this text?"


def _answer(
    doc_type: Optional[str], doc_subclass: Optional[str], confidence: Optional[float], model: str
) -> "DecisionAnswer":
    from pipeline.decision_review import DecisionAnswer

    return DecisionAnswer(doc_type, doc_subclass, confidence, model)


def mock_backend(answers: Mapping[str, tuple[str, float]]) -> "DecisionBackend":
    """Answer from ``{substring: (doc_type, confidence)}``; first match wins.

    A document matching no key gets ``("unknown", 0.0)``.
    """
    table = dict(answers)

    def backend(
        doc_text: str, doc_types: list[str], subclass_catalogs: dict[str, list[str]]
    ) -> "DecisionAnswer":
        for needle, (doc_type, confidence) in table.items():
            if needle in doc_text:
                return _answer(doc_type, None, confidence, "mock")
        return _answer("unknown", None, 0.0, "mock")

    return backend


def _checked_options(label: str, options: list[str]) -> list[str]:
    if len(options) > MAX_CHOICE_OPTIONS:
        raise ValueError(
            f"{label}: {len(options)} options exceeds the decision model's "
            f"{MAX_CHOICE_OPTIONS}-option limit for one question"
        )
    return options


def _output_model(doc_types: list[str], subclass_catalogs: Mapping[str, list[str]]) -> type:
    """Pydantic output model: ``doc_type`` pick-one, ``doc_subclass`` optional pick-one."""
    from pydantic import Field, create_model

    types = _checked_options("doc_type", list(dict.fromkeys(doc_types)))
    if len(types) < 2:
        raise ValueError("doc_type needs at least two options for a pick-one question")
    subclasses = _checked_options(
        "doc_subclass",
        list(dict.fromkeys(s for subs in subclass_catalogs.values() for s in subs)),
    )
    fields: dict[str, Any] = {
        "doc_type": (Literal[tuple(types)], Field(description=_DOC_TYPE_QUESTION)),
    }
    if subclasses:
        fields["doc_subclass"] = (
            Optional[Literal[tuple(subclasses)]],
            Field(description=_DOC_SUBCLASS_QUESTION),
        )
    return create_model("DocumentDecision", __doc__=_GOAL, **fields)


def _confidence(provider_details: Any, field: str) -> Optional[float]:
    """The per-field confidence Pydantic AI reports, or None when absent or not a number."""
    if not isinstance(provider_details, dict):
        return None
    by_field = provider_details.get("confidence")
    if not isinstance(by_field, dict):
        return None
    value = by_field.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def jev_backend(
    model: str = "jev-1.13.0", *, max_input_chars: int = DEFAULT_MAX_INPUT_CHARS
) -> "DecisionBackend":
    """Backend over TypeSafe's Jev via Pydantic AI (``TYPESAFE_API_KEY``).

    ``model`` must be a versioned id such as ``jev-1.13.0``; moving aliases
    (``jev-latest``, ``jev-preview``) are refused. The document is cut to
    ``max_input_chars`` before it is sent. The answer's confidence is the model's
    confidence in ``doc_type`` (``None`` when it reports none).
    """
    if not _VERSIONED_JEV.match(model):
        raise ValueError(
            f"{model!r} is not a pinned Jev version (expected e.g. 'jev-1.13.0'); "
            "moving aliases would silently change a tuned cutoff"
        )

    def backend(
        doc_text: str, doc_types: list[str], subclass_catalogs: dict[str, list[str]]
    ) -> "DecisionAnswer":
        try:
            from pydantic_ai import Agent
        except ImportError as exc:
            raise ImportError(
                'Jev backend needs Pydantic AI: pip install -e ".[decision]"'
            ) from exc

        output = _output_model(doc_types, subclass_catalogs)
        # The graph owns the retry budget: no SDK retries, no output retries.
        agent = Agent(
            f"typesafe:{model}",
            output_type=output,
            model_settings={"max_retries": 0},
            retries=0,
        )
        result = agent.run_sync(doc_text[:max_input_chars])
        picked = result.output
        return _answer(
            getattr(picked, "doc_type", None),
            getattr(picked, "doc_subclass", None),
            _confidence(result.response.provider_details, "doc_type"),
            model,
        )

    return backend


def local_backend(model: str) -> "DecisionBackend":
    """Backend over the ``sorter_reviewer`` agent, served in-house.

    ``model`` records which model answered; preflight proves the agent's route
    serves it and that it is not the sorter's own model. Provider errors
    propagate, so the graph's transient and failed-review handling applies.
    """

    def backend(
        doc_text: str, doc_types: list[str], subclass_catalogs: dict[str, list[str]]
    ) -> "DecisionAnswer":
        from agents.sorter_reviewer import SorterReviewerAgent

        picked = SorterReviewerAgent().review(
            doc_text, valid_doc_types=doc_types, doc_subclass_catalogs=subclass_catalogs
        )
        return _answer(picked.get("doc_type"), picked.get("doc_subclass"), picked.get("confidence"), model)

    return backend


def build_backend(name: str, model: str) -> "DecisionBackend":
    """Backend by name: ``jev``, ``local`` (both use ``model``) or ``mock`` (empty table, all unknown)."""
    if name == "jev":
        return jev_backend(model)
    if name == "local":
        return local_backend(model)
    if name == "mock":
        return mock_backend({})
    raise ValueError(f"unknown decision backend {name!r} (expected 'jev', 'local' or 'mock')")
