"""LLM configurations: the store, its routes, and what never leaves the server.

Covers ``agents/llm_configs.py`` and the ``/api/agents/llm`` routes:

- the file is owner-only and a failed write leaves nothing behind;
- no response carries a key, and a key never follows its configuration to
  another endpoint;
- the validation matrix, duplicate, delete and the default;
- a hosted guest reads the guest configuration and writes nothing, while the
  local guest owns its configurations;
- the model listing borrows a stored key only for that key's own endpoint;
- the configuration chosen per agent: which agents may have one, what the
  listing says each answers with, and a delete moving agents in one write;
- this Curio's own models (the endpoint file): picked as the default or for an
  agent, never configured, and a configuration on this Curio's endpoint
  refused on every write and dropped when the file is read.
"""

from __future__ import annotations

import dataclasses
import json
import os
import stat
from unittest.mock import patch

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents.infrastructure import llm_configs
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support import llm_deployment

KEY = "sk-user-secret-0123456789"
BASE = "/api/agents/llm"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _create(client, token, **fields):
    body = {"label": "OpenAI", "apiType": "openai_compatible",
            "baseUrl": "https://api.openai.com/v1", "apiKey": KEY, "model": "gpt-4o-mini", **fields}
    return client.post(f"{BASE}/configs", json=body, headers=_auth(token))


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    response = client.post("/api/projects", json=body, headers=_auth(token))
    assert response.status_code == 201
    return response.get_json()["id"]


def _shared_guest(db, token="shared-guest-token"):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest", is_guest=True)
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user, token


class TestTheFile:
    def test_it_is_owner_only(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        assert _create(client, token).status_code == 201
        path = llm_configs.default_store().path(_user_dir_key(user))
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
        assert not [p for p in path.parent.iterdir() if p.name.endswith(".tmp")]

    def test_a_failed_write_leaves_nothing_behind(self, tmp_curio):
        store = llm_configs.LlmConfigStore()
        with patch("utk_curio.backend.app.common.owner_only_file.os.replace",
                   side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                store.create("7", {"label": "A", "apiType": "anthropic", "apiKey": KEY,
                                   "model": "claude"})
        directory = store.path("7").parent
        assert not store.path("7").exists()
        assert not [p for p in directory.iterdir() if p.name.endswith(".tmp")]


class TestNoResponseCarriesAKey:
    def test_listing_create_update_and_duplicate(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        created = _create(client, token)
        config_id = created.get_json()["config"]["id"]
        responses = [
            created,
            client.patch(f"{BASE}/configs/{config_id}", json={"model": "gpt-4o"}, headers=_auth(token)),
            client.post(f"{BASE}/configs/{config_id}/duplicate", json={}, headers=_auth(token)),
            client.put(f"{BASE}/default", json={"configId": config_id}, headers=_auth(token)),
            client.get(BASE, headers=_auth(token)),
        ]
        for response in responses:
            assert response.status_code in (200, 201), response.get_json()
            assert KEY not in response.get_data(as_text=True)
        listing = responses[-1].get_json()
        assert all(c["hasApiKey"] for c in listing["configs"])
        assert listing["configs"][0]["baseUrlHost"] == "api.openai.com"

    def test_the_shown_host_carries_no_path_and_no_key(self):
        shown = llm_configs.base_url_host(
            "https://api.example.com/v1?api_key=sk-secret-value-1234", "openai_compatible"
        )
        assert shown == "api.example.com"
        assert llm_configs.base_url_host("http://192.168.1.9:11434/v1") == "192.168.1.9:11434"
        assert llm_configs.base_url_host("localhost:8000/v1") == "localhost:8000"

    def test_an_endpoint_with_no_base_url_is_named_by_kind(self):
        assert llm_configs.base_url_host("", "openai_compatible") == (
            "the default openai_compatible endpoint"
        )
        assert llm_configs.base_url_host("", "") == ""


class TestKeysStayWithTheirEndpoint:
    def _id(self, client, token, **fields):
        return _create(client, token, **fields).get_json()["config"]["id"]

    def test_a_blank_key_keeps_the_stored_one(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        config_id = self._id(client, token)
        client.patch(f"{BASE}/configs/{config_id}", json={"apiKey": "", "label": "Renamed"},
                     headers=_auth(token))
        record = llm_configs.default_store().record(_user_dir_key(user), config_id)
        assert record["apiKey"] == KEY and record["label"] == "Renamed"

    def test_a_new_host_needs_the_key_again(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        config_id = self._id(client, token)
        moved = client.patch(f"{BASE}/configs/{config_id}",
                             json={"baseUrl": "https://elsewhere.example.com/v1"}, headers=_auth(token))
        assert moved.status_code == 400
        assert "key again" in moved.get_json()["error"]
        with_key = client.patch(f"{BASE}/configs/{config_id}",
                                json={"baseUrl": "https://elsewhere.example.com/v1", "apiKey": "sk-new-key-0000"},
                                headers=_auth(token))
        assert with_key.status_code == 200
        assert llm_configs.default_store().record(_user_dir_key(user), config_id)["apiKey"] == "sk-new-key-0000"

    def test_moving_to_a_keyless_endpoint_drops_the_key(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        config_id = self._id(client, token)
        moved = client.patch(f"{BASE}/configs/{config_id}",
                             json={"baseUrl": "http://localhost:11434/v1", "clearApiKey": True},
                             headers=_auth(token))
        assert moved.status_code == 200 and moved.get_json()["config"]["hasApiKey"] is False
        record = llm_configs.default_store().record(_user_dir_key(user), config_id)
        assert record["baseUrl"] == "http://localhost:11434/v1" and not record.get("apiKey")

    def test_a_new_path_on_the_same_host_keeps_the_key(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        config_id = self._id(client, token)
        same_host = client.patch(f"{BASE}/configs/{config_id}",
                                 json={"baseUrl": "https://api.openai.com/v2"}, headers=_auth(token))
        assert same_host.status_code == 200

    def test_another_provider_type_needs_the_key_again(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        config_id = self._id(client, token)
        changed = client.patch(f"{BASE}/configs/{config_id}",
                               json={"apiType": "anthropic", "baseUrl": ""}, headers=_auth(token))
        assert changed.status_code == 400

    def test_clearing_the_key(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        config_id = self._id(client, token, baseUrl="http://localhost:11434/v1")
        cleared = client.patch(f"{BASE}/configs/{config_id}", json={"clearApiKey": True},
                               headers=_auth(token))
        assert cleared.status_code == 200 and cleared.get_json()["config"]["hasApiKey"] is False
        anthropic = self._id(client, token, label="Claude", apiType="anthropic", baseUrl="", model="claude")
        refused = client.patch(f"{BASE}/configs/{anthropic}", json={"clearApiKey": True}, headers=_auth(token))
        assert refused.status_code == 400


class TestValidation:
    @pytest.mark.parametrize("fields, fragment", [
        ({"colour": "red"}, "unknown field"),
        ({"label": ""}, "label is required"),
        ({"model": " "}, "model is required"),
        ({"apiType": "mistral"}, "apiType must be one of"),
        ({"baseUrl": ""}, "needs its base URL"),
        ({"baseUrl": "ftp://api.example.com"}, "http(s)"),
        ({"baseUrl": "https://user:pw@api.example.com/v1"}, "user name or password"),
        ({"baseUrl": "https://api.example.com/v1?key=abc"}, "query or a fragment"),
        ({"baseUrl": "https://api.example.com/v1#frag"}, "query or a fragment"),
        ({"apiType": "anthropic", "baseUrl": "https://api.anthropic.com"}, "takes no base URL"),
        ({"apiType": "gemini", "baseUrl": "", "apiKey": ""}, "needs its API key"),
        ({"apiKey": "two\nlines"}, "one line"),
        ({"apiKey": "k" * 4097}, "longer than 4096"),
        ({"endpoint": "deployment"}, llm_configs.DEPLOYMENT_REFUSAL),
        ({"endpoint": "elsewhere"}, "endpoint must be 'own'"),
        ({"endpointName": "Test gateway"}, "unknown field(s): endpointName"),
    ])
    def test_a_bad_configuration_is_refused(self, client, user_and_token, tmp_curio, fields, fragment):
        _, token = user_and_token
        response = _create(client, token, **fields)
        assert response.status_code == 400, response.get_json()
        assert fragment in response.get_json()["error"]

    def test_labels_are_unique_ignoring_case(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        assert _create(client, token, label="Work").status_code == 201
        again = _create(client, token, label="WORK")
        assert again.status_code == 400 and "already labelled" in again.get_json()["error"]

    def test_an_openai_compatible_endpoint_may_be_keyless(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        response = _create(client, token, baseUrl="http://localhost:11434/v1", apiKey="", model="llama3")
        assert response.status_code == 201
        assert response.get_json()["config"]["hasApiKey"] is False

    def test_an_account_holds_at_most_32(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        for n in range(llm_configs.MAX_CONFIGS_PER_USER):
            assert _create(client, token, label=f"C{n}").status_code == 201
        over = _create(client, token, label="One too many")
        assert over.status_code == 400 and "at most" in over.get_json()["error"]

    def test_the_scripted_provider_is_accepted_only_while_it_is_enabled(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        body = {"label": "Scripted", "apiType": "testing", "model": "scripted"}
        assert client.post(f"{BASE}/configs", json=body, headers=_auth(token)).status_code == 201
        with patch('utk_curio.backend.app.agents.infrastructure.testing_provider.enabled', return_value=False):
            body["label"] = "Scripted 2"
            refused = client.post(f"{BASE}/configs", json=body, headers=_auth(token))
        assert refused.status_code == 400

    @pytest.mark.parametrize("offered", [True, False], ids=["with-the-file", "without-the-file"])
    def test_a_configuration_on_this_curios_endpoint_is_refused_on_create_and_edit(
        self, client, user_and_token, tmp_curio, monkeypatch, offered,
    ):
        """One sentence, whatever else the body says: Curio's models are
        picked, never configured."""
        user, token = user_and_token
        if not offered:
            llm_deployment.withdraw(monkeypatch)
        own = _create(client, token).get_json()["config"]
        before = llm_configs.default_store().read(_user_dir_key(user))
        for body in (
            {"label": "Here", "endpoint": "deployment", "endpointName": "Test gateway", "model": "test-model"},
            {"label": "Here", "endpoint": "deployment", "model": "test-model"},
        ):
            created = client.post(f"{BASE}/configs", json=body, headers=_auth(token))
            assert (created.status_code, created.get_json()["error"]) == (400, llm_configs.DEPLOYMENT_REFUSAL)
        for body in ({"endpoint": "deployment"}, {"endpoint": "deployment", "endpointName": "Test gateway"}):
            edited = client.patch(f"{BASE}/configs/{own['id']}", json=body, headers=_auth(token))
            assert (edited.status_code, edited.get_json()["error"]) == (400, llm_configs.DEPLOYMENT_REFUSAL)
        # Nothing was written, and the own configuration is as it was.
        assert llm_configs.default_store().read(_user_dir_key(user)) == before
        # "own" is still what a configuration says it is.
        assert client.patch(f"{BASE}/configs/{own['id']}", json={"endpoint": "own", "model": "gpt-4o"},
                            headers=_auth(token)).status_code == 200


class TestDuplicateDeleteAndDefault:
    def test_duplicate_copies_the_key_server_side(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        source = _create(client, token).get_json()["config"]
        copy = client.post(f"{BASE}/configs/{source['id']}/duplicate", json={"model": "gpt-4o"},
                           headers=_auth(token)).get_json()["config"]
        assert copy["id"] != source["id"]
        assert copy["label"] == "OpenAI copy" and copy["model"] == "gpt-4o" and "origin" not in copy
        assert llm_configs.default_store().record(_user_dir_key(user), copy["id"])["apiKey"] == KEY

    def test_deleting_the_default_resets_it(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        config_id = _create(client, token).get_json()["config"]["id"]
        client.put(f"{BASE}/default", json={"configId": config_id}, headers=_auth(token))
        removed = client.delete(f"{BASE}/configs/{config_id}", headers=_auth(token)).get_json()
        assert removed == {"deleted": config_id, "moved": [], "default": None}
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert listing["default"] is None and listing["active"]["source"] == "deployment"

    def test_the_default_is_an_id_or_null(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        config_id = _create(client, token).get_json()["config"]["id"]
        chosen = client.put(f"{BASE}/default", json={"configId": config_id}, headers=_auth(token)).get_json()
        assert chosen["default"] == config_id and chosen["active"]["configId"] == config_id
        assert client.put(f"{BASE}/default", json={"configId": "llm-000000000000"},
                          headers=_auth(token)).status_code == 404
        unset = client.put(f"{BASE}/default", json={"configId": None}, headers=_auth(token)).get_json()
        assert unset["default"] is None

    def test_the_listing_says_what_the_deployment_offers(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        response = client.get(BASE, headers=_auth(token))
        listing = response.get_json()
        # Its endpoints' names and models, never a host or a key.
        assert listing["deployment"] == {
            "label": "Curio's default", "apiType": "openai_compatible",
            "model": "test-model", "endpoints": [{"name": "Test gateway", "models": ["test-model"]}],
        }
        assert "test-key" not in response.get_data(as_text=True)
        assert "127.0.0.1" not in response.get_data(as_text=True)
        assert listing["editable"] is True and listing["shared"] is False
        assert listing["active"]["source"] == "deployment"
        assert listing["active"]["baseUrlHost"] == ""


class TestGuests:
    def test_a_hosted_guest_reads_the_guest_configuration_and_writes_nothing(self, client, db, tmp_curio, monkeypatch):
        user, token = _shared_guest(db)
        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
        # A file left under the guest's key (by a local launch) is never read.
        store = llm_configs.default_store()
        store.create("guest", {"label": "Left over", "apiType": "anthropic", "apiKey": KEY,
                               "model": "claude"})
        response = client.get(BASE, headers=_auth(token))
        listing = response.get_json()
        assert listing["configs"] == [] and listing["editable"] is False and "guest" in listing["reason"]
        # The guest configuration is the Deployment default's endpoint and
        # model, whose host never reaches the page.
        assert listing["active"] == {
            "source": "guest", "configId": None, "label": "Guest configuration", "model": "test-model",
            "apiType": "openai_compatible", "baseUrlHost": "",
        }
        assert "127.0.0.1" not in response.get_data(as_text=True)
        # It sees this Curio's endpoints by name, and picks none of them.
        assert listing["deployment"]["endpoints"] == [{"name": "Test gateway", "models": ["test-model"]}]
        assert _create(client, token).status_code == 403
        assert client.put(f"{BASE}/default", json={"configId": None}, headers=_auth(token)).status_code == 403
        pick = llm_configs.pick_choice("Test gateway", "test-model")
        assert client.put(f"{BASE}/default", json={"configId": pick}, headers=_auth(token)).status_code == 403
        assert client.get(BASE, headers=_auth(token)).get_json()["active"]["source"] == "guest"

    def test_the_local_guest_owns_its_configurations(self, client, db, tmp_curio, monkeypatch):
        _, token = _shared_guest(db)
        monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
        assert _create(client, token).status_code == 201
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert listing["editable"] is True and listing["shared"] is True
        assert len(listing["configs"]) == 1


#: The catalog cards (M4's pinned set in test_builtin), which are exactly the
#: built-ins whose configuration can be chosen.
_CARDS = {
    "agent.curio.dataflow-builder", "agent.curio.dataset-finder", "agent.curio.node-builder",
    "agent.curio.researcher",
}


class TestAChoicePerAgent:
    def _choose(self, client, token, body):
        return client.put(f"{BASE}/assignments", json=body, headers=_auth(token))

    def test_the_cards_are_the_choosable_built_ins(self, client, user_and_token, tmp_curio):
        from utk_curio.backend.app.agents.domain import builtin

        _, token = user_and_token
        listing = client.get(BASE, headers=_auth(token)).get_json()
        ids = {row["id"] for row in listing["agents"]}
        assert ids == _CARDS
        assert not ids & builtin.internal_agent_ids()
        builder = next(row for row in listing["agents"] if row["id"] == "agent.curio.dataflow-builder")
        assert builder["name"] == "Dataflow Builder" and builder["choice"] is None
        # With no choice and no default, Curio's default answers it.
        assert builder["answers"]["source"] == "deployment"

    def test_a_choice_is_saved_listed_and_answers(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        config_id = _create(client, token).get_json()["config"]["id"]
        chosen = self._choose(client, token, {"agent.curio.node-builder": config_id})
        assert chosen.status_code == 200, chosen.get_json()
        listing = chosen.get_json()
        assert listing["assignments"] == {"agent.curio.node-builder": config_id}
        row = next(r for r in listing["agents"] if r["id"] == "agent.curio.node-builder")
        assert row["choice"] == config_id
        assert (row["answers"]["source"], row["answers"]["configId"]) == ("assigned", config_id)
        assert KEY not in chosen.get_data(as_text=True)
        # null clears it, and the agent follows its rules again.
        cleared = self._choose(client, token, {"agent.curio.node-builder": None}).get_json()
        assert cleared["assignments"] == {}

    def test_curios_default_is_choosable_only_while_there_is_one(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        _, token = user_and_token
        assert self._choose(client, token, {"agent.curio.dataset-finder": "deployment"}).status_code == 200
        llm_deployment.withdraw(monkeypatch)
        refused = self._choose(client, token, {"agent.curio.researcher": "deployment"})
        assert (refused.status_code, refused.get_json()["error"]) == (400, "This Curio offers no models of its own.")

    @pytest.mark.parametrize("body, status, fragment", [
        ({"agent.curio.dataflow-planner": None}, 400, "not an agent whose model you can choose"),
        ({"agent.test.no-such-agent": None}, 400, "not an agent whose model you can choose"),
        ({"agent.curio.dataset-finder": "llm-000000000000"}, 404, "no LLM configuration"),
    ])
    def test_a_bad_choice_is_refused_and_nothing_is_written(
        self, client, user_and_token, tmp_curio, body, status, fragment
    ):
        user, token = user_and_token
        config_id = _create(client, token).get_json()["config"]["id"]
        # A valid entry beside the bad one is not written either.
        refused = self._choose(client, token, {"agent.curio.researcher": config_id, **body})
        assert refused.status_code == status and fragment in refused.get_json()["error"]
        assert llm_configs.default_store().choices(_user_dir_key(user)) == {}

    def test_an_empty_map_is_refused(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        refused = self._choose(client, token, {})
        assert refused.status_code == 400 and "send" in refused.get_json()["error"]

    def test_an_imported_agent_is_choosable(self, client, user_and_token, tmp_curio, monkeypatch):
        # The route reads the facade (memo dev/142 B5), so that is the attribute to intercept.
        from utk_curio.backend.app.agents import service as services

        _, token = user_and_token
        original = services.choosable_agents
        monkeypatch.setattr(services, "choosable_agents", lambda user_key: [
            *original(user_key), {"id": "agent.test.my-own", "name": "My Own", "category": "chat"},
        ])
        config_id = _create(client, token).get_json()["config"]["id"]
        assert self._choose(client, token, {"agent.test.my-own": config_id}).status_code == 200

    def test_deleting_a_configuration_moves_its_agents_in_the_same_write(
        self, client, user_and_token, tmp_curio
    ):
        user, token = user_and_token
        keep = _create(client, token, label="Keep").get_json()["config"]["id"]
        gone = _create(client, token, label="Gone").get_json()["config"]["id"]
        self._choose(client, token, {
            "agent.curio.node-builder": gone, "agent.curio.dataset-finder": gone, "agent.curio.researcher": keep,
        })
        deleted = client.delete(f"{BASE}/configs/{gone}", headers=_auth(token)).get_json()
        assert deleted["moved"] == ["agent.curio.dataset-finder", "agent.curio.node-builder"]
        assert llm_configs.default_store().choices(_user_dir_key(user)) == {"agent.curio.researcher": keep}

    def test_a_hosted_guest_chooses_nothing(self, client, db, tmp_curio, monkeypatch):
        _, token = _shared_guest(db)
        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert listing["agents"] == [] and listing["assignments"] == {}
        assert self._choose(client, token, {"agent.curio.researcher": None}).status_code == 403


class TestModelListing:
    def _capture(self, monkeypatch):
        seen = []

        def _fake(config_):
            seen.append(config_)
            return ["m1"]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.list_provider_models', _fake)
        return seen

    def test_a_named_configuration_lends_its_key_to_its_own_endpoint_only(self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        seen = self._capture(monkeypatch)
        config_id = _create(client, token).get_json()["config"]["id"]
        client.post("/api/agents/provider-models", json={"configId": config_id}, headers=_auth(token))
        assert (seen[-1].base_url, seen[-1].api_key) == ("https://api.openai.com/v1", KEY)
        client.post("/api/agents/provider-models",
                    json={"configId": config_id, "apiType": "openai_compatible",
                          "baseUrl": "https://elsewhere.example.com/v1"}, headers=_auth(token))
        assert (seen[-1].base_url, seen[-1].api_key) == ("https://elsewhere.example.com/v1", "")

    def test_the_deployments_endpoint_is_never_asked_and_its_key_never_lent(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """Its models are the file's, which the listing names: asking about
        this Curio's endpoint is refused, and asks no one."""
        _, token = user_and_token
        seen = self._capture(monkeypatch)
        for body in (
            {"endpoint": "deployment", "endpointName": "Test gateway"},
            {"endpoint": "deployment", "apiType": "openai_compatible", "baseUrl": "https://elsewhere.example.com/v1"},
        ):
            refused = client.post("/api/agents/provider-models", json=body, headers=_auth(token))
            assert (refused.status_code, refused.get_json()["error"]) == (400, llm_configs.DEPLOYMENT_REFUSAL)
            assert "test-model" not in refused.get_data(as_text=True)
        assert seen == []

    def test_with_neither_no_key_is_borrowed(self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        seen = self._capture(monkeypatch)
        _create(client, token)
        client.post("/api/agents/provider-models",
                    json={"apiType": "openai_compatible", "baseUrl": "https://api.openai.com/v1"},
                    headers=_auth(token))
        assert seen[-1].api_key == ""


#: This Curio's two endpoints in the tests below (fake names, hosts and keys).
#: Their names hold a space, a colon and a slash, and so do their models.
GATEWAY = llm_deployment.endpoint("Gateway: lab one", models=("org/model-a", "model-b"))
SECOND = llm_deployment.endpoint("Second / west", base_url="https://second.example.test/v1",
                                 api_key="second-fake-key-0001", models=("model-b", "org/model-c"))
OFFER = "Gateway: lab one: org/model-a, model-b; Second / west: model-b, org/model-c"


def _pick(endpoint_name: str, model: str) -> str:
    return llm_configs.pick_choice(endpoint_name, model)


class TestCuriosModels:
    """The endpoint file: the listing names its endpoints and their models,
    and any of those models is picked, for the default or for one agent,
    without a configuration. A pick runs on its endpoint's key and URL, and
    one the file no longer offers is refused."""

    @pytest.fixture()
    def offered(self, monkeypatch):
        llm_deployment.offer(monkeypatch, GATEWAY, SECOND)

    def test_the_listing_names_the_endpoints_and_their_models(self, client, user_and_token, tmp_curio, offered):
        _, token = user_and_token
        response = client.get(BASE, headers=_auth(token))
        deployment = response.get_json()["deployment"]
        assert deployment["endpoints"] == [
            {"name": "Gateway: lab one", "models": ["org/model-a", "model-b"]},
            {"name": "Second / west", "models": ["model-b", "org/model-c"]},
        ]
        # Curio's default is the first endpoint's first model.
        assert (deployment["label"], deployment["model"]) == ("Curio's default", "org/model-a")
        assert "endpointOffered" not in deployment
        text = response.get_data(as_text=True)
        assert "example.test" not in text and "fake-key" not in text and "127.0.0.1" not in text

    def test_a_pick_is_stored_as_one_string_and_lists_back_as_it_is(
        self, client, user_and_token, tmp_curio, offered,
    ):
        user, token = user_and_token
        pick = _pick("Second / west", "org/model-c")
        assert pick == 'curio:["Second / west","org/model-c"]'
        chosen = client.put(f"{BASE}/default", json={"configId": pick}, headers=_auth(token))
        assert chosen.status_code == 200, chosen.get_json()
        assert chosen.get_json()["default"] == pick
        on_file = json.loads(llm_configs.default_store().path(_user_dir_key(user)).read_text(encoding="utf-8"))
        assert on_file["default"] == pick
        # The same pair written another way is stored the one way.
        spaced = 'curio:[ "Gateway: lab one" , "model-b" ]'
        again = client.put(f"{BASE}/default", json={"configId": spaced}, headers=_auth(token))
        assert again.get_json()["default"] == _pick("Gateway: lab one", "model-b")

    def test_the_default_on_a_pick_answers_on_that_endpoints_key_and_url(
        self, client, user_and_token, tmp_curio, offered,
    ):
        from utk_curio.backend.app.agents.infrastructure import provider_config as pc

        user, token = user_and_token
        # The same model name on the second endpoint is the second endpoint's.
        client.put(f"{BASE}/default", json={"configId": _pick("Second / west", "model-b")}, headers=_auth(token))
        out = pc.resolve_llm(_user_dir_key(user), "agent.curio.researcher")
        assert (out.base_url, out.api_key, out.model) == (
            "https://second.example.test/v1", "second-fake-key-0001", "model-b",
        )
        assert (out.config_id, out.label, out.source, out.on_deployment) == (
            None, "Curio · Second / west", "default", True,
        )
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert listing["active"] == {
            "source": "default", "configId": None, "label": "Curio · Second / west", "model": "model-b",
            "apiType": "openai_compatible", "baseUrlHost": "",
        }

    def test_an_agent_on_a_pick_answers_on_it_and_the_others_follow_the_default(
        self, client, user_and_token, tmp_curio, offered,
    ):
        from utk_curio.backend.app.agents.infrastructure import provider_config as pc

        user, token = user_and_token
        own = _create(client, token).get_json()["config"]
        client.put(f"{BASE}/default", json={"configId": own["id"]}, headers=_auth(token))
        pick = _pick("Gateway: lab one", "model-b")
        chosen = client.put(f"{BASE}/assignments", json={"agent.curio.node-builder": pick}, headers=_auth(token))
        assert chosen.status_code == 200, chosen.get_json()
        listing = chosen.get_json()
        assert listing["assignments"] == {"agent.curio.node-builder": pick}
        row = next(r for r in listing["agents"] if r["id"] == "agent.curio.node-builder")
        assert row["choice"] == pick
        assert (row["answers"]["source"], row["answers"]["label"], row["answers"]["model"]) == (
            "assigned", "Curio · Gateway: lab one", "model-b",
        )
        out = pc.resolve_llm(_user_dir_key(user), "agent.curio.node-builder")
        assert (out.base_url, out.api_key, out.model) == ("http://127.0.0.1:9/v1", "test-key", "model-b")
        # Another agent follows the account's default.
        assert pc.resolve_llm(_user_dir_key(user), "agent.curio.researcher").config_id == own["id"]
        # Curio's default is a choice too, and null clears either.
        assert client.put(f"{BASE}/assignments", json={"agent.curio.node-builder": "deployment"},
                          headers=_auth(token)).get_json()["assignments"] == {"agent.curio.node-builder": "deployment"}
        assert client.put(f"{BASE}/assignments", json={"agent.curio.node-builder": None},
                          headers=_auth(token)).get_json()["assignments"] == {}

    @pytest.mark.parametrize("pick, sentence", [
        (_pick("Second / west", "org/model-a"), f"'Second / west' offers no model 'org/model-a'; Curio offers {OFFER}."),
        (_pick("Elsewhere", "model-b"), f"Curio has no endpoint 'Elsewhere'; it offers {OFFER}."),
        ("curio:not a pair", f"'curio:not a pair' is not one of Curio's models; it offers {OFFER}."),
    ])
    def test_a_pick_outside_the_file_is_refused_with_one_sentence_and_nothing_is_written(
        self, client, user_and_token, tmp_curio, offered, pick, sentence,
    ):
        user, token = user_and_token
        refused = client.put(f"{BASE}/default", json={"configId": pick}, headers=_auth(token))
        assert (refused.status_code, refused.get_json()["error"]) == (400, sentence)
        refused = client.put(f"{BASE}/assignments", json={
            "agent.curio.researcher": _pick("Gateway: lab one", "model-b"), "agent.curio.node-builder": pick,
        }, headers=_auth(token))
        assert (refused.status_code, refused.get_json()["error"]) == (400, sentence)
        doc = llm_configs.default_store().read(_user_dir_key(user))
        assert (doc["default"], doc["agents"]) == (None, {})

    def test_without_the_file_no_pick_is_accepted(self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        llm_deployment.withdraw(monkeypatch)
        pick = _pick("Test gateway", "test-model")
        for response in (
            client.put(f"{BASE}/default", json={"configId": pick}, headers=_auth(token)),
            client.put(f"{BASE}/assignments", json={"agent.curio.researcher": pick}, headers=_auth(token)),
        ):
            assert (response.status_code, response.get_json()["error"]) == (
                400, "This Curio offers no models of its own.",
            )

    def test_a_pick_that_left_the_file_is_refused_at_run_time_and_listed_as_it_is(
        self, client, user_and_token, tmp_curio, offered, monkeypatch,
    ):
        from utk_curio.backend.app.agents.infrastructure import provider_config as pc

        user, token = user_and_token
        default_pick = _pick("Second / west", "org/model-c")
        agent_pick = _pick("Gateway: lab one", "model-b")
        client.put(f"{BASE}/default", json={"configId": default_pick}, headers=_auth(token))
        client.put(f"{BASE}/assignments", json={"agent.curio.node-builder": agent_pick}, headers=_auth(token))
        # The operator drops the second endpoint and the first one's second model.
        llm_deployment.offer(monkeypatch, dataclasses.replace(GATEWAY, models=("org/model-a",)))
        offer = "Gateway: lab one: org/model-a"
        with pytest.raises(pc.ProviderConfigError) as refused:
            pc.resolve_llm(_user_dir_key(user), "agent.curio.researcher")
        assert str(refused.value) == f"Curio has no endpoint 'Second / west'; it offers {offer}."
        assert refused.value.remedy == {"kind": "llm-config", "agentId": "agent.curio.researcher"}
        with pytest.raises(pc.ProviderConfigError) as refused:
            pc.resolve_llm(_user_dir_key(user), "agent.curio.node-builder")
        assert str(refused.value) == f"'Gateway: lab one' offers no model 'model-b'; Curio offers {offer}."
        # The listing keeps both, so the page can show them as no longer offered.
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert listing["default"] == default_pick
        assert listing["assignments"] == {"agent.curio.node-builder": agent_pick}
        assert listing["active"]["source"] is None and "Second / west" in listing["active"]["error"]
        row = next(r for r in listing["agents"] if r["id"] == "agent.curio.node-builder")
        assert row["choice"] == agent_pick and "offers no model 'model-b'" in row["answers"]["error"]

    def test_no_host_or_key_of_this_curio_in_any_answer(
        self, client, user_and_token, tmp_curio, offered,
    ):
        _, token = user_and_token
        pick = _pick("Second / west", "org/model-c")
        responses = [
            client.put(f"{BASE}/default", json={"configId": pick}, headers=_auth(token)),
            client.put(f"{BASE}/assignments", json={"agent.curio.researcher": pick}, headers=_auth(token)),
            client.put(f"{BASE}/assignments", json={"agent.curio.node-builder": "deployment"}, headers=_auth(token)),
            client.get(BASE, headers=_auth(token)),
        ]
        for response in responses:
            assert response.status_code == 200, response.get_json()
            text = response.get_data(as_text=True)
            assert "example.test" not in text and "127.0.0.1" not in text and "fake-key" not in text
            assert "test-key" not in text
        listing = responses[-1].get_json()
        assert listing["active"]["baseUrlHost"] == ""
        assert {row["answers"]["baseUrlHost"] for row in listing["agents"]} == {""}


class TestAConfigurationOnThisCuriosEndpointIsDropped:
    """A file an earlier Curio wrote can hold a configuration on this Curio's
    endpoint (``endpoint: "deployment"``). It is dropped when the file is read,
    with the default and the choices that named it."""

    def _write_old_file(self, user_key: str) -> dict:
        own = {"label": "Mine", "endpoint": "own", "apiType": "anthropic", "baseUrl": "",
               "apiKey": KEY, "model": "claude", "createdAt": 1, "updatedAt": 1}
        here = {"label": "Here", "endpoint": "deployment", "endpointName": "Test gateway",
                "model": "test-model", "createdAt": 2, "updatedAt": 2}
        doc = {
            "version": 1,
            "configs": {"llm-00000000000a": own, "llm-00000000000d": here},
            "default": "llm-00000000000d",
            "agents": {"agent.curio.researcher": "llm-00000000000d", "agent.curio.node-builder": "llm-00000000000a"},
        }
        store = llm_configs.default_store()
        store.path(user_key).parent.mkdir(parents=True, exist_ok=True)
        store._write(user_key, doc)
        return doc

    def test_it_is_dropped_on_read_and_the_account_falls_back(self, client, user_and_token, tmp_curio):
        from utk_curio.backend.app.agents.infrastructure import provider_config as pc

        user, token = user_and_token
        user_key = _user_dir_key(user)
        self._write_old_file(user_key)
        doc = llm_configs.default_store().read(user_key)
        assert list(doc["configs"]) == ["llm-00000000000a"]
        assert doc["default"] is None
        assert doc["agents"] == {"agent.curio.node-builder": "llm-00000000000a"}
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert [c["id"] for c in listing["configs"]] == ["llm-00000000000a"]
        assert all("endpointName" not in c for c in listing["configs"])
        assert listing["default"] is None and listing["assignments"] == {"agent.curio.node-builder": "llm-00000000000a"}
        # The researcher falls back to the default, Curio's default here.
        out = pc.resolve_llm(user_key, "agent.curio.researcher")
        assert (out.source, out.model) == ("deployment", "test-model")
        # Its id is gone everywhere a request can name it.
        assert client.patch(f"{BASE}/configs/llm-00000000000d", json={"model": "x"},
                            headers=_auth(token)).status_code == 404
        assert client.post("/api/agents/provider-models", json={"configId": "llm-00000000000d"},
                           headers=_auth(token)).status_code == 404
        assert client.put(f"{BASE}/default", json={"configId": "llm-00000000000d"},
                          headers=_auth(token)).status_code == 404

    def test_the_next_write_leaves_it_out_of_the_file(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        user_key = _user_dir_key(user)
        self._write_old_file(user_key)
        assert _create(client, token, label="Another").status_code == 201
        on_file = json.loads(llm_configs.default_store().path(user_key).read_text(encoding="utf-8"))
        assert "llm-00000000000d" not in on_file["configs"]
        assert all(c.get("endpoint") == "own" for c in on_file["configs"].values())
        assert on_file["default"] is None
        assert on_file["agents"] == {"agent.curio.node-builder": "llm-00000000000a"}


class TestTheAccountRowNoLongerHoldsOne:
    def test_patch_me_refuses_the_old_fields(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        response = client.patch("/api/auth/me", json={"llm_model": "gpt-4o"}, headers=_auth(token))
        assert response.status_code == 400
        assert "API Settings" in response.get_json()["error"]
        me = client.get("/api/auth/me", headers=_auth(token)).get_json()
        assert not any(key.startswith(("llm_", "has_llm")) for key in me)

    def test_the_provider_default_route_is_gone(self, app):
        rules = {str(r.rule) for r in app.url_map.iter_rules()}
        assert "/api/agents/provider-default" not in rules


class TestARunNamesItsConfiguration:
    def test_a_refusal_carries_its_remedy(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        llm_deployment.withdraw(monkeypatch)
        coord = "agent.curio.researcher@1"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(f"/api/agents/projects/{alice_project}/attachments",
                          json={"coord": coord, "target": {"kind": "canvas"}},
                          headers=_auth(token)).get_json()["attachmentId"]
        response = client.post(f"/api/agents/projects/{alice_project}/attachments/{att}/run",
                               json={"message": "hi"}, headers=_auth(token))
        assert response.status_code == 400
        assert response.get_json()["remedy"] == {"kind": "llm-config", "agentId": "agent.curio.researcher"}

    @pytest.mark.parametrize("route", ["run", "run/stream"])
    def test_a_provider_error_loses_the_key_before_it_is_kept(self, client, user_and_token, tmp_curio,
                                                              alice_project, monkeypatch, route):
        _, token = user_and_token
        config_id = _create(client, token).get_json()["config"]["id"]
        client.put(f"{BASE}/default", json={"configId": config_id}, headers=_auth(token))

        def _refuse(config_, messages, **kw):
            raise RuntimeError(f"Error code: 401 - Incorrect API key provided: {KEY}")

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _refuse)
        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn',
                            lambda config_, messages, **kw: _refuse(config_, messages))
        coord = "agent.curio.researcher@1"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(f"/api/agents/projects/{alice_project}/attachments",
                          json={"coord": coord, "target": {"kind": "canvas"}},
                          headers=_auth(token)).get_json()["attachmentId"]
        response = client.post(f"/api/agents/projects/{alice_project}/attachments/{att}/{route}",
                               json={"message": "hi"}, headers=_auth(token))
        body = response.get_data(as_text=True)
        turns = client.get(f"/api/agents/projects/{alice_project}/attachments/{att}/session",
                           headers=_auth(token)).get_json()["turns"]
        # The failure is still reported, only without the key.
        assert "401" in body and "401" in json.dumps(turns)
        assert KEY not in body and KEY not in json.dumps(turns)

    def test_the_pins_and_the_ledger_record_it(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.repositories import ledger

        user, token = user_and_token
        config_id = _create(client, token, label="Scripted", apiType="testing", baseUrl="",
                            apiKey="", model="scripted").get_json()["config"]["id"]
        client.put(f"{BASE}/default", json={"configId": config_id}, headers=_auth(token))
        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
                            lambda config_, messages, **kw: "ok")
        coord = "agent.curio.researcher@1"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(f"/api/agents/projects/{alice_project}/attachments",
                          json={"coord": coord, "target": {"kind": "canvas"}},
                          headers=_auth(token)).get_json()["attachmentId"]
        client.post(f"/api/agents/projects/{alice_project}/attachments/{att}/run",
                    json={"message": "hi"}, headers=_auth(token))
        turns = client.get(f"/api/agents/projects/{alice_project}/attachments/{att}/session",
                           headers=_auth(token)).get_json()["turns"]
        pins = next(t["execution"]["pins"] for t in reversed(turns) if t.get("execution"))
        assert pins["llm"] == {"configId": config_id, "label": "Scripted",
                               "baseUrlHost": "the default testing endpoint", "source": "default"}
        entries = ledger._read_entries(_user_dir_key(user), ledger._today())
        assert any(e.get("kind") == "reserve" and e.get("llmConfigId") == config_id for e in entries)
        assert json.dumps(pins).count(KEY) == 0
