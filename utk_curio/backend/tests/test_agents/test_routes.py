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

        # A first run also fires the post-reply title call (memo dev/25), so
        # capture every call and assert on the conversation run (the first).
        calls = []

        def _fake_run(config, messages, **kwargs):
            calls.append(messages)
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
        msgs = calls[0]
        assert msgs[0]["role"] == "system"
        # dev/06 parity: the system turn composes the preamble + instruction,
        # exactly as every legacy call site did.
        preamble = builtin.read_prompt_text("agent.chat-agent@1.0.0", "system")
        instruction = builtin.read_instruction_text("agent.chat-agent@1.0.0")
        from utk_curio.backend.app.agents import content as content_mod

        # dev/39: the runtime-owned structured-tail instruction composes last.
        assert msgs[0]["content"] == f"{preamble}\n\n{instruction}\n\n{content_mod.TAIL_INSTRUCTION}"
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
        # calls[0] is the conversation run; a first run adds a title call after
        # it (memo dev/25).
        calls = []

        def _fake_run(config, messages, **kwargs):
            calls.append(messages)
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
        # The edited intent replaces the instruction portion; the preamble
        # still applies, and the dev/39 tail instruction composes last.
        from utk_curio.backend.app.agents import builtin
        from utk_curio.backend.app.agents import content as content_mod

        preamble = builtin.read_prompt_text("agent.chat-agent@1.0.0", "system")
        assert calls[0][0] == {
            "role": "system",
            "content": f"{preamble}\n\nanswer in one sentence\n\n{content_mod.TAIL_INSTRUCTION}",
        }


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
        from utk_curio.backend.app.agents import services as services_mod

        calls = []

        def _fake_run(config, messages, **kwargs):
            # Answer the post-first-run title call (memo dev/25) out of band so
            # `replies`/`calls` keep tracking the conversation runs only.
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Session Test Title"
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

        def _flaky(config, messages, **kwargs):
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


class TestStreamRun:
    """SSE run path (memo dev/22): deltas → done, persistence parity with run."""

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _events(self, resp):
        out = []
        for block in resp.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            out.append((lines["event"], json.loads(lines["data"])))
        return out

    def test_stream_deltas_then_done_and_persists_once(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _fake_stream(config, messages, **kwargs):
            yield "hel"
            yield "lo"

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _fake_stream
        )
        # The first stream run fires the post-reply title call (memo dev/25);
        # stub the blocking port so it never reaches a real provider.
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "Stream Title",
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.mimetype == "text/event-stream"
        events = self._events(r)
        # The execution handshake precedes the first delta (memo dev/37) and
        # done carries the enriched typed payload.
        assert events[0][0] == "execution"
        execution_id = events[0][1]["executionId"]
        assert execution_id
        assert events[1:3] == [("delta", {"text": "hel"}), ("delta", {"text": "lo"})]
        assert events[3] == (
            "done",
            {"reply": "hello", "executionId": execution_id, "usage": None, "content": []},
        )
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert [(t["role"], t["text"]) for t in turns] == [("user", "q1"), ("agent", "hello")]

    def test_stream_provider_error_emits_error_and_persists_marker(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _flaky(config, messages, **kwargs):
            yield "par"
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _flaky
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._events(r)
        assert events[0][0] == "execution"
        assert events[1] == ("delta", {"text": "par"})
        assert events[-1][0] == "error"
        assert "boom" in events[-1][1]["error"]
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        # The partial text is NOT persisted — user turn + display-only marker.
        assert [(t["role"], bool(t.get("error"))) for t in turns] == [("user", False), ("agent", True)]
        assert "boom" in turns[1]["text"]

    def test_stream_validation_errors_are_plain_json(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/ghost/run/stream",
            json={"message": "hi"}, headers=_auth(token),
        )
        assert r.status_code == 404
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "   "}, headers=_auth(token),
        )
        assert r.status_code == 400

    def test_stream_context_includes_prior_session(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_stream(config, messages, **kwargs):
            calls.append(messages)
            yield "ok"

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _fake_stream
        )
        # Stub the blocking port: the first run's title call must not reach a
        # real provider (memo dev/25).
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "Stream Title",
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        for msg in ("q1", "q2"):
            r = client.post(
                f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
                json={"message": msg}, headers=_auth(token),
            )
            r.get_data()  # consume the stream so the exchange persists
        assert [(m["role"], m["content"]) for m in calls[1][1:]] == [
            ("user", "q1"), ("assistant", "ok"), ("user", "q2"),
        ]


class TestExecutionRecords:
    """Execution records on agent turns (memo dev/37): every completed run
    pins its DEC-031 reproducibility inputs and Actual usage on the transcript
    — the transcript IS the run history."""

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _mock_provider(self, monkeypatch, reply="ok", usage=None):
        """Stub the blocking port; ``usage`` (when given) is written into the
        ``usage_out`` sink for conversation runs. Title calls answer out of
        band and report a token cost of their own."""
        from utk_curio.backend.app.agents import services as services_mod

        calls = []

        def _fake_run(config, messages, usage_out=None, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                if usage_out is not None:
                    usage_out.update({"inputTokens": 5, "outputTokens": 3})
                return "Exec Title"
            calls.append(messages)
            if usage is not None and usage_out is not None:
                usage_out.update(usage)
            return reply

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        return calls

    def _turns(self, client, token, project_id, att_id):
        return client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]

    def test_run_persists_execution_record_with_pins_and_usage(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents import policy
        from utk_curio.backend.config import DEFAULT_LLM_API_TYPE, DEFAULT_LLM_MODEL

        self._mock_provider(monkeypatch, usage={"inputTokens": 12, "outputTokens": 34})
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        body = r.get_json()
        # The blocking response carries the same two new fields (memo dev/37).
        assert body["executionId"]
        assert body["usage"] == {"inputTokens": 12, "outputTokens": 34}
        turns = self._turns(client, token, alice_project, att_id)
        assert "execution" not in turns[0]  # user turns carry no record
        execution = turns[1]["execution"]
        assert execution["executionId"] == body["executionId"]
        assert execution["status"] == "ok"
        assert execution["usage"] == {"inputTokens": 12, "outputTokens": 34}
        assert isinstance(execution["durationMs"], int) and execution["durationMs"] >= 0
        pins = execution["pins"]
        assert pins["coord"] == "agent.chat-agent@1.0.0"
        assert pins["intentEdited"] is False
        # Built-in roster manifests carry no prompt digest — tolerated null.
        assert pins["promptSha256"] is None
        # Unconfigured test user → the deployment-default provider (DEC-039).
        assert pins["provider"] == DEFAULT_LLM_API_TYPE
        assert pins["model"] == DEFAULT_LLM_MODEL
        # dev/39: granted tools are pinned; the registry ships empty.
        assert pins["tools"] == []
        assert pins["policy"] == {
            "runsPerDay": policy.deployment_defaults()["quotas"]["runsPerDay"],
            "maxOutputTokens": policy.DEPLOYMENT_MAX_OUTPUT_TOKENS,
            "dailyBudgetUsd": None,
            "estimatedCostPerRunUsd": None,
        }

    def test_run_usage_null_when_provider_reports_none(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_provider(monkeypatch)  # sink never touched (proxy strips usage)
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.get_json()["usage"] is None
        turns = self._turns(client, token, alice_project, att_id)
        # Actual-or-absent (memo dev/11): never estimated into the field.
        assert turns[1]["execution"]["usage"] is None
        assert turns[1]["execution"]["status"] == "ok"

    def test_provider_error_records_error_execution(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _boom(config, messages, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _boom)
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 502
        turns = self._turns(client, token, alice_project, att_id)
        execution = turns[1]["execution"]
        assert execution["status"] == "error"
        assert execution["usage"] is None
        assert execution["pins"]["coord"] == "agent.chat-agent@1.0.0"

    def test_edited_intent_is_pinned(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_provider(monkeypatch)
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={"intent": "custom instructions"}, headers=_auth(token),
        )
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["execution"]["pins"]["intentEdited"] is True

    def test_stream_persists_execution_record(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _fake_stream(config, messages, usage_out=None, **kwargs):
            yield "hel"
            yield "lo"
            if usage_out is not None:
                usage_out.update({"inputTokens": 7, "outputTokens": 9})

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _fake_stream
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "Stream Title",
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        blocks = [b for b in r.get_data(as_text=True).strip().split("\n\n")]
        events = [
            (lines["event"], json.loads(lines["data"]))
            for lines in (dict(l.split(": ", 1) for l in b.splitlines() if ": " in l) for b in blocks)
        ]
        turns = self._turns(client, token, alice_project, att_id)
        execution = turns[1]["execution"]
        assert execution["status"] == "ok"
        assert execution["usage"] == {"inputTokens": 7, "outputTokens": 9}
        assert execution["pins"]["coord"] == "agent.chat-agent@1.0.0"
        # The SSE envelope correlates with the persisted record (memo dev/37):
        # execution first, done enriched with the same id and Actual usage.
        assert events[0] == ("execution", {"executionId": execution["executionId"]})
        assert events[-1] == (
            "done",
            {
                "reply": "hello",
                "executionId": execution["executionId"],
                "usage": {"inputTokens": 7, "outputTokens": 9},
                "content": [],
            },
        )

    def test_stream_error_records_error_execution(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _flaky(config, messages, **kwargs):
            yield "par"
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _flaky
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        r.get_data()
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["execution"]["status"] == "error"

    def test_title_call_writes_no_execution_record(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The dev/25 auto-title call is internal housekeeping, not an execution:
        # a first run makes two provider calls but exactly one record exists.
        calls = self._mock_provider(monkeypatch, usage={"inputTokens": 1, "outputTokens": 2})
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert len(calls) == 1  # the conversation run; the title call is untracked
        turns = self._turns(client, token, alice_project, att_id)
        assert sum(1 for t in turns if "execution" in t) == 1

    def test_daily_usage_counters_include_the_title_call(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The counters cover every provider call this account paid for — the
        # conversation run (12/34) plus the recordless title call (5/3) — so
        # they may exceed what the transcript's execution records sum to.
        from utk_curio.backend.app.agents import quotas
        from utk_curio.backend.app.projects.services import _user_dir_key

        self._mock_provider(monkeypatch, usage={"inputTokens": 12, "outputTokens": 34})
        user, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert quotas.usage_today(_user_dir_key(user)) == {
            "inputTokens": 17, "outputTokens": 37,
        }

    def test_settings_payloads_expose_usage_today(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_provider(monkeypatch, usage={"inputTokens": 12, "outputTokens": 34})
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        expected = {"inputTokens": 17, "outputTokens": 37}  # run + title call
        acct = client.get("/api/agents/settings", headers=_auth(token)).get_json()
        assert acct["usageToday"] == expected
        proj = client.get(
            f"/api/agents/projects/{alice_project}/defaults/agent.chat-agent@1.0.0",
            headers=_auth(token),
        ).get_json()
        assert proj["effective"]["quotas"]["usageToday"] == expected

    def test_uploaded_definition_prompt_digest_is_pinned(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A digest-stamped definition (upload-import, memo dev/36) pins the
        # exact prompt bytes that dispatched (DEC-031).
        import hashlib

        self._mock_provider(monkeypatch)
        user, token = user_and_token
        prompt_text = "You explain things."
        digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        r = client.post(
            "/api/agents/imports/upload",
            json={
                "manifest": {
                    "id": "agent.pinned",
                    "name": "Pinned",
                    "category": "canvas",
                    "version": "1.0.0",
                    "capabilities": [{"id": "chat.reply", "contractVersion": "1"}],
                    "compatibleTargets": [{"kind": "canvas", "requires": []}],
                    "prompts": {"instruction": {"path": "prompts/instruction.txt", "variables": []}},
                    "provenance": {"publisher": "alice", "trust": "imported"},
                },
                "prompts": {"prompts/instruction.txt": prompt_text},
            },
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        att_id = self._attach_builtin(client, token, alice_project, coord="agent.pinned@1.0.0")
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["execution"]["pins"]["promptSha256"] == digest


class TestToolGrants:
    """Tool-contract substrate on the run path (memo dev/39): declarations are
    never grants; required-but-ungranted refuses the run before admission."""

    def _upload_install_attach(self, client, token, project_id, tools_section):
        coord = "agent.tooled@1.0.0"
        r = client.post(
            "/api/agents/imports/upload",
            json={
                "manifest": {
                    "id": "agent.tooled",
                    "name": "Tooled",
                    "category": "canvas",
                    "version": "1.0.0",
                    "capabilities": [{"id": "chat.reply", "contractVersion": "1"}],
                    "compatibleTargets": [{"kind": "canvas", "requires": []}],
                    "prompts": {"instruction": {"path": "prompts/i.txt", "variables": []}},
                    "tools": tools_section,
                    "provenance": {"publisher": "alice", "trust": "imported"},
                },
                "prompts": {"prompts/i.txt": "You help."},
            },
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return att.get_json()["attachmentId"]

    def test_required_ungranted_tool_refuses_the_run_without_consuming_quota(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents import quotas
        from utk_curio.backend.app.projects.services import _user_dir_key

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "never reached",
        )
        user, token = user_and_token
        att_id = self._upload_install_attach(
            client, token, alice_project, [{"id": "ghost.tool", "required": True}]
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 422
        assert "ghost.tool" in r.get_json()["error"]
        # Validation-stage refusal: no quota consumed, nothing persisted.
        assert quotas.runs_used_today(_user_dir_key(user)) == 0
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert turns == []

    def test_optional_ungranted_tool_runs_and_pins_no_grant(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "ok",
        )
        _, token = user_and_token
        att_id = self._upload_install_attach(
            client, token, alice_project, [{"id": "ghost.tool", "required": False}]
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert turns[1]["execution"]["pins"]["tools"] == []

    def test_registered_read_tool_is_granted_and_pinned(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents import tools as tools_mod
        from utk_curio.backend.app.agents.tools import ToolContract

        monkeypatch.setitem(
            tools_mod.REGISTRY,
            "ghost.tool",
            ToolContract(id="ghost.tool", contract_version="1", effect="read", description="d"),
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "ok",
        )
        _, token = user_and_token
        att_id = self._upload_install_attach(
            client, token, alice_project, [{"id": "ghost.tool", "required": True}]
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert turns[1]["execution"]["pins"]["tools"] == ["ghost.tool"]


class TestToolLoop:
    """The bounded read-tool execution loop (memo dev/41): granted reads
    execute with normalized events; everything else refuses loudly to the
    model, invisibly to the user; grant-less runs stay byte-identical to T2."""

    def _save_node(self, client, token, project_id, node):
        r = client.put(
            f"/api/projects/{project_id}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [node], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)

    def _install_attach(self, client, token, project_id, coord, target):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": target},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        return r.get_json()["attachmentId"]

    def _sse_events(self, resp):
        out = []
        for block in resp.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            out.append((lines["event"], json.loads(lines["data"])))
        return out

    TOOL_TAIL = '```curio.v1\n{"toolRequest": {"tool": "node.read", "params": {}}}\n```'

    def test_granted_read_tool_executes_with_events_and_record(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_stream(config, messages, usage_out=None, **kwargs):
            calls.append(messages)
            if usage_out is not None:
                usage_out.update({"inputTokens": len(calls), "outputTokens": len(calls) * 2})
            if len(calls) == 1:
                yield "Let me look at the node.\n"
                yield self.TOOL_TAIL
            else:
                yield "It prints 1."

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _fake_stream
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "Loop Title",
        )
        _, token = user_and_token
        self._save_node(client, token, alice_project, {"id": "n1", "type": "CODE", "content": "print(1)"})
        att_id = self._install_attach(
            client, token, alice_project, "agent.node-explainer@1.0.0",
            {"kind": "node", "targetId": "n1"},
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "explain"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        kinds = [k for k, _ in events]
        # Normalized ordering (dev/03:344 vocabulary over the T1 envelope).
        assert kinds.index("tool_requested") < kinds.index("tool_started") < kinds.index("tool_result")
        assert kinds.index("tool_result") < kinds.index("done")
        tool_result = next(p for k, p in events if k == "tool_result")
        assert tool_result == {"tool": "node.read", "status": "ok"}
        deltas = "".join(p["text"] for k, p in events if k == "delta")
        assert "curio.v1" not in deltas  # the request tail never flashed
        done = events[-1][1]
        assert done["reply"] == "Let me look at the node.\n\nIt prints 1."
        # The grant-aware instruction listed the granted tool.
        assert "- node.read:" in calls[0][0]["content"]
        # The tool result (node JSON) reached the second call as framed data.
        second_ctx = calls[1][-1]["content"]
        assert second_ctx.startswith("[tool result] node.read: ok")
        assert "print(1)" in second_ctx
        # Execution record: toolCalls + usage summed across both rounds.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        execution = turns[1]["execution"]
        assert execution["usage"] == {"inputTokens": 3, "outputTokens": 6}
        (call,) = execution["toolCalls"]
        assert call["tool"] == "node.read" and call["status"] == "ok"
        assert isinstance(call["durationMs"], int)
        assert turns[1]["text"] == "Let me look at the node.\n\nIt prints 1."

    def test_ungranted_request_is_refused_to_the_model_only(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents import services as services_mod

            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            if len(calls) == 1:
                return '```curio.v1\n{"toolRequest": {"tool": "dataflow.read", "params": {}}}\n```'
            return "Done without it."

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        _, token = user_and_token
        # Chat agent declares no tools → nothing granted.
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": "agent.chat-agent@1.0.0"}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": "agent.chat-agent@1.0.0", "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.get_json()["reply"] == "Done without it."
        assert "not granted" in calls[1][-1]["content"]
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        (call,) = turns[1]["execution"]["toolCalls"]
        assert call["status"] == "refused"

    def test_round_cap_bounds_the_loop(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents import services as services_mod

            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return f"Round {len(calls)}.\n" + TestToolLoop.TOOL_TAIL  # always wants more

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        _, token = user_and_token
        self._save_node(client, token, alice_project, {"id": "n1", "content": "x"})
        att_id = self._install_attach(
            client, token, alice_project, "agent.node-explainer@1.0.0",
            {"kind": "node", "targetId": "n1"},
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200
        assert len(calls) == 3  # MAX_TOOL_ROUNDS executions + the final call
        # The last tool result told the model to answer with what it has.
        assert "answer with what you have" in calls[2][-1]["content"]
        body = r.get_json()
        # The dangling third request was dropped; all round text kept.
        assert body["reply"] == "Round 1.\n\nRound 2.\n\nRound 3."
        assert body["content"] == []
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert len(turns[1]["execution"]["toolCalls"]) == 2

    def test_mutate_request_never_executes_in_the_loop(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents import services as services_mod

            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            if len(calls) == 1:
                return (
                    '```curio.v1\n{"toolRequest": {"tool": "node.content.write", '
                    '"params": {"nodeId": "n1", "content": "pwned"}}}\n```'
                )
            return "Proposed."

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        user, token = user_and_token
        self._save_node(client, token, alice_project, {"id": "n1", "content": "original"})
        att_id = self._install_attach(
            client, token, alice_project, "agent.node-content-builder@1.0.0",
            {"kind": "node", "targetId": "n1"},
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200
        # The spec is untouched: the loop NEVER executes a mutation (DEC-006).
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        assert spec["dataflow"]["nodes"][0]["content"] == "original"

    def test_grantless_system_turn_is_byte_identical_to_t2(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents import builtin
        from utk_curio.backend.app.agents import content as content_mod
        from utk_curio.backend.app.agents import services as services_mod

        calls = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return "ok"

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        _, token = user_and_token
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": "agent.chat-agent@1.0.0"}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": "agent.chat-agent@1.0.0", "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        preamble = builtin.read_prompt_text("agent.chat-agent@1.0.0", "system")
        instruction = builtin.read_instruction_text("agent.chat-agent@1.0.0")
        assert calls[0][0]["content"] == (
            f"{preamble}\n\n{instruction}\n\n{content_mod.TAIL_INSTRUCTION}"
        )


class TestStructuredContent:
    """Structured-tail protocol end-to-end (memo dev/39, DEC-043): a valid
    terminal curio.v1 block becomes typed parts on the turn and the envelope;
    anything else fails open to visible text."""

    TAIL = '```curio.v1\n{"suggestedPrompts": {"primary": "Next step", "alternatives": ["Alt"]}}\n```'
    PARTS = [{"type": "suggestedPrompts", "primary": "Next step", "alternatives": ["Alt"]}]

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _mock_run(self, monkeypatch, replies):
        from utk_curio.backend.app.agents import services as services_mod

        calls = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Content Title"
            calls.append(messages)
            return replies[len(calls) - 1]

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        return calls

    def _mock_stream(self, monkeypatch, deltas):
        def _fake_stream(config, messages, **kwargs):
            yield from deltas

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _fake_stream
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "Stream Title",
        )

    def _turns(self, client, token, project_id, att_id):
        return client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]

    def _sse_events(self, resp):
        out = []
        for block in resp.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            out.append((lines["event"], json.loads(lines["data"])))
        return out

    def test_run_strips_valid_tail_and_persists_parts(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = self._mock_run(monkeypatch, [f"Answer.\n{self.TAIL}", "second"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        body = r.get_json()
        assert body["reply"] == "Answer."
        assert body["content"] == self.PARTS
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["text"] == "Answer."
        assert turns[1]["content"] == self.PARTS
        # The tail never re-enters provider context on the next turn.
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q2"}, headers=_auth(token),
        )
        assert {"role": "assistant", "content": "Answer."} in calls[1]
        # (Only the system turn mentions curio.v1 — via the tail instruction.)
        assert not any("curio.v1" in m["content"] for m in calls[1] if m["role"] != "system")

    def test_run_invalid_tail_stays_visible_verbatim(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        reply = "Answer.\n```curio.v1\n{broken\n```"
        self._mock_run(monkeypatch, [reply])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        body = r.get_json()
        assert body["reply"] == reply  # fail-open: nothing stripped
        assert body["content"] == []
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["text"] == reply
        assert "content" not in turns[1]

    def test_stream_withholds_tail_and_emits_content_event(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The fence marker is split across delta boundaries on purpose.
        self._mock_stream(
            monkeypatch,
            ["Answer.\n``", '`curio.v1\n{"suggestedPrompts": {"primary": "Next step", ', '"alternatives": ["Alt"]}}', "\n```"],
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        deltas = "".join(p["text"] for kind, p in events if kind == "delta")
        # The tail never flashed into the live transcript.
        assert "curio.v1" not in deltas
        assert deltas == "Answer.\n"
        kinds = [k for k, _ in events]
        assert kinds.index("content") < kinds.index("done")
        content_event = next(p for k, p in events if k == "content")
        assert content_event == {"parts": self.PARTS}
        done = events[-1][1]
        assert done["reply"] == "Answer."
        assert done["content"] == self.PARTS
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["text"] == "Answer."
        assert turns[1]["content"] == self.PARTS

    def test_stream_mid_reply_block_is_flushed_not_typed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A closed block followed by prose is body text (false positive).
        full = "Syntax:\n" + self.TAIL + "\nUse it like so."
        self._mock_stream(monkeypatch, ["Syntax:\n", self.TAIL, "\nUse it like so."])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        assert "content" not in [k for k, _ in events]
        deltas = "".join(p["text"] for kind, p in events if kind == "delta")
        assert deltas == full  # everything streamed, nothing swallowed
        assert events[-1][1]["reply"] == full
        assert events[-1][1]["content"] == []

    def test_stream_invalid_terminal_tail_is_flushed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        full = "Answer.\n```curio.v1\n{broken\n```"
        self._mock_stream(monkeypatch, ["Answer.\n", "```curio.v1\n{broken\n```"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        assert "content" not in [k for k, _ in events]
        deltas = "".join(p["text"] for kind, p in events if kind == "delta")
        assert deltas == full
        assert events[-1][1]["reply"] == full

    def test_stream_ending_on_partial_marker_is_flushed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_stream(monkeypatch, ["Answer ``", "`cu"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        deltas = "".join(p["text"] for kind, p in events if kind == "delta")
        assert deltas == "Answer ```cu"
        assert events[-1][1]["reply"] == "Answer ```cu"

    def test_legacy_json_reply_passes_through_untouched(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Planner-style agents whose whole reply is machine JSON (no fence):
        # byte-identical passthrough for their legacy consumers.
        reply = '{"dataflow": {"nodes": [], "edges": []}}'
        self._mock_run(monkeypatch, [reply])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.get_json()["reply"] == reply
        assert r.get_json()["content"] == []


class TestQuotaAdmission:
    """Both run paths admit up to the daily limit, then 429 with a stable body
    (memo dev/22): a denied run consumes nothing and persists nothing."""

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def test_run_denied_after_limit_with_stable_429(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "2")
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", lambda c, m, **kw: "ok"
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        url = f"/api/agents/projects/{alice_project}/attachments/{att_id}/run"
        for _ in range(2):
            assert client.post(url, json={"message": "q"}, headers=_auth(token)).status_code == 200
        r = client.post(url, json={"message": "q3"}, headers=_auth(token))
        assert r.status_code == 429
        body = r.get_json()
        assert body["quota"] is True
        assert "resetAt" in body and "limit" in body["error"]
        # The denied message was not persisted to the session.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert len(turns) == 4  # two admitted exchanges only

    def test_stream_denied_with_plain_429_before_streaming(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "1")

        def _fake_stream(config, messages, **kwargs):
            yield "ok"

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _fake_stream
        )
        # The admitted first run's title call must not reach a real provider —
        # and must not consume the single quota slot (memo dev/25).
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda c, m, **kw: "Stream Title",
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        url = f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream"
        first = client.post(url, json={"message": "q"}, headers=_auth(token))
        first.get_data()
        assert first.status_code == 200
        r = client.post(url, json={"message": "q2"}, headers=_auth(token))
        assert r.status_code == 429
        assert r.mimetype == "application/json"
        assert r.get_json()["quota"] is True

    def test_invalid_request_consumes_no_quota(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "1")
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", lambda c, m, **kw: "ok"
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        # A 404 run (unknown attachment) must not consume the single slot.
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/ghost/run",
            json={"message": "q"}, headers=_auth(token),
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200


class TestProjectAgentDefaults:
    """Project-agent-default scope (memo dev/23): materialized at install,
    read-only effective view, dropped at uninstall, lazy for legacy installs."""

    COORD = "agent.chat-agent@1.0.0"

    def _install(self, client, token, project_id, coord=None):
        r = client.post(
            f"/api/agents/projects/{project_id}/install",
            json={"coord": coord or self.COORD},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)

    def _get(self, client, token, project_id, coord=None):
        return client.get(
            f"/api/agents/projects/{project_id}/defaults/{coord or self.COORD}",
            headers=_auth(token),
        )

    def test_install_materializes_and_get_returns_effective_view(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "5")
        _, token = user_and_token
        self._install(client, token, alice_project)
        r = self._get(client, token, alice_project)
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["coord"] == self.COORD
        assert body["name"] == "Chat"
        assert body["revision"] == 1
        assert body["settings"] == {}  # built-ins carry no settingsDefaults
        q = body["effective"]["quotas"]["runsPerDay"]
        assert q == {"value": 5, "usedToday": 0, "source": "deployment"}
        assert body["effective"]["cost"]["configured"] is False
        assert body["effective"]["cost"]["estimatedSpendTodayUsd"] is None
        # No-secrets provider summary from the request user's resolved config.
        res = body["effective"]["resources"]
        assert res["maxOutputTokens"] == {"value": 4096, "source": "deployment"}
        assert "provider" in res and "model" in res
        assert "api_key" not in res and "apiKey" not in res

    def test_used_today_reflects_runs(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", lambda c, m, **kw: "ok"
        )
        _, token = user_and_token
        self._install(client, token, alice_project)
        att = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        body = self._get(client, token, alice_project).get_json()
        assert body["effective"]["quotas"]["runsPerDay"]["usedToday"] == 1

    def test_not_installed_404_and_uninstall_drops(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        assert self._get(client, token, alice_project).status_code == 404
        self._install(client, token, alice_project)
        assert self._get(client, token, alice_project).status_code == 200
        client.delete(
            f"/api/agents/projects/{alice_project}/{self.COORD}", headers=_auth(token)
        )
        assert self._get(client, token, alice_project).status_code == 404

    def test_lazy_materialization_for_legacy_installs(self, client, user_and_token, tmp_curio, alice_project):
        # A lockfile entry written before the defaults section existed.
        from utk_curio.backend.app.projects import storage as projects_storage

        user, token = user_and_token
        self._install(client, token, alice_project)
        ukey = _user_dir_key(user)
        spec = projects_storage.read_spec(ukey, alice_project)
        del spec["dataflow"]["agentDefaults"]
        projects_storage.write_spec(ukey, alice_project, spec)
        r = self._get(client, token, alice_project)
        assert r.status_code == 200
        assert r.get_json()["revision"] == 1
        # And it persisted.
        spec = projects_storage.read_spec(ukey, alice_project)
        assert self.COORD in spec["dataflow"]["agentDefaults"]

    def test_records_are_per_project_and_survive_saves(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        self._install(client, token, alice_project)
        # A canvas save without agent sections must not wipe the record.
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert self._get(client, token, alice_project).status_code == 200
        # A second project gets its own independent record.
        other = client.post(
            "/api/projects",
            json={"name": "p2", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        ).get_json()["id"]
        assert self._get(client, token, other).status_code == 404
        self._install(client, token, other)
        assert self._get(client, token, other).status_code == 200

    def test_reinstall_does_not_reset_the_record(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.projects import storage as projects_storage

        user, token = user_and_token
        self._install(client, token, alice_project)
        ukey = _user_dir_key(user)
        spec = projects_storage.read_spec(ukey, alice_project)
        spec["dataflow"]["agentDefaults"][self.COORD]["revision"] = 7
        projects_storage.write_spec(ukey, alice_project, spec)
        self._install(client, token, alice_project)  # idempotent reinstall
        assert self._get(client, token, alice_project).get_json()["revision"] == 7


class TestSettingsScreensApi:
    """Account + project policy editing (memo dev/24): tighten-only, revisions,
    reset-to-default, and end-to-end enforcement of edited values."""

    COORD = "agent.chat-agent@1.0.0"

    def _install_and_attach(self, client, token, project_id):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.COORD}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _patch_account(self, client, token, revision, settings):
        return client.patch(
            "/api/agents/settings", json={"revision": revision, "settings": settings}, headers=_auth(token)
        )

    def _patch_project(self, client, token, project_id, revision, settings, coord=None):
        return client.patch(
            f"/api/agents/projects/{project_id}/defaults/{coord or self.COORD}",
            json={"revision": revision, "settings": settings},
            headers=_auth(token),
        )

    def test_account_get_patch_roundtrip_and_409(self, client, user_and_token, tmp_curio, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "100")
        _, token = user_and_token
        body = client.get("/api/agents/settings", headers=_auth(token)).get_json()
        assert body["revision"] == 1 and body["settings"] == {}
        assert body["effective"]["quotas"]["runsPerDay"]["source"] == "deployment"
        assert body["ceilings"]["quotas"]["runsPerDay"] == 100
        r = self._patch_account(client, token, 1, {"quotas": {"runsPerDay": 30}, "cost": {"estimatedCostPerRunUsd": 0.05}})
        assert r.status_code == 200, r.get_data(as_text=True)
        out = r.get_json()
        assert out["revision"] == 2
        assert out["effective"]["quotas"]["runsPerDay"] == {"value": 30, "source": "account"}
        # Stale revision → 409, no change.
        assert self._patch_account(client, token, 1, {}).status_code == 409
        assert client.get("/api/agents/settings", headers=_auth(token)).get_json()["revision"] == 2

    def test_tighten_only_400s(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "100")
        _, token = user_and_token
        r = self._patch_account(client, token, 1, {"quotas": {"runsPerDay": 500}})
        assert r.status_code == 400
        assert "inherited limit" in r.get_json()["error"]
        self._patch_account(client, token, 1, {"quotas": {"runsPerDay": 30}})
        self._install_and_attach(client, token, alice_project)
        r = self._patch_project(client, token, alice_project, 1, {"quotas": {"runsPerDay": 60}})
        assert r.status_code == 400
        r = self._patch_project(client, token, alice_project, 1, {"cost": {"estimatedCostPerRunUsd": 1}})
        assert r.status_code == 400  # estimate is account-only

    def test_project_limit_gates_runs_and_reset_restores(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "100")
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", lambda c, m, **kw: "ok"
        )
        _, token = user_and_token
        att = self._install_and_attach(client, token, alice_project)
        r = self._patch_project(client, token, alice_project, 1, {"quotas": {"runsPerDay": 1}})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["effective"]["quotas"]["runsPerDay"] == {
            "value": 1, "source": "project", "usedToday": 0,
        }
        url = f"/api/agents/projects/{alice_project}/attachments/{att}/run"
        assert client.post(url, json={"message": "q"}, headers=_auth(token)).status_code == 200
        denied = client.post(url, json={"message": "q"}, headers=_auth(token))
        assert denied.status_code == 429
        assert denied.get_json()["reason"] == "quota"
        assert "project run limit" in denied.get_json()["error"]
        # Reset to agent default clears the override → runs admit again.
        r = self._patch_project(client, token, alice_project, 2, {})
        assert r.get_json()["effective"]["quotas"]["runsPerDay"]["source"] == "deployment"
        assert client.post(url, json={"message": "q"}, headers=_auth(token)).status_code == 200

    def test_budget_gates_runs_with_budget_reason(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "100")
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", lambda c, m, **kw: "ok"
        )
        _, token = user_and_token
        att = self._install_and_attach(client, token, alice_project)
        self._patch_account(client, token, 1, {"cost": {"dailyBudgetUsd": 0.1, "estimatedCostPerRunUsd": 0.06}})
        url = f"/api/agents/projects/{alice_project}/attachments/{att}/run"
        assert client.post(url, json={"message": "q"}, headers=_auth(token)).status_code == 200
        denied = client.post(url, json={"message": "q"}, headers=_auth(token))
        assert denied.status_code == 429
        assert denied.get_json()["reason"] == "budget"
        assert "budget" in denied.get_json()["error"]
        # The GET view reports the estimated spend so far.
        body = client.get(
            f"/api/agents/projects/{alice_project}/defaults/{self.COORD}", headers=_auth(token)
        ).get_json()
        assert body["effective"]["cost"]["estimatedSpendTodayUsd"] == 0.06

    def test_max_output_tokens_reaches_the_provider(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # seen[0] is the conversation run; a first run adds the small-capped
        # title call after it (memo dev/25).
        seen = []

        def _fake(config, messages, max_output_tokens=None, **kwargs):
            seen.append(max_output_tokens)
            return "ok"

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake)
        _, token = user_and_token
        att = self._install_and_attach(client, token, alice_project)
        self._patch_project(client, token, alice_project, 1, {"resources": {"maxOutputTokens": 512}})
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert seen[0] == 512

    def test_patch_preserves_non_policy_seed_keys(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.projects import storage as projects_storage

        user, token = user_and_token
        self._install_and_attach(client, token, alice_project)
        ukey = _user_dir_key(user)
        spec = projects_storage.read_spec(ukey, alice_project)
        spec["dataflow"]["agentDefaults"][self.COORD]["settings"]["profileId"] = "seed-p"
        projects_storage.write_spec(ukey, alice_project, spec)
        r = self._patch_project(client, token, alice_project, 1, {"quotas": {"runsPerDay": 9}})
        assert r.status_code == 200
        assert r.get_json()["settings"] == {"profileId": "seed-p", "quotas": {"runsPerDay": 9}}


class TestMaterializePreamble:
    """Install materializes BOTH prompt assets (instruction + system preamble)."""

    def test_install_writes_preamble_and_instruction(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents import storage as agents_storage

        user, token = user_and_token
        coord = "agent.syntax-analysis-agent@1.0.0"
        r = client.post(
            f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token)
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        d = agents_storage.agent_definition_dir(_user_dir_key(user), coord)
        assert (d / "prompts/syntax_analysis_prompt.txt").is_file()
        assert (d / "prompts/syntax_analysis_preamble.txt").is_file()
