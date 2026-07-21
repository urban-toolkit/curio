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
        coord = "agent.chat-agent@1.0.0"  # dual-compatible built-in (node + canvas)
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
        assert att["name"] == "Chat"

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
    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        # Chat is dual-compatible (node + canvas), so a canvas attachment is valid.
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
        assert msgs[0]["content"] == builtin.read_instruction_text("agent.chat-agent@1.0.0")
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
        coord = "agent.chat-agent@1.0.0"  # dual-compatible, so a canvas attachment is valid
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


class TestPruneAttachmentsOnDelete:
    """Deleting a node on the canvas (a save whose spec no longer contains it)
    prunes the attachment bound to that node; canvas attachments survive."""

    def test_node_attachment_pruned_when_its_node_is_deleted(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        node_coord = "agent.node-explainer@1.0.0"  # node-only
        canvas_coord = "agent.dataflow-explainer@1.0.0"  # canvas-only
        for c in (node_coord, canvas_coord):
            client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": c}, headers=_auth(token))
        # Persist a node so a node-target attachment validates against the spec.
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        node_att = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": node_coord, "target": {"kind": "node", "targetId": "n1"}},
            headers=_auth(token),
        ).get_json()
        canvas_att = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": canvas_coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()
        # Delete the node: save a spec without n1 (and without agentAttachments).
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        ids = {a["attachmentId"] for a in listed}
        assert node_att["attachmentId"] not in ids  # pruned
        assert ids == {canvas_att["attachmentId"]}  # canvas survives


class TestAttachCompatibility:
    """Attach validation enforces the agent's compatibleTargets: canvas-only to
    canvas, node-only to nodes, dual-compatible to either."""

    def _install(self, client, token, project_id, coord):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))

    def _attach(self, client, token, project_id, coord, target):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": target},
            headers=_auth(token),
        )

    def test_canvas_only_agent_rejected_on_a_node(self, client, user_and_token, tmp_curio, alice_project):
        # dataflow-explainer is a canvas-category (canvas-only) built-in.
        _, token = user_and_token
        coord = "agent.dataflow-explainer@1.0.0"
        self._install(client, token, alice_project, coord)
        # Persist a node so the node target would otherwise exist.
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        r = self._attach(client, token, alice_project, coord, {"kind": "node", "targetId": "n1"})
        assert r.status_code == 400
        assert "canvas" in r.get_data(as_text=True).lower()
        # …but attaching to the canvas works.
        assert self._attach(client, token, alice_project, coord, {"kind": "canvas"}).status_code == 201

    def test_node_only_agent_rejected_on_canvas(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.node-explainer@1.0.0"  # node-only
        self._install(client, token, alice_project, coord)
        r = self._attach(client, token, alice_project, coord, {"kind": "canvas"})
        assert r.status_code == 400
        assert "node" in r.get_data(as_text=True).lower()

    def test_dual_agent_attaches_to_either(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.chat-agent@1.0.0"  # dual: node + canvas
        self._install(client, token, alice_project, coord)
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert self._attach(client, token, alice_project, coord, {"kind": "canvas"}).status_code == 201
        assert self._attach(client, token, alice_project, coord, {"kind": "node", "targetId": "n1"}).status_code == 201

    def test_chat_and_debug_declare_both_targets(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        by_id = {a["id"]: a for a in cat}
        assert sorted(by_id["agent.chat-agent"]["hooks"]) == ["canvas", "node"]
        assert sorted(by_id["agent.debug-agent"]["hooks"]) == ["canvas", "node"]

    def test_debug_attaches_to_canvas_and_node(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.debug-agent@1.0.0"
        self._install(client, token, alice_project, coord)
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert self._attach(client, token, alice_project, coord, {"kind": "canvas"}).status_code == 201
        assert self._attach(client, token, alice_project, coord, {"kind": "node", "targetId": "n1"}).status_code == 201

    def test_stale_materialized_builtin_resolves_fresh_roster_metadata(
        self, client, user_and_token, tmp_curio, alice_project
    ):
        # An earlier install materialized Chat when it was node-only. The stale
        # store copy must NOT override the roster's now-dual compatibleTargets:
        # the palette shows both pills and a canvas attach is accepted.
        user, token = user_and_token
        ukey = _user_dir_key(user)
        coord = "agent.chat-agent@1.0.0"
        stale = {
            "id": "agent.chat-agent",
            "name": "Chat",
            "category": "node",
            "version": "1.0.0",
            "purpose": "old node-only chat",
            "capabilities": [{"id": "conversation.respond", "contractVersion": "1"}],
            "compatibleTargets": [{"kind": "node", "requires": []}],  # STALE
            "prompts": {"instruction": {"path": "prompts/chat_prompt.txt", "variables": []}},
            "provenance": {"publisher": "curio", "license": "MIT", "trust": "built-in"},
        }
        storage.write_definition(ukey, coord, stale, {"prompts/chat_prompt.txt": "hi"})
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord}, headers=_auth(token),
        )
        listed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()
        chat = next(a for a in listed["agents"] if a["id"] == "agent.chat-agent")
        assert sorted(chat["hooks"]) == ["canvas", "node"]  # fresh roster, not the stale copy
        r = self._attach(client, token, alice_project, coord, {"kind": "canvas"})
        assert r.status_code == 201, r.get_data(as_text=True)


class TestIntent:
    """Attachment intent (memo dev/19): served from the prompt source unless
    edited; PATCH persists an override used as the run's system turn."""

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()

    def test_card_intent_is_the_prompt_source(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents import builtin

        _, token = user_and_token
        card = self._attach_builtin(client, token, alice_project)
        # Same file the runtime resolves — no literal duplicated in the test either.
        assert card["intent"] == builtin.read_instruction_text("agent.chat-agent@1.0.0")
        assert card["intentEdited"] is False

    def test_patch_persists_and_null_restores(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents import builtin

        _, token = user_and_token
        att = self._attach_builtin(client, token, alice_project)
        att_id = att["attachmentId"]
        r = client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={"intent": "focus on runtime cost"},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        card = r.get_json()
        assert card["intent"] == "focus on runtime cost"
        assert card["intentEdited"] is True
        assert card["revision"] == att["revision"] + 1
        # Persisted across a fresh GET.
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["intent"] == "focus on runtime cost"
        # Clearing falls back to the prompt source.
        r = client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={"intent": None},
            headers=_auth(token),
        )
        card = r.get_json()
        assert card["intent"] == builtin.read_instruction_text("agent.chat-agent@1.0.0")
        assert card["intentEdited"] is False

    def test_patch_validation_and_404(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        att = self._attach_builtin(client, token, alice_project)
        att_id = att["attachmentId"]
        assert client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={}, headers=_auth(token),
        ).status_code == 400
        assert client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={"intent": 42}, headers=_auth(token),
        ).status_code == 400
        assert client.patch(
            f"/api/agents/projects/{alice_project}/attachments/ghost",
            json={"intent": "x"}, headers=_auth(token),
        ).status_code == 404

    def test_run_uses_edited_intent_as_system(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        captured = {}

        def _fake_run(config, messages):
            captured["messages"] = messages
            return "ok"

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        _, token = user_and_token
        att = self._attach_builtin(client, token, alice_project)
        att_id = att["attachmentId"]
        client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={"intent": "answer in one sentence"},
            headers=_auth(token),
        )
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "hi"},
            headers=_auth(token),
        )
        assert captured["messages"][0] == {"role": "system", "content": "answer in one sentence"}


class TestSession:
    """Persistent chat sessions (memo dev/20): the transcript survives across
    requests, feeds bounded context into runs, and dies with its attachment."""

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()

    def _mock_provider(self, monkeypatch, replies):
        calls = []

        def _fake_run(config, messages):
            calls.append(messages)
            return replies[len(calls) - 1]

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        return calls

    def test_runs_persist_and_get_session_returns_history(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_provider(monkeypatch, ["a1", "a2"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)["attachmentId"]
        for msg in ("q1", "q2"):
            client.post(
                f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
                json={"message": msg}, headers=_auth(token),
            )
        r = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        )
        assert r.status_code == 200
        body = r.get_json()
        assert [(t["role"], t["text"]) for t in body["turns"]] == [
            ("user", "q1"), ("agent", "a1"), ("user", "q2"), ("agent", "a2"),
        ]
        assert body["sessionId"]

    def test_second_run_includes_prior_context(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = self._mock_provider(monkeypatch, ["a1", "a2"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)["attachmentId"]
        for msg in ("q1", "q2"):
            client.post(
                f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
                json={"message": msg}, headers=_auth(token),
            )
        second = calls[1]
        assert second[0]["role"] == "system"
        assert [(m["role"], m["content"]) for m in second[1:]] == [
            ("user", "q1"), ("assistant", "a1"), ("user", "q2"),
        ]

    def test_provider_error_persists_marker_and_is_excluded_from_context(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _flaky(config, messages):
            calls.append(messages)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return "recovered"

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _flaky)
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 502
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert [(t["role"], bool(t.get("error"))) for t in turns] == [("user", False), ("agent", True)]
        # Retry: the error marker is display-only, not provider context.
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q2"}, headers=_auth(token),
        )
        assert [(m["role"], m["content"]) for m in calls[1][1:]] == [
            ("user", "q1"), ("user", "q2"),
        ]

    def test_clear_session_keeps_attachment(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_provider(monkeypatch, ["a1"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)["attachmentId"]
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        r = client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.get_json()["turns"] == []
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert [a["attachmentId"] for a in listed] == [att_id]

    def test_session_404_on_unknown_attachment(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        for method in ("get", "delete"):
            r = getattr(client, method)(
                f"/api/agents/projects/{alice_project}/attachments/ghost/session",
                headers=_auth(token),
            )
            assert r.status_code == 404

    def test_detach_deletes_transcript_file(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents import sessions as sessions_mod

        self._mock_provider(monkeypatch, ["a1"])
        user, token = user_and_token
        card = self._attach_builtin(client, token, alice_project)
        att_id, session_id = card["attachmentId"], card["sessionId"]
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        ukey = _user_dir_key(user)
        assert sessions_mod._session_path(ukey, alice_project, session_id).exists()
        client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            headers=_auth(token),
        )
        assert not sessions_mod._session_path(ukey, alice_project, session_id).exists()

    def test_prune_on_save_deletes_transcript_file(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents import sessions as sessions_mod

        self._mock_provider(monkeypatch, ["a1"])
        user, token = user_and_token
        coord = "agent.node-explainer@1.0.0"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        card = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": coord, "target": {"kind": "node", "targetId": "n1"}},
            headers=_auth(token),
        ).get_json()
        att_id, session_id = card["attachmentId"], card["sessionId"]
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        ukey = _user_dir_key(user)
        assert sessions_mod._session_path(ukey, alice_project, session_id).exists()
        # Delete the node: the pruned attachment's transcript is GC'd too.
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert not sessions_mod._session_path(ukey, alice_project, session_id).exists()
