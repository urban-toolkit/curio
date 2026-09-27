"""LLM configurations: the store, its routes, and what never leaves the server.

Covers ``agents/llm_configs.py`` and the ``/api/agents/llm`` routes:

- the file is owner-only and a failed write leaves nothing behind;
- no response carries a key, and a key never follows its configuration to
  another endpoint;
- the validation matrix, duplicate, delete and the default;
- a configuration a running training job uses keeps its endpoint and key;
- a hosted guest reads the guest configuration and writes nothing, while the
  local guest owns its configurations;
- the model listing borrows a stored key only for that key's own endpoint.
"""

from __future__ import annotations

import json
import os
import stat
from unittest.mock import patch

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents import llm_configs
from utk_curio.backend.app.projects.services import _user_dir_key

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
                                   "model": "claude"}, deployment_offered=False)
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
        ({"endpoint": "deployment"}, "only a label and a model"),
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
        with patch("utk_curio.backend.app.agents.testing_provider.enabled", return_value=False):
            body["label"] = "Scripted 2"
            refused = client.post(f"{BASE}/configs", json=body, headers=_auth(token))
        assert refused.status_code == 400

    def test_this_curio_install_needs_the_deployment_to_offer_it(self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        body = {"label": "Here", "endpoint": "deployment", "model": "llama4"}
        assert client.post(f"{BASE}/configs", json=body, headers=_auth(token)).status_code == 201
        monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", "")
        monkeypatch.setattr(config, "DEFAULT_LLM_API_KEY", "")
        body["label"] = "Here 2"
        assert client.post(f"{BASE}/configs", json=body, headers=_auth(token)).status_code == 400


class TestDuplicateDeleteAndDefault:
    def test_duplicate_copies_the_key_server_side(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        source = _create(client, token).get_json()["config"]
        copy = client.post(f"{BASE}/configs/{source['id']}/duplicate", json={"model": "gpt-4o"},
                           headers=_auth(token)).get_json()["config"]
        assert copy["id"] != source["id"]
        assert copy["label"] == "OpenAI copy" and copy["model"] == "gpt-4o" and copy["origin"] == "user"
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
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert listing["deployment"] == {
            "label": "Deployment default", "endpointOffered": True, "apiType": "openai_compatible",
            "baseUrlHost": "127.0.0.1:9", "model": "test-model",
        }
        assert listing["editable"] is True and listing["shared"] is False
        assert listing["active"]["source"] == "deployment"


class TestTrainingLocksItsConfiguration:
    def _running_job_on(self, user_key, config_id):
        from utk_curio.backend.app.agents.training import records as records_mod

        record = records_mod.TrainingRecord(job_id=records_mod.new_job_id(), config_id=config_id)
        record.append("submitted", providerJobId="ftjob-1", baseModel="gpt-4o-mini")
        record.status = "running"
        records_mod.write(user_key, record)

    def test_its_endpoint_key_and_existence_are_frozen(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        config_id = _create(client, token).get_json()["config"]["id"]
        self._running_job_on(_user_dir_key(user), config_id)
        assert client.delete(f"{BASE}/configs/{config_id}", headers=_auth(token)).status_code == 409
        assert client.patch(f"{BASE}/configs/{config_id}", json={"apiKey": "sk-other-000000"},
                            headers=_auth(token)).status_code == 409
        assert client.patch(f"{BASE}/configs/{config_id}",
                            json={"baseUrl": "https://api.openai.com/v2"}, headers=_auth(token)).status_code == 200
        assert client.patch(f"{BASE}/configs/{config_id}", json={"label": "Still fine", "model": "gpt-4o"},
                            headers=_auth(token)).status_code == 200


class TestGuests:
    def test_a_hosted_guest_reads_the_guest_configuration_and_writes_nothing(self, client, db, tmp_curio, monkeypatch):
        user, token = _shared_guest(db)
        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
        monkeypatch.setattr(config, "GUEST_LLM_API_KEY", "guest-key-000000")
        monkeypatch.setattr(config, "GUEST_LLM_BASE_URL", "https://guest.example.edu/v1")
        monkeypatch.setattr(config, "GUEST_LLM_MODEL", "small")
        # A file left under the guest's key (by a local launch) is never read.
        store = llm_configs.default_store()
        store.create("guest", {"label": "Left over", "apiType": "anthropic", "apiKey": KEY,
                               "model": "claude"}, deployment_offered=False)
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert listing["configs"] == [] and listing["editable"] is False and "guest" in listing["reason"]
        assert listing["active"] == {
            "source": "guest", "configId": None, "label": "Guest configuration", "model": "small",
            "apiType": "openai_compatible", "baseUrlHost": "guest.example.edu",
        }
        assert _create(client, token).status_code == 403
        assert client.put(f"{BASE}/default", json={"configId": None}, headers=_auth(token)).status_code == 403

    def test_the_local_guest_owns_its_configurations(self, client, db, tmp_curio, monkeypatch):
        _, token = _shared_guest(db)
        monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
        assert _create(client, token).status_code == 201
        listing = client.get(BASE, headers=_auth(token)).get_json()
        assert listing["editable"] is True and listing["shared"] is True
        assert len(listing["configs"]) == 1


class TestModelListing:
    def _capture(self, monkeypatch):
        seen = []

        def _fake(config_):
            seen.append(config_)
            return ["m1"]

        monkeypatch.setattr("utk_curio.backend.app.agents.providers.list_provider_models", _fake)
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

    def test_the_deployment_endpoint_uses_its_own_key(self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        seen = self._capture(monkeypatch)
        client.post("/api/agents/provider-models", json={"endpoint": "deployment"}, headers=_auth(token))
        assert (seen[-1].base_url, seen[-1].api_key) == ("http://127.0.0.1:9/v1", "test-key")

    def test_with_neither_no_key_is_borrowed(self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        seen = self._capture(monkeypatch)
        _create(client, token)
        client.post("/api/agents/provider-models",
                    json={"apiType": "openai_compatible", "baseUrl": "https://api.openai.com/v1"},
                    headers=_auth(token))
        assert seen[-1].api_key == ""


class TestTheAccountRowNoLongerHoldsOne:
    def test_patch_me_refuses_the_old_fields(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        response = client.patch("/api/auth/me", json={"llm_model": "gpt-4o"}, headers=_auth(token))
        assert response.status_code == 400
        assert "AI Settings" in response.get_json()["error"]
        me = client.get("/api/auth/me", headers=_auth(token)).get_json()
        assert not any(key.startswith(("llm_", "has_llm")) for key in me)

    def test_the_provider_default_route_is_gone(self, app):
        rules = {str(r.rule) for r in app.url_map.iter_rules()}
        assert "/api/agents/provider-default" not in rules


class TestARunNamesItsConfiguration:
    def test_a_refusal_carries_its_remedy(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "")
        coord = "agent.chat-agent@1.0.0"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(f"/api/agents/projects/{alice_project}/attachments",
                          json={"coord": coord, "target": {"kind": "canvas"}},
                          headers=_auth(token)).get_json()["attachmentId"]
        response = client.post(f"/api/agents/projects/{alice_project}/attachments/{att}/run",
                               json={"message": "hi"}, headers=_auth(token))
        assert response.status_code == 400
        assert response.get_json()["remedy"] == {"kind": "llm-config", "agentId": "agent.chat-agent"}

    @pytest.mark.parametrize("route", ["run", "run/stream"])
    def test_a_provider_error_loses_the_key_before_it_is_kept(self, client, user_and_token, tmp_curio,
                                                              alice_project, monkeypatch, route):
        _, token = user_and_token
        config_id = _create(client, token).get_json()["config"]["id"]
        client.put(f"{BASE}/default", json={"configId": config_id}, headers=_auth(token))

        def _refuse(config_, messages, **kw):
            raise RuntimeError(f"Error code: 401 - Incorrect API key provided: {KEY}")

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _refuse)
        monkeypatch.setattr("utk_curio.backend.app.agents.services.stream_chat_completion",
                            lambda config_, messages, **kw: _refuse(config_, messages))
        coord = "agent.chat-agent@1.0.0"
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
        from utk_curio.backend.app.agents import ledger

        user, token = user_and_token
        config_id = _create(client, token, label="Scripted", apiType="testing", baseUrl="",
                            apiKey="", model="scripted").get_json()["config"]["id"]
        client.put(f"{BASE}/default", json={"configId": config_id}, headers=_auth(token))
        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion",
                            lambda config_, messages, **kw: "ok")
        coord = "agent.chat-agent@1.0.0"
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
