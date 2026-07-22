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

        def _create(model, messages, stream):
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
                    completions=t.SimpleNamespace(create=lambda model, messages, stream: _chunks())
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
