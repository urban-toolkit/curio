"""What a chat endpoint can do beyond text, and where the answer comes from.

``chat_capabilities`` answers from the table (Anthropic, Gemini, OpenAI's own
endpoint), from training (a model trained in Curio stays fenced), from the
script (the scripted provider, fenced unless a test says otherwise), or from a
charged trial that asks any other OpenAI-compatible server once per model and
remembers the answer per account. Nothing refuses a run for want of a
capability: ``providerRequirements`` is a preference.
"""

from __future__ import annotations

import types

import pytest

from utk_curio.backend.app.agents import chat_capabilities as cc
from utk_curio.backend.app.agents import ledger, model_catalog, providers, testing_provider
from utk_curio.backend.app.agents.providers import ProviderConfig

USER = "7"

_REAL_PROBE = providers.probe_native_tools


@pytest.fixture(autouse=True)
def _the_trial_runs(monkeypatch, _endpoint_not_asked_about_tools):
    """These tests are about the trial, so it asks the (faked) endpoint."""
    monkeypatch.setattr(providers, "probe_native_tools", _REAL_PROBE)


def _cfg(**kw):
    base = dict(api_key="sk-local-key-0123456789", api_type="openai_compatible",
                base_url="http://localhost:11434/v1", model="llama3", config_id="llm-00000000000a")
    base.update(kw)
    return ProviderConfig(**base)


class _Trial:
    """A fake OpenAI client whose one completion answers the trial."""

    def __init__(self, monkeypatch, *, calls_tool=True, error=None):
        self.requests = []

        def _create(**kwargs):
            self.requests.append(kwargs)
            if error is not None:
                raise error
            message = types.SimpleNamespace(
                content=None if calls_tool else "pong",
                tool_calls=[types.SimpleNamespace(id="c1")] if calls_tool else None,
            )
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=message)],
                usage=types.SimpleNamespace(prompt_tokens=20, completion_tokens=3),
            )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=_create))

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)


class _Refused(Exception):
    status_code = 400


class TestTheTable:
    @pytest.mark.parametrize("config", [
        _cfg(api_type="anthropic", base_url=""),
        _cfg(api_type="gemini", base_url=""),
        _cfg(base_url="https://api.openai.com/v1"),
    ])
    def test_known_apis_take_tools_and_a_reply_schema_without_a_trial(self, tmp_curio, monkeypatch, config):
        trial = _Trial(monkeypatch)
        found = cc.chat_capabilities(config, USER)
        assert (found.tools, found.structured_output, found.source) == (True, True, "table")
        assert found.protocol == "native"
        assert trial.requests == []

    def test_a_model_trained_in_curio_stays_fenced(self, tmp_curio, monkeypatch):
        trial = _Trial(monkeypatch)
        found = cc.chat_capabilities(_cfg(base_url="https://api.openai.com/v1", trained=True), USER)
        assert (found.protocol, found.source) == ("fenced", "trained")
        assert trial.requests == []


class TestTheScript:
    def test_the_scripted_provider_is_fenced_unless_scripted(self, tmp_curio):
        testing_provider.reset()
        assert cc.chat_capabilities(_cfg(api_type="testing"), USER).protocol == "fenced"
        testing_provider.script_chat_capabilities(tools=True)
        assert cc.chat_capabilities(_cfg(api_type="testing"), USER).protocol == "native"
        testing_provider.reset()
        assert cc.chat_capabilities(_cfg(api_type="testing"), USER).protocol == "fenced"


class TestTheTrial:
    def test_a_tool_call_means_native_tools_and_is_remembered(self, tmp_curio, monkeypatch):
        trial = _Trial(monkeypatch, calls_tool=True)
        found = cc.chat_capabilities(_cfg(), USER)
        assert (found.tools, found.structured_output, found.source) == (True, False, "trial")
        (request,) = trial.requests
        assert request["model"] == "llama3" and request["tools"][0]["function"]["name"] == "ping"
        remembered = model_catalog.remembered_chat_capabilities(
            USER, "openai_compatible", "http://localhost:11434/v1", "llama3"
        )
        assert remembered["tools"] is True
        # The trial is charged: its tokens are on the ledger, with the configuration.
        entries = ledger._read_entries(USER, ledger._today())
        (probe,) = [e for e in entries if e.get("note") == "capability-probe"]
        assert probe["usage"]["inputTokens"] == 20 and probe["llmConfigId"] == "llm-00000000000a"

    def test_the_answer_is_reused_until_a_refresh(self, tmp_curio, monkeypatch):
        trial = _Trial(monkeypatch, calls_tool=True)
        cc.chat_capabilities(_cfg(), USER)
        again = cc.chat_capabilities(_cfg(), USER)
        assert again.source == "remembered" and again.tools is True
        assert len(trial.requests) == 1
        cc.chat_capabilities(_cfg(), USER, refresh=True)
        assert len(trial.requests) == 2

    def test_another_model_on_the_same_server_is_asked_on_its_own(self, tmp_curio, monkeypatch):
        trial = _Trial(monkeypatch, calls_tool=True)
        cc.chat_capabilities(_cfg(), USER)
        cc.chat_capabilities(_cfg(model="mistral"), USER)
        assert [r["model"] for r in trial.requests] == ["llama3", "mistral"]

    @pytest.mark.parametrize("outcome", ["refused", "ignored"])
    def test_a_refusal_or_an_ignored_tool_means_the_fenced_protocol(self, tmp_curio, monkeypatch, outcome):
        if outcome == "refused":
            _Trial(monkeypatch, error=_Refused("tools are not supported by this model"))
        else:
            _Trial(monkeypatch, calls_tool=False)
        found = cc.chat_capabilities(_cfg(), USER)
        assert (found.protocol, found.source) == ("fenced", "trial")
        assert model_catalog.remembered_chat_capabilities(
            USER, "openai_compatible", "http://localhost:11434/v1", "llama3"
        )["tools"] is False

    def test_an_endpoint_that_cannot_answer_is_asked_again_next_time(self, tmp_curio, monkeypatch):
        trial = _Trial(monkeypatch, error=ConnectionError("offline"))
        found = cc.chat_capabilities(_cfg(), USER)
        assert (found.protocol, found.source) == ("fenced", "unknown")
        assert "offline" in found.reason
        assert model_catalog.remembered_chat_capabilities(
            USER, "openai_compatible", "http://localhost:11434/v1", "llama3"
        ) is None
        cc.chat_capabilities(_cfg(), USER)
        assert len(trial.requests) == 2

    def test_the_key_never_reaches_the_reason(self, tmp_curio, monkeypatch):
        _Trial(monkeypatch, error=ConnectionError("refused for sk-local-key-0123456789"))
        found = cc.chat_capabilities(_cfg(), USER)
        assert "sk-local-key-0123456789" not in found.reason


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    response = client.post("/api/projects", json=body,
                           headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    assert response.status_code == 201
    return response.get_json()["id"]


class TestItIsAPreference:
    def test_a_built_in_declaring_structured_output_runs_on_a_provider_without_it(
        self, client, user_and_token, tmp_curio, alice_project
    ):
        """Every built-in declares ``structured-output``; the scripted provider
        has none, and a run still answers."""
        from utk_curio.backend.app.agents import builtin

        testing_provider.reset()
        spec = next(s for s in builtin.BUILTIN_AGENTS if s.agent_id == "agent.chat-agent")
        manifest = builtin.get_builtin_manifest(f"{spec.agent_id}@{builtin.BUILTIN_VERSION}")
        assert "structured-output" in manifest.provider_capabilities
        assert cc.chat_capabilities(_cfg(api_type="testing"), USER).structured_output is False

        _, token = user_and_token
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        created = client.post("/api/agents/llm/configs", headers=headers, json={
            "label": "Scripted", "apiType": "testing", "model": "scripted"})
        client.put("/api/agents/llm/default", headers=headers,
                   json={"configId": created.get_json()["config"]["id"]})
        coord = f"agent.chat-agent@{builtin.BUILTIN_VERSION}"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=headers)
        att = client.post(f"/api/agents/projects/{alice_project}/attachments",
                          json={"coord": coord, "target": {"kind": "canvas"}},
                          headers=headers).get_json()["attachmentId"]
        testing_provider.push_reply("Here is my answer.")
        run = client.post(f"/api/agents/projects/{alice_project}/attachments/{att}/run",
                          json={"message": "hi"}, headers=headers)
        assert run.status_code == 200, run.get_json()
        assert run.get_json()["reply"] == "Here is my answer."


class TestCachedInputReachesTheRun:
    def test_a_run_reports_the_providers_cache_counts(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents import builtin

        testing_provider.reset()
        _, token = user_and_token
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        created = client.post("/api/agents/llm/configs", headers=headers, json={
            "label": "Scripted", "apiType": "testing", "model": "scripted"})
        client.put("/api/agents/llm/default", headers=headers,
                   json={"configId": created.get_json()["config"]["id"]})
        coord = f"agent.chat-agent@{builtin.BUILTIN_VERSION}"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=headers)
        att = client.post(f"/api/agents/projects/{alice_project}/attachments",
                          json={"coord": coord, "target": {"kind": "canvas"}},
                          headers=headers).get_json()["attachmentId"]
        testing_provider.push_reply("Cached.", usage={"in": 1000, "out": 20, "cacheRead": 900, "cacheWrite": 0})
        run = client.post(f"/api/agents/projects/{alice_project}/attachments/{att}/run",
                          json={"message": "hi"}, headers=headers).get_json()
        assert run["usage"] == {"inputTokens": 1000, "outputTokens": 20,
                                "cacheReadTokens": 900, "cacheWriteTokens": 0}
