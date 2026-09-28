"""Tests for the deployment's default LLM provider settings.

``config.DEFAULT_LLM_*`` is the single source of the deployment default, and
``GUEST_LLM_*`` inherits it. Curio ships no endpoint of its own. How a run
resolves against them is ``test_agents/test_provider_config.py``.
"""

from __future__ import annotations

import os

import utk_curio.backend.config as cfg


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
