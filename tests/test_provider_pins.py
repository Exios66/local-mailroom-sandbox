"""Provider pins + served-provider ledger (R01). Fake vendored modules; no network."""

from __future__ import annotations

import json
import sys
import types

import pytest

from mailroom_sandbox import provider_pins as pp


class _Resp:
    def __init__(self, model, provider):
        self.model = model
        self.model_extra = {"provider": provider}


class _Client:
    def __init__(self, base_url):
        self.base_url = base_url


class _FakeChatOpenAI:
    """Placeholder ``ChatOpenAI`` for the fake vendored LangChain module."""


@pytest.fixture
def vendored(monkeypatch):
    seen = []

    def original(client, **kwargs):
        seen.append(kwargs)
        return _Resp(kwargs["model"], "Served-Co")

    llm = types.ModuleType("llm")
    retry = types.ModuleType("llm.retry")
    retry.retry_chat_completion = original
    llm.retry = retry
    agents = types.ModuleType("agents")
    base = types.ModuleType("agents.base")
    base.retry_chat_completion = original
    agents.base = base
    # A stand-in for the vendored LangChain base module, so activation never patches the real one.
    lc = types.ModuleType("langchain_agents")
    lc_base = types.ModuleType("langchain_agents.base_agent")
    lc_base.ChatOpenAI = _FakeChatOpenAI
    lc.base_agent = lc_base
    for name, mod in (("llm", llm), ("llm.retry", retry), ("agents", agents), ("agents.base", base),
                      ("langchain_agents", lc), ("langchain_agents.base_agent", lc_base)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(pp, "_ORIGINAL", None)
    monkeypatch.setattr(pp, "_LC_ORIGINAL", None)
    pp.reset_ledger()
    yield seen, base
    pp.restore()
    pp.reset_ledger()


PINS = {"qwen/qwen3.7-flash": {"order": ["Alibaba"], "allow_fallbacks": False,
                              "canonical_slug": None, "reasoning_effort": None},
        "deepseek/x": {"order": [], "allow_fallbacks": False, "canonical_slug": None, "reasoning_effort": None}}


def test_pin_merges_into_extra_body_and_keeps_existing_provider_keys(vendored):
    seen, base = vendored
    assert pp.apply_provider_pins(PINS) == 1
    client = _Client("https://openrouter.ai/api/v1")
    base.retry_chat_completion(client, model="qwen/qwen3.7-flash",
                               extra_body={"provider": {"require_parameters": True}, "reasoning": {"effort": "low"}})
    sent = seen[-1]["extra_body"]
    assert sent["provider"] == {"require_parameters": True, "order": ["Alibaba"], "allow_fallbacks": False}
    assert sent["reasoning"] == {"effort": "low"}
    entry = pp.ledger()[-1]
    assert entry["served_provider"] == "Served-Co" and entry["mismatch"] is True


def test_unpinned_model_is_recorded_not_routed(vendored, tmp_path, monkeypatch):
    seen, base = vendored
    log = tmp_path / "served.jsonl"
    monkeypatch.setenv("SANDBOX_SERVED_LOG", str(log))
    pp.apply_provider_pins(PINS)
    base.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="deepseek/x")
    assert "extra_body" not in seen[-1]
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["requested_model"] == "deepseek/x" and row["mismatch"] is False
    assert pp.summarize(pp.ledger())["deepseek/x"]["providers"] == {"Served-Co": 1}


def test_non_openrouter_calls_pass_through(vendored):
    seen, base = vendored
    pp.apply_provider_pins(PINS)
    base.retry_chat_completion(_Client("https://example.modal.run/v1"), model="qwen/qwen3.7-flash")
    assert "extra_body" not in seen[-1]
    assert pp.ledger() == []


def test_reapply_does_not_stack_wrappers(vendored):
    seen, base = vendored
    pp.apply_provider_pins(PINS)
    pp.apply_provider_pins(PINS)
    base.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="qwen/qwen3.7-flash")
    assert len(seen) == 1 and len(pp.ledger()) == 1


def test_committed_pin_file_parses():
    pins = pp.load_pins()
    assert "qwen/qwen3.7-flash" in pins
    assert all(p["allow_fallbacks"] is False for p in pins.values())


def test_provider_compare_ignores_case_and_flags_a_substituted_model(vendored, monkeypatch):
    seen, base = vendored
    pins = {"z/glm": {"order": ["served-co"], "allow_fallbacks": False, "canonical_slug": "z/glm-20261102"}}
    pp.apply_provider_pins(pins)
    client = _Client("https://openrouter.ai/api/v1")
    base.retry_chat_completion(client, model="z/glm")  # served model == requested
    first = pp.ledger()[-1]
    assert first["provider_mismatch"] is False and first["mismatch"] is False

    def dated(client, **kwargs):
        seen.append(kwargs)
        return _Resp("z/glm-20261102", "Served-Co")

    monkeypatch.setattr(pp, "_ORIGINAL", dated)
    pp.apply_provider_pins(pins)
    base.retry_chat_completion(client, model="z/glm")
    assert pp.ledger()[-1]["mismatch"] is False  # the canonical dated slug is allowed

    def other(client, **kwargs):
        return _Resp("z/glm-lite", "Served-Co")

    monkeypatch.setattr(pp, "_ORIGINAL", other)
    pp.apply_provider_pins(pins)
    base.retry_chat_completion(client, model="z/glm")
    last = pp.ledger()[-1]
    assert last["model_mismatch"] is True and last["mismatch"] is True


def test_endpoint_tags_match_the_display_name_openrouter_reports():
    """Pins hold endpoint tags; responses name the provider for display. Both must agree."""
    assert pp.provider_in_order("DeepInfra", ["deepinfra/bf16"])
    assert pp.provider_in_order("Z.AI", ["z-ai/fp8"])
    assert pp.provider_in_order("Alibaba", ["alibaba"])
    assert pp.provider_in_order("DeepSeek", ["deepseek"])
    assert pp.provider_in_order("Served-Co", ["Served-Co"])
    assert not pp.provider_in_order("Novita", ["deepinfra/bf16"])
    assert not pp.provider_in_order("DeepInfra", ["deepseek"])


def test_committed_pins_name_one_endpoint_each_without_fallbacks():
    """R01: one endpoint per model, no fallbacks. DeepSeek 4.1 Flash is Together at list price."""
    pins = pp.load_pins()
    assert {m: p["order"] for m, p in pins.items()} == {
        "qwen/qwen3.7-flash": ["alibaba"],
        "qwen/qwen3.5-9b": ["deepinfra/bf16"],
        "deepseek/deepseek-v4.1-flash-1017": ["together"],
        "z-ai/glm-5.3-flashx-legal": ["z-ai/fp8"],
    }
    assert not any(p["allow_fallbacks"] for p in pins.values())


def test_explicit_fallback_chain_is_recorded_not_pinned(vendored):
    seen, base = vendored
    pp.apply_provider_pins(PINS)
    body = {"models": ["qwen/qwen3.7-flash", "deepseek/x"]}
    base.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="qwen/qwen3.7-flash", extra_body=body)
    assert "provider" not in seen[-1]["extra_body"]
    assert len(pp.ledger()) == 1


def test_status_is_verified_only_with_a_pin_and_observed_provider_and_model(vendored, monkeypatch):
    seen, base = vendored
    client = _Client("https://openrouter.ai/api/v1")
    pins = {"q/m": {"order": ["Served-Co"], "allow_fallbacks": False, "canonical_slug": None}}
    pp.apply_provider_pins(pins)
    base.retry_chat_completion(client, model="q/m")
    assert pp.ledger()[-1]["status"] == "verified"

    def silent(client, **kwargs):
        return _Resp(kwargs["model"], None)  # the response omits its provider

    monkeypatch.setattr(pp, "_ORIGINAL", silent)
    pp.apply_provider_pins(pins)
    base.retry_chat_completion(client, model="q/m")
    row = pp.ledger()[-1]
    assert row["mismatch"] is False and row["status"] == "unverified"
    pp.apply_provider_pins({"q/m": {"order": [], "allow_fallbacks": False, "canonical_slug": None}})
    monkeypatch.setattr(pp, "_ORIGINAL", None)
    summary = pp.summarize(pp.ledger())["q/m"]
    assert (summary["verified"], summary["unverified"], summary["mismatches"]) == (1, 1, 0)


def test_fallback_chain_allows_its_models_and_skips_the_provider_pin(vendored, monkeypatch):
    seen, base = vendored

    def fell_back(client, **kwargs):
        return _Resp("deepseek/x", "Other-Co")

    monkeypatch.setattr(pp, "_ORIGINAL", fell_back)
    pp.apply_provider_pins(PINS)
    body = {"models": ["qwen/qwen3.7-flash", "deepseek/x"]}
    base.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="qwen/qwen3.7-flash", extra_body=body)
    row = pp.ledger()[-1]
    assert row["mismatch"] is False and row["pinned_order"] == [] and row["status"] == "unverified"
    assert row["fallback_models"] == ["qwen/qwen3.7-flash", "deepseek/x"]


def test_retry_path_rows_name_their_call_path(vendored):
    seen, base = vendored
    pp.apply_provider_pins(PINS)
    base.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="qwen/qwen3.7-flash")
    assert pp.ledger()[-1]["call_path"] == "retry_chat_completion"


# --- LangChain path (finding 13): the real ChatOpenAI over a stubbed HTTP transport ---------

LC_PINS = {"qwen/qwen3.7-flash": {"order": ["Alibaba"], "allow_fallbacks": False, "canonical_slug": None},
           "z/glm": {"order": ["Z-Co"], "allow_fallbacks": False, "canonical_slug": "z/glm-20261102"}}


def _chat_openai(base_url, responses, sent, model="qwen/qwen3.7-flash", **kwargs):
    """A pinned ChatOpenAI whose HTTP calls are answered from ``responses`` (no network)."""
    import httpx
    from langchain_openai import ChatOpenAI

    def handler(request):
        sent.append(json.loads(request.content))
        body = dict(responses.pop(0))
        body.setdefault("id", "gen-1")
        body.setdefault("object", "chat.completion")
        body.setdefault("created", 0)
        body.setdefault("usage", {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
        return httpx.Response(200, json=body)

    cls = pp.pinned_chat_openai(ChatOpenAI)
    return cls(model=model, api_key="test-key", base_url=base_url, max_retries=0,
               http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def _completion(model, provider, content="ok"):
    body = {"model": model, "choices": [{"index": 0, "finish_reason": "stop",
                                         "message": {"role": "assistant", "content": content}}]}
    if provider is not None:
        body["provider"] = provider
    return body


@pytest.fixture
def lc_pins(monkeypatch):
    monkeypatch.setattr(pp, "_ACTIVE", LC_PINS)
    pp.reset_ledger()
    yield
    pp.reset_ledger()


def test_langchain_request_is_pinned_and_recorded_verified(lc_pins, tmp_path, monkeypatch):
    log = tmp_path / "served.jsonl"
    monkeypatch.setenv("SANDBOX_SERVED_LOG", str(log))
    sent = []
    llm = _chat_openai("https://openrouter.ai/api/v1", [_completion("qwen/qwen3.7-flash", "Alibaba")], sent)
    assert llm.invoke("hi").content == "ok"
    assert sent[0]["provider"] == {"order": ["Alibaba"], "allow_fallbacks": False}
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["call_path"] == "langchain" and row["status"] == "verified"
    assert (row["requested_model"], row["served_model"], row["served_provider"]) == (
        "qwen/qwen3.7-flash", "qwen/qwen3.7-flash", "Alibaba")


def test_langchain_bound_extra_body_keeps_the_pin_and_its_own_keys(lc_pins):
    sent = []
    llm = _chat_openai("https://openrouter.ai/api/v1", [_completion("qwen/qwen3.7-flash", "Alibaba")], sent,
                       extra_body={"provider": {"require_parameters": True}})
    # A per-call bind replaces the client's extra_body wholesale (how the vendored
    # reasoning-effort path sends its block); the pin still lands on the final payload.
    llm.bind(extra_body={"reasoning": {"effort": "low"}}).invoke("hi")
    assert sent[0]["reasoning"] == {"effort": "low"}
    assert sent[0]["provider"] == {"order": ["Alibaba"], "allow_fallbacks": False}
    llm2 = _chat_openai("https://openrouter.ai/api/v1", [_completion("qwen/qwen3.7-flash", "Alibaba")], sent,
                        extra_body={"provider": {"require_parameters": True}})
    llm2.invoke("hi")
    assert sent[1]["provider"] == {"require_parameters": True, "order": ["Alibaba"], "allow_fallbacks": False}


def test_langchain_structured_output_is_recorded(lc_pins):
    sent = []
    content = json.dumps({"doc_type": "contract"})
    llm = _chat_openai("https://openrouter.ai/api/v1", [_completion("qwen/qwen3.7-flash", "Alibaba", content)], sent)
    schema = {"title": "out", "type": "object", "properties": {"doc_type": {"type": "string"}},
              "required": ["doc_type"], "additionalProperties": False}
    out = llm.with_structured_output(schema, method="json_schema", include_raw=True).invoke("hi")
    assert out["parsed"] == {"doc_type": "contract"}
    assert "response_format" in sent[0] and sent[0]["provider"]["order"] == ["Alibaba"]
    assert pp.ledger()[-1]["status"] == "verified" and pp.ledger()[-1]["call_path"] == "langchain"


def test_langchain_status_mismatch_and_unverified(lc_pins):
    sent = []
    responses = [_completion("qwen/qwen3.7-flash", "Other-Co"), _completion("qwen/qwen3.7-flash", None),
                 _completion("z/glm-20261102", "z-co"), _completion("z/glm-lite", "Z-Co")]
    llm = _chat_openai("https://openrouter.ai/api/v1", responses, sent)
    llm.invoke("a")
    llm.invoke("b")
    glm = _chat_openai("https://openrouter.ai/api/v1", responses, sent, model="z/glm")
    glm.invoke("c")
    glm.invoke("d")
    statuses = [(r["status"], r["provider_mismatch"], r["model_mismatch"]) for r in pp.ledger()]
    assert statuses == [("mismatch", True, False), ("unverified", False, False),
                        ("verified", False, False), ("mismatch", False, True)]


def test_langchain_off_openrouter_is_neither_pinned_nor_recorded(lc_pins):
    sent = []
    llm = _chat_openai("https://example.modal.run/v1", [_completion("qwen/qwen3.7-flash", None)], sent)
    llm.invoke("hi")
    assert "provider" not in sent[0]
    assert pp.ledger() == []


def test_langchain_unpinned_model_is_recorded_unverified(lc_pins):
    sent = []
    llm = _chat_openai("https://openrouter.ai/api/v1", [_completion("other/m", "X")], sent, model="other/m")
    llm.invoke("hi")
    assert "provider" not in sent[0]
    assert pp.ledger()[-1]["status"] == "unverified"


def test_activation_installs_one_langchain_subclass_and_restore_removes_it(vendored):
    lc_base = sys.modules["langchain_agents.base_agent"]
    pp.apply_provider_pins(PINS)
    installed = lc_base.ChatOpenAI
    assert installed is not _FakeChatOpenAI and issubclass(installed, _FakeChatOpenAI)
    assert pp.langchain_pins_active()

    class Later(installed):  # what llm_timeout installs on a later re-activation
        pass

    lc_base.ChatOpenAI = Later
    pp.apply_provider_pins(PINS)
    assert lc_base.ChatOpenAI is Later  # the pin is inherited, never stacked
    pp.restore()
    assert lc_base.ChatOpenAI is _FakeChatOpenAI and not pp.langchain_pins_active()


def test_a_non_class_chat_openai_is_left_alone(vendored):
    lc_base = sys.modules["langchain_agents.base_agent"]

    def factory(**kwargs):  # a test double installed in place of the class
        return None

    lc_base.ChatOpenAI = factory
    assert pp.apply_provider_pins(PINS) == 1  # the retry path is still wrapped
    assert lc_base.ChatOpenAI is factory and not pp.langchain_pins_active()


def test_activation_without_langchain_agents_still_wraps_the_retry_path(vendored, monkeypatch):
    monkeypatch.setitem(sys.modules, "langchain_agents", None)  # import raises ImportError
    monkeypatch.delitem(sys.modules, "langchain_agents.base_agent")
    assert pp.apply_provider_pins(PINS) == 1
    assert pp.apply_langchain_pins() is False and pp.langchain_pins_active() is False


def test_real_vendored_class_keeps_the_timeout_override_and_gains_the_pin(monkeypatch, lc_pins):
    """Activation order (llm_timeout, then pins) on the real vendored module, both orders of re-activation."""
    import httpx

    import mailroom_sandbox.llm_timeout as lt

    base_agent = pytest.importorskip("langchain_agents.base_agent")
    monkeypatch.setattr(base_agent, "ChatOpenAI", base_agent.ChatOpenAI)  # restored after the test
    monkeypatch.setattr(lt, "_APPLIED", None)
    monkeypatch.setattr(pp, "_LC_ORIGINAL", None)
    assert lt.apply_llm_timeout(600) is True
    assert pp.apply_langchain_pins() is True
    assert lt.apply_llm_timeout(600) is True  # re-activation, as runtime.activate does per run
    assert pp.apply_langchain_pins() is True and pp.langchain_pins_active()
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={**_completion("qwen/qwen3.7-flash", "Alibaba"), "id": "g", "object":
                                         "chat.completion", "created": 0})

    client = base_agent.ChatOpenAI(model="qwen/qwen3.7-flash", api_key="x", base_url="https://openrouter.ai/api/v1",
                                   timeout=120, max_retries=0,
                                   http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.request_timeout == 600
    client.invoke("hi")
    assert sent[0]["provider"]["order"] == ["Alibaba"] and pp.ledger()[-1]["status"] == "verified"
    monkeypatch.setattr(pp, "_LC_ORIGINAL", None)  # monkeypatch restores the vendored class itself


def test_vendored_base_agent_builds_its_client_from_the_patched_name():
    """The pin subclass only works while the vendored agent resolves ChatOpenAI at call time."""
    import inspect

    from langchain_agents import base_agent

    source = inspect.getsource(base_agent.BaseAgent.llm)
    assert "self._llm = ChatOpenAI(" in source


# --- Decisions API -------------------------------------------------------------------------


def test_decision_rows_are_verified_only_on_the_requested_id_or_its_dated_slug(tmp_path, monkeypatch):
    pp.reset_ledger()
    log = tmp_path / "served.jsonl"
    monkeypatch.setenv("SANDBOX_SERVED_LOG", str(log))
    slug = "typesafe/jev-1.14-20261014"
    assert pp.record_decision("typesafe/jev-1.14", {"model": slug}, slug)["status"] == "verified"
    assert pp.record_decision("typesafe/jev-1.14:nitro", {"model": "typesafe/jev-1.14"}, slug)["status"] == "verified"
    assert pp.record_decision("typesafe/jev-1.14", {"model": "typesafe/jev-1.13"}, slug)["status"] == "mismatch"
    assert pp.record_decision("typesafe/jev-1.14", {}, slug)["status"] == "unverified"
    assert pp.record_decision("x/no-slug", {"model": "x/no-slug"}, None)["status"] == "unverified"
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["call_path"] for r in rows] == ["decisions"] * 5
    assert rows[2]["model_mismatch"] is True and rows[2]["mismatch"] is True
    pp.reset_ledger()


def test_decide_and_decide_extraction_record_the_served_model(monkeypatch):
    from mailroom_sandbox import decision_backends as db

    pp.reset_ledger()
    model = "openai/gpt-6-luna-decisions"
    slug = db.decision_model(model)["canonical_slug"]
    monkeypatch.setattr(db, "_post_decision", lambda body, *, timeout, attempts: {"model": slug, "answers": {}, "usage": {}})
    monkeypatch.setattr(db, "_record_usage", lambda *a, **k: None)
    monkeypatch.setattr(db, "gate_questions", lambda qset, doc_type, subclass: {})
    db.decide("text", model=model, questions={"doc_type": {}})
    db.decide_extraction("text", {"doc_type": "contract"}, model=model, qset={"version": "t"})
    rows = pp.ledger()
    assert [(r["call_path"], r["status"], r["canonical_slug"]) for r in rows] == [("decisions", "verified", slug)] * 2
    pp.reset_ledger()


def test_ledger_rows_carry_the_run_that_made_them(vendored):
    seen, base = vendored
    client = _Client("https://openrouter.ai/api/v1")
    pins = {"q/m": {"order": ["Served-Co"], "allow_fallbacks": False, "canonical_slug": None}}
    pp.apply_provider_pins(pins)
    pp.set_run_context("run-a", "hash-a")
    try:
        base.retry_chat_completion(client, model="q/m")
    finally:
        pp.set_run_context(None)
    base.retry_chat_completion(client, model="q/m")
    stamped, bare = pp.ledger()[-2:]
    assert (stamped["run_id"], stamped["spec_hash"]) == ("run-a", "hash-a") and stamped["recorded_at"]
    assert "run_id" not in bare


def test_ledger_rows_carry_provider_reported_usage_and_cost():
    from types import SimpleNamespace

    from mailroom_sandbox import provider_pins as pp

    pp.reset_ledger()
    pins = {"qwen/qwen3.7-flash": {"order": ["alibaba"]}}
    chat = SimpleNamespace(model="qwen/qwen3.7-flash", provider="Alibaba",
                           usage=SimpleNamespace(prompt_tokens=66575, completion_tokens=136, cost=0.0067119))
    pp._record("qwen/qwen3.7-flash", chat, pins)
    pp._record("qwen/qwen3.7-flash", {"model": "qwen/qwen3.7-flash", "provider": "Alibaba",
                                      "usage": {"prompt_tokens": 10, "completion_tokens": 2}}, pins)
    pp.record_decision("openai/gpt-6-luna-decisions",
                       {"model": "openai/gpt-6-luna-decisions-20261006", "provider": "OpenAI",
                        "usage": {"input_tokens": 3622, "output_tokens": 0, "cost": 0.0003622}},
                       "openai/gpt-6-luna-decisions-20261006")
    rows = pp.ledger()
    assert rows[0]["reported_cost_usd"] == 0.0067119 and rows[0]["prompt_tokens"] == 66575
    assert "reported_cost_usd" not in rows[1] and rows[1]["completion_tokens"] == 2  # not reported, not 0
    assert rows[2]["reported_cost_usd"] == 0.0003622 and rows[2]["prompt_tokens"] == 3622
    s = pp.summarize(rows)
    assert s["qwen/qwen3.7-flash"]["reported_cost_usd"] == 0.0067119
    assert s["qwen/qwen3.7-flash"]["cost_reported_calls"] == 1 and s["qwen/qwen3.7-flash"]["calls"] == 2
    assert pp.served_usage(SimpleNamespace(usage=None)) == {}
    pp.reset_ledger()


def test_served_usage_keeps_object_zeros_and_drops_non_finite_values():
    from types import SimpleNamespace

    zero = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=120, completion_tokens=0, cost=0.0))
    assert pp.served_usage(zero) == {"prompt_tokens": 120, "completion_tokens": 0, "reported_cost_usd": 0.0}
    bad = {"usage": {"prompt_tokens": 50, "completion_tokens": float("inf"), "cost": float("nan")}}
    assert pp.served_usage(bad) == {"prompt_tokens": 50}


def test_preimported_pdf_transcriber_uses_pinned_guarded_transport(vendored, monkeypatch):
    seen, base = vendored
    pdf = types.ModuleType("agents.pdf_transcriber")
    pdf.retry_chat_completion = base.retry_chat_completion
    monkeypatch.setitem(sys.modules, "agents.pdf_transcriber", pdf)
    pp.apply_provider_pins(PINS)
    pdf.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="qwen/qwen3.7-flash")
    assert seen[-1]["extra_body"]["provider"]["order"] == ["Alibaba"]
    assert len(pp.ledger()) == 1


# L1 (phase 2): one retry layer. Each HTTP attempt the vendored loop sends is guarded, counted and capped at
# the run deadline, and the OpenAI SDK's own retries are off underneath it.


class _ServerError(Exception):
    status_code = 503


class _SdkClient:
    """An OpenAI-shaped client: ``with_options`` and ``chat.completions.create`` with scripted outcomes."""

    def __init__(self, base_url, outcomes, options=True):
        self.base_url, self.outcomes, self.sent, self.options = base_url, list(outcomes), [], []
        self.max_retries = 2  # the OpenAI SDK default
        outer = self

        class _Completions:
            def create(self, **kw):
                outer.sent.append(kw)
                outcome = outer.outcomes.pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        self.chat = types.SimpleNamespace(completions=_Completions())
        if options:
            self.with_options = self._with_options

    def _with_options(self, **opts):
        self.options.append(opts)
        return self


def _loop(attempts=3):
    """Stand-in for the vendored retry loop: up to ``attempts`` sends, each with the call timeout."""

    def original(client, timeout=600.0, **kwargs):
        for attempt in range(1, attempts + 1):
            try:
                response = client.chat.completions.create(**kwargs, timeout=timeout)
                if getattr(response, "choices", None) == []:  # as the vendored validate_completion does
                    raise RuntimeError("LLM response had no usable completion")
                return response
            except Exception:
                if attempt == attempts:
                    raise

    return original


@pytest.fixture
def run_deadline():
    from pipeline import limits

    yield limits.set_run_deadline
    limits.set_run_deadline(None)


def _install(monkeypatch, original):
    monkeypatch.setattr(sys.modules["llm.retry"], "retry_chat_completion", original)
    monkeypatch.setattr(sys.modules["agents.base"], "retry_chat_completion", original)
    pp.apply_provider_pins(PINS)
    return sys.modules["agents.base"].retry_chat_completion


_REQUEST = {"model": "qwen/qwen3.7-flash", "messages": [{"role": "user", "content": "x" * 4000}], "max_tokens": 100}


# S2 (phase 1): the guarded transports reserve each request's cost and always settle it.


@pytest.fixture
def armed_budget():
    from mailroom_sandbox.job import api_budget, call_guard

    budget = api_budget.ApiBudget(1.0, 0.10, 0.25, ["qwen/qwen3.5-9b"])
    call_guard.arm(budget, None)
    yield budget
    call_guard.disarm()


def test_pinned_chat_completion_releases_on_success_and_charges_on_timeout(vendored, monkeypatch, armed_budget):
    import httpx

    call = _install(monkeypatch, _loop(attempts=1))
    client = _SdkClient("https://openrouter.ai/api/v1",
                        [_Resp("qwen/qwen3.7-flash", "Alibaba"), httpx.ReadTimeout("no response")])
    call(client, **_REQUEST)
    assert armed_budget.reserved_usd == 0.0 and armed_budget.unreported_usd == 0.0
    with pytest.raises(httpx.ReadTimeout):
        call(client, **_REQUEST)
    assert armed_budget.reserved_usd == 0.0
    assert armed_budget.unreported_usd == pytest.approx(armed_budget.estimate_call_usd(1000, 100))


def test_langchain_reservation_is_settled_on_success_and_on_failure(lc_pins, armed_budget):
    import httpx
    from langchain_openai import ChatOpenAI

    fail = []

    def handler(request):
        if fail:
            raise httpx.ReadTimeout("no response")
        body = {**_completion("qwen/qwen3.7-flash", "Alibaba"), "id": "gen-1", "object": "chat.completion",
                "created": 0, "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
        return httpx.Response(200, json=body)

    cls = pp.pinned_chat_openai(ChatOpenAI)
    llm = cls(model="qwen/qwen3.7-flash", api_key="test-key", base_url="https://openrouter.ai/api/v1",
              max_retries=0, max_tokens=50, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.invoke("x" * 400).content == "ok"
    assert armed_budget.reserved_usd == 0.0 and armed_budget.unreported_usd == 0.0
    fail.append(True)
    with pytest.raises(Exception):
        llm.invoke("x" * 400)
    assert armed_budget.reserved_usd == 0.0 and armed_budget.unreported_usd > 0


def test_a_failed_langchain_attempt_counts_toward_the_document(lc_pins):
    import httpx
    from langchain_openai import ChatOpenAI

    from mailroom_sandbox.job import call_guard

    def handler(request):
        raise httpx.ReadTimeout("no response")

    cls = pp.pinned_chat_openai(ChatOpenAI)
    for base_url in ("https://openrouter.ai/api/v1", "http://vllm.invalid/v1"):  # L1 counts every attempt
        llm = cls(model="qwen/qwen3.7-flash", api_key="test-key", base_url=base_url, max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        with call_guard.document() as scope:
            for _ in range(3):
                with pytest.raises(Exception):
                    llm.invoke("x")
        assert scope["llm_calls"] == 3, base_url


def test_a_refused_langchain_request_is_not_counted(lc_pins, armed_budget):
    from mailroom_sandbox.job import call_guard

    llm = _chat_openai("https://openrouter.ai/api/v1", [_completion("qwen/qwen3.7-flash", "Alibaba")], [],
                       max_tokens=50)
    armed_budget.reserve(0.999999)
    with call_guard.document() as scope:
        with pytest.raises(Exception, match="call refused"):
            llm.invoke("x" * 400)
    assert scope["llm_calls"] == 0


def test_a_langchain_request_too_dear_for_the_cap_never_goes_out(lc_pins, armed_budget):
    sent = []
    llm = _chat_openai("https://openrouter.ai/api/v1", [_completion("qwen/qwen3.7-flash", "Alibaba")], sent,
                       max_tokens=50)
    armed_budget.reserve(0.999999)  # the rest of the cap is held by requests in flight
    with pytest.raises(Exception, match="call refused"):
        llm.invoke("x" * 400)
    assert sent == []


def test_each_http_attempt_reserves_and_settles_once(vendored, monkeypatch, armed_budget):
    from mailroom_sandbox.job import call_guard

    reservations = []
    real_guard = pp._guard_call
    monkeypatch.setattr(pp, "_guard_call", lambda *a: reservations.append(a) or real_guard(*a))
    call = _install(monkeypatch, _loop())
    client = _SdkClient("https://openrouter.ai/api/v1",
                        [_ServerError("bad gateway"), _ServerError("bad gateway"), _Resp("qwen/qwen3.7-flash", "Alibaba")])
    with call_guard.document() as scope:
        call(client, **_REQUEST)
    assert len(reservations) == 3 and len(client.sent) == 3
    assert armed_budget.reserved_usd == 0.0  # every reservation ended
    assert armed_budget.unreported_usd == pytest.approx(2 * armed_budget.estimate_call_usd(1000, 100))
    assert (scope["calls"], scope["llm_calls"]) == (2, 2)  # the returned call is priced by after_call (HF-004)


class _EmptyResp:
    """A 200 whose ``choices`` is empty: the vendored ``validate_completion`` rejects it."""
    model, choices, model_extra = "qwen/qwen3.7-flash", [], {}


def test_a_reply_with_no_usable_choice_counts_as_a_failed_attempt(vendored, monkeypatch, armed_budget):
    from mailroom_sandbox.job import call_guard

    call = _install(monkeypatch, _loop())
    client = _SdkClient("https://openrouter.ai/api/v1", [_EmptyResp(), _Resp("qwen/qwen3.7-flash", "Alibaba")])
    with call_guard.document() as scope:
        call(client, **_REQUEST)
    assert len(client.sent) == 2 and armed_budget.reserved_usd == 0.0
    assert armed_budget.unreported_usd == pytest.approx(armed_budget.estimate_call_usd(1000, 100))  # may be billed
    assert (scope["calls"], scope["llm_calls"]) == (1, 1)  # the empty reply; the returned call is priced later


def test_sdk_retries_are_off_under_the_wrapper(vendored, monkeypatch):
    call = _install(monkeypatch, _loop())
    client = _SdkClient("http://vllm.invalid/v1", [_Resp("m", "p")])
    call(client, model="m", messages=[])
    assert client.options == [{"max_retries": 0}]


def test_the_attempt_timeout_never_outlives_the_run_deadline(vendored, monkeypatch, run_deadline):
    import time

    run_deadline(time.time() + 5)
    call = _install(monkeypatch, _loop())
    client = _SdkClient("http://vllm.invalid/v1", [_Resp("m", "p")])
    call(client, model="m", messages=[], timeout=600.0)
    assert 1.0 <= client.sent[0]["timeout"] <= 5.0


def test_no_attempt_is_sent_past_the_run_deadline(vendored, monkeypatch, run_deadline, armed_budget):
    import time

    from pipeline.limits import RunDeadlineExceeded

    run_deadline(time.time() - 1)
    call = _install(monkeypatch, _loop(attempts=1))
    client = _SdkClient("https://openrouter.ai/api/v1", [_Resp("qwen/qwen3.7-flash", "Alibaba")])
    with pytest.raises(RunDeadlineExceeded):
        call(client, **_REQUEST)
    assert client.sent == []
    assert armed_budget.reserved_usd == 0.0 and armed_budget.unreported_usd == 0.0


def test_a_mock_client_keeps_its_scripted_create(vendored, monkeypatch):
    from unittest.mock import MagicMock

    call = _install(monkeypatch, _loop())
    client = MagicMock()  # the mock pilot's client: with_options would return a new, unscripted mock
    client.base_url = "http://vllm.invalid/v1"
    client.chat.completions.create.side_effect = lambda **kw: _Resp(kw["model"], "p")
    assert call(client, model="m", messages=[]).model == "m"
    client.with_options.assert_not_called()


def test_a_client_without_with_options_still_works(vendored, monkeypatch):
    call = _install(monkeypatch, _loop())
    client = _SdkClient("http://vllm.invalid/v1", [_Resp("m", "p")], options=False)
    assert call(client, model="m", messages=[]).model == "m"
    assert client.sent[0]["timeout"] == 600.0  # no deadline: the call timeout is untouched
