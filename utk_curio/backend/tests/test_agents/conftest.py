"""Shared fixtures for agent tests - reuses the common app/DB/auth fixtures."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import agent_jobs, provider_config
from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    app,
    client,
    db,
    guest_user_and_token,
    tmp_curio,
    user_and_token,
)


@pytest.fixture(autouse=True)
def _default_provider(monkeypatch):
    """Give the suite a deployment-configured default LLM provider.

    Almost every test here drives a route that resolves a provider before it
    validates anything else, so with no default configured they all fail at
    that first step with a 400 instead of exercising what they are about.

    Curio ships no built-in endpoint (see ``config.DEFAULT_LLM_*``), which is
    deliberate: an instance whose operator configured nothing must not send
    prompts to a third party. The tests therefore stand in for the operator
    rather than leaning on a shipped default. The URL is unroutable on purpose
    - anything that actually reaches out is stubbed, and a test that forgot to
    stub should fail loudly rather than make a real call.
    """
    monkeypatch.setattr(provider_config, "DEFAULT_LLM_API_TYPE", "openai_compatible")
    monkeypatch.setattr(provider_config, "DEFAULT_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(provider_config, "DEFAULT_LLM_MODEL", "test-model")
    monkeypatch.setattr(provider_config, "DEFAULT_LLM_API_KEY", "test-key")


@pytest.fixture(autouse=True)
def _fresh_agent_jobs():
    """dev/115: the detached-job registry is process state — every test starts
    with none and leaves none behind (a leaked live job would hit the
    per-attachment guard or the per-user cap in an unrelated test)."""
    agent_jobs.reset_registry()
    yield
    agent_jobs.reset_registry()
