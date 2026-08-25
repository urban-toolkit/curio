"""Tests for the agents-owned provider-config resolution (memo dev/22, slice 1).

Behavior ported from the former ``app/api/routes.py::_resolve_llm_config``:
guest key handling, the aiconn default for unconfigured users, and configured
passthrough — plus the import-boundary guarantee that ``app/agents`` no longer
reaches into ``app/api``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.app.agents import provider_config as pc
from utk_curio.backend.app.agents.provider_config import (
    ProviderConfigError,
    resolve_provider_config,
)


def _user(**kw):
    base = dict(
        is_guest=False,
        llm_model=None,
        llm_api_key=None,
        llm_api_type=None,
        llm_base_url=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestResolve:
    def test_guest_without_key_refused(self, monkeypatch):
        monkeypatch.setattr(pc, "GUEST_LLM_API_KEY", "")
        with pytest.raises(ProviderConfigError, match="guest"):
            resolve_provider_config(_user(is_guest=True))

    def test_guest_with_key_uses_guest_config(self, monkeypatch):
        monkeypatch.setattr(pc, "GUEST_LLM_API_KEY", "gk")
        monkeypatch.setattr(pc, "GUEST_LLM_API_TYPE", "openai_compatible")
        monkeypatch.setattr(pc, "GUEST_LLM_BASE_URL", "https://guest.example/v1")
        monkeypatch.setattr(pc, "GUEST_LLM_MODEL", "guest-model")
        cfg = resolve_provider_config(_user(is_guest=True))
        assert (cfg.api_key, cfg.api_type, cfg.base_url, cfg.model) == (
            "gk", "openai_compatible", "https://guest.example/v1", "guest-model",
        )

    def test_unconfigured_user_falls_back_to_aiconn_default(self, monkeypatch):
        monkeypatch.setattr(pc, "DEFAULT_LLM_API_KEY", "dk")
        monkeypatch.setattr(pc, "DEFAULT_LLM_API_TYPE", "openai_compatible")
        monkeypatch.setattr(pc, "DEFAULT_LLM_BASE_URL", "https://sage200.evl.uic.edu/v1")
        monkeypatch.setattr(pc, "DEFAULT_LLM_MODEL", "llama4-nim")
        cfg = resolve_provider_config(_user())
        assert (cfg.api_key, cfg.base_url, cfg.model) == (
            "dk", "https://sage200.evl.uic.edu/v1", "llama4-nim",
        )

    def test_configured_user_passthrough_with_fallback_fields(self):
        cfg = resolve_provider_config(
            _user(llm_model="my-model", llm_api_key=None, llm_api_type=None, llm_base_url=None)
        )
        assert (cfg.api_key, cfg.api_type, cfg.base_url, cfg.model) == (
            "", "openai_compatible", "", "my-model",
        )
        cfg = resolve_provider_config(
            _user(llm_model="m", llm_api_key="k", llm_api_type="anthropic", llm_base_url="b")
        )
        assert (cfg.api_key, cfg.api_type, cfg.base_url, cfg.model) == ("k", "anthropic", "b", "m")


class TestImportBoundary:
    def test_app_agents_never_imports_app_api(self):
        """The agents/ boundary owns provider resolution; the legacy bridge goes
        the other way (app/api reads through app/agents)."""
        agents_dir = Path(pc.__file__).resolve().parent
        offenders = [
            p.name
            for p in agents_dir.glob("*.py")
            if "backend.app.api" in p.read_text(encoding="utf-8")
        ]
        assert offenders == []
