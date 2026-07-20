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
