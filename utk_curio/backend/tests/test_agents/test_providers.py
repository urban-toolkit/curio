"""Tests for the provider-neutral chat-completion port (Feature 4).

The three backends are dispatched by ``api_type``; the provider SDKs are
monkeypatched so the tests assert routing + config wiring without network calls.
"""

from __future__ import annotations

import sys
import types

import pytest

from utk_curio.backend.app.agents.providers import ProviderConfig, run_chat_completion


def _cfg(**kw):
    base = dict(api_key="k", api_type="openai_compatible", base_url="", model="m")
    base.update(kw)
    return ProviderConfig(**base)


class TestOpenAICompatible:
    def test_dispatch_wires_model_messages_and_base_url(self, monkeypatch):
        seen = {}

        def _create(model, messages):
            seen["model"] = model
            seen["messages"] = messages
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="hello"))]
            )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                seen["kwargs"] = kwargs
                self.chat = types.SimpleNamespace(
                    completions=types.SimpleNamespace(create=_create)
                )

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        msgs = [{"role": "user", "content": "hi"}]
        out = run_chat_completion(
            _cfg(api_key="sk-1", base_url="https://sage200.evl.uic.edu/v1", model="llama4-nim"),
            msgs,
        )
        assert out == "hello"
        assert seen["model"] == "llama4-nim"
        assert seen["messages"] == msgs
        assert seen["kwargs"]["api_key"] == "sk-1"
        assert seen["kwargs"]["base_url"] == "https://sage200.evl.uic.edu/v1"

    def test_missing_key_falls_back_to_no_key_and_omits_base_url(self, monkeypatch):
        seen = {}

        class FakeOpenAI:
            def __init__(self, **kwargs):
                seen["kwargs"] = kwargs
                self.chat = types.SimpleNamespace(
                    completions=types.SimpleNamespace(
                        create=lambda model, messages: types.SimpleNamespace(
                            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="x"))]
                        )
                    )
                )

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        run_chat_completion(_cfg(api_key="", base_url=""), [{"role": "user", "content": "hi"}])
        assert seen["kwargs"]["api_key"] == "no-key"
        assert "base_url" not in seen["kwargs"]  # omitted when unset


class TestAnthropic:
    def test_splits_system_and_returns_first_block(self, monkeypatch):
        seen = {}

        def _create(model, system, messages, max_tokens):
            seen.update(model=model, system=system, messages=messages, max_tokens=max_tokens)
            return types.SimpleNamespace(content=[types.SimpleNamespace(text="claude-reply")])

        fake = types.ModuleType("anthropic")
        fake.NOT_GIVEN = object()
        fake.Anthropic = lambda **kw: types.SimpleNamespace(
            messages=types.SimpleNamespace(create=_create)
        )
        monkeypatch.setitem(sys.modules, "anthropic", fake)

        msgs = [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ]
        out = run_chat_completion(_cfg(api_type="anthropic", model="claude-x"), msgs)
        assert out == "claude-reply"
        assert seen["system"] == "be terse"
        assert seen["messages"] == [{"role": "user", "content": "hi"}]  # system removed
        assert seen["max_tokens"] == 4096

    def test_no_system_uses_not_given(self, monkeypatch):
        sentinel = object()
        seen = {}

        def _create(model, system, messages, max_tokens):
            seen["system"] = system
            return types.SimpleNamespace(content=[types.SimpleNamespace(text="ok")])

        fake = types.ModuleType("anthropic")
        fake.NOT_GIVEN = sentinel
        fake.Anthropic = lambda **kw: types.SimpleNamespace(
            messages=types.SimpleNamespace(create=_create)
        )
        monkeypatch.setitem(sys.modules, "anthropic", fake)
        run_chat_completion(_cfg(api_type="anthropic"), [{"role": "user", "content": "hi"}])
        assert seen["system"] is sentinel


class TestGemini:
    def test_dispatch_configures_and_sends_last_message(self, monkeypatch):
        seen = {}

        def _configure(api_key):
            seen["api_key"] = api_key

        class FakeChat:
            def send_message(self, msg):
                seen["last"] = msg
                return types.SimpleNamespace(text="gemini-reply")

        class FakeModel:
            def __init__(self, model, system_instruction=None):
                seen["model"] = model
                seen["system_instruction"] = system_instruction

            def start_chat(self, history):
                seen["history"] = history
                return FakeChat()

        fake = types.ModuleType("google.generativeai")
        fake.configure = _configure
        fake.GenerativeModel = FakeModel
        google_pkg = types.ModuleType("google")
        google_pkg.generativeai = fake
        monkeypatch.setitem(sys.modules, "google", google_pkg)
        monkeypatch.setitem(sys.modules, "google.generativeai", fake)

        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "mid"},
            {"role": "user", "content": "last"},
        ]
        out = run_chat_completion(_cfg(api_type="gemini", api_key="gk", model="gemini-x"), msgs)
        assert out == "gemini-reply"
        assert seen["api_key"] == "gk"
        assert seen["model"] == "gemini-x"
        assert seen["system_instruction"] == "sys"
        assert seen["last"] == "last"
        # history excludes the trailing user message and maps assistant->model
        assert seen["history"] == [
            {"role": "user", "parts": ["first"]},
            {"role": "model", "parts": ["mid"]},
        ]


class TestProviderConfig:
    def test_is_frozen(self):
        cfg = _cfg()
        with pytest.raises(Exception):
            cfg.model = "other"  # type: ignore[misc]


class TestStreaming:
    """stream_chat_completion yields reply deltas per backend (memo dev/22)."""

    def test_openai_compatible_streams_deltas(self, monkeypatch):
        import types as t
        from utk_curio.backend.app.agents.providers import stream_chat_completion

        seen = {}

        def _chunk(text):
            return t.SimpleNamespace(choices=[t.SimpleNamespace(delta=t.SimpleNamespace(content=text))])

        def _create(model, messages, stream, **kwargs):
            seen["model"], seen["messages"], seen["stream"] = model, messages, stream
            return iter([_chunk("he"), _chunk(None), _chunk("llo")])

        class FakeOpenAI:
            def __init__(self, **kwargs):
                seen["kwargs"] = kwargs
                self.chat = t.SimpleNamespace(completions=t.SimpleNamespace(create=_create))

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        msgs = [{"role": "user", "content": "hi"}]
        out = list(stream_chat_completion(_cfg(model="llama4-nim"), msgs))
        assert out == ["he", "llo"]  # empty deltas skipped
        assert seen["stream"] is True
        assert seen["messages"] == msgs

    def test_anthropic_streams_text_events(self, monkeypatch):
        import types as t
        from utk_curio.backend.app.agents.providers import stream_chat_completion

        seen = {}

        class FakeStream:
            text_stream = iter(["a", "", "b"])
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        class FakeClient:
            def __init__(self, api_key):
                seen["api_key"] = api_key
                self.messages = t.SimpleNamespace(stream=self._stream)
            def _stream(self, model, system, messages, max_tokens):
                seen["model"], seen["system"], seen["messages"] = model, system, messages
                return FakeStream()

        fake_mod = t.SimpleNamespace(Anthropic=FakeClient, NOT_GIVEN="NOT_GIVEN")
        monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
        out = list(
            stream_chat_completion(
                _cfg(api_type="anthropic", model="c"),
                [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            )
        )
        assert out == ["a", "b"]
        assert seen["system"] == "sys"
        assert seen["messages"] == [{"role": "user", "content": "hi"}]

    def test_stopping_iteration_stops_consumption(self, monkeypatch):
        import types as t
        from utk_curio.backend.app.agents.providers import stream_chat_completion

        produced = []

        def _chunks():
            for i in range(100):
                produced.append(i)
                yield t.SimpleNamespace(
                    choices=[t.SimpleNamespace(delta=t.SimpleNamespace(content=f"c{i}"))]
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = t.SimpleNamespace(
                    completions=t.SimpleNamespace(create=lambda **kwargs: _chunks())
                )

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        gen = stream_chat_completion(_cfg(), [{"role": "user", "content": "hi"}])
        assert next(gen) == "c0"
        gen.close()
        assert len(produced) <= 2  # generator close stops the provider stream


class TestMaxOutputTokens:
    """The effective resources.maxOutputTokens reaches each provider call."""

    def test_openai_compatible_run_and_stream(self, monkeypatch):
        import types as t
        from utk_curio.backend.app.agents.providers import (
            run_chat_completion, stream_chat_completion,
        )

        seen = {}

        def _create(**kwargs):
            seen.update(kwargs)
            if kwargs.get("stream"):
                return iter([t.SimpleNamespace(choices=[t.SimpleNamespace(delta=t.SimpleNamespace(content="x"))])])
            return t.SimpleNamespace(choices=[t.SimpleNamespace(message=t.SimpleNamespace(content="x"))])

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = t.SimpleNamespace(completions=t.SimpleNamespace(create=_create))

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        msgs = [{"role": "user", "content": "hi"}]
        run_chat_completion(_cfg(), msgs, max_output_tokens=512)
        assert seen["max_tokens"] == 512
        seen.clear()
        list(stream_chat_completion(_cfg(), msgs, max_output_tokens=256))
        assert seen["max_tokens"] == 256
        seen.clear()
        run_chat_completion(_cfg(), msgs)  # unset → provider default (no kwarg)
        assert "max_tokens" not in seen

    def test_anthropic_uses_effective_or_4096(self, monkeypatch):
        import types as t
        from utk_curio.backend.app.agents.providers import run_chat_completion

        seen = {}

        class FakeClient:
            def __init__(self, api_key):
                self.messages = t.SimpleNamespace(create=self._create)
            def _create(self, model, system, messages, max_tokens):
                seen["max_tokens"] = max_tokens
                return t.SimpleNamespace(content=[t.SimpleNamespace(text="x")])

        monkeypatch.setitem(sys.modules, "anthropic", t.SimpleNamespace(Anthropic=FakeClient, NOT_GIVEN="NG"))
        run_chat_completion(_cfg(api_type="anthropic"), [{"role": "user", "content": "hi"}], max_output_tokens=999)
        assert seen["max_tokens"] == 999
        run_chat_completion(_cfg(api_type="anthropic"), [{"role": "user", "content": "hi"}])
        assert seen["max_tokens"] == 4096

class TestUsageCapture:
    """Actual token usage flows into the caller's sink (memo dev/37)."""

    def test_openai_non_stream_and_stream_usage(self, monkeypatch):
        import types as t
        from utk_curio.backend.app.agents.providers import (
            run_chat_completion, stream_chat_completion,
        )

        usage_obj = t.SimpleNamespace(prompt_tokens=11, completion_tokens=7)

        def _create(**kwargs):
            if kwargs.get("stream"):
                assert kwargs["stream_options"] == {"include_usage": True}
                final = t.SimpleNamespace(choices=[], usage=usage_obj)
                delta = t.SimpleNamespace(
                    choices=[t.SimpleNamespace(delta=t.SimpleNamespace(content="x"))], usage=None
                )
                return iter([delta, final])
            return t.SimpleNamespace(
                choices=[t.SimpleNamespace(message=t.SimpleNamespace(content="x"))],
                usage=usage_obj,
            )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = t.SimpleNamespace(completions=t.SimpleNamespace(create=_create))

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        msgs = [{"role": "user", "content": "hi"}]
        sink = {}
        run_chat_completion(_cfg(), msgs, usage_out=sink)
        assert sink == {"inputTokens": 11, "outputTokens": 7}
        sink = {}
        assert list(stream_chat_completion(_cfg(), msgs, usage_out=sink)) == ["x"]
        assert sink == {"inputTokens": 11, "outputTokens": 7}

    def test_anthropic_stream_usage_from_final_message(self, monkeypatch):
        import types as t
        from utk_curio.backend.app.agents.providers import stream_chat_completion

        class FakeStream:
            text_stream = iter(["a"])
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def get_final_message(self):
                return t.SimpleNamespace(usage=t.SimpleNamespace(input_tokens=3, output_tokens=5))

        class FakeClient:
            def __init__(self, api_key):
                self.messages = t.SimpleNamespace(stream=lambda **kw: FakeStream())

        monkeypatch.setitem(
            sys.modules, "anthropic", t.SimpleNamespace(Anthropic=FakeClient, NOT_GIVEN="NG")
        )
        sink = {}
        out = list(
            stream_chat_completion(
                _cfg(api_type="anthropic"), [{"role": "user", "content": "hi"}], usage_out=sink
            )
        )
        assert out == ["a"]
        assert sink == {"inputTokens": 3, "outputTokens": 5}

    def test_missing_usage_leaves_sink_empty(self, monkeypatch):
        import types as t
        from utk_curio.backend.app.agents.providers import run_chat_completion

        def _create(**kwargs):
            return t.SimpleNamespace(
                choices=[t.SimpleNamespace(message=t.SimpleNamespace(content="x"))], usage=None
            )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = t.SimpleNamespace(completions=t.SimpleNamespace(create=_create))

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        sink = {}
        run_chat_completion(_cfg(), [{"role": "user", "content": "hi"}], usage_out=sink)
        assert sink == {}


# ---------------------------------------------------------------------------
# The typed turn: system slots per provider, cache usage, and the shim
# ---------------------------------------------------------------------------

from utk_curio.backend.app.agents import contracts
from utk_curio.backend.app.agents.providers import (
    ChatTurn,
    run_chat_turn,
    stream_chat_completion,
    stream_chat_turn,
)


def _slotted():
    """A system turn the way a run builds it, then the conversation."""
    system = contracts.system_message(contracts.compose_system(
        preamble="PREAMBLE", instruction="INSTRUCTION", configuration="SETTINGS",
        tool_protocol="TOOLS", runtime=("ROSTER",),
    ))
    return [system, {"role": "user", "content": "hi"}]


class TestTheSystemTurnPerProvider:
    def test_the_message_carries_its_slots_and_the_joined_text(self):
        system = _slotted()[0]
        assert system["content"] == "PREAMBLE\n\nINSTRUCTION\n\nSETTINGS\n\nTOOLS\n\nROSTER"
        assert [s["kind"] for s in system["slots"]] == [
            "preamble", "instruction", "configuration", "tool-protocol", "runtime",
        ]

    def test_anthropic_gets_a_block_per_slot_with_the_preamble_cacheable(self, monkeypatch):
        seen = {}

        def _create(model, system, messages, max_tokens):
            seen.update(system=system, messages=messages)
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text="ok")],
                usage=types.SimpleNamespace(input_tokens=10, output_tokens=4,
                                            cache_read_input_tokens=900, cache_creation_input_tokens=0),
            )

        fake = types.ModuleType("anthropic")
        fake.NOT_GIVEN = object()
        fake.Anthropic = lambda **kw: types.SimpleNamespace(messages=types.SimpleNamespace(create=_create))
        monkeypatch.setitem(sys.modules, "anthropic", fake)
        sink = {}
        turn = run_chat_turn(_cfg(api_type="anthropic"), _slotted(), usage_out=sink)
        assert turn == ChatTurn(text="ok")
        assert seen["system"] == [
            {"type": "text", "text": "PREAMBLE", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "INSTRUCTION"},
            {"type": "text", "text": "SETTINGS"},
            {"type": "text", "text": "TOOLS"},
            {"type": "text", "text": "ROSTER"},
        ]
        assert seen["messages"] == [{"role": "user", "content": "hi"}]
        # Every input token is counted, the cached ones too.
        assert sink == {"inputTokens": 910, "outputTokens": 4, "cacheReadTokens": 900, "cacheWriteTokens": 0}

    def test_anthropic_streams_the_same_blocks_and_counts_a_cache_write(self, monkeypatch):
        seen = {}

        class FakeStream:
            text_stream = iter(["a"])
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def get_final_message(self):
                return types.SimpleNamespace(usage=types.SimpleNamespace(
                    input_tokens=10, output_tokens=2, cache_read_input_tokens=0,
                    cache_creation_input_tokens=900))

        def _stream(**kwargs):
            seen.update(kwargs)
            return FakeStream()

        fake = types.SimpleNamespace(
            Anthropic=lambda **kw: types.SimpleNamespace(messages=types.SimpleNamespace(stream=_stream)),
            NOT_GIVEN="NG",
        )
        monkeypatch.setitem(sys.modules, "anthropic", fake)
        sink = {}
        assert list(stream_chat_turn(_cfg(api_type="anthropic"), _slotted(), usage_out=sink)) == ["a"]
        assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert sink == {"inputTokens": 910, "outputTokens": 2, "cacheReadTokens": 0, "cacheWriteTokens": 900}

    def test_gemini_gets_a_list_of_system_instructions(self, monkeypatch):
        seen = {}

        class FakeChat:
            def send_message(self, msg, **kwargs):
                # A function-call part has no text; response.text would raise.
                parts = [types.SimpleNamespace(text="he"), types.SimpleNamespace(text="", function_call=object()),
                         types.SimpleNamespace(text="llo")]
                return types.SimpleNamespace(
                    candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=parts))],
                    usage_metadata=types.SimpleNamespace(prompt_token_count=50, candidates_token_count=3,
                                                         cached_content_token_count=40),
                )

        class FakeModel:
            def __init__(self, model, system_instruction=None):
                seen["system_instruction"] = system_instruction
            def start_chat(self, history):
                return FakeChat()

        fake = types.ModuleType("google.generativeai")
        fake.configure = lambda api_key: None
        fake.GenerativeModel = FakeModel
        google_pkg = types.ModuleType("google")
        google_pkg.generativeai = fake
        monkeypatch.setitem(sys.modules, "google", google_pkg)
        monkeypatch.setitem(sys.modules, "google.generativeai", fake)
        sink = {}
        turn = run_chat_turn(_cfg(api_type="gemini"), _slotted(), usage_out=sink)
        assert turn.text == "hello"
        assert seen["system_instruction"] == ["PREAMBLE", "INSTRUCTION", "SETTINGS", "TOOLS", "ROSTER"]
        assert sink == {"inputTokens": 50, "outputTokens": 3, "cacheReadTokens": 40}

    def test_an_openai_compatible_server_gets_one_joined_system_message(self, monkeypatch):
        seen = {}

        def _create(**kwargs):
            seen.update(kwargs)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=None),
                                               finish_reason="tool_calls")],
                usage=types.SimpleNamespace(prompt_tokens=120, completion_tokens=6,
                                            prompt_tokens_details=types.SimpleNamespace(cached_tokens=100)),
            )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=_create))

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        sink = {}
        turn = run_chat_turn(_cfg(), _slotted(), usage_out=sink)
        # Some local chat templates reject several system messages; the slots stay home.
        assert seen["messages"] == [
            {"role": "system", "content": "PREAMBLE\n\nINSTRUCTION\n\nSETTINGS\n\nTOOLS\n\nROSTER"},
            {"role": "user", "content": "hi"},
        ]
        # A reply with no content is an empty text, not None.
        assert turn == ChatTurn(text="", stop_reason="tool_calls")
        assert sink == {"inputTokens": 120, "outputTokens": 6, "cacheReadTokens": 100}


class TestTheShim:
    def test_a_bare_string_is_a_text_turn(self):
        assert ChatTurn.of("reply") == ChatTurn(text="reply")
        turn = ChatTurn(text="x", stop_reason="stop")
        assert ChatTurn.of(turn) is turn
        assert ChatTurn.of(None) == ChatTurn(text="")

    def test_the_text_stream_leaves_out_other_events(self, monkeypatch):
        from utk_curio.backend.app.agents import providers as providers_mod

        monkeypatch.setattr(providers_mod, "stream_chat_turn",
                            lambda *a, **k: iter(["a", object(), "b"]))
        assert list(stream_chat_completion(_cfg(), [])) == ["a", "b"]


# --- Native tools ------------------------------------------------------------

_TOOLS = [
    {"name": "node__read", "description": "Read one node.",
     "parameters": {"type": "object", "properties": {"nodeId": {"type": "string"}}}},
    {"name": "delegate", "description": "Delegate.",
     "parameters": {"type": "object", "properties": {
         "capability": {"type": "string", "enum": ["node.content.generate"]},
         "inputs": {"type": "object", "description": "What the delegate needs."},
     }, "required": ["capability"]}},
]

#: One native round: the model's call, its result, and the follow-up.
_NATIVE_ROUND = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "go"},
    {"role": "assistant", "content": "Reading.", "tool_calls": [
        {"id": "c1", "name": "node__read", "arguments": {"nodeId": "n1"}},
        {"id": "c2", "name": "delegate", "arguments": {"capability": "node.content.generate"}},
    ]},
    {"role": "tool", "tool_call_id": "c1", "name": "node__read", "content": '{"id": "n1"}', "is_error": False},
    {"role": "tool", "tool_call_id": "c2", "name": "delegate", "content": "not run", "is_error": True},
]


class _Refusal(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def _fake_openai(monkeypatch, *, message=None, chunks=None, error=None):
    seen = {}

    def _create(**kwargs):
        seen.update(kwargs)
        if error is not None:
            raise error
        if kwargs.get("stream"):
            return iter(chunks)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message, finish_reason="tool_calls")])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=_create))

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    return seen


def _openai_call(call_id, name, arguments):
    return types.SimpleNamespace(id=call_id, function=types.SimpleNamespace(name=name, arguments=arguments))


class TestNativeToolsOnOpenAI:
    def test_tools_and_the_choice_are_sent_and_calls_read_back(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import ToolCall, run_chat_turn

        message = types.SimpleNamespace(content=None, tool_calls=[
            _openai_call("c1", "node__read", '{"nodeId": "n1"}'),
            _openai_call("c2", "node__read", '{"nodeId": '),
        ])
        seen = _fake_openai(monkeypatch, message=message)
        turn = run_chat_turn(_cfg(), [{"role": "user", "content": "go"}], tools=_TOOLS, tool_choice="none")
        assert seen["tool_choice"] == "none"
        assert seen["tools"][0] == {"type": "function", "function": {
            "name": "node__read", "description": "Read one node.", "parameters": _TOOLS[0]["parameters"]}}
        assert turn.text == ""
        assert turn.tool_calls[0] == ToolCall("c1", "node__read", {"nodeId": "n1"})
        assert turn.tool_calls[1].error.startswith("the arguments are not valid JSON")

    def test_a_native_round_is_sent_in_openai_shape(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import run_chat_turn

        seen = _fake_openai(monkeypatch, message=types.SimpleNamespace(content="ok", tool_calls=None))
        run_chat_turn(_cfg(), _NATIVE_ROUND, tools=_TOOLS)
        assert seen["messages"][2] == {"role": "assistant", "content": "Reading.", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "node__read", "arguments": '{"nodeId": "n1"}'}},
            {"id": "c2", "type": "function", "function": {
                "name": "delegate", "arguments": '{"capability": "node.content.generate"}'}},
        ]}
        assert seen["messages"][3:] == [
            {"role": "tool", "tool_call_id": "c1", "content": '{"id": "n1"}'},
            {"role": "tool", "tool_call_id": "c2", "content": "not run"},
        ]

    def test_without_tools_the_request_carries_none(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import run_chat_turn

        seen = _fake_openai(monkeypatch, message=types.SimpleNamespace(
            content="hi", tool_calls=[_openai_call("c1", "node__read", "{}")]))
        turn = run_chat_turn(_cfg(), [{"role": "user", "content": "go"}])
        assert "tools" not in seen and "tool_choice" not in seen
        assert turn.tool_calls == ()

    def test_a_streamed_call_is_put_together_by_index(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import ToolCall, stream_chat_turn

        def _chunk(text=None, calls=None):
            delta = types.SimpleNamespace(content=text, tool_calls=calls)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)], usage=None)

        def _piece(index, call_id=None, name=None, arguments=None):
            return types.SimpleNamespace(index=index, id=call_id,
                                         function=types.SimpleNamespace(name=name, arguments=arguments))

        chunks = [
            _chunk("Reading."),
            _chunk(calls=[_piece(0, "c1", "node__read", '{"node')]),
            _chunk(calls=[_piece(0, None, None, 'Id": "n1"}')]),
            _chunk(calls=[_piece(1, "c2", "delegate", '{"capability": "node.content.generate"}')]),
        ]
        seen = _fake_openai(monkeypatch, chunks=chunks)
        events = list(stream_chat_turn(_cfg(), [{"role": "user", "content": "go"}], tools=_TOOLS))
        assert seen["tools"] and seen["tool_choice"] == "auto"
        assert events == [
            "Reading.",
            ToolCall("c1", "node__read", {"nodeId": "n1"}),
            ToolCall("c2", "delegate", {"capability": "node.content.generate"}),
        ]

    @pytest.mark.parametrize("status", [400, 422])
    def test_a_refusal_of_the_tools_is_typed_and_keyless(self, monkeypatch, status):
        from utk_curio.backend.app.agents.providers import NativeToolsRefused, run_chat_turn, stream_chat_turn

        _fake_openai(monkeypatch, error=_Refusal("tools not supported for key sk-secret-000", status))
        config = _cfg(api_key="sk-secret-000")
        with pytest.raises(NativeToolsRefused) as refused:
            run_chat_turn(config, [{"role": "user", "content": "go"}], tools=_TOOLS)
        assert "sk-secret-000" not in str(refused.value) and "tools not supported" in str(refused.value)
        with pytest.raises(NativeToolsRefused):
            list(stream_chat_turn(config, [{"role": "user", "content": "go"}], tools=_TOOLS))

    def test_other_errors_and_requests_without_tools_raise_as_they_are(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import run_chat_turn

        _fake_openai(monkeypatch, error=_Refusal("bad request", 400))
        with pytest.raises(_Refusal):
            run_chat_turn(_cfg(), [{"role": "user", "content": "go"}])
        _fake_openai(monkeypatch, error=_Refusal("server error", 500))
        with pytest.raises(_Refusal):
            run_chat_turn(_cfg(), [{"role": "user", "content": "go"}], tools=_TOOLS)


class TestNativeToolsOnAnthropic:
    def _fake(self, monkeypatch, content_blocks, *, stream_text=()):
        seen = {}

        class FakeStream:
            text_stream = iter(stream_text)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return types.SimpleNamespace(content=content_blocks, usage=None)

        class FakeClient:
            def __init__(self, api_key):
                self.messages = types.SimpleNamespace(create=self._create, stream=self._stream)

            def _create(self, **kwargs):
                seen.update(kwargs)
                return types.SimpleNamespace(content=content_blocks, usage=None, stop_reason="tool_use")

            def _stream(self, **kwargs):
                seen.update(kwargs)
                return FakeStream()

        monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeClient, NOT_GIVEN="NG"))
        return seen

    def test_tools_calls_and_results_in_anthropic_shape(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import ToolCall, run_chat_turn

        blocks = [types.SimpleNamespace(type="text", text="Reading."),
                  types.SimpleNamespace(type="tool_use", id="t1", name="node__read", input={"nodeId": "n1"})]
        seen = self._fake(monkeypatch, blocks)
        turn = run_chat_turn(_cfg(api_type="anthropic"), _NATIVE_ROUND, tools=_TOOLS, tool_choice="none")
        assert seen["tool_choice"] == {"type": "none"}
        assert seen["tools"][1] == {"name": "delegate", "description": "Delegate.",
                                    "input_schema": _TOOLS[1]["parameters"]}
        assert seen["messages"][1] == {"role": "assistant", "content": [
            {"type": "text", "text": "Reading."},
            {"type": "tool_use", "id": "c1", "name": "node__read", "input": {"nodeId": "n1"}},
            {"type": "tool_use", "id": "c2", "name": "delegate", "input": {"capability": "node.content.generate"}},
        ]}
        # One user turn answers both calls, the refused one flagged.
        assert seen["messages"][2:] == [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": '{"id": "n1"}'},
            {"type": "tool_result", "tool_use_id": "c2", "content": "not run", "is_error": True},
        ]}]
        assert (turn.text, turn.tool_calls) == ("Reading.", (ToolCall("t1", "node__read", {"nodeId": "n1"}),))

    def test_a_stream_ends_with_the_calls_of_the_final_message(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import ToolCall, stream_chat_turn

        blocks = [types.SimpleNamespace(type="tool_use", id="t1", name="node__read", input={})]
        seen = self._fake(monkeypatch, blocks, stream_text=["Read", "ing."])
        events = list(stream_chat_turn(_cfg(api_type="anthropic"), [{"role": "user", "content": "go"}], tools=_TOOLS))
        assert events == ["Read", "ing.", ToolCall("t1", "node__read", {})]
        assert seen["tool_choice"] == {"type": "auto"}


class TestNativeToolsOnGemini:
    def _fake(self, monkeypatch, parts):
        seen = {}

        class FakeChat:
            def send_message(self, message, **kwargs):
                seen["sent"], seen["send_kwargs"] = message, kwargs
                return types.SimpleNamespace(
                    candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=parts))],
                    usage_metadata=None,
                )

        class FakeModel:
            def __init__(self, model, system_instruction=None):
                pass

            def start_chat(self, history):
                seen["history"] = history
                return FakeChat()

        fake = types.ModuleType("google.generativeai")
        fake.configure = lambda api_key: None
        fake.GenerativeModel = FakeModel
        google_pkg = types.ModuleType("google")
        google_pkg.generativeai = fake
        monkeypatch.setitem(sys.modules, "google", google_pkg)
        monkeypatch.setitem(sys.modules, "google.generativeai", fake)
        return seen

    def test_declarations_calls_and_responses_in_gemini_shape(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import run_chat_turn

        call = types.SimpleNamespace(name="delegate", args={
            "capability": "node.content.generate", "inputs": '{"intent": "load", "rows": 3.0}'})
        parts = [types.SimpleNamespace(text="Delegating.", function_call=None),
                 types.SimpleNamespace(text="", function_call=call)]
        seen = self._fake(monkeypatch, parts)
        turn = run_chat_turn(_cfg(api_type="gemini"), _NATIVE_ROUND, tools=_TOOLS, tool_choice="none")
        (declarations,) = seen["send_kwargs"]["tools"]
        delegate = declarations["function_declarations"][1]["parameters"]
        # Gemini has no open objects: inputs is offered as a JSON string.
        assert delegate["properties"]["inputs"]["type"] == "string"
        assert delegate["properties"]["capability"] == {
            "type": "string", "enum": ["node.content.generate"], "format": "enum"}
        assert seen["send_kwargs"]["tool_config"] == {"function_calling_config": {"mode": "NONE"}}
        assert seen["history"][-1] == {"role": "model", "parts": ["Reading.",
            {"function_call": {"name": "node__read", "args": {"nodeId": "n1"}}},
            {"function_call": {"name": "delegate", "args": {"capability": "node.content.generate"}}}]}
        assert seen["sent"] == {"role": "user", "parts": [
            {"function_response": {"name": "node__read", "response": {"result": '{"id": "n1"}'}}},
            {"function_response": {"name": "delegate", "response": {"error": "not run"}}}]}
        (made,) = turn.tool_calls
        assert turn.text == "Delegating."
        assert (made.name, made.arguments) == (
            "delegate", {"capability": "node.content.generate", "inputs": {"intent": "load", "rows": 3}})

    def test_the_sdk_takes_the_declarations_and_the_conversation(self):
        """The real SDK's conversion, offline: every tool the registry offers,
        and a native round, become its protos without complaint."""
        content_types = pytest.importorskip("google.generativeai.types.content_types")
        from utk_curio.backend.app.agents import providers, tools

        specs = tools.native_tools(list(tools.REGISTRY), ["node.content.generate"])
        content_types._make_tools(providers._gemini_tools(specs))
        history, last = providers._gemini_turn(_NATIVE_ROUND)
        content_types.to_contents(history)
        content_types.to_content(last)
        content_types.to_tool_config(providers._gemini_tool_config("none"))

    def test_a_refusal_is_read_from_the_code_gemini_errors_carry(self, monkeypatch):
        from utk_curio.backend.app.agents.providers import NativeToolsRefused, run_chat_turn

        class InvalidArgument(Exception):
            code = 400

        class FakeChat:
            def send_message(self, message, **kwargs):
                raise InvalidArgument("function calling is not enabled")

        fake = types.ModuleType("google.generativeai")
        fake.configure = lambda api_key: None
        fake.GenerativeModel = lambda model, system_instruction=None: types.SimpleNamespace(
            start_chat=lambda history: FakeChat())
        google_pkg = types.ModuleType("google")
        google_pkg.generativeai = fake
        monkeypatch.setitem(sys.modules, "google", google_pkg)
        monkeypatch.setitem(sys.modules, "google.generativeai", fake)
        with pytest.raises(NativeToolsRefused):
            run_chat_turn(_cfg(api_type="gemini"), [{"role": "user", "content": "go"}], tools=_TOOLS)


class TestTheRealSDKs:
    """The OpenAI and Anthropic SDKs themselves, over a mock HTTP transport:
    they serialize the request this module builds and parse the endpoint's
    answer into their own types, streamed tool calls included."""

    @staticmethod
    def _sse(events) -> bytes:
        return "".join(events).encode("utf-8")

    def _openai(self, monkeypatch, respond):
        import json as _json

        import httpx
        import openai

        seen: list = []

        def handler(request):
            seen.append(_json.loads(request.content))
            return respond(request)

        real = openai.OpenAI
        monkeypatch.setattr(openai, "OpenAI", lambda **kw: real(
            **kw, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler))))
        return seen

    def _anthropic(self, monkeypatch, respond):
        import json as _json

        import anthropic
        import httpx

        seen: list = []

        def handler(request):
            seen.append(_json.loads(request.content))
            return respond(request)

        real = anthropic.Anthropic
        monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: real(
            **kw, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler))))
        return seen

    def test_openai_a_call_and_a_native_round(self, monkeypatch):
        import httpx

        from utk_curio.backend.app.agents.providers import ToolCall, run_chat_turn

        seen = self._openai(monkeypatch, lambda request: httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "node__read", "arguments": '{"nodeId": "n1"}'}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }))
        sink: dict = {}
        turn = run_chat_turn(_cfg(base_url="http://endpoint.test/v1"), _NATIVE_ROUND,
                             usage_out=sink, tools=_TOOLS)
        assert turn.tool_calls == (ToolCall("call_1", "node__read", {"nodeId": "n1"}),)
        assert turn.stop_reason == "tool_calls" and sink["inputTokens"] == 10
        (sent,) = seen
        assert sent["tool_choice"] == "auto" and sent["tools"][1]["function"]["name"] == "delegate"
        assert [m["role"] for m in sent["messages"]] == ["system", "user", "assistant", "tool", "tool"]
        assert sent["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"nodeId": "n1"}'

    def test_openai_a_streamed_call(self, monkeypatch):
        import json as _json

        import httpx

        from utk_curio.backend.app.agents.providers import ToolCall, stream_chat_turn

        def chunk(delta, finish=None):
            return "data: " + _json.dumps({
                "id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"

        body = self._sse([
            chunk({"role": "assistant", "content": "Reading."}),
            chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                   "function": {"name": "node__read", "arguments": ""}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"nodeId": '}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"n1"}'}}]}, "tool_calls"),
            "data: [DONE]\n\n",
        ])
        seen = self._openai(monkeypatch, lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body))
        events = list(stream_chat_turn(_cfg(base_url="http://endpoint.test/v1"),
                                       [{"role": "user", "content": "go"}], tools=_TOOLS, tool_choice="none"))
        assert events == ["Reading.", ToolCall("call_1", "node__read", {"nodeId": "n1"})]
        assert seen[0]["stream"] is True and seen[0]["tool_choice"] == "none"

    def test_openai_a_refusal_of_the_tools(self, monkeypatch):
        import httpx

        from utk_curio.backend.app.agents.providers import NativeToolsRefused, run_chat_turn

        self._openai(monkeypatch, lambda request: httpx.Response(
            400, json={"error": {"message": "tools is not supported", "type": "invalid_request_error"}}))
        with pytest.raises(NativeToolsRefused, match="tools is not supported"):
            run_chat_turn(_cfg(base_url="http://endpoint.test/v1"), [{"role": "user", "content": "go"}],
                          tools=_TOOLS)

    def test_anthropic_a_call_and_a_native_round(self, monkeypatch):
        import httpx

        from utk_curio.backend.app.agents.providers import ToolCall, run_chat_turn

        seen = self._anthropic(monkeypatch, lambda request: httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "c",
            "stop_reason": "tool_use", "stop_sequence": None,
            "content": [{"type": "text", "text": "Reading."},
                        {"type": "tool_use", "id": "toolu_1", "name": "node__read", "input": {"nodeId": "n1"}}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }))
        turn = run_chat_turn(_cfg(api_type="anthropic"), _NATIVE_ROUND, tools=_TOOLS)
        assert (turn.text, turn.tool_calls) == ("Reading.", (ToolCall("toolu_1", "node__read", {"nodeId": "n1"}),))
        (sent,) = seen
        assert sent["tool_choice"] == {"type": "auto"}
        assert sent["tools"][0]["input_schema"] == _TOOLS[0]["parameters"]
        assert [block["type"] for block in sent["messages"][1]["content"]] == ["text", "tool_use", "tool_use"]
        assert [block["tool_use_id"] for block in sent["messages"][2]["content"]] == ["c1", "c2"]

    def test_anthropic_a_streamed_call(self, monkeypatch):
        import json as _json

        import httpx

        from utk_curio.backend.app.agents.providers import ToolCall, stream_chat_turn

        def event(kind, data):
            return f"event: {kind}\ndata: {_json.dumps({'type': kind, **data})}\n\n"

        body = self._sse([
            event("message_start", {"message": {
                "id": "msg_1", "type": "message", "role": "assistant", "model": "c", "content": [],
                "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}),
            event("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
            event("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Reading."}}),
            event("content_block_stop", {"index": 0}),
            event("content_block_start", {"index": 1, "content_block": {
                "type": "tool_use", "id": "toolu_1", "name": "node__read", "input": {}}}),
            event("content_block_delta", {"index": 1, "delta": {
                "type": "input_json_delta", "partial_json": '{"nodeId": '}}),
            event("content_block_delta", {"index": 1, "delta": {
                "type": "input_json_delta", "partial_json": '"n1"}'}}),
            event("content_block_stop", {"index": 1}),
            event("message_delta", {"delta": {"stop_reason": "tool_use", "stop_sequence": None},
                                    "usage": {"output_tokens": 12}}),
            event("message_stop", {}),
        ])
        self._anthropic(monkeypatch, lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body))
        sink: dict = {}
        events = list(stream_chat_turn(_cfg(api_type="anthropic"), [{"role": "user", "content": "go"}],
                                       usage_out=sink, tools=_TOOLS))
        assert events == ["Reading.", ToolCall("toolu_1", "node__read", {"nodeId": "n1"})]
        assert sink["outputTokens"] == 12

    def test_anthropic_a_refusal_of_the_tools(self, monkeypatch):
        import httpx

        from utk_curio.backend.app.agents.providers import NativeToolsRefused, run_chat_turn, stream_chat_turn

        self._anthropic(monkeypatch, lambda request: httpx.Response(400, json={
            "type": "error", "error": {"type": "invalid_request_error", "message": "tools: bad schema"}}))
        with pytest.raises(NativeToolsRefused, match="bad schema"):
            run_chat_turn(_cfg(api_type="anthropic"), [{"role": "user", "content": "go"}], tools=_TOOLS)
        with pytest.raises(NativeToolsRefused, match="bad schema"):
            list(stream_chat_turn(_cfg(api_type="anthropic"), [{"role": "user", "content": "go"}], tools=_TOOLS))
