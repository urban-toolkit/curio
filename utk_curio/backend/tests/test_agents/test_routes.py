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
                "provenance": {"publisher": "curio", "trust": "built-in"},
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
