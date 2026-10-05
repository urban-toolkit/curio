"""Tests for the deployment's default LLM provider settings.

``config.DEFAULT_LLM_*`` is the single source of the deployment default, and
``GUEST_LLM_*`` inherits it. Curio ships no endpoint of its own. How a run
resolves against them is ``test_agents/test_provider_config.py``.
"""

from __future__ import annotations

import importlib
import os
from unittest import mock

import utk_curio.backend.config as cfg


def _default_key_under(**env) -> str:
    """``DEFAULT_LLM_API_KEY`` as config.py resolves it under this environment.

    config.py reads its settings at import, so it is reloaded inside the
    patched environment and restored afterwards.
    """
    with mock.patch.dict(os.environ, env, clear=False):
        for name in ("CURIO_DEFAULT_LLM_API_KEY", "AICONN_API_KEY"):
            if name not in env:
                os.environ.pop(name, None)
        importlib.reload(cfg)
        try:
            return cfg.DEFAULT_LLM_API_KEY
        finally:
            importlib.reload(cfg)


class TestTheDeploymentKey:
    """#480: the key comes from ``CURIO_DEFAULT_LLM_API_KEY`` alone, the one
    variable DEPLOYMENT.md and AGENT-CATALOG.md document."""

    def test_the_documented_variable_sets_it(self):
        assert _default_key_under(CURIO_DEFAULT_LLM_API_KEY="sk-documented") == "sk-documented"

    def test_the_old_aiconn_name_does_not(self):
        assert _default_key_under(AICONN_API_KEY="sk-undocumented") == ""


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

    def test_guest_inherits_default_when_unset(self):
        if not os.environ.get("GUEST_LLM_MODEL"):
            assert cfg.GUEST_LLM_MODEL == cfg.DEFAULT_LLM_MODEL
        if not os.environ.get("GUEST_LLM_BASE_URL"):
            assert cfg.GUEST_LLM_BASE_URL == cfg.DEFAULT_LLM_BASE_URL
        if not os.environ.get("GUEST_LLM_API_TYPE"):
            assert cfg.GUEST_LLM_API_TYPE == cfg.DEFAULT_LLM_API_TYPE
