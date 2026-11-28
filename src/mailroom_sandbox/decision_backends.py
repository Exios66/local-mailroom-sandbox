"""Decision-model backends for the Lane A reviewer.

A backend is a plain callable, ``backend(doc_text, doc_types, subclass_catalogs)
-> DecisionAnswer`` (``agents.decision_backend.DecisionBackend`` in the vendored
llm-mailroom). The graph never builds one; the sandbox does, and registers it.

* ``jev_backend`` asks Jev (TypeSafe, through Pydantic AI) two pick-one
  questions: ``doc_type`` and an optional ``doc_subclass``.
* ``local_backend`` runs the ``sorter_reviewer`` agent on the run's own serving
  route, so no document text leaves it.
* ``api_backend`` runs the same agent on a third-party API route, pinned to one
  model id.
* ``decisions_backend`` asks a Decisions-API model (``openai/gpt-6-luna-decisions``
  on OpenRouter) a question set from ``config/decisions``: one request per document,
  a probability for every option, no output tokens.
* ``mock_backend`` answers from a fixed table, for offline runs and tests.

Pydantic AI is an optional dependency (``pip install -e ".[decision]"``). It is
imported inside the call path, so offline installs keep working. The family
types (``DecisionAnswer``) are imported lazily too, after
``mailroom_sandbox.runtime.activate`` has put the mailroom source on ``sys.path``.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import math
import re
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Mapping, Optional

if TYPE_CHECKING:  # family types are imported lazily: activate() must run first
    from agents.decision_backend import DecisionBackend
    from pipeline.decision_review import DecisionAnswer

# Jev picks from at most this many options in one question; a 256th is a 400.
MAX_CHOICE_OPTIONS = 255

DEFAULT_MAX_INPUT_CHARS = 12000

# A tuned cutoff is tied to one model version, so only a versioned id is allowed.
_VERSIONED_JEV = re.compile(r"^jev-\d+(\.\d+)+$")

# OpenRouter's moving aliases (``~``, ``-latest``) and routing variants (``:floor``).
_PINNED_API = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")

_GOAL = "Classify one document from its text."
_DOC_TYPE_QUESTION = "Which document type is this text?"
_DOC_SUBCLASS_QUESTION = "Which subclass of the document type best fits this text?"
_DOCUMENT_FORM_QUESTION = "What form is this document in, as an input to extraction?"


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


def _norm_class(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


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
        prompt = doc_text[:max_input_chars]
        _record_read("jev", prompt)
        result = agent.run_sync(prompt)
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


def api_backend(model: str) -> "DecisionBackend":
    """Backend over the ``sorter_reviewer`` agent on a third-party API route.

    ``model`` must be an exact provider id such as ``openai/gpt-6-luna``, because a
    tuned cutoff is tied to one model; ``openrouter/*`` ids route dynamically. Preflight proves the agent's route serves it.
    """
    if not _PINNED_API.match(model) or model.endswith("-latest") or model.startswith("openrouter/"):
        raise ValueError(
            f"{model!r} is not a pinned API model id (expected e.g. 'openai/gpt-6-luna'); "
            "moving aliases would silently change a tuned cutoff"
        )
    return local_backend(model)


# ---------------------------------------------------------------------------
# Decisions API (OpenRouter alpha): typed answers with a probability per option.
# ---------------------------------------------------------------------------

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DECISIONS_DIR_NAME = "decisions"
# Full documents fit: the largest train document is about 1.0M characters (~250k tokens),
# inside Luna Decisions' 1.05M-token context. The cap only guards against a runaway input.
DECISIONS_MAX_INPUT_CHARS = 2_000_000
# Sizing of one Decisions request: 0.25 tokens per character, an estimate measured on Luna only
# (fit 0.2073; unverified for other tokenizers), plus a question reserve of at least 4k tokens
# (larger when the serialized questions are: reviewer v4.2.0 is ~4.6k tokens). Preflight and the
# autoresearch context check (autoresearch/levers.py) size requests with the same numbers.
DECISIONS_TOKENS_PER_CHAR = 0.25
DECISIONS_QUESTION_TOKENS = 4000
# Below this many document characters a request answers on a sliver of the document: refuse it.
DECISIONS_MIN_WINDOW_CHARS = 8000
_TRANSIENT = {408, 429, 500, 502, 503, 504, 524, 529}


def classify_window_chars(qset: Mapping[str, Any] | None, override: Any = None) -> int:
    """Document characters sent to one Decisions classify call.

    The question set's ``max_input_chars`` is the floor. A run's ``reviewer.max_input_chars``
    may raise it so a model with a million-token window is not cut at a million characters.
    The override never lowers the set.
    """
    set_cap = 0
    if isinstance(qset, Mapping):
        try:
            set_cap = int(qset.get("max_input_chars") or 0)
        except (TypeError, ValueError):
            set_cap = 0
    extra = override if isinstance(override, int) and not isinstance(override, bool) and override > 0 else 0
    if set_cap and extra:
        return max(set_cap, extra)
    return extra or set_cap or DECISIONS_MAX_INPUT_CHARS

# A card-shaped number: four groups of four digits with a space or hyphen between groups
# (plus up to three trailing digits). OpenRouter's Decisions endpoint refuses a document
# holding one (403 "content filter: [CREDIT_CARD]"), even a synthetic IBAN tail, and the
# refusal leaves the reviewer with no answer. The digits carry no classification or
# field-support signal, so they are masked before any request. Unbroken digit runs
# (EDGAR accession numbers, claim notice ids) passed the filter and are extracted fields, so
# they are kept.
_CARD_SHAPED = re.compile(r"(?<![\w-])\d{4}(?:[ -]\d{4}){3}(?:[ -]?\d{1,3})?(?![\w-])")


def mask_card_numbers(text: str) -> str:
    """Replace every digit of each card-shaped number with ``#``; separators and other text stay."""
    return _CARD_SHAPED.sub(lambda m: re.sub(r"\d", "#", m.group()), text)


def _mask_card_values(value: Any) -> Any:
    """``mask_card_numbers`` on every string inside a JSON-like value (keys stay unchanged)."""
    if isinstance(value, str):
        return mask_card_numbers(value)
    if isinstance(value, Mapping):
        return {k: _mask_card_values(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_card_values(v) for v in value]
    return value
NOT_THIS_CLASS = "not_this_class"
SUBCLASS_UNDETERMINED = "undetermined"
# The class-level abstain thresholds a question set may set (4.0.0+). Each one is optional.
ABSTAIN_KEYS = ("margin", "subclass_not_this_class_max", "unknown_max")
SUBCLASS_POLICIES = ("park", "keep_sorter")


# Built-in floor for the catalog: the one model every locked run so far used. config/decision_models.yaml
# (OpenRouter ``GET /api/v1/models?output_modalities=decisions``) is the real list.
_BUILTIN_DECISION_MODELS: dict[str, dict[str, Any]] = {
    "openai/gpt-6-luna-decisions": {"canonical_slug": "openai/gpt-6-luna-decisions-20261006",
                                    "endpoints": ["/api/alpha/decisions"], "context_length": 1_050_000,
                                    "prompt": 0.10},
}


def _is_alias(model: str) -> bool:
    """A moving alias (``~org/model``, ``...-latest``, with or without a ``:variant``): never a pinned decision model."""
    base = model.split(":", 1)[0]
    return base.startswith("~") or base.endswith("-latest")


@functools.lru_cache(maxsize=1)
def decision_catalog() -> dict[str, dict[str, Any]]:
    """The Decisions-API models from ``config/decision_models.yaml``, by id (built-in floor if unreadable)."""
    import yaml

    from mailroom_sandbox.paths import config_dir

    try:
        doc = yaml.safe_load((config_dir() / "decision_models.yaml").read_text(encoding="utf-8")) or {}
        models = {str(k): dict(v or {}) for k, v in (doc.get("models") or {}).items() if not _is_alias(str(k))}
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
        models = {}
    return {**_BUILTIN_DECISION_MODELS, **models}


def decision_model(model: str | None) -> dict[str, Any] | None:
    """The catalog row of a pinned Decisions-API model (by id or canonical slug), else None."""
    if not model or _is_alias(str(model)):
        return None
    catalog = decision_catalog()
    if str(model) in catalog:
        return catalog[str(model)]
    return next((row for row in catalog.values() if row.get("canonical_slug") == model), None)


def decision_window_chars(model: str | None, *, question_chars: int = 0) -> int | None:
    """The most document characters one request to ``model`` can carry, from its catalog ``context_length``.

    ``None`` when the catalog gives no window (the question set's cap then applies alone). A
    ``:variant`` has its base's window. The reserve is the larger of ``DECISIONS_QUESTION_TOKENS``
    and the questions actually sent (``question_chars``), so a small-window model (Jev 1.14 at
    262,144 tokens, Clef at 65k) is cut to what it should accept by ``DECISIONS_TOKENS_PER_CHAR``
    (an estimate measured on Luna only) instead of being sent a request its window cannot hold.
    """
    if not model:
        return None
    row = decision_model(model) or decision_model(str(model).split(":", 1)[0])
    try:
        context = int((row or {}).get("context_length") or 0)
    except (TypeError, ValueError):
        context = 0
    if context <= 0:
        return None
    reserve = max(DECISIONS_QUESTION_TOKENS, int(question_chars * DECISIONS_TOKENS_PER_CHAR) + 1000)
    return max(0, int((context - reserve) / DECISIONS_TOKENS_PER_CHAR))


def decision_input_cap(model: str | None, cap: int | None, *, question_chars: int = 0) -> int:
    """The input cap a request to ``model`` uses: the question set's ``cap`` (else the global), within the model's window.

    Luna Decisions (1.05M tokens) keeps every question set's own cap; a model with a smaller
    window gets the smaller of the two, and the answer reports ``truncated`` as before.
    """
    limit = int(cap or DECISIONS_MAX_INPUT_CHARS)
    window = decision_window_chars(model, question_chars=question_chars)
    if window is not None and window < min(limit, DECISIONS_MIN_WINDOW_CHARS):
        raise ValueError(f"{model!r} has room for only {window:,} document characters next to these questions "
                         f"(minimum {min(limit, DECISIONS_MIN_WINDOW_CHARS):,}); choose a model with a larger context")
    return limit if window is None else min(limit, window)


def is_decisions_model(model: str | None) -> bool:
    """True for a pinned Decisions-API model id listed in ``config/decision_models.yaml``.

    A name that merely looks like one is not enough (``typesafe/jev-router`` is a chat model), and a
    moving alias (``~typesafe/jev-latest``, ``...-latest``) is refused: a cutoff is tuned to one version.

    An OpenRouter ``:variant`` suffix (``openai/gpt-6-luna-decisions:nitro``) is accepted when the id without it
    is listed; an id that is itself listed with a variant (``perplexity/pplx-decider-v1.3:free``) matches exactly
    first. An alias stays refused with a variant too (``~typesafe/jev-latest:free``). ``decision_model`` itself
    stays exact, so pricing never assumes a variant bills like its base.
    """
    if decision_model(model) is not None:
        return True
    base, _, variant = str(model or "").partition(":")
    return bool(variant) and decision_model(base) is not None


# The decision models the reviewer lane supports, by backend. A model outside this list can
# still be frozen (the spec guards check its shape), but these are the ones calibrated here.
# Only openai/gpt-6-luna-decisions is calibrated; the others are the ones the autoresearch
# loop measures (config/autoresearch/levers.yaml). Jev goes through OpenRouter Decisions
# (typesafe/jev-1.14, typesafe/jev-1.13); the ``jev`` backend calls TypeSafe directly.
SUPPORTED_DECISION_MODELS: dict[str, tuple[str, ...]] = {
    "jev": ("jev-1.13.0",),
    "decisions": ("openai/gpt-6-luna-decisions", "typesafe/jev-1.14", "typesafe/jev-1.13", "liquid/d1.2",
                  "perplexity/pplx-decider-v1.2", "upstage/solar-decide", "google/gemini-decision-1"),
}


def frontrunner_question_set() -> str:
    """The question-set stem the lineage (config/decisions/LINEAGE.yaml) names as frontrunner."""
    import yaml

    lineage = yaml.safe_load((decisions_dir() / "LINEAGE.yaml").read_text(encoding="utf-8")) or {}
    front = str(lineage.get("frontrunner") or "")
    for entry in lineage.get("versions") or []:
        if str(entry.get("version")) == front:
            return str(entry["file"]).removesuffix(".yaml")
    raise ValueError(f"LINEAGE.yaml frontrunner {front!r} has no versions entry")


def decisions_dir() -> "Any":
    from mailroom_sandbox.paths import repo_root

    return repo_root() / "config" / DECISIONS_DIR_NAME


def load_question_set(stem: str) -> dict[str, Any]:
    """Parse ``config/decisions/<stem>.yaml`` and check its shape."""
    import yaml

    if not stem or "/" in stem or stem.startswith("."):
        raise ValueError(f"question set {stem!r} must be a plain stem under config/decisions/")
    path = decisions_dir() / f"{stem}.yaml"
    if not path.is_file():
        raise ValueError(f"question set {stem!r} not found at {path}")
    qset = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if qset.get("kind") == EXTRACTION_GATE:
        return _checked_gate_set(stem, qset)
    if qset.get("kind") == CLOSED_FIELD_RESOLVER:
        return _checked_resolver_set(stem, qset)
    doc_type = qset.get("doc_type") or {}
    if not isinstance(doc_type.get("criteria"), dict) or len(doc_type["criteria"]) < 2:
        raise ValueError(f"{stem}: doc_type needs instructions and at least two criteria")
    verdict = qset.get("verdict")
    if verdict is not None:
        if not isinstance(verdict.get("criteria"), dict) or len(verdict["criteria"]) < 2:
            raise ValueError(f"{stem}: verdict needs instructions and at least two criteria")
        if set(qset.get("human_verdicts") or []) - set(verdict["criteria"]):
            raise ValueError(f"{stem}: human_verdicts must name verdict options")
    for cls, block in (qset.get("subclass") or {}).items():
        if not isinstance(block, dict) or not isinstance(block.get("criteria"), dict) or not block["criteria"]:
            raise ValueError(f"{stem}: subclass.{cls} needs instructions and criteria")
        if block.get("markers") is not None:
            markers, order = block["markers"], block.get("order") or []
            if not isinstance(markers, dict) or not markers or set(order) - set(markers):
                raise ValueError(f"{stem}: subclass.{cls}.order must name only keys of its markers")
    _check_v42_keys(stem, qset)
    return qset


def _check_v42_form_flags(stem: str, qset: Mapping[str, Any]) -> None:
    """``document_form_flags`` shape: exclusive with ``document_form``, park_min in (0, 1]."""
    flags = qset.get("document_form_flags")
    if flags is None:
        return
    if not isinstance(flags, dict):
        raise ValueError(f"{stem}: document_form_flags must be a mapping with park_min and flags")
    items = flags.get("flags")
    if not isinstance(items, dict) or not items or not all(isinstance(v, dict) and v.get("instructions") for v in items.values()):
        raise ValueError(f"{stem}: document_form_flags.flags needs one block with instructions per flag")
    if qset.get("document_form"):
        raise ValueError(f"{stem}: ask document_form or document_form_flags, not both")
    if not 0.0 < float(flags.get("park_min", 0.5)) <= 1.0:
        raise ValueError(f"{stem}: document_form_flags.park_min must be in (0, 1]")


def _is_string_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    return all(isinstance(item, str) for item in value)


def _exclude_names_known(qset: Mapping[str, Any], cls: str, names: list[str]) -> bool:
    options = ((qset.get("subclass") or {}).get(cls) or {}).get("criteria") or {}
    return bool(options) and all(name in options for name in names)


def _check_v42_fit_exclude(stem: str, qset: Mapping[str, Any], exclude: Any) -> None:
    """``subclass_fit.exclude`` is a list or class→option-list map naming known criteria."""
    groups = list(exclude.values()) if isinstance(exclude, dict) else [exclude]
    if any(not _is_string_list(group) for group in groups):
        raise ValueError(f"{stem}: subclass_fit.exclude must be a list or class mapping of option lists")
    if not isinstance(exclude, dict):
        return
    for cls, names in exclude.items():
        if not _exclude_names_known(qset, cls, names):
            raise ValueError(f"{stem}: subclass_fit.exclude has an unknown class or option")


def _check_v42_subclass_fit(stem: str, qset: Mapping[str, Any]) -> None:
    """``subclass_fit`` instructions/exclusions and ``abstain.subclass_fit_min`` when set."""
    fit = qset.get("subclass_fit")
    if fit is not None:
        exclude = fit.get("exclude", []) if isinstance(fit, dict) else None
        _check_v42_fit_exclude(stem, qset, exclude)
        text = str(fit.get("instructions") or "")
        if "{cls}" not in text or "{options}" not in text:
            raise ValueError(f"{stem}: subclass_fit.instructions must name {{cls}} and {{options}}")
    fit_min = (qset.get("abstain") or {}).get("subclass_fit_min")
    if fit_min is not None and not 0.0 < float(fit_min) <= 1.0:
        raise ValueError(f"{stem}: abstain.subclass_fit_min must be in (0, 1]")


def _check_v42_keys(stem: str, qset: Mapping[str, Any]) -> None:
    """Shape checks for the 4.2.0 keys; a misspelt block must fail at load, not mid-run."""
    if qset.get("state_shape") not in (None, "object"):
        raise ValueError(f"{stem}: state_shape must be 'object' when set")
    if qset.get("session_id") not in (None, "run"):
        raise ValueError(f"{stem}: session_id must be 'run' when set")
    for key in ("form_signals", "record_refusals"):
        if key in qset and not isinstance(qset[key], bool):
            raise ValueError(f"{stem}: {key} must be true or false")
    if "untrusted_notice" in qset and not (isinstance(qset["untrusted_notice"], str) and qset["untrusted_notice"].strip()):
        raise ValueError(f"{stem}: untrusted_notice must be a non-empty sentence")
    _check_v42_form_flags(stem, qset)
    _check_v42_subclass_fit(stem, qset)


EXTRACTION_GATE = "extraction_gate"


def _checked_gate_set(stem: str, qset: dict[str, Any]) -> dict[str, Any]:
    verdict = qset.get("verdict") or {}
    if not isinstance(verdict.get("criteria"), dict) or "accept" not in verdict["criteria"] or len(verdict["criteria"]) < 2:
        raise ValueError(f"{stem}: an extraction gate needs a verdict with an accept option and at least one other")
    if set(qset.get("human_verdicts") or []) - set(verdict["criteria"]):
        raise ValueError(f"{stem}: human_verdicts must name verdict options")
    fields = qset.get("fields") or {}
    if not isinstance(fields, dict) or not fields or not all(isinstance(v, dict) and v for v in fields.values()):
        raise ValueError(f"{stem}: fields must map each gated class to {{field: meaning}}")
    if "{field}" not in str(qset.get("field_instructions") or ""):
        raise ValueError(f"{stem}: field_instructions must contain {{field}}")
    if not str(verdict.get("instructions") or "").strip():
        raise ValueError(f"{stem}: the verdict needs instructions")
    _checked_options("verdict", list(verdict["criteria"]))
    # Build every class's questions now: a format typo ({meanin}, a stray brace) fails at load,
    # not on each row of a paid run.
    for doc_type in fields:
        try:
            gate_questions(qset, doc_type)
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(f"{stem}: field_instructions do not format for {doc_type}: {exc!r}") from exc
    return qset


def gate_questions(qset: Mapping[str, Any], doc_type: str, subclass: str | None = None) -> dict[str, Any]:
    """The gate request's questions: the verdict plus one yes/no per key field of ``doc_type``.

    1.3.0+: ``subclass_fields[doc_type][subclass]`` replaces the class rule of the fields it names,
    so the gate is asked only the rule of the document's own template. Unknown or missing
    subclass: the class rules.
    """
    instructions = str(qset["verdict"]["instructions"])
    scope = (qset["verdict"].get("class_scope") or {}).get(doc_type)
    if scope:  # 1.2.0+: the verdict judges only the class's key fields, named here
        instructions = f"{instructions} {scope}"
    questions: dict[str, Any] = {"verdict": {"type": "choice", "instructions": instructions,
                                             "criteria": dict(qset["verdict"]["criteria"])}}
    by_sub = (((qset.get("subclass_fields") or {}).get(doc_type) or {}).get(subclass or "") or {})
    for field, meaning in ((qset.get("fields") or {}).get(doc_type) or {}).items():
        meaning = by_sub.get(field, meaning)
        questions[f"field__{field}"] = {"type": "noul",
                                        "instructions": str(qset["field_instructions"]).format(field=field, meaning=meaning)}
    return questions


def key_field_score(field_support: Mapping[str, float], asked: Iterable[str] | None = None) -> float | None:
    """The gating score of a 1.2.0+ answer: the product of the key-field support probabilities.

    The verdict question is answered on its own and ignores the per-template field rules; on the
    1.3.0 calibration (1,591 labelled documents) this product separates extractions whose key
    fields are all right from the rest far better than ``accept_probability`` (AUROC 0.76 vs
    0.67 overall; corporate 0.89 vs 0.52, insurance 0.87 vs 0.78). None when no field was asked.

    ``asked`` names the fields the request asked about; an asked field with no numeric answer
    counts as support 0.0, so a missing answer can never raise the score.
    """
    import math

    if asked is None:
        values = [float(v) for v in field_support.values()]
    else:
        values = [float(field_support.get(f, 0.0)) for f in asked]
    return round(math.prod(values), 6) if values else None


def extraction_handoff(doc_type: str, extraction: Mapping[str, Any] | None,
                       doc_subclass: str | None = None) -> dict[str, Any]:
    """What the gate sees of a specialist's answer: the class it extracted for and the fields.

    ``doc_subclass`` is the sorter's subclass when the pipeline knows it (selects the 1.3.0+
    template rules). Underscore keys (parse diagnostics, raw text) are dropped; nothing of the
    scoring travels.
    """
    fields = {k: v for k, v in (extraction or {}).items() if not str(k).startswith("_")}
    out: dict[str, Any] = {"doc_type": doc_type, "fields": fields} if extraction else {"doc_type": doc_type, "available": False}
    if doc_subclass:
        out["doc_subclass"] = str(doc_subclass)
    return out


def extraction_gate_backend(model: str, qset: Mapping[str, Any]) -> Callable[[str, Mapping[str, Any]], dict[str, Any]]:
    """The pipeline gate registered with llm-mailroom (``agents.extraction_gate``).

    It answers ``gate(doc_text, handoff)`` with ``decide_extraction``. The subclass is
    the handoff's ``doc_subclass``, which is the **sorter's**, and there is no fallback to a
    labelled subclass: with none, the gate uses the class rules (1.2.0 behaviour). Pipeline
    gate numbers therefore include the sorter's subclass errors, unlike calibration runs.
    """
    if not is_decisions_model(model):
        raise ValueError(f"{model!r} is not a Decisions-API model")
    if qset.get("kind") != EXTRACTION_GATE:
        raise ValueError("the pipeline extraction gate needs an extraction_gate question set")
    version = str(qset.get("version") or "")

    def gate(doc_text: str, handoff: Mapping[str, Any]) -> dict[str, Any]:
        """Review one pipeline extraction."""
        subclass = handoff.get("doc_subclass")
        out = decide_extraction(doc_text, handoff, model=model, qset=qset,
                                subclass=str(subclass) if subclass else None)
        return {**out, "question_set": version, "model": model}

    return gate


def mock_extraction_gate_backend(model: str, qset: Mapping[str, Any]) -> Callable[[str, Mapping[str, Any]], dict[str, Any]]:
    """An offline gate for mock pipeline runs: a fixed neutral answer, no network call, no usage."""
    version = str((qset or {}).get("version") or "")

    def gate(doc_text: str, handoff: Mapping[str, Any]) -> dict[str, Any]:
        """Answer one extraction without calling the Decisions API."""
        return {"doc_type": handoff.get("doc_type"), "verdict": "accept", "accept_probability": 0.5,
                "human_review_probability": 0.0, "verdict_probabilities": {"accept": 0.5}, "field_support": {},
                "question_set": version, "model": model, "mock": True}

    return gate


CLOSED_FIELD_RESOLVER = "closed_field_resolver"


def _checked_resolver_set(stem: str, qset: dict[str, Any]) -> dict[str, Any]:
    """A ``kind: closed_field_resolver`` set: instructions, a per-label criterion and a none option."""
    for key in ("instructions", "label_criterion", "none_option", "none_criterion"):
        if not str(qset.get(key) or "").strip():
            raise ValueError(f"{stem}: a closed-field resolver set needs {key}")
    try:
        resolver_question(qset, {"doc_type": "contract", "field": "f", "value": "v", "allowed": ["a", "b"]})
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"{stem}: the resolver texts do not format: {exc!r}") from exc
    return qset


def resolver_question(qset: Mapping[str, Any], handoff: Mapping[str, Any]) -> dict[str, Any]:
    """The one pick-one question: every allowed label of the handoff's field plus the none option."""
    field, doc_type = str(handoff.get("field") or ""), str(handoff.get("doc_type") or "")
    value = json.dumps(handoff.get("value"), ensure_ascii=False)[:200]
    allowed = [str(v) for v in dict.fromkeys(handoff.get("allowed") or []) if str(v).strip()]
    none = str(qset["none_option"])
    if not allowed:
        raise ValueError(f"closed-field resolver: field {field!r} has no allowed labels")
    if none in allowed:
        raise ValueError(f"closed-field resolver: none option {none!r} is also an allowed label of {field!r}")
    criteria = {label: str(qset["label_criterion"]).format(label=label, field=field, doc_type=doc_type)
                for label in allowed}
    criteria[none] = str(qset["none_criterion"]).format(field=field, doc_type=doc_type)
    _checked_options(f"closed field {field}", list(criteria))
    return {"label": {"type": "choice", "criteria": criteria,
                      "instructions": str(qset["instructions"]).format(field=field, doc_type=doc_type, value=value)}}


def decide_closed_field(doc_text: str, handoff: Mapping[str, Any], *, model: str, qset: Mapping[str, Any],
                        timeout: float = 120.0, attempts: int = 3) -> dict[str, Any]:
    """One resolver request: ``{document, closed_field_handoff}`` and the pick-one question.

    Returns the picked ``value`` (``None`` when the model picked the none option) and its
    ``probability``, the full ``probabilities`` and the usage. llm-mailroom checks the pick
    against the field's vocabulary again and applies it only at its own ``min_probability``.
    """
    if not is_decisions_model(model):
        raise ValueError(f"{model!r} is not a Decisions-API model")
    masked = _mask_card_values(dict(handoff))  # the value is quoted in the question text too
    questions = resolver_question(qset, masked)
    limit = decision_input_cap(model, qset.get("max_input_chars"),
                               question_chars=len(json.dumps(questions, default=str)) + len(json.dumps(masked, default=str)))
    text = mask_card_numbers((doc_text or "")[:limit])
    body = {"model": model,
            "state": {"document": text if text.strip() else "(empty document)", "closed_field_handoff": masked},
            "questions": questions}
    data = _post_decision(body, timeout=max(timeout, 60.0 + len(text) / 4_000), attempts=attempts)
    usage = data.get("usage") or {}
    _record_usage(model, usage, agent=CLOSED_FIELD_RESOLVER)
    answer = (data.get("answers") or {}).get("label") or {}
    probs = {str(k): float(v) for k, v in (answer.get("probabilities") or {}).items()
             if isinstance(v, (int, float)) and not isinstance(v, bool)}
    choice = answer.get("choice")
    picked = None if choice in (None, qset["none_option"]) else str(choice)
    return {"value": picked, "probability": probs.get(str(choice)) if choice is not None else None,
            "probabilities": probs, "truncated": len(doc_text or "") > limit, "served_model": data.get("model"),
            "usage": {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                      "cost": usage.get("cost")}}


def closed_field_resolver_backend(model: str, qset: Mapping[str, Any]) -> Callable[[str, Mapping[str, Any]], dict[str, Any]]:
    """The resolver registered with llm-mailroom (``agents.closed_field_resolver``)."""
    if not is_decisions_model(model):
        raise ValueError(f"{model!r} is not a Decisions-API model")
    if qset.get("kind") != CLOSED_FIELD_RESOLVER:
        raise ValueError("the closed-field resolver needs a closed_field_resolver question set")
    version = str(qset.get("version") or "")

    def resolver(doc_text: str, handoff: Mapping[str, Any]) -> dict[str, Any]:
        """Pick an allowed label for one off-list closed field."""
        out = decide_closed_field(doc_text, handoff, model=model, qset=qset)
        return {**out, "question_set": version, "model": model}

    return resolver


def mock_closed_field_resolver_backend(model: str, qset: Mapping[str, Any]) -> Callable[[str, Mapping[str, Any]], dict[str, Any]]:
    """An offline resolver for mock runs: always the none option, so nothing is ever applied."""
    version = str((qset or {}).get("version") or "")

    def resolver(doc_text: str, handoff: Mapping[str, Any]) -> dict[str, Any]:
        """Answer one off-list field without calling the Decisions API."""
        return {"value": None, "probability": None, "question_set": version, "model": model, "mock": True}

    return resolver


def _decision_retry_delay(response: Any, attempt: int) -> float:
    """Backoff for a transient response, respecting numeric and HTTP-date Retry-After."""
    import math
    import time
    from email.utils import parsedate_to_datetime

    delay = float(2 ** attempt)
    raw = (getattr(response, "headers", None) or {}).get("Retry-After")
    if raw is None:
        return delay
    try:
        wait = float(raw)
    except (TypeError, ValueError):
        try:
            wait = parsedate_to_datetime(str(raw)).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return delay
    return max(delay, wait) if math.isfinite(wait) else delay


def _record_read(agent: str, request: str) -> None:
    """Record the request's read ranges; building or recording it can never raise into the call."""
    try:
        from mailroom_sandbox.job import read_ranges

        read_ranges.record(agent, request)
    except Exception:
        pass


def _decision_lane(state: Any) -> str:
    """The Decisions lane, from the state shape (the body carries no lane key)."""
    if isinstance(state, Mapping):
        if "closed_field_handoff" in state:
            return CLOSED_FIELD_RESOLVER
        if "extraction_handoff" in state:
            return "extraction_gate"
    return "classification"


def _record_decision_read(body: Mapping[str, Any]) -> None:
    """Record one Decisions request: the document, the handoff if any and the questions."""
    try:
        state = body.get("state")
        parts: list[str] = []
        if isinstance(state, Mapping):
            parts.append(str(state.get("document") or ""))
            for key in ("closed_field_handoff", "extraction_handoff"):
                if key in state:
                    parts.append(json.dumps(state[key], default=str))
        else:
            parts.append(str(state or ""))
        parts.append(json.dumps(body.get("questions"), default=str))
        _record_read(f"decisions:{_decision_lane(state)}", "\n".join(parts))
    except Exception:
        pass
    try:
        from mailroom_sandbox.job import prompt_capture

        prompt_capture.observe_decision(body, agent=f"decisions:{_decision_lane(body.get('state'))}")
    except Exception:
        pass


def _post_decision(body: Mapping[str, Any], *, timeout: float, attempts: int) -> dict[str, Any]:
    """POST one Decisions request and return its JSON; the one retry loop for every caller.

    Transport errors and ``_TRANSIENT`` statuses are retried with backoff (``attempts`` in all);
    any other status, or a refusal, raises at once. The timeout covers all attempts and
    backoff together, starting here after backend preparation. An active pipeline run also
    caps that allowance at its configured call timeout and checks its absolute run deadline.
    The caller's earlier node timer is not propagated here; it can expire first.
    """
    import os
    import time
    import math

    import httpx
    from pipeline import limits

    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError("Decisions attempts must be a positive integer")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Decisions timeout must be finite and positive")
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Decisions backend needs OPENROUTER_API_KEY")
    run_deadline = limits.get_run_deadline()
    call_timeout = min(timeout, limits.get_call_timeout_seconds()) if run_deadline is not None else timeout
    deadline = time.monotonic() + call_timeout

    def remaining() -> float:
        limits.check_run_deadline(run_deadline)
        room = deadline - time.monotonic()
        if run_deadline is not None:
            room = min(room, run_deadline - time.time())
        if not room > 0:
            raise TimeoutError("Decisions request deadline exceeded") from last
        return room

    last: Exception | None = None
    count = attempts
    recorded = False
    from mailroom_sandbox.job import call_guard

    # S2: every attempt reserves the request's worst-case cost (its whole body as text, its output cap).
    size = call_guard.request_tokens([{"content": json.dumps(dict(body), default=str)}],
                                     body.get("max_completion_tokens") or body.get("max_tokens"))
    for attempt in range(count):
        # Decisions calls bypass the chat provider wrappers; enforce the same run guard
        # before each HTTP attempt, including retries.
        attempt_timeout = remaining()
        held = call_guard.before_call(*size)
        if not recorded:  # once per logical request, and only once the guard and deadline let it go out
            _record_decision_read(body)
            recorded = True
        resp = None
        try:
            resp = httpx.post(DECISIONS_URL, json=dict(body), timeout=attempt_timeout,
                              headers={"Authorization": f"Bearer {key}", "X-Title": "local-mailroom-sandbox"})
        except httpx.TransportError as exc:
            call_guard.settle(held, billed=call_guard.billed_failure(exc))
            call_guard.note_failed_attempt()  # L1: an attempt with no usage still counts
            last = exc
        except BaseException as exc:
            call_guard.settle(held, billed=call_guard.billed_failure(exc))
            call_guard.note_failed_attempt()
            raise
        else:
            # Settled before the body is read: a 200 is priced by after_call below, a 5xx may have been billed.
            call_guard.settle(held, billed=resp.status_code >= 500)
            if resp.status_code == 200:
                data = resp.json()
                # The single live charge for this HTTP response. HF-004 also
                # prices ``record_usage``; ``_record_usage`` uses the unwrapped
                # accumulator so the same response is not charged again. A
                # payload with no usage keys still takes one ceiling slot.
                call_guard.after_call((data or {}).get("usage") or {})
                return data
            call_guard.note_failed_attempt()
            last = RuntimeError(f"Decisions API {resp.status_code}: {resp.text[:300]}")
            if resp.status_code not in _TRANSIENT or "refused to answer" in resp.text:
                raise last
        if attempt + 1 < count:
            time.sleep(min(_decision_retry_delay(resp, attempt), remaining()))
    raise last or RuntimeError("Decisions API failed")


def decide_extraction(doc_text: str, handoff: Mapping[str, Any], *, model: str, qset: Mapping[str, Any],
                      timeout: float = 120.0, attempts: int = 3, subclass: str | None = None) -> dict[str, Any]:
    """One extraction-gate request: ``{document, extraction_handoff}`` and the gate questions.

    Returns the verdict, ``accept_probability`` (the gating score), the human-review
    probability and one support probability per field. ``subclass`` (else the handoff's
    ``doc_subclass``) selects the template rules of a 1.3.0+ set.
    """
    if not is_decisions_model(model):
        raise ValueError(f"{model!r} is not a Decisions-API model")
    doc_type = str(handoff.get("doc_type") or "")
    questions = gate_questions(qset, doc_type, subclass or handoff.get("doc_subclass"))
    masked = _mask_card_values(dict(handoff))  # extracted values (an IBAN field) trip the same filter
    limit = decision_input_cap(model, (qset.get("max_input_chars_by_class") or {}).get(doc_type)
                               or qset.get("max_input_chars"),
                               question_chars=len(json.dumps(questions, default=str)) + len(json.dumps(masked, default=str)))
    text = mask_card_numbers((doc_text or "")[:limit])
    body = {"model": model, "state": {"document": text if text.strip() else "(empty document)",
                                      "extraction_handoff": masked},
            "questions": questions}
    # A whole long document (up to ~250k tokens) takes longer to read than the 120 s default allows.
    data = _post_decision(body, timeout=max(timeout, 60.0 + len(text) / 4_000), attempts=attempts)
    _record_served(model, data)
    usage = data.get("usage") or {}
    _record_usage(model, usage, agent=EXTRACTION_GATE)
    answers = data.get("answers") or {}
    verdict = answers.get("verdict") or {}
    probs = {k: float(v) for k, v in (verdict.get("probabilities") or {}).items()}
    human = set(qset.get("human_verdicts") or [])
    fields = {}
    for key, answer in answers.items():
        value = (answer or {}).get("noul") if key.startswith("field__") else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            fields[key.removeprefix("field__")] = float(value)
    return {
        "doc_type": doc_type,
        "doc_subclass": subclass or handoff.get("doc_subclass"),
        "input_chars": len(text),
        "truncated": len(doc_text or "") > limit,
        "verdict": verdict.get("choice"),
        "verdict_probabilities": probs,
        "accept_probability": probs.get("accept"),
        "human_review_probability": sum(v for k, v in probs.items() if k in human) if probs else None,
        "field_support": fields,
        # The key fields asked, kept as evidence (llm-mailroom's decision slots judge coverage
        # from their own taxonomy gate_key_fields, never from this list).
        "fields_asked": (asked := [k.removeprefix("field__") for k in questions if k.startswith("field__")]),
        "key_field_score": key_field_score(fields, asked),
        "confidence": probs.get("accept"),
        "served_model": data.get("model"),
        "usage": {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                  "cost": usage.get("cost")},
    }


#: 4.2.0+ question-key prefixes: yes/no form flags and the separate subclass-fit question.
FORM_FLAG_PREFIX = "form__"
FIT_PREFIX = "fit__"


def _fit_option_names(block: Mapping[str, Any], fit: Mapping[str, Any], cls: str) -> str:
    """Comma-joined subclass options for the fit question, omitting class-specific exclusions."""
    options = dict(block["criteria"])
    excluded = fit.get("exclude") or ()
    if isinstance(excluded, dict):
        excluded = excluded.get(cls, ())
    return ", ".join(k for k in options if k not in set(excluded))


def _subclass_pick_options(
    qset: Mapping[str, Any],
    cls: str,
    block: Mapping[str, Any],
    *,
    contract: bool,
    fit: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Criteria for ``subclass__<cls>``, with fit-mode, not-this-class, or undetermined options."""
    if fit:
        # 4.2.0+: fit is a separate question, so the pick has no NOT_THIS_CLASS option.
        options = dict(block["criteria"])
    else:
        # Every subclass question is asked of every document, and the model refuses a question
        # with no option that fits; NOT_THIS_CLASS is that option. Only the chosen class's
        # answer is used.
        options = {**block["criteria"], NOT_THIS_CLASS: f"The document is not {cls}."}
    if contract and qset.get("subclass_gate") and SUBCLASS_UNDETERMINED not in options:
        # 4.0.0+ (SHF-009): every subclass question can abstain.
        options[SUBCLASS_UNDETERMINED] = "The text does not settle which subclass this is."
    return options


def _add_subclass_questions(
    questions: dict[str, Any],
    qset: Mapping[str, Any],
    cls: str,
    block: Mapping[str, Any],
    *,
    contract: bool,
    fit: Mapping[str, Any] | None,
) -> None:
    """Append one class's marker and/or fit + subclass pick questions."""
    if block.get("markers"):
        # Marker classes: one yes/no question per marker; marker_subclass applies the order.
        for key, text in block["markers"].items():
            questions[f"marker__{cls}__{key}"] = {"type": "noul", "instructions": text}
        return
    if fit:
        # 4.2.0+: "does any option fit?" is its own yes/no question instead of an option,
        # so a forced pick never hides a wrong class. A refusal of the pick is recorded.
        # A catch-all ("other": no family fits) would make "does one fit?" a near-certain yes.
        names = _fit_option_names(block, fit, cls)
        questions[f"{FIT_PREFIX}{cls}"] = {
            "type": "noul",
            "instructions": fit["instructions"].format(cls=cls, options=names),
        }
    options = _subclass_pick_options(qset, cls, block, contract=contract, fit=fit)
    _checked_options(f"subclass.{cls}", list(options))
    questions[f"subclass__{cls}"] = {
        "type": "choice",
        "instructions": block.get("instructions") or _DOC_SUBCLASS_QUESTION,
        "criteria": options,
    }


def _add_form_questions(questions: dict[str, Any], qset: Mapping[str, Any], *, contract: bool) -> None:
    """Append the pick-one form question or the 4.2.0 per-flag yes/no questions."""
    if not contract:
        return
    if qset.get("document_form"):
        # 4.0.0+ (SHF-009): the state of the document as an extraction input.
        form = dict(qset["document_form"]["criteria"])
        _checked_options("document_form", list(form))
        questions["document_form"] = {
            "type": "choice",
            "instructions": qset["document_form"]["instructions"],
            "criteria": form,
        }
    if qset.get("document_form_flags"):
        # 4.2.0+: one yes/no question per form defect; a cut-off text can also be a bundle.
        for key, block in qset["document_form_flags"]["flags"].items():
            questions[f"{FORM_FLAG_PREFIX}{key}"] = {"type": "noul", "instructions": block["instructions"]}


def _prefix_untrusted_notice(questions: dict[str, Any], qset: Mapping[str, Any]) -> None:
    """4.2.0+: every question says that the document is data, never instructions."""
    notice = str(qset.get("untrusted_notice") or "").strip()
    if not notice:
        return
    for question in questions.values():
        question["instructions"] = f"{notice} {question['instructions']}"


def decision_questions(qset: Mapping[str, Any], doc_types: list[str] | None = None) -> dict[str, Any]:
    """The request's ``questions``: ``doc_type`` plus one ``subclass__<class>`` per class.

    ``doc_types`` (the live taxonomy) limits the doc_type options; an option with no
    criterion in the set gets its own name, so a new class is never silently dropped.
    """
    criteria = dict(qset["doc_type"]["criteria"])
    if doc_types:
        criteria = {cls: criteria.get(cls) or cls for cls in dict.fromkeys(doc_types)}
    _checked_options("doc_type", list(criteria))
    questions: dict[str, Any] = {
        "doc_type": {"type": "choice", "instructions": qset["doc_type"].get("instructions") or _DOC_TYPE_QUESTION,
                     "criteria": criteria},
    }
    if qset.get("verdict"):
        # 3.0.0+: the routing outcome against the sorter handoff, including the human-review cases.
        questions["verdict"] = {"type": "choice", "instructions": qset["verdict"]["instructions"],
                                "criteria": dict(qset["verdict"]["criteria"])}
    contract = _contract_enabled(qset)
    _add_form_questions(questions, qset, contract=contract)
    fit = subclass_fit(qset)
    for cls, block in (qset.get("subclass") or {}).items():
        if doc_types and cls not in criteria:
            continue
        _add_subclass_questions(questions, qset, cls, block, contract=contract, fit=fit)
    _prefix_untrusted_notice(questions, qset)
    return questions


def subclass_fit(qset: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The 4.2.0+ ``subclass_fit`` block when the SHF-009 contract applies, else None."""
    block = (qset or {}).get("subclass_fit")
    return dict(block) if isinstance(block, Mapping) and _contract_enabled(qset) else None


def form_signals(text: str, *, original_chars: int, window_chars: int) -> dict[str, Any]:
    """Facts code can establish about a document's form, passed to the model as data (4.2.0+).

    Nothing here is a judgement: the model still decides whether the document is a fragment or
    a bundle, but it no longer has to find the last line of a million-character text itself.
    """
    stripped = text.rstrip()
    last = stripped[-1:] if stripped else ""
    lower = text.lower()
    return {
        "characters": original_chars,
        "cut_by_window": original_chars > window_chars,
        "ends_with": stripped[-240:],
        "ends_with_sentence_punctuation": last in '.!?:;)]"\'' if last else False,
        "document_tags": lower.count("<document>"),
        "type_tags": lower.count("<type>"),
        "filing_source_lines": sum(1 for line in text.splitlines() if line.lstrip().lower().startswith("source:")),
    }


def run_session_id(qset: Mapping[str, Any] | None) -> str | None:
    """OpenRouter ``session_id`` for a 4.2.0+ request: the run id, so provider logs group by run.

    OpenRouter uses it for observability grouping and never sends it to the provider (at most
    256 characters). None outside a run, or when the question set does not ask for it.
    """
    if (qset or {}).get("session_id") != "run":
        return None
    try:
        from mailroom_sandbox.provider_pins import run_context

        run_id = run_context().get("run_id")
    except Exception:  # noqa: BLE001 - no run context: no session id
        return None
    return f"sandbox-{run_id}"[:256] if run_id else None


def lane_question_chars(lane: str, qset: Mapping[str, Any]) -> int:
    """Serialized size of the largest ``questions`` payload a lane sends with this set.

    Preflight sizes each Decisions window with it, the way execution does. The run's handoff
    (sorter answer, extraction, closed-field card) is not known before the run, so it is not
    counted: the window preflight reports can exceed the one execution uses by its size. The
    resolver's figure is a floor: its labels arrive with the handoff, so one minimal field is sized.
    """
    def size(questions: Mapping[str, Any]) -> int:
        return len(json.dumps(dict(questions), default=str))

    if lane == "extraction_gate":
        sizes = [0]
        for doc_type in (qset.get("fields") or {}):
            subclasses = [None, *(((qset.get("subclass_fields") or {}).get(doc_type) or {}).keys())]
            sizes.extend(size(gate_questions(qset, doc_type, sub)) for sub in subclasses)
        return max(sizes)
    if lane == CLOSED_FIELD_RESOLVER:  # one field's labels: the vocabulary arrives with the handoff
        return size(resolver_question(qset, {"doc_type": "contract", "field": "f", "value": "v", "allowed": ["a"]}))
    return size(decision_questions(qset))


def refused_questions(questions: Mapping[str, Any], answers: Mapping[str, Any]) -> list[str]:
    """Questions asked but not answered: missing, flagged as refused, or with no choice or noul.

    The exact refusal shape of a single refused question is not pinned here (no live call was
    made to confirm it), so anything that is not a usable answer counts as refused.
    """
    out = []
    for key, question in questions.items():
        answer = answers.get(key)
        if not isinstance(answer, Mapping) or any(answer.get(k) for k in ("refusal", "refused", "error")):
            out.append(key)
            continue
        value = answer.get("noul") if question.get("type") == "noul" else answer.get("choice")
        if question.get("type") == "noul":
            usable = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1
        else:
            usable = isinstance(value, str) and bool(value) and (not question.get("criteria") or value in question["criteria"])
        if not usable:
            out.append(key)
    return out


def build_handoff(sorter_doc_type: Any, sorter_doc_subclass: Any, sorter_confidence: Any,
                  *, sorter_unsure: bool | None = None, retried: bool | None = None) -> dict[str, Any]:
    """The sorter handoff the reviewer sees, the same shape in the pipeline and in calibration.

    Every document of a decision class reaches the reviewer at any sorter confidence, so the
    trigger says that, plus whether the sorter ended below its class's low band.
    """
    triggers = ["decision_class_review"]
    if sorter_unsure:
        triggers.append("sorter_below_low_band")
    if retried:
        triggers.append("after_sorter_retry")
    confidence = sorter_confidence if isinstance(sorter_confidence, (int, float)) and not isinstance(sorter_confidence, bool) else None
    return {
        "sorter_doc_type": sorter_doc_type,
        "sorter_doc_subclass": sorter_doc_subclass,
        "sorter_confidence": round(float(confidence), 4) if confidence is not None else None,
        "review_trigger": triggers,
    }


def calibration_handoff(answer: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A frozen sorter answer as the pipeline would hand it over (low band from the live taxonomy)."""
    if not answer:
        return None
    unsure = None
    try:
        from pipeline.config import get_confidence_thresholds

        conf = answer.get("sorter_confidence")
        if isinstance(conf, (int, float)):
            unsure = float(conf) < float(get_confidence_thresholds(answer.get("sorter_doc_type")).get("low", 0.70))
    except Exception:  # noqa: BLE001 - no mailroom config: leave the band unknown
        unsure = None
    return build_handoff(answer.get("sorter_doc_type"), answer.get("sorter_doc_subclass"),
                         answer.get("sorter_confidence"), sorter_unsure=unsure)


def marker_subclass(block: Mapping[str, Any], answers: Mapping[str, Any], cls: str) -> tuple[str | None, float | None, dict[str, float]]:
    """Subclass from yes/no marker answers: the first marker in ``order`` with p >= 0.5, else ``default``.

    The confidence is the chosen marker's probability, or for the default the probability
    that no earlier marker is present (the smallest of 1 - p).
    """
    probs: dict[str, float] = {}
    for key in block["markers"]:
        value = (answers.get(f"marker__{cls}__{key}") or {}).get("noul")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            probs[key] = float(value)
    for key in block.get("order") or list(block["markers"]):
        if probs.get(key, 0.0) >= 0.5:
            return key, probs[key], probs
    default = block.get("default")
    return default, (min((1.0 - p for p in probs.values()), default=None) if default else None), probs


def _record_usage(model: str, usage: Mapping[str, Any], *, agent: str = "sorter_reviewer") -> None:
    """Count the call in the run's usage accumulator, so job budgets and cost see it.

    ``_post_decision`` already priced this response, including a payload with no
    usage keys. HF-004 wraps ``record_usage`` and prices it again; while that
    wrapper is installed, the tokens go to the unwrapped accumulator only.
    """
    try:
        from pipeline.limits import record_usage
    except ImportError:
        return
    fn = record_usage
    if getattr(fn, "_sandbox_hotfix", None) == "HF-004":
        fn = getattr(fn, "__wrapped__", fn)
    # The unwrapped accumulator does not see HF-004, so the provider cost is noted here.
    # prompt_/completion_ keys: record_usage reads ``output_tokens or completion_tokens``, so a
    # Decisions call's output_tokens=0 under the output_ key would read as missing and drop the call.
    from mailroom_sandbox.job.usage_capture import note_provider_call

    counted: dict[str, Any] = {
        "prompt_tokens": int(usage.get("input_tokens") or 0),
        "completion_tokens": int(usage.get("output_tokens") or 0),
        "cost": usage.get("cost"),
    }
    # The accumulator only wants prompt and completion. Cache fields stay on the note so a
    # provider that returns them is not recorded as an all-fresh prompt.
    for name in ("prompt_tokens_details", "input_tokens_details", "input_token_details",
                 "cached_tokens", "cache_write_tokens", "cache_read", "cache_creation"):
        if usage.get(name) is not None:
            counted[name] = usage[name]
    note_provider_call(counted)
    fn(counted, model=model, agent=agent)


def _record_served(model: str, data: Mapping[str, Any]) -> None:
    """Append the served model to the R01 ledger (``provider_pins``, ``call_path: decisions``)."""
    try:
        from mailroom_sandbox.provider_pins import record_decision

        row = decision_model(model) or decision_model(str(model).split(":", 1)[0]) or {}
        record_decision(model, data, row.get("canonical_slug"))
    except Exception as exc:  # noqa: BLE001 — recording never fails a call
        import logging

        logging.getLogger(__name__).warning("served-model record failed: %s", exc)


def decide(doc_text: str, *, model: str, questions: Mapping[str, Any], timeout: float = 120.0,
           attempts: int = 3, max_input_chars: int = DECISIONS_MAX_INPUT_CHARS,
           qset: Mapping[str, Any] | None = None, handoff: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One Decisions request: the document as ``state``, every question at once.

    Returns ``{doc_type, doc_subclass, contract_subtype, confidence, probabilities,
    subclass_confidence, subclass_probabilities, served_model, usage}``. ``confidence`` is
    the probability the model gives the chosen doc_type. Transient HTTP errors are retried
    (``attempts`` in all); anything else raises.
    """
    if not is_decisions_model(model):
        raise ValueError(f"{model!r} is not a Decisions-API model")
    text = doc_text or ""
    original_chars = len(text)
    max_input_chars = decision_input_cap(model, max_input_chars, question_chars=len(json.dumps(dict(questions), default=str))
                                         + (len(json.dumps(dict(handoff), default=str)) if handoff else 0))
    if len(text) > max_input_chars:
        text = text[:max_input_chars]
    text = mask_card_numbers(text)
    document = text if text.strip() else "(empty document)"
    state: Any = document
    if (qset or {}).get("handoff"):
        # 3.0.0+: the sorter's answer travels with the document as a claim to check.
        state = {"document": document,
                 "sorter_handoff": dict(handoff) if handoff else {"available": False, "note": "no sorter answer was passed"}}
    elif (qset or {}).get("state_shape") == "object":
        # 4.2.0+: the questions say "state.document", so the document is always that field.
        # 4.0.x sent the bare text while its questions named state.document (a field that did not exist).
        state = {"document": document}
    if isinstance(state, dict) and (qset or {}).get("form_signals"):
        state["form_signals"] = form_signals(text, original_chars=original_chars, window_chars=max_input_chars)
    body: dict[str, Any] = {"model": model, "state": state, "questions": dict(questions)}
    session = run_session_id(qset)
    if session:
        body["session_id"] = session
    data = _post_decision(body, timeout=timeout, attempts=attempts)
    _record_served(model, data)
    usage = data.get("usage") or {}
    _record_usage(model, usage)
    answers = data.get("answers") or {}
    refused = refused_questions(questions, answers) if (qset or {}).get("record_refusals") else None
    top = answers.get("doc_type") or {}
    doc_type = top.get("choice")
    probs = top.get("probabilities") or {}
    confidence = probs.get(doc_type, top.get("confidence")) if doc_type else None
    block = ((qset or {}).get("subclass") or {}).get(doc_type) or {}
    sub: dict[str, Any] = {}
    if block.get("markers"):
        subclass, sub_conf, sub_probs = marker_subclass(block, answers, doc_type)
    else:
        sub = answers.get(f"subclass__{doc_type}") or {}
        subclass = sub.get("choice")
        sub_probs = {k: v for k, v in (sub.get("probabilities") or {}).items() if k != NOT_THIS_CLASS}
        if subclass == NOT_THIS_CLASS:
            # The subclass question disagrees with doc_type: report the best real subclass.
            subclass = max(sub_probs, key=sub_probs.get) if sub_probs else None
        sub_conf = sub_probs.get(subclass, sub.get("confidence")) if subclass else None
    verdict_answer = answers.get("verdict") or {}
    verdict = verdict_answer.get("choice")
    verdict_probs = verdict_answer.get("probabilities") or {}
    human = set((qset or {}).get("human_verdicts") or [])
    human_probability = sum(float(v) for k, v in verdict_probs.items() if k in human) if verdict_probs else None
    route_to_human = bool(verdict and verdict in human)
    doc_type_probability = float(confidence) if isinstance(confidence, (int, float)) else None
    # The gating confidence: the doc_type probability, or 0 when the verdict sends the document
    # to a person, so every cutoff parks it.
    gated = 0.0 if route_to_human else doc_type_probability
    result = {
        "doc_type": doc_type,
        "doc_subclass": subclass,
        "doc_type_probability": doc_type_probability,
        "verdict": verdict,
        "verdict_probabilities": verdict_probs,
        "human_review_probability": human_probability,
        "route_to_human": route_to_human,
        "handoff": dict(handoff) if handoff else None,
        "contract_subtype": subclass if doc_type == "contract" else None,
        "confidence": gated,
        "probabilities": probs,
        "subclass_confidence": sub_conf,
        "subclass_probabilities": sub_probs,
        "served_model": data.get("model"),
        "usage": {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                  "cost": usage.get("cost")},
    }
    if refused is not None:
        result["refused_questions"] = refused
    if session:
        result["session_id"] = session
    if _contract_enabled(qset):
        result = apply_question_set_contract(result, answers, qset or {}, handoff=handoff,
                                             truncated=original_chars > max_input_chars,
                                             original_chars=original_chars, window_chars=max_input_chars)
        result = apply_v42_rules(result, answers, qset or {}, handoff=handoff)
    result.update(document_form_evidence(answers, qset))
    return result


def _v42_fired_form_flags(
    answers: Mapping[str, Any], qset: Mapping[str, Any], flag_block: Mapping[str, Any]
) -> tuple[list[str], dict[str, float]]:
    """Flags at or above ``park_min``, plus every flag's probability."""
    park_min = float(flag_block.get("park_min", 0.5))
    flags = form_flag_probabilities(answers, qset)
    keys = [str(k) for k in flag_block.get("flags") or {}]
    fired = [k for k in keys if flags.get(k, 0.0) >= park_min]
    return fired, flags


def _v42_form_flag_reasons(
    out: dict[str, Any], answers: Mapping[str, Any], qset: Mapping[str, Any], refused: set[str]
) -> list[str]:
    """Record fired form flags and refused-flag reasons; mutate ``out`` with form fields."""
    flag_block = qset.get("document_form_flags") or {}
    if not flag_block:
        return []
    fired, flags = _v42_fired_form_flags(answers, qset, flag_block)
    keys = [str(k) for k in flag_block.get("flags") or {}]
    out["document_form"] = fired[0] if fired else ("complete_instrument" if flags else None)
    out["document_form_flags"] = fired
    reasons = [f"document_form:{k}" for k in fired]
    for key in keys:
        if f"{FORM_FLAG_PREFIX}{key}" in refused:
            reasons.append(f"refused:{FORM_FLAG_PREFIX}{key}")
    return reasons


def _v42_marker_unusable(
    out: dict[str, Any],
    block: Mapping[str, Any],
    answers: Mapping[str, Any],
    doc_type: str,
    refused: set[str],
) -> str | None:
    """Clear subclass when a refused marker can still change the ordered pick."""
    for key in block.get("order") or list(block["markers"]):
        question = f"marker__{doc_type}__{key}"
        if question in refused:
            out["doc_subclass"] = None
            out["subclass_confidence"] = None
            return "marker_unanswered"
        if (answers.get(question) or {}).get("noul", 0.0) >= 0.5:
            return None
    return None


def _v42_fit_status(
    out: dict[str, Any],
    answers: Mapping[str, Any],
    qset: Mapping[str, Any],
    doc_type: str,
    refused: set[str],
) -> tuple[str | None, list[str]]:
    """Record fit probability; return (unusable reason, abstain reasons)."""
    value = (answers.get(f"{FIT_PREFIX}{doc_type}") or {}).get("noul")
    answered = f"{FIT_PREFIX}{doc_type}" not in refused
    usable = answered and isinstance(value, (int, float)) and not isinstance(value, bool)
    if not usable:
        return "fit_unanswered", []
    out["subclass_fit_probability"] = float(value)
    threshold = float((qset.get("abstain") or {}).get("subclass_fit_min", 0.5))
    return (None, ["subclass_fit"]) if float(value) < threshold else (None, [])


def _v42_keep_sorter_subclass(
    out: dict[str, Any], doc_type: str | None, handoff: Mapping[str, Any] | None, unusable: str
) -> list[str]:
    """Reuse a same-class sorter subclass, or park when none is available."""
    same_class = _norm_class((handoff or {}).get("sorter_doc_type")) == _norm_class(doc_type)
    kept = (handoff or {}).get("sorter_doc_subclass") if same_class else None
    out["doc_subclass"] = kept
    out["subclass_source"] = "sorter" if kept is not None else "unresolved"
    out["subclass_confidence"] = None
    if doc_type == "contract":
        out["contract_subtype"] = out["doc_subclass"]
    return [] if kept is not None else [f"subclass_gate:{unusable}"]


def _v42_apply_unusable_subclass(
    out: dict[str, Any],
    qset: Mapping[str, Any],
    doc_type: str | None,
    unusable: str,
    handoff: Mapping[str, Any] | None,
) -> list[str]:
    """Apply ``subclass_gate`` for an unusable subclass; return new abstain reasons."""
    if "subclass_gate" in out:
        return []
    gate = qset.get("subclass_gate") or {}
    policy = ((gate.get(doc_type) or gate.get("default") or {}).get("on_low")) or "keep_sorter"
    out["subclass_gate"] = policy
    if policy == "park":
        return [f"subclass_gate:{unusable}"]
    return _v42_keep_sorter_subclass(out, doc_type, handoff, unusable)


def _v42_subclass_gate_reasons(
    out: dict[str, Any],
    answers: Mapping[str, Any],
    qset: Mapping[str, Any],
    refused: set[str],
    handoff: Mapping[str, Any] | None,
) -> list[str]:
    """Fit / marker unusable handling and the resulting subclass_gate reasons."""
    doc_type = out.get("doc_type")
    block = ((qset.get("subclass") or {}).get(doc_type) or {}) if doc_type else {}
    fit = subclass_fit(qset)
    reasons: list[str] = []
    unusable = None
    if block.get("markers"):
        unusable = _v42_marker_unusable(out, block, answers, str(doc_type), refused)
    elif fit and doc_type and doc_type not in NON_CLASS_OPTIONS:
        unusable, fit_reasons = _v42_fit_status(out, answers, qset, str(doc_type), refused)
        reasons.extend(fit_reasons)
    if unusable:
        reasons.extend(_v42_apply_unusable_subclass(out, qset, doc_type, unusable, handoff))
    return reasons


#: Functions whose source is the 4.2.0 routing identity. The question-set SHA-256 covers YAML only.
#: ``form_flag_probabilities`` and ``subclass_fit`` are included because the rules call them:
#: a change there changes which flag or fit decision is applied, and resume must refuse it.
_V42_ROUTING = (
    "form_flag_probabilities",
    "subclass_fit",
    "_v42_fired_form_flags",
    "_v42_form_flag_reasons",
    "_v42_marker_unusable",
    "_v42_fit_status",
    "_v42_keep_sorter_subclass",
    "_v42_apply_unusable_subclass",
    "_v42_subclass_gate_reasons",
    "apply_v42_rules",
)


def uses_v42_routing(qset: Mapping[str, Any] | None) -> bool:
    """True when this question set applies the 4.2.0 routing rules."""
    if not qset:
        return False
    return bool(qset.get("document_form_flags") or qset.get("subclass_fit") or qset.get("record_refusals"))


def v42_routing_sha256() -> str:
    """sha256 of the 4.2.0 routing helpers. Resume refuses a lock whose copy differs."""
    chunks = [inspect.getsource(globals()[name]) for name in _V42_ROUTING]
    return hashlib.sha256("".join(chunks).encode()).hexdigest()


def apply_v42_rules(result: Mapping[str, Any], answers: Mapping[str, Any], qset: Mapping[str, Any], *,
                    handoff: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The 4.2.0 routing rules, applied after the SHF-009 contract and only for a set that asks them.

    Kept out of ``apply_question_set_contract`` so SHF-009's fingerprint (and every lock taken
    under it) is untouched: a 4.0.x answer leaves here unchanged. A 4.2.0 answer is parked when a
    yes/no form flag is at or above ``document_form_flags.park_min``, when a form flag or
    ``doc_type`` went unanswered (``refused_questions``), or when the chosen class's ``fit__``
    answer is below ``abstain.subclass_fit_min``. An unanswered ``fit__`` question is an unusable
    subclass and goes through the class's ``subclass_gate`` policy, like ``undetermined``.
    """
    flag_block = qset.get("document_form_flags") or {}
    fit = subclass_fit(qset)
    if not flag_block and not fit and "refused_questions" not in result:
        return dict(result)
    out = dict(result)
    refused = set(out.get("refused_questions") or [])
    reasons = list(out.get("abstain_reasons") or [])
    reasons.extend(_v42_form_flag_reasons(out, answers, qset, refused))
    if "doc_type" in refused:
        reasons.append("refused:doc_type")
    reasons.extend(_v42_subclass_gate_reasons(out, answers, qset, refused, handoff))
    out["abstain_reasons"] = reasons
    out["abstained"] = bool(reasons)
    if reasons:
        out["route_to_human"] = True
        out["confidence"] = 0.0
    return out


def document_form_evidence(answers: Mapping[str, Any], qset: Mapping[str, Any] | None) -> dict[str, Any]:
    """Record-only: the ``document_form`` answer's probabilities and their mass on ``human_forms``.

    Calibration evidence for a future probability floor on form parks. It changes no routing
    or score (the SHF-009 contract still parks on the chosen form); empty when the question
    set asks no form question or the answer carries no probabilities.
    """
    flags = form_flag_probabilities(answers, qset)
    if flags:
        # 4.2.0+: the flags are not exclusive, so the mass that needs a person is the largest one.
        return {"document_form_flag_probabilities": flags,
                "document_form_human_mass": round(max(flags.values()), 6)}
    raw = (answers.get("document_form") or {}).get("probabilities")
    if not isinstance(raw, Mapping):
        return {}
    probs = {str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if not probs:
        return {}
    human = set((qset or {}).get("human_forms") or [])
    return {"document_form_probabilities": probs,
            "document_form_human_mass": round(sum(v for k, v in probs.items() if k in human), 6)}


def form_flag_probabilities(answers: Mapping[str, Any], qset: Mapping[str, Any] | None) -> dict[str, float]:
    """``{flag: p(yes)}`` of the 4.2.0+ yes/no form questions that were answered."""
    flags = ((qset or {}).get("document_form_flags") or {}).get("flags") or {}
    out = {}
    for key in flags:
        value = (answers.get(f"{FORM_FLAG_PREFIX}{key}") or {}).get("noul")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[str(key)] = float(value)
    return out


#: Doc-type options that are not a class: probability on them is abstention mass (4.0.0 ``unknown_max``).
NON_CLASS_OPTIONS = ("unknown",)


def _contract_enabled(qset: Mapping[str, Any] | None) -> bool:
    """A 4.0.0+ question set's routing contract applies (SHF-009 current; docs/scoring-hotfixes.md)."""
    if not qset or not any(qset.get(k) for k in ("document_form", "abstain", "subclass_gate", "truncation_notice")):
        return False
    from mailroom_sandbox import scoring_hotfixes as sh

    return sh.enabled("SHF-009")


def apply_question_set_contract(result: Mapping[str, Any], answers: Mapping[str, Any], qset: Mapping[str, Any], *,
                                handoff: Mapping[str, Any] | None = None, truncated: bool = False,
                                original_chars: int | None = None, window_chars: int | None = None) -> dict[str, Any]:
    """SHF-009: the 4.0.0 routing contract over one Decisions answer.

    ``human_forms`` (a ``document_form`` answer), the ``abstain`` rules (top-two ``margin``,
    ``subclass_not_this_class_max``, ``unknown_max``) and the per-class ``subclass_gate`` (``park``
    folds the confidence to 0, ``keep_sorter`` passes the sorter's subclass through) decide whether
    the document is parked. A parked document is an abstention: ``abstained`` and ``route_to_human``
    are True, ``confidence`` is 0 and ``abstain_reasons`` names the rules that fired. The
    forced-choice reading of the same answers (what decide returned before) is kept under
    ``forced_choice``. ``truncation_notice`` records a window that still cut the document.
    """
    out = dict(result)
    out["forced_choice"] = {k: result.get(k) for k in ("doc_type", "doc_subclass", "confidence", "route_to_human")}
    reasons: list[str] = []
    doc_type = result.get("doc_type")
    form = ((answers.get("document_form") or {}).get("choice"))
    out["document_form"] = form
    if form and form in set(qset.get("human_forms") or []):
        reasons.append(f"document_form:{form}")
    rules = qset.get("abstain") or {}
    probs = {k: float(v) for k, v in (result.get("probabilities") or {}).items() if isinstance(v, (int, float))}
    if doc_type in NON_CLASS_OPTIONS:
        reasons.append(f"doc_type:{doc_type}")
    ranked = sorted(probs.values(), reverse=True)
    if "margin" in rules and len(ranked) >= 2 and ranked[0] - ranked[1] < float(rules["margin"]):
        reasons.append("margin")
    if "unknown_max" in rules and sum(probs.get(k, 0.0) for k in NON_CLASS_OPTIONS) >= float(rules["unknown_max"]):
        reasons.append("unknown_max")
    sub_answer = answers.get(f"subclass__{doc_type}") or {}
    sub_probs = sub_answer.get("probabilities") or {}
    not_this = sub_probs.get(NOT_THIS_CLASS)
    if ("subclass_not_this_class_max" in rules and isinstance(not_this, (int, float))
            and float(not_this) >= float(rules["subclass_not_this_class_max"])):
        reasons.append("subclass_not_this_class")
    gate = qset.get("subclass_gate") or {}
    block = ((qset.get("subclass") or {}).get(doc_type) or {}) if doc_type else {}
    if gate and doc_type and not block.get("markers"):
        choice = sub_answer.get("choice")
        if choice in (None, NOT_THIS_CLASS, SUBCLASS_UNDETERMINED):
            policy = ((gate.get(doc_type) or gate.get("default") or {}).get("on_low")) or "keep_sorter"
            out["subclass_gate"] = policy
            if policy == "park":
                reasons.append(f"subclass_gate:{choice or 'none'}")
            else:
                # The sorter's subclass belongs to the sorter's class: reuse it only when the
                # classes agree, and never under the reviewer's probability for another answer.
                same_class = _norm_class((handoff or {}).get("sorter_doc_type")) == _norm_class(doc_type)
                kept = (handoff or {}).get("sorter_doc_subclass") if same_class else None
                out["doc_subclass"] = kept
                out["subclass_source"] = "sorter" if kept is not None else "unresolved"
                out["subclass_confidence"] = None
                if doc_type == "contract":
                    out["contract_subtype"] = out["doc_subclass"]
                if kept is None:
                    reasons.append(f"subclass_gate:{choice or 'none'}")
    if qset.get("truncation_notice"):
        out["truncated"] = bool(truncated)
        if truncated:
            out["truncation_notice"] = (f"the {window_chars}-character window cut a {original_chars}-character "
                                        "document")
    out["abstained"] = bool(reasons)
    out["abstain_reasons"] = reasons
    if reasons:
        out["route_to_human"] = True
        out["confidence"] = 0.0
    out["scoring_hotfixes"] = ["SHF-009"]
    return out


def decisions_backend(model: str, questions: str | None = None, *, qset: Mapping[str, Any] | None = None,
                      max_input_chars: int | None = None) -> "DecisionBackend":
    """Backend over a Decisions-API model with a question set from ``config/decisions``.

    ``max_input_chars`` is the run's ``reviewer.max_input_chars``. It raises the question
    set's document window the same way the isolated eval path does, and never lowers it.
    """
    if not is_decisions_model(model) or not _PINNED_API.match(model.split(":", 1)[0]):
        raise ValueError(f"{model!r} is not a pinned Decisions-API model id (expected e.g. 'openai/gpt-6-luna-decisions')")
    if qset is None and not questions:
        raise ValueError("decisions backend needs questions: <stem> (config/decisions/<stem>.yaml)")
    loaded: dict[str, Any] = {}

    def backend(doc_text: str, doc_types: list[str], subclass_catalogs: dict[str, list[str]],
                handoff: Mapping[str, Any] | None = None) -> "DecisionAnswer":
        if not loaded:
            loaded.update(qset if qset is not None else load_question_set(str(questions)))
        picked = decide(doc_text, model=model, questions=decision_questions(loaded, doc_types),
                        max_input_chars=classify_window_chars(loaded, max_input_chars), qset=loaded,
                        handoff=handoff)
        return _answer(picked["doc_type"], picked["doc_subclass"], picked["confidence"], model)

    return backend


def build_backend(name: str, model: str, *, questions: str | None = None) -> "DecisionBackend":
    """Backend by name: ``jev``, ``local``, ``api``, ``decisions`` (all use ``model``) or ``mock`` (empty table, all unknown)."""
    if name == "decisions":
        return decisions_backend(model, questions)
    if name == "jev":
        return jev_backend(model)
    if name == "local":
        return local_backend(model)
    if name == "mock":
        return mock_backend({})
    if name == "api":
        return api_backend(model)
    raise ValueError(f"unknown decision backend {name!r} (expected 'jev', 'local', 'api', 'decisions' or 'mock')")
