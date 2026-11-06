"""The one resolver, as a table: which LLM configuration answers a run.

``provider_config.resolve_llm`` decides for every run from the account's LLM
configurations (``agents/llm_configs.py``) and the operator's endpoints
(``config.DEFAULT_LLM_ENDPOINTS``, the endpoint file, read at call time):

- a hosted guest runs on the guest configuration, the Deployment default's
  endpoint and model;
- an internal agent on its caller's, always;
- any other agent on the configuration chosen for it;
- with no choice, a delegated agent on its caller's, and an attached one on
  the default configuration, else the Deployment default (the first
  endpoint's first model), else a refusal whose remedy opens API Settings;
- a reference that does not resolve is refused, never replaced.

Two regressions are pinned: a user's key never goes to an operator's host,
and an operator's key never goes to a host a user typed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents.infrastructure import llm_configs
from utk_curio.backend.app.agents.infrastructure import provider_config as pc
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.tests._support import llm_deployment

USER = "7"

#: The operator's two endpoints (fake hosts and keys). The model names
#: ``llama4`` on both is one name on two endpoints, each its own model.
GATEWAY = llm_deployment.endpoint(
    "Gateway", base_url="https://sage.example.edu/v1", api_key="operator-secret-key",
    models=("llama4", "llama4-large"),
)
SECOND = llm_deployment.endpoint(
    "Second", base_url="https://second.example.test/v1", api_key="second-secret-key",
    models=("llama4", "small-model"),
)


@pytest.fixture()
def deployment(monkeypatch, tmp_curio):
    """An operator whose endpoint file names two endpoints."""
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    llm_deployment.offer(monkeypatch, GATEWAY, SECOND)
    return llm_configs.default_store()


def _own(store, user_key=USER, **fields):
    body = {"label": "Mine", "apiType": "openai_compatible",
            "baseUrl": "https://api.openai.com/v1", "apiKey": "user-secret-key",
            "model": "gpt-4o-mini", **fields}
    return store.create(user_key, body)


def _here(store, endpoint_name="Gateway", model="llama4-large", label="Here", user_key=USER):
    """A This Curio install configuration, saved as the route saves one."""
    return store.create(
        user_key, {"label": label, "endpoint": "deployment", "endpointName": endpoint_name, "model": model},
        offered_endpoints=pc.deployment_endpoints(),
    )


class TestTheFallbackOrder:
    def test_the_default_configuration_answers(self, deployment):
        created = _own(deployment)
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER, "agent.curio.researcher")
        assert (out.api_type, out.base_url, out.api_key, out.model) == (
            "openai_compatible", "https://api.openai.com/v1", "user-secret-key", "gpt-4o-mini",
        )
        assert (out.config_id, out.label, out.source) == (created["id"], "Mine", "default")

    def test_no_default_is_the_deployment_default(self, deployment):
        _own(deployment)  # a configuration that is not the default changes nothing
        out = pc.resolve_llm(USER)
        # The first endpoint's first model.
        assert (out.base_url, out.api_key, out.model) == (
            "https://sage.example.edu/v1", "operator-secret-key", "llama4",
        )
        assert (out.config_id, out.source, out.label) == (None, "deployment", "Deployment default")

    def test_nothing_configured_is_a_refusal_with_a_remedy(self, deployment, monkeypatch):
        llm_deployment.withdraw(monkeypatch)
        with pytest.raises(pc.ProviderConfigError) as refused:
            pc.resolve_llm(USER, "agent.curio.researcher")
        assert "API Settings" in str(refused.value)
        assert refused.value.remedy == {"kind": "llm-config", "agentId": "agent.curio.researcher"}

    def test_an_unchosen_delegate_answers_with_its_callers(self, deployment):
        caller = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="claude",
                                config_id="llm-00000000000a", label="Caller", source="default")
        out = pc.resolve_llm(USER, "agent.curio.node-builder", caller=caller)
        assert (out.api_key, out.model, out.config_id, out.label) == ("k", "claude", "llm-00000000000a", "Caller")
        assert out.source == "caller"


class TestAChoicePerAgent:
    def _chosen(self, store, agent_id="agent.curio.node-builder", **fields):
        created = _own(store, label=fields.pop("label", "Chosen"), model=fields.pop("model", "chosen-model"), **fields)
        store.set_choices(USER, {agent_id: created["id"]},
                          choosable=frozenset({agent_id}), deployment_default=True)
        return created

    def test_an_attached_agent_runs_on_its_choice_over_the_default(self, deployment):
        default = _own(deployment, label="Default")
        deployment.set_default(USER, default["id"])
        chosen = self._chosen(deployment, "agent.curio.researcher")
        out = pc.resolve_llm(USER, "agent.curio.researcher")
        assert (out.config_id, out.model, out.source) == (chosen["id"], "chosen-model", "assigned")
        # Another agent still follows the default.
        assert pc.resolve_llm(USER, "agent.curio.dataflow-builder").config_id == default["id"]

    def test_a_delegate_runs_on_its_own_choice_not_its_callers(self, deployment):
        chosen = self._chosen(deployment)
        caller = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="claude",
                                source="default")
        out = pc.resolve_llm(USER, "agent.curio.node-builder", caller=caller)
        assert (out.config_id, out.api_key, out.source) == (chosen["id"], "user-secret-key", "assigned")

    def test_an_internal_agent_always_runs_on_its_callers(self, deployment):
        # A choice cannot be written for one; a hand-edited file is ignored.
        created = _own(deployment, label="Planner")
        doc = deployment.read(USER)
        doc["agents"]["agent.curio.dataflow-planner"] = created["id"]
        deployment._write(USER, doc)
        caller = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="claude",
                                source="assigned")
        out = pc.resolve_llm(USER, "agent.curio.dataflow-planner", caller=caller)
        assert (out.api_key, out.model, out.source) == ("k", "claude", "caller")

    def test_the_deployment_default_can_be_chosen(self, deployment):
        deployment.set_choices(USER, {"agent.curio.researcher": "deployment"},
                               choosable=frozenset({"agent.curio.researcher"}), deployment_default=True)
        out = pc.resolve_llm(USER, "agent.curio.researcher")
        assert (out.model, out.source, out.label) == ("llama4", "assigned", "Deployment default")

    def test_a_choice_that_names_nothing_is_refused_not_replaced(self, deployment):
        chosen = self._chosen(deployment, "agent.curio.researcher")
        doc = deployment.read(USER)
        del doc["configs"][chosen["id"]]  # a hand-edited file
        deployment._write(USER, doc)
        with pytest.raises(pc.ProviderConfigError, match="chosen for agent.curio.researcher") as refused:
            pc.resolve_llm(USER, "agent.curio.researcher")
        assert refused.value.remedy == {"kind": "llm-config", "agentId": "agent.curio.researcher"}

    def test_a_withdrawn_deployment_choice_is_refused(self, deployment, monkeypatch):
        deployment.set_choices(USER, {"agent.curio.researcher": "deployment"},
                               choosable=frozenset({"agent.curio.researcher"}), deployment_default=True)
        llm_deployment.withdraw(monkeypatch)
        with pytest.raises(pc.ProviderConfigError, match="no longer offers"):
            pc.resolve_llm(USER, "agent.curio.researcher")

    def test_a_guest_caller_keeps_its_delegates_on_the_guest_configuration(self, deployment):
        self._chosen(deployment)
        caller = pc.resolve_llm("guest", "agent.curio.dataflow-builder")
        assert caller.source == "guest"
        assert pc.resolve_llm("guest", "agent.curio.node-builder", caller=caller) is caller

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
        llm_deployment.change_first(monkeypatch, models=("changed-after-import",))
        assert pc.resolve_llm(USER).model == "changed-after-import"


class TestThisCurioInstall:
    def test_it_takes_the_endpoints_url_and_key_with_the_users_model(self, deployment):
        created = _here(deployment, "Gateway", "llama4-large")
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER)
        assert (out.base_url, out.api_key, out.model) == (
            "https://sage.example.edu/v1", "operator-secret-key", "llama4-large",
        )
        assert (out.config_id, out.on_deployment) == (created["id"], True)

    def test_a_configuration_on_the_second_endpoint_answers_on_its_key(self, deployment):
        created = _here(deployment, "Second", "small-model")
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER)
        assert (out.base_url, out.api_key, out.model) == (
            "https://second.example.test/v1", "second-secret-key", "small-model",
        )

    def test_a_model_name_on_two_endpoints_runs_on_the_one_chosen(self, deployment):
        on_gateway = _here(deployment, "Gateway", "llama4", label="On the gateway")
        on_second = _here(deployment, "Second", "llama4", label="On the second")
        deployment.set_default(USER, on_second["id"])
        assert (pc.resolve_llm(USER).base_url, pc.resolve_llm(USER).api_key) == (
            "https://second.example.test/v1", "second-secret-key",
        )
        deployment.set_default(USER, on_gateway["id"])
        assert (pc.resolve_llm(USER).base_url, pc.resolve_llm(USER).api_key) == (
            "https://sage.example.edu/v1", "operator-secret-key",
        )

    def test_a_withdrawn_endpoint_file_is_refused(self, deployment, monkeypatch):
        created = _here(deployment)
        deployment.set_default(USER, created["id"])
        llm_deployment.withdraw(monkeypatch)
        with pytest.raises(pc.ProviderConfigError, match="no\\s+longer offers"):
            pc.resolve_llm(USER)

    def test_a_model_that_left_its_endpoints_list_is_refused_not_replaced(self, deployment, monkeypatch):
        created = _here(deployment, "Gateway", "llama4-large")
        deployment.set_default(USER, created["id"])
        llm_deployment.change_first(monkeypatch, models=("llama4",))
        with pytest.raises(pc.ProviderConfigError) as refused:
            pc.resolve_llm(USER, "agent.curio.researcher")
        assert str(refused.value) == pc.offered_refusal("Gateway", "llama4-large")
        assert str(refused.value) == (
            "'llama4-large' is not a model of 'Gateway' on this Curio install, which offers "
            "Gateway: llama4; Second: llama4, small-model."
        )
        assert refused.value.remedy == {"kind": "llm-config", "agentId": "agent.curio.researcher"}

    def test_an_endpoint_the_file_no_longer_names_is_refused_not_replaced(self, deployment, monkeypatch):
        created = _here(deployment, "Second", "small-model")
        deployment.set_default(USER, created["id"])
        llm_deployment.offer(monkeypatch, GATEWAY)
        with pytest.raises(pc.ProviderConfigError) as refused:
            pc.resolve_llm(USER)
        assert str(refused.value) == (
            "This Curio install has no endpoint 'Second'; it offers Gateway: llama4, llama4-large."
        )

    @pytest.mark.parametrize("endpoint_name, model, fragment", [
        ("Elsewhere", "llama4", "has no endpoint 'Elsewhere'"),
        ("Gateway", "small-model", "'small-model' is not a model of 'Gateway'"),
        ("", "llama4", "names one of its endpoints"),
    ])
    def test_a_save_outside_the_file_is_refused_with_the_same_sentence(
        self, deployment, endpoint_name, model, fragment,
    ):
        with pytest.raises(llm_configs.LlmConfigError) as refused:
            _here(deployment, endpoint_name, model)
        assert fragment in str(refused.value)
        assert str(refused.value) == pc.offered_refusal(endpoint_name, model)
        assert deployment.list(USER) == []


class TestKeysStayWithTheirEndpoint:
    def test_a_users_key_never_reaches_the_deployment_host(self, deployment):
        # The OpenAI preset stores OpenAI's own URL. A blank URL would fall
        # through to whatever the server's environment points at, and a
        # custom deployment host would receive the user's OpenAI key.
        created = _own(deployment)
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER)
        assert out.base_url == "https://api.openai.com/v1"
        assert out.base_url not in {endpoint.base_url for endpoint in config.DEFAULT_LLM_ENDPOINTS}

    def test_the_operators_key_never_reaches_a_host_a_user_typed(self, deployment):
        created = _own(deployment, baseUrl="https://attacker.example.com/v1", apiKey="")
        deployment.set_default(USER, created["id"])
        out = pc.resolve_llm(USER)
        assert out.base_url == "https://attacker.example.com/v1"
        assert out.api_key == ""


class TestGuests:
    def test_a_hosted_guest_runs_on_the_deployment_default(self, deployment):
        out = pc.resolve_llm("guest", "agent.curio.researcher")
        assert (out.base_url, out.api_key, out.model, out.source, out.label) == (
            "https://sage.example.edu/v1", "operator-secret-key", "llama4", "guest", "Guest configuration",
        )

    def test_a_hosted_guest_never_reads_a_configurations_file(self, deployment):
        _own(deployment, user_key="guest")
        deployment.set_default("guest", deployment.list("guest")[0]["id"])
        assert pc.resolve_llm("guest").source == "guest"

    def test_without_an_endpoint_file_guests_get_no_ai(self, deployment, monkeypatch):
        llm_deployment.withdraw(monkeypatch)
        with pytest.raises(pc.ProviderConfigError, match="not available for guest users"):
            pc.resolve_llm("guest")

    def test_the_local_guest_owns_its_configurations(self, deployment, monkeypatch):
        monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
        assert pc.resolve_llm("guest").source == "deployment"  # its default is everyone's
        assert pc.resolve_llm("guest").model == "llama4"
        created = _own(deployment, user_key="guest")
        deployment.set_default("guest", created["id"])
        assert pc.resolve_llm("guest").config_id == created["id"]

    def test_a_guest_that_is_not_the_shared_one_is_still_a_guest(self, deployment):
        assert pc.resolve_llm("12", guest=True).source == "guest"


class TestWhatARunRecords:
    def test_the_key_is_not_in_the_repr(self):
        config_ = ProviderConfig(api_key="sk-live-abcdefgh", api_type="anthropic", base_url="", model="m")
        assert "sk-live" not in repr(config_)

    def test_the_url_is_not_in_the_repr(self):
        config_ = ProviderConfig(api_key="k", api_type="openai_compatible",
                                 base_url="https://llm.example.test/v1", model="m")
        assert "llm.example.test" not in repr(config_)
        assert "operator-secret-key" not in repr(GATEWAY) and "sage.example.edu" not in repr(GATEWAY)

    def test_the_pin_names_the_configuration_not_the_key(self):
        config_ = ProviderConfig(api_key="sk-live-abcdefgh", api_type="openai_compatible",
                                 base_url="https://api.openai.com/v1?x=1", model="m",
                                 config_id="llm-000000000001", label="Mine", source="default")
        pin = pc.llm_pin(config_)
        assert pin == {"configId": "llm-000000000001", "label": "Mine",
                       "baseUrlHost": "api.openai.com", "source": "default"}

    def test_a_pin_on_this_curios_endpoints_names_no_host(self, deployment):
        created = _here(deployment, "Second", "small-model")
        deployment.set_default(USER, created["id"])
        for config_ in (pc.resolve_llm(USER), pc.deployment_config(USER), pc.resolve_llm("guest")):
            pin, answers = pc.llm_pin(config_), pc._answers(config_)
            assert pin["baseUrlHost"] == "" and answers["baseUrlHost"] == "", (pin, answers)
            text = repr((pin, answers))
            assert "sage.example.edu" not in text and "second.example.test" not in text
        payload = pc._deployment_payload(USER, False)
        assert payload == {
            "label": "Deployment default", "endpointOffered": True, "apiType": "openai_compatible",
            "model": "llama4", "endpoints": [
                {"name": "Gateway", "models": ["llama4", "llama4-large"]},
                {"name": "Second", "models": ["llama4", "small-model"]},
            ],
        }
        assert "example" not in repr(payload) and "secret" not in repr(payload)

    def test_provider_errors_lose_the_calls_key(self):
        config_ = ProviderConfig(api_key="sk-live-abcdefgh", api_type="anthropic", base_url="", model="m")
        text = pc.redact_error(RuntimeError("401: bad key sk-live-abcdefgh"), config_)
        assert "sk-live-abcdefgh" not in text and "401" in text

    def test_provider_errors_lose_every_endpoint_of_this_curio(self, deployment):
        """Each endpoint's URL, host and port, host and key, whichever
        configuration made the call, in both redactors."""
        from utk_curio.backend.app.agents.infrastructure import providers

        error = RuntimeError(
            "Connection error: HTTPSConnectionPool(host='sage.example.edu', port=443): "
            "Max retries exceeded with url https://sage.example.edu/v1/chat/completions "
            "(sage.example.edu:443, key operator-secret-key); also https://second.example.test/v1 "
            "at second.example.test with second-secret-key"
        )
        own = ProviderConfig(api_key="user-secret-key", api_type="openai_compatible",
                             base_url="https://api.openai.com/v1", model="m")
        for config_ in (pc.resolve_llm(USER), own, None):
            for text in (pc.redact_error(error, config_), providers.redacted_text(error, config_)):
                for value in ("sage.example.edu", "second.example.test", "operator-secret-key",
                              "second-secret-key"):
                    assert value not in text, text
                assert "Connection error" in text and "/chat/completions" in text, text
        assert "sage.example.edu" not in providers._redacted(error, own)

    def test_a_short_host_is_taken_out_too(self, deployment, monkeypatch):
        llm_deployment.change_first(monkeypatch, base_url="http://gw7:8080/v1")
        text = pc.redact_error(RuntimeError("HTTPConnectionPool(host='gw7', port=8080) at gw7:8080"), None)
        assert "gw7" not in text and "port=8080" in text, text

    def test_a_users_own_host_stays_in_its_errors(self, deployment):
        own = ProviderConfig(api_key="user-secret-key", api_type="openai_compatible",
                             base_url="https://api.openai.com/v1", model="m")
        text = pc.redact_error(RuntimeError("could not reach api.openai.com"), own)
        assert "api.openai.com" in text


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
