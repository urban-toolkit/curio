"""The dashboard agent (``POST /api/agents/dashboard-chat``): what it sends the
model, which changes it lets through, when it runs, and its refusals."""

from __future__ import annotations

import json

from utk_curio.backend import config
from utk_curio.backend.app.agents.application import dashboard_chat
from utk_curio.backend.tests._support.agent_routes import _auth

URL = "/api/agents/dashboard-chat"

CONTROLS = [
    {"id": "n1:season", "node": "Simulate Shadows", "scenario": "Winter", "name": "season",
     "label": "Season", "type": "choice", "options": {"choices": ["spring", "summer", "winter"]},
     "value": "winter"},
    {"id": "n2:season", "node": "Simulate Shadows", "scenario": "Summer", "name": "season",
     "label": "Season", "type": "choice", "options": {"choices": ["spring", "summer", "winter"]},
     "value": "summer"},
    {"id": "n3:height", "node": "Rasterize Buildings", "scenario": None, "name": "height",
     "label": "Max height", "type": "slider", "options": {"min": 0, "max": 550}, "value": 550},
]


def _reply(**document):
    return json.dumps({"reply": "ok", "changes": [], "run": False, "needsClarification": False, **document})


def _fake(monkeypatch, text, calls=None):
    def run(config_, messages, **kwargs):
        if calls is not None:
            calls.append({"messages": messages, **kwargs})
        return text

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", run)


def _post(client, token, message, **body):
    return client.post(URL, json={"message": message, "controls": CONTROLS,
                                  "scenarios": ["Winter", "Summer"], "canRun": True, **body},
                       headers=_auth(token))


class TestTurn:
    def test_the_model_reads_the_controls_and_the_conversation(self, client, user_and_token, monkeypatch):
        calls = []
        _fake(monkeypatch, _reply(), calls)
        _, token = user_and_token
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        r = _post(client, token, "set the height to 300", history=history)
        assert r.status_code == 200, r.get_data(as_text=True)
        messages = calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert '"n3:height"' in messages[0]["content"] and '"canRun": true' in messages[0]["content"]
        assert messages[1:] == [*history, {"role": "user", "content": "set the height to 300"}]

    def test_several_changes_and_a_run(self, client, user_and_token, monkeypatch):
        _fake(monkeypatch, _reply(changes=[
            {"id": "n1:season", "valueJson": '"spring"'},
            {"id": "n3:height", "valueJson": "300"},
        ], run=True))
        _, token = user_and_token
        body = _post(client, token, "spring in Winter, height 300, and rerun").get_json()
        assert body["changes"] == [{"id": "n1:season", "value": "spring"}, {"id": "n3:height", "value": 300}]
        assert body["run"] is True and body["rejected"] == []

    def test_a_value_its_control_does_not_take_is_rejected(self, client, user_and_token, monkeypatch):
        _fake(monkeypatch, _reply(changes=[
            {"id": "n3:height", "valueJson": "900"},
            {"id": "n1:season", "valueJson": '"autumn"'},
            {"id": "n9:nope", "valueJson": "1"},
        ]))
        _, token = user_and_token
        body = _post(client, token, "height 900, autumn").get_json()
        assert body["changes"] == []
        assert [r["id"] for r in body["rejected"]] == ["n3:height", "n1:season", "n9:nope"]

    def test_a_question_changes_nothing_and_does_not_run(self, client, user_and_token, monkeypatch):
        _fake(monkeypatch, _reply(reply="Which scenario, Winter or Summer?", needsClarification=True,
                                  changes=[{"id": "n1:season", "valueJson": '"spring"'}], run=True))
        _, token = user_and_token
        body = _post(client, token, "set the season to spring").get_json()
        assert body["needsClarification"] is True
        assert body["changes"] == [] and body["run"] is False
        assert "Winter" in body["reply"]

    def test_no_run_for_a_viewer_who_may_not_run(self, client, user_and_token, monkeypatch):
        _fake(monkeypatch, _reply(run=True))
        _, token = user_and_token
        assert _post(client, token, "rerun", canRun=False).get_json()["run"] is False

    def test_a_reply_in_a_fence_with_prose_around_it_is_read(self, client, user_and_token, monkeypatch):
        fenced = "Sure.\n```json\n" + _reply(changes=[{"id": "n3:height", "valueJson": "10"}]) + "\n```"
        _fake(monkeypatch, fenced)
        _, token = user_and_token
        assert _post(client, token, "height 10").get_json()["changes"] == [{"id": "n3:height", "value": 10}]

    def test_plain_text_is_a_reply_with_no_changes(self, client, user_and_token, monkeypatch):
        _fake(monkeypatch, "The height slider sets the tallest building.")
        _, token = user_and_token
        body = _post(client, token, "what does height do?").get_json()
        assert body["reply"].startswith("The height slider") and body["changes"] == []


class TestRefusals:
    def test_no_llm_configuration_is_a_refusal_with_the_api_settings_remedy(self, client, user_and_token, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "")
        _, token = user_and_token
        r = _post(client, token, "rerun")
        assert r.status_code == 400
        assert r.get_json()["remedy"] == {"kind": "llm-config"}

    def test_a_message_is_required(self, client, user_and_token, monkeypatch):
        _fake(monkeypatch, _reply())
        _, token = user_and_token
        assert _post(client, token, "  ").status_code == 400

    def test_a_provider_failure_is_a_502_without_the_key(self, client, user_and_token, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError("bad key test-key")

        monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", boom)
        _, token = user_and_token
        r = _post(client, token, "rerun")
        assert r.status_code == 502 and "test-key" not in r.get_data(as_text=True)

    def test_sign_in_is_required(self, client):
        assert client.post(URL, json={"message": "x", "controls": []}).status_code == 401


class TestReplySchema:
    def test_sent_when_the_endpoint_takes_one_and_dropped_when_it_refuses(self, client, user_and_token, monkeypatch):
        from utk_curio.backend.app.agents.infrastructure.providers import ReplySchemaRefused

        monkeypatch.setattr(dashboard_chat, "_reply_schema",
                            lambda *_: {"name": "dashboard_reply", "schema": dashboard_chat.REPLY_SCHEMA})
        monkeypatch.setattr("utk_curio.backend.app.agents.application.reply_schemas.note_refused", lambda *_: None)
        calls = []

        def run(config_, messages, **kwargs):
            calls.append(kwargs.get("reply_schema"))
            if kwargs.get("reply_schema"):
                raise ReplySchemaRefused("400")
            return _reply()

        monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", run)
        _, token = user_and_token
        assert _post(client, token, "rerun").status_code == 200
        assert calls[0]["name"] == "dashboard_reply" and calls[1] is None


class TestConfiguration:
    def test_a_configuration_that_is_not_the_default_is_enough(self, client, user_and_token, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "")
        _, token = user_and_token
        created = client.post("/api/agents/llm/configs", json={
            "label": "Mine", "apiType": "openai_compatible", "baseUrl": "http://127.0.0.1:9/v1",
            "apiKey": "k", "model": "my-model",
        }, headers=_auth(token))
        assert created.status_code in (200, 201), created.get_data(as_text=True)
        seen = []

        def run(config_, messages, **kwargs):
            seen.append(config_.model)
            return _reply()

        monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", run)
        r = _post(client, token, "rerun")
        assert r.status_code == 200, r.get_data(as_text=True)
        assert seen == ["my-model"]
