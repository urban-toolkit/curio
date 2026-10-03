"""Integration tests for the /api/agents attachment routes (routes/attachments.py).

Attaching agents to a node or the canvas, attachment intent, the chat
session and pruning."""

from __future__ import annotations

from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.projects.services import _user_dir_key

from utk_curio.backend.tests._support.agent_routes import _auth


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
            json={"coord": "agent.connection-builder@1.0.0", "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        assert r.status_code == 400

    def test_attach_bad_node_target_rejected(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.connection-builder@1.0.0"
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
            json={"coord": "agent.connection-builder@1.0.0"},
            headers=_auth(token),
        )
        assert r.status_code == 400


class TestPruneAttachmentsOnDelete:
    """Deleting a node on the canvas (a save whose spec no longer contains it)
    prunes the attachment bound to that node; canvas attachments survive."""

    def test_node_attachment_pruned_when_its_node_is_deleted(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        node_coord = "agent.node-content-builder@1.0.0"  # node-only
        canvas_coord = "agent.dataflow-builder@1.0.0"  # canvas-only
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
        # dataflow-builder is a canvas-only built-in.
        _, token = user_and_token
        coord = "agent.dataflow-builder@1.0.0"
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
        coord = "agent.node-content-builder@1.0.0"  # node-only
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

    def test_chat_declares_both_targets(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        by_id = {a["id"]: a for a in cat}
        assert sorted(by_id["agent.chat-agent"]["hooks"]) == ["canvas", "node"]

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
        from utk_curio.backend.app.agents.domain import builtin

        _, token = user_and_token
        card = self._attach_builtin(client, token, alice_project)
        # Same file the runtime resolves — no literal duplicated in the test either.
        assert card["intent"] == builtin.read_instruction_text("agent.chat-agent@1.0.0")
        assert card["intentEdited"] is False

    def test_patch_persists_and_null_restores(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents.domain import builtin

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

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
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
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.agents.domain import content as content_mod

        preamble = builtin.read_prompt_text("agent.chat-agent@1.0.0", "system")
        assert calls[0][0]["role"] == "system"
        assert calls[0][0]["content"].startswith(
            f"{preamble}\n\nanswer in one sentence\n\n{content_mod.TAIL_INSTRUCTION}"
        )


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
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        calls = []

        def _fake_run(config, messages, **kwargs):
            # Answer the post-first-run title call (memo dev/25) out of band so
            # `replies`/`calls` keep tracking the conversation runs only.
            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Session Test Title"
            calls.append(messages)
            return replies[len(calls) - 1]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
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

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _flaky)
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
        from utk_curio.backend.app.agents.repositories import sessions as sessions_mod

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
        from utk_curio.backend.app.agents.repositories import sessions as sessions_mod

        self._mock_provider(monkeypatch, ["a1"])
        user, token = user_and_token
        coord = "agent.node-content-builder@1.0.0"
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


class TestAttachRequiresGating:
    """dev/50 — compatibleTargets[].requires gets runtime meaning: a node
    target must match a declared template-id suffix; empty requires = any
    node (every pre-dev/50 agent byte-identical)."""

    FINDER = "agent.dataset-finder@1.0.0"

    def _project_with_nodes(self, client, token):
        body = {
            "name": "p",
            "spec": {"dataflow": {"nodes": [
                {"id": "load1", "type": "curio.builtin/data-loading", "content": ""},
                {"id": "comp1", "type": "curio.builtin/computation-analysis", "content": ""},
                {"id": "legacy1", "type": "DATA_LOADING", "content": ""},
                {"id": "ver1", "type": "curio.builtin/data-loading@1", "content": ""},
            ], "edges": [], "packages": []}},
            "outputs": [],
        }
        resp = client.post("/api/projects", json=body, headers=_auth(token))
        assert resp.status_code == 201
        return resp.get_json()["id"]

    def _attach(self, client, token, pid, target, coord=None):
        client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord or self.FINDER}, headers=_auth(token))
        return client.post(
            f"/api/agents/projects/{pid}/attachments",
            json={"coord": coord or self.FINDER, "target": target},
            headers=_auth(token),
        )

    def test_data_loading_node_attaches(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        pid = self._project_with_nodes(client, token)
        r = self._attach(client, token, pid, {"kind": "node", "targetId": "load1"})
        assert r.status_code == 201, r.get_data(as_text=True)

    def test_other_node_is_refused_naming_the_requirement(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        pid = self._project_with_nodes(client, token)
        r = self._attach(client, token, pid, {"kind": "node", "targetId": "comp1"})
        assert r.status_code == 400
        assert "data-loading" in r.get_json()["error"]

    def test_versioned_and_legacy_type_spellings_match(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        pid = self._project_with_nodes(client, token)
        assert self._attach(client, token, pid, {"kind": "node", "targetId": "ver1"}).status_code == 201
        assert self._attach(client, token, pid, {"kind": "node", "targetId": "legacy1"}).status_code == 201

    def test_canvas_attach_needs_no_node(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        pid = self._project_with_nodes(client, token)
        assert self._attach(client, token, pid, {"kind": "canvas"}).status_code == 201

    def test_empty_requires_agents_attach_to_any_node(self, client, user_and_token, tmp_curio):
        # Regression: pre-dev/50 agents (empty requires) are unaffected.
        _, token = user_and_token
        pid = self._project_with_nodes(client, token)
        r = self._attach(
            client, token, pid, {"kind": "node", "targetId": "comp1"},
            coord="agent.node-content-builder@1.0.0",
        )
        assert r.status_code == 201, r.get_data(as_text=True)
