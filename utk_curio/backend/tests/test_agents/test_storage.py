"""Tests for the filesystem-backed agent lifecycle storage (Feature 3).

Covers the three FS aggregates that mirror the node-package catalog:
- ``storage``: the definition artifact store under ``.curio/users/<key>/agents/``.
- ``imports``: the account-level "My Imports" registry JSON.
- ``project_agents``: the per-project installed-template lockfile in the spec.

All storage roots derive from ``CURIO_LAUNCH_CWD``; the fixture points it at a
tmp dir so tests never touch a real ``.curio`` tree.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import imports, project_agents, storage
from utk_curio.backend.app.agents.manifest import AgentManifestError


@pytest.fixture
def user_key(tmp_path, monkeypatch):
    """Point the .curio storage root at a tmp dir and return a user key."""
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    return "42"


def _manifest_dict(agent_id="agent.node-explainer", version="1.0.0"):
    return {
        "id": agent_id,
        "name": "Node Explainer",
        "category": "node",
        "version": version,
        "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
        "provenance": {"publisher": "curio", "trust": "built-in"},
    }


def _write_definition(user_key, agent_id="agent.node-explainer", version="1.0.0"):
    d = storage.user_agents_dir(user_key) / f"{agent_id}@{version}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(_manifest_dict(agent_id, version)), encoding="utf-8")
    return d


# ── storage: definition artifact store ──────────────────────────────────────
class TestDefinitionStore:
    def test_dir_name_grammar(self):
        assert storage.AGENT_DIR_RE.match("agent.node-explainer@1.0.0")
        assert storage.AGENT_DIR_RE.match("agent.dataflow-builder@2.1.0-beta.1")
        assert not storage.AGENT_DIR_RE.match("curio.builtin@1")       # not an agent id
        assert not storage.AGENT_DIR_RE.match("agent.node-explainer@1")  # not semver

    def test_parse_dir_name(self):
        assert storage.parse_agent_dir_name("agent.node-explainer@1.0.0") == (
            "agent.node-explainer",
            "1.0.0",
        )
        with pytest.raises(AgentManifestError):
            storage.parse_agent_dir_name("nope")

    def test_empty_store_lists_nothing(self, user_key):
        assert storage.list_installed_agent_definitions(user_key) == []
        assert storage.load_installed_agent_definition(user_key, "agent.x@1.0.0") is None

    def test_load_and_list(self, user_key):
        _write_definition(user_key, "agent.node-explainer", "1.0.0")
        _write_definition(user_key, "agent.dataflow-builder", "1.0.0")
        listed = storage.list_installed_agent_definitions(user_key)
        assert [m.agent_id for m in listed] == ["agent.dataflow-builder", "agent.node-explainer"]
        one = storage.load_installed_agent_definition(user_key, "agent.node-explainer@1.0.0")
        assert one is not None and one.agent_id == "agent.node-explainer"

    def test_invalid_definition_is_skipped_not_fatal(self, user_key):
        _write_definition(user_key, "agent.node-explainer", "1.0.0")
        bad = storage.user_agents_dir(user_key) / "agent.broken@1.0.0"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "manifest.json").write_text("{not json", encoding="utf-8")
        listed = storage.list_installed_agent_definitions(user_key)
        assert [m.agent_id for m in listed] == ["agent.node-explainer"]

    def test_path_traversal_blocked(self, user_key):
        with pytest.raises(AgentManifestError):
            storage.agent_definition_dir(user_key, "../../escape@1.0.0")


# ── imports: My Imports registry ─────────────────────────────────────────────
class TestImportsRegistry:
    def test_missing_is_empty(self, user_key):
        assert imports.load_imported_agents(user_key) == set()

    def test_add_and_remove_roundtrip(self, user_key):
        imports.add_imported_agent(user_key, "agent.node-explainer@1.0.0")
        imports.add_imported_agent(user_key, "agent.dataflow-builder@1.0.0")
        assert imports.load_imported_agents(user_key) == {
            "agent.node-explainer@1.0.0",
            "agent.dataflow-builder@1.0.0",
        }
        imports.remove_imported_agent(user_key, "agent.node-explainer@1.0.0")
        assert imports.load_imported_agents(user_key) == {"agent.dataflow-builder@1.0.0"}

    def test_add_is_idempotent(self, user_key):
        imports.add_imported_agent(user_key, "agent.node-explainer@1.0.0")
        imports.add_imported_agent(user_key, "agent.node-explainer@1.0.0")
        assert imports.load_imported_agents(user_key) == {"agent.node-explainer@1.0.0"}

    def test_add_invalid_coord_rejected(self, user_key):
        with pytest.raises(ValueError):
            imports.add_imported_agent(user_key, "curio.builtin@1")

    def test_corrupt_file_treated_as_empty(self, user_key):
        path = storage._users_base() / "42" / "imported-agents.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        assert imports.load_imported_agents(user_key) == set()


# ── project_agents: per-project lockfile ─────────────────────────────────────
class TestProjectLockfile:
    def test_empty_spec(self):
        assert project_agents.project_agents(None) == []
        assert project_agents.project_agents({}) == []
        assert project_agents.project_agents({"dataflow": {}}) == []

    def test_read_declared(self):
        spec = {"dataflow": {"agents": ["agent.node-explainer@1.0.0", "curio.builtin@1", "junk"]}}
        # invalid coordinates are filtered out
        assert project_agents.project_agents(spec) == ["agent.node-explainer@1.0.0"]

    def test_set_creates_dataflow_and_sorts(self):
        spec: dict = {}
        out = project_agents.set_project_agents(
            spec, ["agent.node-explainer@1.0.0", "agent.dataflow-builder@1.0.0"]
        )
        assert out["dataflow"]["agents"] == [
            "agent.dataflow-builder@1.0.0",
            "agent.node-explainer@1.0.0",
        ]
        assert out is spec  # mutates in place

    def test_set_filters_invalid(self):
        out = project_agents.set_project_agents({}, ["agent.x@1.0.0", "bad", "curio.builtin@1"])
        assert out["dataflow"]["agents"] == ["agent.x@1.0.0"]
