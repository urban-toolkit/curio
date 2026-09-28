"""Catalog settings: values the user owns, edited in the Agent Catalog and
rendered into the runs that read them.

Covers the registry's shipped default, ``GET``/``PUT /api/agents/settings``
(validation, reset, the hosted-guest refusal), the per-account file, and the
slot order of an attached run that reads a setting.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from utk_curio.backend.app.agents import catalog_settings, contracts
from utk_curio.backend.app.projects.services import _user_dir_key

URL = "/api/agents/settings"

#: The keyword taxonomy exactly as the prompts carried it before it became a
#: setting. The shipped default has to render it byte for byte.
_TAXONOMY = """\
- Action: can usually be mapped to a specific node or part of the dataflow. Are commonly denoted by verbs. Examples: "Load", "Visualize", "Filter", "Clean".
- Dataset: semantic references to datasets. Can be a single word or a set of words that describe the dataset. Examples: "311 requests", "Sidewalk", "Crime", "Temperature".
- Where: a geographical location of interest. Examples: "New York City", "Brazil", "Illinois", "Chicago".
- When: related to time. Examples: "over time", "on 1999", "12/06/2000", "between June and September".
- About: related to the organization of the workflow. Examples: "two scenarios", "the second part of the dataflow", "the first half of the dataflow".
- Interaction: denote interactions between nodes, with a node or with the data. Examples: "brushing", "click", "higlight", "widgets".
- Source: source of the dataset. Examples: "API", "local file", "simulation".
- Connection: describe how nodes or parts of the workflow are connected to each other. They can be explicit references to connection or implicit. Examples: "then", "after that", "second step", "connected".
- Content: references to the content of a node or part of the workflow. They can make references to a column of a dataset, machine learning models, type of visualization and so on. Examples: "column", "model".
- Metadata: information about the data like its format, number of columns, type. Examples: "2D", "3D", "JSON", "CSV".
- None: all keywords that are not of any other type."""

_HAZARDS = [
    {"name": "Hazard", "description": "a natural hazard.", "examples": ["flood", "heat wave"]},
    {"name": "Asset", "description": "what a hazard can damage."},
]


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _keyword_types(body):
    return next(s for s in body["settings"] if s["key"] == "keywordTypes")


class TestRegistry:
    def test_the_default_renders_the_old_taxonomy(self):
        assert contracts.KEYWORD_TYPES.render(contracts.KEYWORD_TYPES.default) == _TAXONOMY

    def test_the_default_satisfies_its_own_schema(self):
        for key, setting in contracts.CATALOG_SETTINGS.items():
            assert catalog_settings.errors(key, setting.default) == [], key

    def test_the_configuration_slot_frames_the_values_as_data(self):
        text = contracts.render_configuration({"keywordTypes": _HAZARDS})
        assert text.startswith(contracts.CONFIGURATION_FRAME)
        assert "Keyword types:\n- Hazard: a natural hazard. Examples: \"flood\", \"heat wave\".\n- Asset: what a hazard can damage." in text
        assert contracts.render_configuration({}) is None
        assert contracts.render_configuration({"notASetting": 1}) is None

    def test_an_example_cannot_break_out_of_its_quotes(self):
        text = contracts.KEYWORD_TYPES.render([
            {"name": "Quote", "description": "d.", "examples": ['say "hi"']},
        ])
        assert text == '- Quote: d. Examples: "say \\"hi\\"".'


class TestReadAndWrite:
    def test_the_listing_shows_the_default_and_who_reads_it(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        r = client.get(URL, headers=_auth(token))
        assert r.status_code == 200
        body = r.get_json()
        assert body["editable"] is True and body["reason"] is None
        setting = _keyword_types(body)
        assert setting["value"] == contracts.KEYWORD_TYPES.default
        assert setting["isDefault"] is True
        assert setting["schema"] == contracts.KEYWORD_TYPES.schema
        # Internal agents are listed as readers: settings do not depend on cards.
        assert {(e["agentId"], e["capability"], e["internal"]) for e in setting["readBy"]} == {
            ("agent.dataflow-planner", "workflow.keywords.extract", True),
            ("agent.dataflow-planner", "workflow.keyword.bind", True),
            ("agent.dataflow-planner", "workflow.plan.refresh", True),
        }

    def test_a_value_is_saved_per_account(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        r = client.put(URL, json={"keywordTypes": _HAZARDS}, headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        setting = _keyword_types(r.get_json())
        assert setting["value"] == _HAZARDS and setting["isDefault"] is False
        assert _keyword_types(client.get(URL, headers=_auth(token)).get_json())["value"] == _HAZARDS
        # Beside the account's imported-agents.json.
        from utk_curio.backend.app.agents import imports

        path = catalog_settings._path(_user_dir_key(user))
        assert path.parent == imports._imports_path(_user_dir_key(user)).parent
        assert json.loads(path.read_text(encoding="utf-8")) == {
            "version": 1, "values": {"keywordTypes": _HAZARDS},
        }

    def test_null_restores_the_default(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        client.put(URL, json={"keywordTypes": _HAZARDS}, headers=_auth(token))
        r = client.put(URL, json={"keywordTypes": None}, headers=_auth(token))
        setting = _keyword_types(r.get_json())
        assert setting["isDefault"] is True
        assert setting["value"] == contracts.KEYWORD_TYPES.default

    def test_saving_the_default_stores_nothing(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        client.put(URL, json={"keywordTypes": contracts.KEYWORD_TYPES.default}, headers=_auth(token))
        assert catalog_settings.stored_values(_user_dir_key(user)) == {}

    @pytest.mark.parametrize("value, fragment", [
        ([], "should be non-empty"),
        ([{"name": "A"}], "'description' is a required property"),
        ([{"name": "A\nB", "description": "d."}], "does not match"),
        ([{"name": "A", "description": "d.", "colour": "red"}], "Additional properties"),
        ([{"name": "A", "description": "d."}, {"name": "a", "description": "e."}], "appears more than once"),
        ("Action, Dataset", "is not of type 'array'"),
    ])
    def test_an_invalid_value_is_refused_and_nothing_is_saved(
        self, client, user_and_token, tmp_curio, value, fragment
    ):
        user, token = user_and_token
        r = client.put(URL, json={"keywordTypes": value}, headers=_auth(token))
        assert r.status_code == 400
        assert fragment in r.get_json()["error"]
        assert catalog_settings.stored_values(_user_dir_key(user)) == {}

    def test_an_unknown_key_is_refused(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        for body in ({"colours": ["red"]}, {"colours": None}, {}, ["keywordTypes"]):
            r = client.put(URL, json=body, headers=_auth(token))
            assert r.status_code == 400, body

    def test_a_corrupt_file_reads_as_the_default(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        client.put(URL, json={"keywordTypes": _HAZARDS}, headers=_auth(token))
        path = catalog_settings._path(_user_dir_key(user))
        path.write_text("{not json", encoding="utf-8")
        assert catalog_settings.values(_user_dir_key(user))["keywordTypes"] == contracts.KEYWORD_TYPES.default
        path.write_text(json.dumps({"version": 1, "values": {"keywordTypes": "nope"}}), encoding="utf-8")
        assert catalog_settings.values(_user_dir_key(user))["keywordTypes"] == contracts.KEYWORD_TYPES.default


class TestGuests:
    def test_a_hosted_guest_reads_but_cannot_write(self, client, guest_user_and_token, tmp_curio):
        from utk_curio.backend import config

        _, token = guest_user_and_token
        with patch.object(config, "CURIO_NO_AUTH", False):
            body = client.get(URL, headers=_auth(token)).get_json()
            assert body["editable"] is False and "guest" in body["reason"]
            r = client.put(URL, json={"keywordTypes": _HAZARDS}, headers=_auth(token))
        assert r.status_code == 403

    def test_a_local_guest_owns_the_settings(self, client, guest_user_and_token, tmp_curio):
        from utk_curio.backend import config

        _, token = guest_user_and_token
        with patch.object(config, "CURIO_NO_AUTH", True):
            r = client.put(URL, json={"keywordTypes": _HAZARDS}, headers=_auth(token))
        assert r.status_code == 200


class TestAttachedRunOrder:
    """An attached run's system turn: preamble, instruction, configuration,
    tool protocol, then the runtime blocks."""

    def _upload(self, client, token):
        manifest = {
            "id": "agent.hazard-mapper",
            "name": "Hazard Mapper",
            "category": "canvas",
            "version": "1.0.0",
            "capabilities": [{"id": "hazard.map", "contractVersion": "1"}],
            "compatibleTargets": [{"kind": "canvas", "requires": []}],
            "prompts": {
                "system": {"path": "prompts/system.txt", "variables": []},
                "instruction": {"path": "prompts/instruction.txt", "variables": []},
            },
            "inputs": {"reads": ["mission"], "requiredConfig": ["keywordTypes", "notASetting"]},
            "tools": [{"id": "dataflow.read"}, {"id": "node.create"}],
            "delegatesTo": ["agent.node-content-builder"],
            "provenance": {"publisher": "alice", "trust": "imported"},
        }
        prompts = {
            "prompts/system.txt": "HAZARD PREAMBLE.",
            "prompts/instruction.txt": "HAZARD INSTRUCTION.",
        }
        r = client.post("/api/agents/imports/upload", json={"manifest": manifest, "prompts": prompts},
                        headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)

    def test_the_slots_come_in_order(self, client, user_and_token, tmp_curio, monkeypatch, caplog):
        from utk_curio.backend.app.agents import content

        _, token = user_and_token
        self._upload(client, token)
        pid = client.post("/api/projects", json={
            "name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": [],
        }, headers=_auth(token)).get_json()["id"]
        coord = "agent.hazard-mapper@1.0.0"
        client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=_auth(token))
        client.post(f"/api/agents/projects/{pid}/install",
                    json={"coord": "agent.node-content-builder@1.0.0"}, headers=_auth(token))
        att = client.post(f"/api/agents/projects/{pid}/attachments",
                          json={"coord": coord, "target": {"kind": "canvas"}}, headers=_auth(token))
        att_id = att.get_json()["attachmentId"]
        client.put(URL, json={"keywordTypes": _HAZARDS}, headers=_auth(token))
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents import services as services_mod

            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return "Mapped."

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        with caplog.at_level("WARNING"):
            r = client.post(f"/api/agents/projects/{pid}/attachments/{att_id}/run",
                            json={"message": "map the floods"}, headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        system = calls[0][0]["content"]
        order = [
            system.index("HAZARD PREAMBLE."),
            system.index("HAZARD INSTRUCTION."),
            system.index(contracts.CONFIGURATION_FRAME),
            system.index(content.TAIL_INSTRUCTION),
            system.index("Available node templates"),
            system.index("You may also delegate"),
        ]
        assert order == sorted(order)
        assert "- Hazard: a natural hazard." in system
        # A key no setting defines is skipped with a warning, not an error.
        assert any("notASetting" in rec.getMessage() for rec in caplog.records)
        pins = r.get_json().get("pins") or client.get(
            f"/api/agents/projects/{pid}/attachments/{att_id}/session", headers=_auth(token)
        ).get_json()["turns"][-1]["execution"]["pins"]
        assert len(pins["configurationSha256"]) == 64
