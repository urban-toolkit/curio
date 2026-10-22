"""Integration tests for the /api/agents lifecycle routes (routes/lifecycle.py).

Installing agents into a project, uninstalling them, and the bytes an
install materializes."""

from __future__ import annotations

import json

from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.projects.services import _user_dir_key

from utk_curio.backend.tests._support.agent_routes import (
    _auth,
    _write_def,
)


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
            json={"coord": "agent.test.ghost@1"},
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

    # ── dev/106: the requiresAgents closure ─────────────────────────────
    DFB = "agent.curio.dataflow-builder@1"
    # dev/126: the Dataset Finder (resolution delegates dataset.discover from
    # a server path) and the Node Builder (every plan-created node is given
    # one at Apply, and Solve writes content through its content mode), in
    # the Dataflow Builder's own declaration order.
    DF = "agent.curio.dataset-finder@1"
    NB = "agent.curio.node-builder@1"
    CLOSURE = [DF, NB]

    def test_installing_the_builder_installs_its_required_specialist_in_one_write(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        from utk_curio.backend.app.projects import storage as projects_storage

        writes = []
        real = projects_storage.write_spec
        monkeypatch.setattr(
            'utk_curio.backend.app.projects.storage.write_spec',
            lambda *a, **k: (writes.append(1), real(*a, **k))[1],
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": self.DFB}, headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        body = r.get_json()
        assert body["agents"] == sorted([self.DFB, *self.CLOSURE])
        assert body["installed"] == [self.DFB, *self.CLOSURE]
        assert body["required"] == self.CLOSURE
        assert len(writes) == 1  # atomic: root + closure in one spec write
        # The dependency's bytes are materialized (AC-5) — no import row added.
        assert storage.load_installed_agent_definition(_user_dir_key(user), self.NB) is not None
        assert client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"] == []

    def test_reinstall_with_satisfied_closure_is_idempotent(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": self.DFB}, headers=_auth(token))
        r = client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": self.DFB}, headers=_auth(token))
        assert r.status_code == 201
        assert r.get_json()["installed"] == []
        assert r.get_json()["agents"] == sorted([self.DFB, *self.CLOSURE])

    def test_dependency_already_installed_adds_only_the_root(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        # The Dataset Finder requires nothing, so this installs it alone.
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": self.DF}, headers=_auth(token))
        r = client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": self.DFB}, headers=_auth(token))
        # The already-installed member is not re-added; the rest of the
        # closure is (dev/126).
        assert r.get_json()["installed"] == [self.DFB, self.NB]
        assert sorted(r.get_json()["agents"]) == sorted([self.DFB, *self.CLOSURE])

    def test_unresolvable_dependency_409s_and_writes_nothing(self, client, user_and_token, tmp_curio, alice_project):
        user, token = user_and_token
        key = _user_dir_key(user)
        d = storage.user_agents_dir(key) / "agent.test.needy@1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({
            "id": "agent.test.needy", "name": "Needy", "category": "node", "version": "1.0.0",
            "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
            "compatibleTargets": [{"kind": "node", "requires": []}],
            "delegatesTo": ["agent.curio.node-builder", "agent.test.ghost"],
            "requiresAgents": ["agent.curio.node-builder", "agent.test.ghost"],
            "provenance": {"publisher": "curio", "trust": "imported"},
        }), encoding="utf-8")
        r = client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": "agent.test.needy@1"}, headers=_auth(token),
        )
        assert r.status_code == 409
        assert "agent.test.ghost" in r.get_json()["error"]
        assert "nothing was installed" in r.get_json()["error"]
        listed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()
        assert listed["agents"] == []  # not even the resolvable Node Builder landed

    def test_uninstalling_a_required_dependency_409s_naming_the_dependent(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": self.DFB}, headers=_auth(token))
        for dependency in self.CLOSURE:
            r = client.delete(f"/api/agents/projects/{alice_project}/{dependency}", headers=_auth(token))
            assert r.status_code == 409, dependency
            assert "Dataflow Builder" in r.get_json()["error"]
        # dev/126: the Dataset Finder is required by the Node Builder too, so
        # its refusal names both dependents.
        r = client.delete(f"/api/agents/projects/{alice_project}/{self.DF}", headers=_auth(token))
        assert "Node Builder" in r.get_json()["error"]
        # Parent first, then the dependencies — no cascade either way.
        assert client.delete(f"/api/agents/projects/{alice_project}/{self.DFB}", headers=_auth(token)).status_code == 200
        listed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()
        assert sorted(a["dirName"] for a in listed["agents"]) == sorted(self.CLOSURE)
        # The Node Builder still requires the Dataset Finder: builder first.
        assert client.delete(f"/api/agents/projects/{alice_project}/{self.DF}", headers=_auth(token)).status_code == 409
        assert client.delete(f"/api/agents/projects/{alice_project}/{self.NB}", headers=_auth(token)).status_code == 200
        assert client.delete(f"/api/agents/projects/{alice_project}/{self.DF}", headers=_auth(token)).status_code == 200
        # Every member of the closure is gone, one by one.
        listed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()
        assert listed["agents"] == []

    def test_catalog_cards_disclose_requires_agents_per_project(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        cat = client.get(f"/api/agents/catalog?projectId={alice_project}", headers=_auth(token)).get_json()["agents"]
        dfb = next(a for a in cat if a["dirName"] == self.DFB)
        assert dfb["requiresAgents"] == [
            {"id": "agent.curio.dataset-finder", "name": "Dataset Finder",
             "coord": self.DF, "visible": True, "installedInProject": False},
            {"id": "agent.curio.node-builder", "name": "Node Builder",
             "coord": self.NB, "visible": True, "installedInProject": False},
        ]
        # The Dataset Finder is the member that requires nothing.
        df = next(a for a in cat if a["dirName"] == self.DF)
        assert df["requiresAgents"] == []
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": self.DF}, headers=_auth(token))
        cat = client.get(f"/api/agents/catalog?projectId={alice_project}", headers=_auth(token)).get_json()["agents"]
        dfb = next(a for a in cat if a["dirName"] == self.DFB)
        assert dfb["requiresAgents"][0]["installedInProject"] is True
        assert dfb["requiresAgents"][1]["installedInProject"] is False
        installed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()["agents"]
        assert installed[0]["requiresAgents"] == []

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


class TestMaterialize:
    def test_installing_a_builtin_materializes_its_bytes(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents.repositories import storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        coord = "agent.curio.dataset-finder@1"
        # Not in the store before install (it's a built-in resolved from the roster).
        assert storage.load_installed_agent_definition(_user_dir_key(user), coord) is None
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord}, headers=_auth(token),
        )
        # After install, the definition + its prompt asset are on disk in the store.
        d = storage.agent_definition_dir(_user_dir_key(user), coord)
        assert (d / "manifest.json").is_file()
        assert (d / "prompts" / "discovery_instruction.md").is_file()

    def test_materialized_builtin_is_not_publishable(self, client, user_and_token, tmp_curio):
        # Even after its bytes are in the store, a built-in stays non-publishable.
        _, token = user_and_token
        coord = "agent.curio.dataset-finder@1"
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        by_id = {a["id"]: a for a in client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]}
        assert by_id["agent.curio.dataset-finder"]["publishable"] is False
        r = client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token))
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
        coord = _write_def(user, "agent.test.my-agent")
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
        coord = "agent.curio.researcher@1"  # dual-compatible, so a canvas attachment is valid
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
        coord = _write_def(user, "agent.test.my-agent")
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


class TestMaterializationHeal:
    """Stale built-in store copies self-heal on install/import (memo dev/44)."""

    def test_pre_dev38_copy_gains_the_system_asset(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.agents.repositories import storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        ukey = _user_dir_key(user)
        coord = "agent.curio.node-builder@1"
        # Fabricate the stale pre-dev/38 store copy: instruction only. A copy
        # that old has no modes either, so no capability names a prompt of its
        # own and no delegatesTo entry names the agent itself.
        manifest = catalog.builtin_definition_bundle(coord)["manifest"]
        stale = dict(manifest)
        stale["prompts"] = {"instruction": manifest["prompts"]["instruction"]}
        stale["capabilities"] = [
            {"id": c["id"], "contractVersion": c["contractVersion"]} for c in manifest["capabilities"]
        ]
        stale["delegatesTo"] = [
            d for d in manifest["delegatesTo"] if not isinstance(d, dict) or d["id"] != manifest["id"]
        ]
        storage.write_definition(
            ukey, coord, stale,
            {manifest["prompts"]["instruction"]["path"]: "old instruction bytes"},
        )
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord}, headers=_auth(token),
        )
        healed = storage.load_installed_agent_definition(ukey, coord)
        # Every prompt the shipped manifest declares, the preamble included.
        assert set(healed.prompts) == set(builtin.get_builtin_manifest(coord).prompts) >= {"system", "instruction"}
        base = storage.agent_definition_dir(ukey, coord)
        for asset in healed.prompts.values():
            assert (base / asset.path).is_file()

    def test_complete_copy_is_untouched(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents.repositories import storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        ukey = _user_dir_key(user)
        coord = "agent.curio.node-builder@1"
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
        manifest_path = storage.agent_definition_dir(ukey, coord) / "manifest.json"
        before = manifest_path.stat().st_mtime_ns, manifest_path.read_bytes()
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
        assert (manifest_path.stat().st_mtime_ns, manifest_path.read_bytes()) == before

    def test_imported_shadow_is_never_overwritten(self, client, user_and_token, tmp_curio):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        ukey = _user_dir_key(user)
        # An owned imported definition deliberately shadowing a built-in coord.
        coord = _write_def(user, "agent.curio.node-builder")
        catalog._materialize_definition(ukey, coord)
        from utk_curio.backend.app.agents.repositories import storage

        kept = storage.load_installed_agent_definition(ukey, coord)
        assert kept.provenance.trust == "imported"  # bytes untouched


class TestMaterializePreamble:
    """Install materializes BOTH prompt assets (instruction + system preamble)."""

    def test_install_writes_preamble_and_instruction(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.agents.repositories import storage as agents_storage

        user, token = user_and_token
        coord = "agent.curio.dataset-finder@1"
        r = client.post(
            f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token)
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        d = agents_storage.agent_definition_dir(_user_dir_key(user), coord)
        assert (d / "prompts/discovery_instruction.md").is_file()
        assert (d / "prompts/default_preamble.md").is_file()


class TestBuiltinPromptPropagation:
    """dev/60 — roster bytes reach existing installs: the user's 'clear the
    canvas' refusal came from a STALE materialized instruction."""

    COORD = "agent.curio.dataflow-builder@1"

    def _install_with_stale_instruction(self, client, user, token, project_id):
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.agents.repositories import storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.COORD}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        # Simulate a pre-dev/59 install: overwrite the materialized copy with
        # the superseded posture.
        key = _user_dir_key(user)
        base = storage.agent_definition_dir(key, self.COORD)
        instruction = base / builtin.get_builtin_manifest(self.COORD).prompts["instruction"].path
        stale = "Plans are ADDITIVE: removals are theirs to make on the canvas."
        instruction.write_text(stale, encoding="utf-8")
        return att_id, key, base, instruction

    def test_run_composes_current_roster_bytes_over_a_stale_store_copy(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _, _, _ = self._install_with_stale_instruction(client, user, token, alice_project)
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return "ok"

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "clear the canvas"}, headers=_auth(token),
        )
        assert r.status_code == 200
        system = calls[0][0]["content"]
        # The dev/59 posture — not the stale materialized bytes.
        assert "Never remove uninvited" in system
        assert "removals are theirs to make" not in system

    def test_reinstall_heals_drifted_bytes_on_disk(self, client, user_and_token, tmp_curio, alice_project):
        user, token = user_and_token
        _, key, base, instruction = self._install_with_stale_instruction(client, user, token, alice_project)
        # A fresh install (another project is enough) re-materializes.
        body = {"name": "p2", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
        p2 = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        client.post(f"/api/agents/projects/{p2}/install", json={"coord": self.COORD}, headers=_auth(token))
        from utk_curio.backend.app.agents.domain import builtin

        on_disk = instruction.read_text(encoding="utf-8")
        assert on_disk == builtin.read_prompt_text(self.COORD, "instruction")

    def test_owned_import_shadow_keeps_its_bytes(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A deliberate user shadow of a built-in coord is authoritative for
        # its OWN bytes — dev/60 must not steamroll it (regression).
        user, token = user_and_token
        manifest = {
            "id": "agent.curio.dataflow-builder", "name": "My Builder", "category": "canvas",
            "version": "1.0.0", "purpose": "mine",
            "capabilities": [{"id": "dataflow.orchestrate", "contractVersion": "1"}],
            "prompts": {
                "system": {"path": "prompts/preamble.txt", "variables": []},
                "instruction": {"path": "prompts/mine.txt", "variables": []},
            },
            "compatibleTargets": [{"kind": "canvas", "requires": []}],
            "inputs": {"reads": ["mission"], "requiredConfig": []},
            "runtime": {"execution": "foreground", "reviewPolicy": "report-only"},
            "providerRequirements": {"capabilities": ["structured-output"]},
            "provenance": {"publisher": "me", "license": "MIT", "trust": "imported"},
        }
        r = client.post(
            "/api/agents/imports/upload",
            json={"manifest": manifest, "prompts": {
                "prompts/preamble.txt": "my preamble",
                "prompts/mine.txt": "MY OWN INSTRUCTION BYTES",
            }},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": self.COORD}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return "ok"

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "hi"}, headers=_auth(token),
        )
        assert "MY OWN INSTRUCTION BYTES" in calls[0][0]["content"]
