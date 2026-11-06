"""Tests for the deployment's own LLM endpoints as ``config.py`` reads them.

``config.DEFAULT_LLM_ENDPOINTS`` is the single source of the deployment's
endpoints, read only from the file ``--llm-endpoint-file`` names; its first
endpoint's first model is the Deployment default, and the guests'. Curio ships
no endpoint of its own. How a run resolves against them is
``test_agents/test_provider_config.py``; the file's format is
``test_llm_endpoint_file.py``.
"""

from __future__ import annotations

import contextlib
import importlib
import os
from unittest import mock

import utk_curio.backend.config as cfg
from utk_curio.common.llm_endpoint import ENDPOINT_FILE_VARIABLE, RETIRED_VARIABLES

#: Every variable the deployment's LLM settings were or are read from.
_LLM_VARIABLES = (ENDPOINT_FILE_VARIABLE, *RETIRED_VARIABLES, "AICONN_API_KEY", "CURIO_NO_AUTH", "CURIO_NO_PROJECT")


@contextlib.contextmanager
def _config_under(**env):
    """config.py as a backend started under exactly these LLM settings reads
    it, put back afterwards. config.py reads its settings at import, so it is
    reloaded inside the patched environment."""
    try:
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in _LLM_VARIABLES:
                os.environ.pop(name, None)
            os.environ.update(env)
            yield importlib.reload(cfg)
    finally:
        importlib.reload(cfg)


def _endpoint_file(tmp_path):
    path = tmp_path / "llm-endpoints"
    path.write_text(
        "[Lab gateway]\nbase_url=https://llm.example.test/v1\napi_key=fake-endpoint-key-0001\n"
        "models=model-a,model-b\n\n[Second]\nbase_url=https://second.example.test/v1\n"
        "api_key=fake-second-key-0002\nmodels=model-b,model-c\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return str(path)


class TestTheDeploymentKey:
    """#480 and the endpoint file: no variable sets the deployment's key, not
    ``CURIO_DEFAULT_LLM_API_KEY`` and not the older ``AICONN_API_KEY``."""

    def test_the_old_variable_does_not_set_it(self):
        with _config_under(CURIO_DEFAULT_LLM_API_KEY="sk-old-fake-0001") as settings:
            assert settings.DEFAULT_LLM_ENDPOINTS == ()
            assert not hasattr(settings, "DEFAULT_LLM_API_KEY")

    def test_the_old_aiconn_name_does_not(self):
        with _config_under(AICONN_API_KEY="sk-undocumented") as settings:
            assert settings.DEFAULT_LLM_ENDPOINTS == ()

    def test_the_file_sets_it(self, tmp_path):
        with _config_under(**{ENDPOINT_FILE_VARIABLE: _endpoint_file(tmp_path)}) as settings:
            assert [e.api_key for e in settings.DEFAULT_LLM_ENDPOINTS] == [
                "fake-endpoint-key-0001", "fake-second-key-0002",
            ]


class TestConfigDefaults:
    def test_ships_no_built_in_endpoint(self):
        """Curio ships no live provider as its built-in default.

        The branch this merged from defaulted to a specific university-hosted
        endpoint and model, which would have sent an unconfigured instance's
        prompts to a third party its operator never chose. Without an endpoint
        file there is none."""
        if not os.environ.get(ENDPOINT_FILE_VARIABLE):
            assert cfg.DEFAULT_LLM_ENDPOINTS == ()

    def test_the_guest_configuration_has_no_settings_of_its_own(self):
        """Guests answer on the Deployment default: no endpoint, key, provider
        or model is theirs alone, so none is read."""
        for name in ("GUEST_LLM_API_TYPE", "GUEST_LLM_BASE_URL", "GUEST_LLM_API_KEY", "GUEST_LLM_MODEL",
                     "DEFAULT_LLM_API_TYPE", "DEFAULT_LLM_BASE_URL", "DEFAULT_LLM_API_KEY", "DEFAULT_LLM_MODEL"):
            assert not hasattr(cfg, name), name


class TestTheEndpointFile:
    """Fake names, hosts and keys only."""

    def test_a_hosted_guest_answers_on_the_first_endpoints_first_model(self, tmp_path):
        from utk_curio.backend.app.agents.infrastructure import provider_config as pc

        with _config_under(**{ENDPOINT_FILE_VARIABLE: _endpoint_file(tmp_path)},
                           CURIO_NO_AUTH="0", CURIO_NO_PROJECT="0") as settings:
            assert [e.name for e in settings.DEFAULT_LLM_ENDPOINTS] == ["Lab gateway", "Second"]
            out = pc.resolve_llm("guest", "agent.curio.researcher")
            assert (out.source, out.model, out.base_url, out.api_key) == (
                "guest", "model-a", "https://llm.example.test/v1", "fake-endpoint-key-0001",
            )
            assert pc._answers(out)["baseUrlHost"] == ""
            default = pc.deployment_config("7")
            assert (default.source, default.model, default.api_key) == (
                "deployment", "model-a", "fake-endpoint-key-0001",
            )

    def test_the_old_variables_beside_the_file_are_not_read(self, tmp_path):
        with _config_under(**{ENDPOINT_FILE_VARIABLE: _endpoint_file(tmp_path)},
                           CURIO_DEFAULT_LLM_API_KEY="sk-old-fake-0001",
                           CURIO_DEFAULT_LLM_BASE_URL="https://old.example.test/v1",
                           GUEST_LLM_MODEL="old-model") as settings:
            endpoints = settings.DEFAULT_LLM_ENDPOINTS
            assert [(e.base_url, e.api_key, e.models[0]) for e in endpoints] == [
                ("https://llm.example.test/v1", "fake-endpoint-key-0001", "model-a"),
                ("https://second.example.test/v1", "fake-second-key-0002", "model-b"),
            ]
