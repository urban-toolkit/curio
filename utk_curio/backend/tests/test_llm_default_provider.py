"""Tests for the default LLM provider.

Covers the two moving parts:
- ``config.DEFAULT_LLM_*`` is the single source of the default provider, and
  ``GUEST_LLM_*`` inherits it. Curio ships no endpoint of its own here.
- ``routes._resolve_llm_config`` falls back to that default for an unconfigured
  user (instead of erroring), while a configured user keeps their exact config.
"""

from __future__ import annotations

import os
import types

import pytest
from flask import Flask, g
from werkzeug.exceptions import HTTPException

import utk_curio.backend.config as cfg
# Resolution moved into the agents boundary (memo dev/22, ADR-AG-012 v1 step);
# these tests patch the moved module while still calling the legacy shim in
# app/api/routes, proving the bridge keeps the exact /llm/* contract.
import utk_curio.backend.app.agents.provider_config as provider_config
from utk_curio.backend.app.api.routes import _resolve_llm_config


def _fake_user(**kw):
    base = dict(
        is_guest=False,
        llm_api_key=None,
        llm_api_type=None,
        llm_base_url=None,
        llm_model=None,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _ctx():
    """A bare Flask request context — enough for flask.g and abort()."""
    return Flask(__name__).test_request_context()


class TestConfigDefaults:
    def test_ships_no_built_in_endpoint(self):
        """Curio ships no live provider as its built-in default.

        The branch this merged from defaulted to a specific university-hosted
        endpoint and model, which would have sent an unconfigured instance's
        prompts to a third party its operator never chose. The env knobs stay;
        only the shipped values are empty. Env can override, so assert the
        built-in values only when unset.
        """
        if not os.environ.get("CURIO_DEFAULT_LLM_BASE_URL"):
            assert cfg.DEFAULT_LLM_BASE_URL == ""
        if not os.environ.get("CURIO_DEFAULT_LLM_MODEL"):
            assert cfg.DEFAULT_LLM_MODEL == ""
        # The transport shape is still a sensible default: an operator points
        # CURIO_DEFAULT_LLM_BASE_URL at any OpenAI-compatible server.
        if not os.environ.get("CURIO_DEFAULT_LLM_API_TYPE"):
            assert cfg.DEFAULT_LLM_API_TYPE == "openai_compatible"

    def test_unconfigured_deployment_refuses_rather_than_guessing(self, monkeypatch):
        """With no operator default, an unconfigured user gets a clear refusal."""
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_MODEL", "")
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_BASE_URL", "")
        with pytest.raises(provider_config.ProviderConfigError) as exc:
            provider_config.resolve_provider_config(_fake_user())
        assert "AI Settings" in str(exc.value)

    def test_guest_inherits_default_when_unset(self):
        if not os.environ.get("GUEST_LLM_MODEL"):
            assert cfg.GUEST_LLM_MODEL == cfg.DEFAULT_LLM_MODEL
        if not os.environ.get("GUEST_LLM_BASE_URL"):
            assert cfg.GUEST_LLM_BASE_URL == cfg.DEFAULT_LLM_BASE_URL
        if not os.environ.get("GUEST_LLM_API_TYPE"):
            assert cfg.GUEST_LLM_API_TYPE == cfg.DEFAULT_LLM_API_TYPE


class TestResolveLlmConfig:
    def test_unconfigured_user_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_API_KEY", "seed-key")
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_API_TYPE", "openai_compatible")
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_BASE_URL", "https://sage200.evl.uic.edu/v1")
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_MODEL", "llama4-nim")
        with _ctx():
            g.user = _fake_user()  # no llm_model → unconfigured
            assert _resolve_llm_config() == (
                "seed-key",
                "openai_compatible",
                "https://sage200.evl.uic.edu/v1",
                "llama4-nim",
            )

    def test_configured_user_keeps_own_config(self, monkeypatch):
        # A configured provider must NOT get the default base_url injected.
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_BASE_URL", "https://sage200.evl.uic.edu/v1")
        with _ctx():
            g.user = _fake_user(llm_api_type="anthropic", llm_model="claude-x", llm_api_key="k")
            assert _resolve_llm_config() == ("k", "anthropic", "", "claude-x")

    def test_configured_openai_compatible_user_keeps_base_url(self, monkeypatch):
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_BASE_URL", "https://sage200.evl.uic.edu/v1")
        with _ctx():
            g.user = _fake_user(
                llm_api_type="openai_compatible",
                llm_base_url="http://localhost:11434/v1",
                llm_model="llama3.2",
            )
            assert _resolve_llm_config() == ("", "openai_compatible", "http://localhost:11434/v1", "llama3.2")

    def test_guest_uses_guest_config(self, monkeypatch):
        monkeypatch.setattr(provider_config, "GUEST_LLM_API_KEY", "gkey")
        monkeypatch.setattr(provider_config, "GUEST_LLM_API_TYPE", "openai_compatible")
        monkeypatch.setattr(provider_config, "GUEST_LLM_BASE_URL", "https://sage200.evl.uic.edu/v1")
        monkeypatch.setattr(provider_config, "GUEST_LLM_MODEL", "llama4-nim")
        with _ctx():
            g.user = _fake_user(is_guest=True)
            assert _resolve_llm_config() == (
                "gkey",
                "openai_compatible",
                "https://sage200.evl.uic.edu/v1",
                "llama4-nim",
            )

    def test_guest_without_key_aborts(self, monkeypatch):
        monkeypatch.setattr(provider_config, "GUEST_LLM_API_KEY", "")
        with _ctx():
            g.user = _fake_user(is_guest=True)
            with pytest.raises(HTTPException) as exc:
                _resolve_llm_config()
        assert exc.value.code == 400
