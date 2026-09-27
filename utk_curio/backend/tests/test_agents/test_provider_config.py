"""The one resolver, as a table: which LLM configuration answers a run.

``provider_config.resolve_llm`` decides for every run from the account's LLM
configurations (``agents/llm_configs.py``) and the deployment
(``config.DEFAULT_LLM_*`` / ``GUEST_LLM_*``, read at call time):

- a hosted guest runs on the guest configuration;
- an internal agent on its caller's, always;
- any other agent on the configuration chosen for it;
- with no choice, a delegated agent on its caller's, and an attached one on
  the default configuration, else the deployment default, else a refusal whose
  remedy opens AI Settings;
- a reference that does not resolve is refused, never replaced.

Two regressions are pinned: a user's key never goes to the deployment's host,
and the operator's key never goes to a host a user typed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents import llm_configs
from utk_curio.backend.app.agents import provider_config as pc
from utk_curio.backend.app.agents.providers import ProviderConfig

USER = "7"


@pytest.fixture()
def deployment(monkeypatch, tmp_curio):
    """An operator who set a custom endpoint, a key and a model."""
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    monkeypatch.setattr(config, "DEFAULT_LLM_API_TYPE", "openai_compatible")
    monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", "https://sage.example.edu/v1")
    monkeypatch.setattr(config, "DEFAULT_LLM_API_KEY", "operator-secret-key")
    monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "llama4")
    monkeypatch.setattr(config, "GUEST_LLM_API_TYPE", "openai_compatible")
    monkeypatch.setattr(config, "GUEST_LLM_BASE_URL", "https://guest.example.edu/v1")
    monkeypatch.setattr(config, "GUEST_LLM_API_KEY", "guest-secret-key")
    monkeypatch.setattr(config, "GUEST_LLM_MODEL", "small-model")
    return llm_configs.default_store()


def _own(store, user_key=USER, **fields):
    body = {"label": "Mine", "apiType": "openai_compatible",
            "baseUrl": "https://api.openai.com/v1", "apiKey": "user-secret-key",
            "model": "gpt-4o-mini", **fields}
    return store.create(user_key, body, deployment_offered=True)


class TestTheFallbackOrder:
    def test_the_default_configuration_answers(self, deployment):
        created = _own(deployment)
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER, "agent.chat-agent")
        assert (out.api_type, out.base_url, out.api_key, out.model) == (
            "openai_compatible", "https://api.openai.com/v1", "user-secret-key", "gpt-4o-mini",
        )
        assert (out.config_id, out.label, out.source) == (created["id"], "Mine", "default")

    def test_no_default_is_the_deployment_default(self, deployment):
        _own(deployment)  # a configuration that is not the default changes nothing
        out = pc.resolve_llm(USER)
        assert (out.base_url, out.api_key, out.model) == (
            "https://sage.example.edu/v1", "operator-secret-key", "llama4",
        )
        assert (out.config_id, out.source, out.label) == (None, "deployment", "Deployment default")

    def test_nothing_configured_is_a_refusal_with_a_remedy(self, deployment, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "")
        with pytest.raises(pc.ProviderConfigError) as refused:
            pc.resolve_llm(USER, "agent.chat-agent")
        assert "AI Settings" in str(refused.value)
        assert refused.value.remedy == {"kind": "llm-config", "agentId": "agent.chat-agent"}

    def test_an_unchosen_delegate_answers_with_its_callers(self, deployment):
        caller = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="claude",
                                config_id="llm-00000000000a", label="Caller", source="default")
        out = pc.resolve_llm(USER, "agent.node-content-builder", caller=caller)
        assert (out.api_key, out.model, out.config_id, out.label) == ("k", "claude", "llm-00000000000a", "Caller")
        assert out.source == "caller"


class TestAChoicePerAgent:
    def _chosen(self, store, agent_id="agent.node-content-builder", **fields):
        created = _own(store, label=fields.pop("label", "Chosen"), model=fields.pop("model", "chosen-model"), **fields)
        store.set_choices(USER, {agent_id: created["id"]},
                          choosable=frozenset({agent_id}), deployment_default=True)
        return created

    def test_an_attached_agent_runs_on_its_choice_over_the_default(self, deployment):
        default = _own(deployment, label="Default")
        deployment.set_default(USER, default["id"])
        chosen = self._chosen(deployment, "agent.chat-agent")
        out = pc.resolve_llm(USER, "agent.chat-agent")
        assert (out.config_id, out.model, out.source) == (chosen["id"], "chosen-model", "assigned")
        # Another agent still follows the default.
        assert pc.resolve_llm(USER, "agent.dataflow-builder").config_id == default["id"]

    def test_a_delegate_runs_on_its_own_choice_not_its_callers(self, deployment):
        chosen = self._chosen(deployment)
        caller = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="claude",
                                source="default")
        out = pc.resolve_llm(USER, "agent.node-content-builder", caller=caller)
        assert (out.config_id, out.api_key, out.source) == (chosen["id"], "user-secret-key", "assigned")

    def test_an_internal_agent_always_runs_on_its_callers(self, deployment):
        # A choice cannot be written for one; a hand-edited file is ignored.
        created = _own(deployment, label="Planner")
        doc = deployment.read(USER)
        doc["agents"]["agent.dataflow-planner"] = created["id"]
        deployment._write(USER, doc)
        caller = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="claude",
                                source="assigned")
        out = pc.resolve_llm(USER, "agent.dataflow-planner", caller=caller)
        assert (out.api_key, out.model, out.source) == ("k", "claude", "caller")

    def test_the_deployment_default_can_be_chosen(self, deployment):
        deployment.set_choices(USER, {"agent.chat-agent": "deployment"},
                               choosable=frozenset({"agent.chat-agent"}), deployment_default=True)
        out = pc.resolve_llm(USER, "agent.chat-agent")
        assert (out.model, out.source, out.label) == ("llama4", "assigned", "Deployment default")

    def test_a_choice_that_names_nothing_is_refused_not_replaced(self, deployment):
        chosen = self._chosen(deployment, "agent.chat-agent")
        doc = deployment.read(USER)
        del doc["configs"][chosen["id"]]  # a hand-edited file
        deployment._write(USER, doc)
        with pytest.raises(pc.ProviderConfigError, match="chosen for agent.chat-agent") as refused:
            pc.resolve_llm(USER, "agent.chat-agent")
        assert refused.value.remedy == {"kind": "llm-config", "agentId": "agent.chat-agent"}

    def test_a_withdrawn_deployment_choice_is_refused(self, deployment, monkeypatch):
        deployment.set_choices(USER, {"agent.chat-agent": "deployment"},
                               choosable=frozenset({"agent.chat-agent"}), deployment_default=True)
        monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "")
        with pytest.raises(pc.ProviderConfigError, match="no longer offers"):
            pc.resolve_llm(USER, "agent.chat-agent")

    def test_a_guest_caller_keeps_its_delegates_on_the_guest_configuration(self, deployment):
        self._chosen(deployment)
        caller = pc.resolve_llm("guest", "agent.dataflow-builder")
        assert caller.source == "guest"
        assert pc.resolve_llm("guest", "agent.node-content-builder", caller=caller) is caller

    def test_a_default_that_names_nothing_is_refused_not_replaced(self, deployment):
        created = _own(deployment)
        deployment.set_default(USER, created["id"])
        doc = deployment.read(USER)
        del doc["configs"][created["id"]]  # a hand-edited file
        deployment._write(USER, doc)
        with pytest.raises(pc.ProviderConfigError, match="no longer exists"):
            pc.resolve_llm(USER)

    def test_an_unreadable_file_is_refused_not_replaced(self, deployment):
        _own(deployment)
        deployment.path(USER).write_text("{broken", encoding="utf-8")
        with pytest.raises(pc.ProviderConfigError, match="unreadable"):
            pc.resolve_llm(USER)

    def test_the_deployment_is_read_at_call_time(self, deployment, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "changed-after-import")
        assert pc.resolve_llm(USER).model == "changed-after-import"


class TestThisCurioInstall:
    def test_it_takes_the_deployments_endpoint_with_the_users_model(self, deployment):
        created = deployment.create(
            USER, {"label": "Here", "endpoint": "deployment", "model": "llama4-large"},
            deployment_offered=True,
        )
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER)
        assert (out.base_url, out.api_key, out.model) == (
            "https://sage.example.edu/v1", "operator-secret-key", "llama4-large",
        )
        assert out.config_id == created["id"]

    def test_an_endpoint_without_a_model_is_still_offered(self, deployment, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "")
        assert pc.deployment_config(USER) is None
        assert pc.deployment_endpoint(USER) == (
            "openai_compatible", "https://sage.example.edu/v1", "operator-secret-key",
        )

    def test_a_withdrawn_endpoint_is_refused(self, deployment, monkeypatch):
        created = deployment.create(
            USER, {"label": "Here", "endpoint": "deployment", "model": "m"},
            deployment_offered=True,
        )
        deployment.set_default(USER, created["id"])
        monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", "")
        monkeypatch.setattr(config, "DEFAULT_LLM_API_KEY", "")
        with pytest.raises(pc.ProviderConfigError, match="no\\s+longer offers"):
            pc.resolve_llm(USER)


class TestKeysStayWithTheirEndpoint:
    def test_a_users_key_never_reaches_the_deployment_host(self, deployment):
        # The OpenAI preset stores OpenAI's own URL. A blank URL would fall
        # through to whatever the server's environment points at, and a
        # custom deployment host would receive the user's OpenAI key.
        created = _own(deployment)
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER)
        assert out.base_url == "https://api.openai.com/v1"
        assert out.base_url != config.DEFAULT_LLM_BASE_URL

    def test_the_operators_key_never_reaches_a_host_a_user_typed(self, deployment):
        created = _own(deployment, baseUrl="https://attacker.example.com/v1", apiKey="")
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER)
        assert out.base_url == "https://attacker.example.com/v1"
        assert out.api_key == ""


class TestGuests:
    def test_a_hosted_guest_runs_on_the_guest_configuration(self, deployment):
        out = pc.resolve_llm("guest", "agent.chat-agent")
        assert (out.base_url, out.api_key, out.model, out.source) == (
            "https://guest.example.edu/v1", "guest-secret-key", "small-model", "guest",
        )

    def test_a_hosted_guest_never_reads_a_configurations_file(self, deployment):
        _own(deployment, user_key="guest")
        deployment.set_default("guest", deployment.list("guest")[0]["id"])
        assert pc.resolve_llm("guest").source == "guest"

    def test_the_guest_configuration_needs_a_key_and_a_model(self, deployment, monkeypatch):
        monkeypatch.setattr(config, "GUEST_LLM_MODEL", "")
        with pytest.raises(pc.ProviderConfigError):
            pc.resolve_llm("guest")
        monkeypatch.setattr(config, "GUEST_LLM_MODEL", "small-model")
        monkeypatch.setattr(config, "GUEST_LLM_API_KEY", "")
        with pytest.raises(pc.ProviderConfigError):
            pc.resolve_llm("guest")

    def test_the_local_guest_owns_its_configurations(self, deployment, monkeypatch):
        monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
        assert pc.resolve_llm("guest").source == "deployment"  # its deployment is GUEST_LLM_*
        assert pc.resolve_llm("guest").model == "small-model"
        created = _own(deployment, user_key="guest")
        deployment.set_default("guest", created["id"])
        assert pc.resolve_llm("guest").config_id == created["id"]

    def test_a_guest_that_is_not_the_shared_one_is_still_a_guest(self, deployment):
        assert pc.resolve_llm("12", guest=True).source == "guest"


class TestWhatARunRecords:
    def test_the_key_is_not_in_the_repr(self):
        config_ = ProviderConfig(api_key="sk-live-abcdefgh", api_type="anthropic", base_url="", model="m")
        assert "sk-live" not in repr(config_)

    def test_the_pin_names_the_configuration_not_the_key(self):
        config_ = ProviderConfig(api_key="sk-live-abcdefgh", api_type="openai_compatible",
                                 base_url="https://api.openai.com/v1?x=1", model="m",
                                 config_id="llm-000000000001", label="Mine", source="default")
        pin = pc.llm_pin(config_)
        assert pin == {"configId": "llm-000000000001", "label": "Mine",
                       "baseUrlHost": "api.openai.com", "source": "default"}

    def test_provider_errors_lose_the_calls_key(self):
        config_ = ProviderConfig(api_key="sk-live-abcdefgh", api_type="anthropic", base_url="", model="m")
        text = pc.redact_error(RuntimeError("401: bad key sk-live-abcdefgh"), config_)
        assert "sk-live-abcdefgh" not in text and "401" in text


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
