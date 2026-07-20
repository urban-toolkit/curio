"""Integration tests for the /api/agents endpoints (Feature 5a)."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import storage
from utk_curio.backend.app.projects.services import _user_dir_key


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _write_def(user, agent_id="agent.node-explainer", version="1.0.0"):
    """Materialize a valid agent definition in the user's FS store."""
    user_key = _user_dir_key(user)
    d = storage.user_agents_dir(user_key) / f"{agent_id}@{version}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "id": agent_id,
                "name": "Node Explainer",
                "category": "node",
                "version": version,
                "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
                "compatibleTargets": [{"kind": "node", "requires": []}],
                # These helper-written defs represent user-authored/owned imports.
                "provenance": {"publisher": "curio", "trust": "imported"},
            }
        ),
        encoding="utf-8",
    )
    return f"{agent_id}@{version}"


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


class TestMyImports:
    def test_empty(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        resp = client.get("/api/agents/imports", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.get_json() == {"agents": []}

    def test_import_then_listed(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user)
        r = client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        listed = client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]
        assert [a["dirName"] for a in listed] == [coord]
        card = listed[0]
        assert card["id"] == "agent.node-explainer"
        assert card["capabilities"] == ["node.explain"]
        assert card["hooks"] == ["node"]
        assert card["imported"] is True

    def test_import_unknown_definition_404(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        r = client.post("/api/agents/imports", json={"coord": "agent.ghost@1.0.0"}, headers=_auth(token))
        assert r.status_code == 404

    def test_import_missing_coord_400(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        r = client.post("/api/agents/imports", json={}, headers=_auth(token))
        assert r.status_code == 400

    def test_remove_import(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user)
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        r = client.delete(f"/api/agents/imports/{coord}", headers=_auth(token))
        assert r.status_code == 200
        assert client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"] == []

    def test_requires_auth(self, client, tmp_curio):
        assert client.get("/api/agents/imports").status_code in (401, 403)


class TestGlobalCatalog:
    def test_lists_thirteen_builtins(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        resp = client.get("/api/agents/catalog", headers=_auth(token))
        assert resp.status_code == 200
        agents = resp.get_json()["agents"]
        assert len(agents) == 13
        assert all(a["scope"] == "global" and a["provenance"]["trust"] == "built-in" for a in agents)
        assert "agent.node-explainer" in {a["id"] for a in agents}

    def test_import_a_builtin(self, client, user_and_token, tmp_curio):
        # A built-in resolves without being written to the user store first.
        _, token = user_and_token
        coord = "agent.node-explainer@1.0.0"
        r = client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        imports_listed = client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]
        assert [a["dirName"] for a in imports_listed] == [coord]
        # And the catalog now marks it imported.
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        ne = next(a for a in cat if a["id"] == "agent.node-explainer")
        assert ne["imported"] is True

    def test_install_a_builtin_into_project(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.dataflow-task-planner@1.0.0"
        r = client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        assert r.get_json()["agents"] == [coord]
        cat = client.get(
            f"/api/agents/catalog?projectId={alice_project}", headers=_auth(token)
        ).get_json()["agents"]
        planner = next(a for a in cat if a["id"] == "agent.dataflow-task-planner")
        assert planner["installedInProject"] is True


class TestProjectInstall:
    def test_install_list_uninstall(self, client, user_and_token, tmp_curio, alice_project):
        user, token = user_and_token
        coord = _write_def(user)
        # install
        r = client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        assert r.get_json()["agents"] == [coord]
        # list
        listed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()
        assert [a["dirName"] for a in listed["agents"]] == [coord]
        assert listed["agents"][0]["installedInProject"] is True
        # uninstall
        r = client.delete(f"/api/agents/projects/{alice_project}/{coord}", headers=_auth(token))
        assert r.status_code == 200
        assert r.get_json()["agents"] == []

    def test_install_unknown_definition_404(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        r = client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": "agent.ghost@1.0.0"},
            headers=_auth(token),
        )
        assert r.status_code == 404

    def test_install_unknown_project_404(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user)
        r = client.post(
            "/api/agents/projects/does-not-exist/install",
            json={"coord": coord},
            headers=_auth(token),
        )
        assert r.status_code == 404

    def test_install_is_explicit_not_auto_import(self, client, user_and_token, tmp_curio, alice_project):
        # Installing into a project must NOT add the agent to My Imports (no chaining).
        user, token = user_and_token
        coord = _write_def(user)
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord},
            headers=_auth(token),
        )
        assert client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"] == []


class TestPublish:
    def test_publish_owned_import_appears_in_catalog(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user, "agent.my-custom", "1.0.0")  # owned, store-backed
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        r = client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        pub = next(a for a in cat if a["id"] == "agent.my-custom")
        assert pub["published"] is True

    def test_publish_builtin_rejected(self, client, user_and_token, tmp_curio):
        # A built-in is not an owned store-backed import → cannot be published.
        _, token = user_and_token
        client.post("/api/agents/imports", json={"coord": "agent.node-explainer@1.0.0"}, headers=_auth(token))
        r = client.post(
            "/api/agents/publications",
            json={"coord": "agent.node-explainer@1.0.0"},
            headers=_auth(token),
        )
        assert r.status_code == 400

    def test_publish_not_imported_rejected(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user, "agent.my-custom", "1.0.0")  # in store but not imported
        r = client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 400

    def test_publishable_flag_owned_vs_builtin(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        client.post("/api/agents/imports", json={"coord": "agent.node-explainer@1.0.0"}, headers=_auth(token))
        coord = _write_def(user, "agent.my-custom", "1.0.0")
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        by_id = {a["id"]: a for a in client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]}
        assert by_id["agent.node-explainer"]["publishable"] is False  # built-in
        assert by_id["agent.my-custom"]["publishable"] is True  # owned store-backed

    def test_unpublish(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user, "agent.my-custom", "1.0.0")
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token))
        r = client.delete(f"/api/agents/publications/{coord}", headers=_auth(token))
        assert r.status_code == 200
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        assert not any(a["id"] == "agent.my-custom" for a in cat)


class TestAttachments:
    def test_attach_canvas_then_list_then_detach(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.node-explainer@1.0.0"  # a built-in
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord}, headers=_auth(token),
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        att = r.get_json()
        assert att["coord"] == coord
        assert att["target"] == {"kind": "canvas"}
        assert att["attachmentId"] and att["sessionId"]
        assert att["name"] == "Node Explainer"

        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert len(listed) == 1 and listed[0]["attachmentId"] == att["attachmentId"]

        d = client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att['attachmentId']}",
            headers=_auth(token),
        )
        assert d.status_code == 200 and d.get_json()["detached"] is True
        assert client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"] == []

    def test_attach_requires_installed_template(self, client, user_and_token, tmp_curio, alice_project):
        # not installed in the project → 400 (no auto-install)
        _, token = user_and_token
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": "agent.node-explainer@1.0.0", "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        assert r.status_code == 400

    def test_attach_bad_node_target_rejected(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.node-explainer@1.0.0"
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord}, headers=_auth(token),
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": coord, "target": {"kind": "node", "targetId": "ghost"}},
            headers=_auth(token),
        )
        assert r.status_code == 400  # node id doesn't exist in the (empty) project

    def test_attach_missing_target_400(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": "agent.node-explainer@1.0.0"},
            headers=_auth(token),
        )
        assert r.status_code == 400


class TestMaterialize:
    def test_installing_a_builtin_materializes_its_bytes(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents import storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        coord = "agent.node-explainer@1.0.0"
        # Not in the store before install (it's a built-in resolved from the roster).
        assert storage.load_installed_agent_definition(_user_dir_key(user), coord) is None
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord}, headers=_auth(token),
        )
        # After install, the definition + its prompt asset are on disk in the store.
        d = storage.agent_definition_dir(_user_dir_key(user), coord)
        assert (d / "manifest.json").is_file()
        assert (d / "prompts" / "single_box_explanation_prompt.txt").is_file()

    def test_materialized_builtin_is_not_publishable(self, client, user_and_token, tmp_curio):
        # Even after its bytes are in the store, a built-in stays non-publishable.
        _, token = user_and_token
        coord = "agent.node-explainer@1.0.0"
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        by_id = {a["id"]: a for a in client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]}
        assert by_id["agent.node-explainer"]["publishable"] is False
        r = client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 400


class TestRun:
    def _attach_builtin(self, client, token, project_id, coord="agent.node-explainer@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def test_run_dispatches_instruction_as_system(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents import builtin

        captured = {}

        def _fake_run(config, messages):
            captured["messages"] = messages
            return "hello from the model"

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "explain this node"},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["reply"] == "hello from the model"
        msgs = captured["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == builtin.read_instruction_text("agent.node-explainer@1.0.0")
        assert msgs[1] == {"role": "user", "content": "explain this node"}

    def test_run_unknown_attachment_404(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/nope/run",
            json={"message": "hi"},
            headers=_auth(token),
        )
        assert r.status_code == 404

    def test_run_empty_message_400(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "   "},
            headers=_auth(token),
        )
        assert r.status_code == 400


class TestSavePreservesAgentState:
    """A canvas save (PUT /api/projects/<id>) sends a spec without the agent
    sections; the backend must not let it wipe installed agents/attachments."""

    def _save_without_agents(self, client, token, project_id):
        # Mimics TrillGenerator's canvas spec: nodes/edges/packages, no agents.
        body = {
            "name": "p",
            "spec": {"dataflow": {"nodes": [{"id": "n1"}], "edges": [], "packages": []}},
            "outputs": [],
        }
        r = client.put(f"/api/projects/{project_id}", json=body, headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)

    def test_installed_agent_survives_a_canvas_save(self, client, user_and_token, tmp_curio, alice_project):
        user, token = user_and_token
        coord = _write_def(user, "agent.my-agent")
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord},
            headers=_auth(token),
        )
        self._save_without_agents(client, token, alice_project)
        listed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()
        assert [a["dirName"] for a in listed["agents"]] == [coord]

    def test_attachment_survives_a_canvas_save(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.node-explainer@1.0.0"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()
        self._save_without_agents(client, token, alice_project)
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert [a["attachmentId"] for a in listed] == [att["attachmentId"]]
        # The install lockfile is preserved too.
        agents = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()
        assert [a["dirName"] for a in agents["agents"]] == [coord]

    def test_client_sent_agents_list_is_honored(self, client, user_and_token, tmp_curio, alice_project):
        # A save that explicitly declares dataflow.agents wins (future client);
        # an empty list clears the lockfile rather than being carried forward.
        user, token = user_and_token
        coord = _write_def(user, "agent.my-agent")
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord},
            headers=_auth(token),
        )
        body = {
            "name": "p",
            "spec": {"dataflow": {"nodes": [], "edges": [], "packages": [], "agents": []}},
            "outputs": [],
        }
        r = client.put(f"/api/projects/{alice_project}", json=body, headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        listed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()
        assert listed["agents"] == []
