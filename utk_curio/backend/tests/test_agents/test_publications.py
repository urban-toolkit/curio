"""Tests for the shared publications catalog store (imported-only Publish)."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import publications
from utk_curio.backend.app.agents.manifest import AgentManifestError


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    return tmp_path


def _make_def_dir(tmp_path, coord="agent.my-custom@1.0.0"):
    d = tmp_path / "src" / coord
    d.mkdir(parents=True, exist_ok=True)
    agent_id, version = coord.rsplit("@", 1)
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "id": agent_id,
                "name": "Custom",
                "category": "node",
                "version": version,
                "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
                "provenance": {"publisher": "me", "trust": "imported"},
            }
        ),
        encoding="utf-8",
    )
    return d


class TestPublicationsStore:
    def test_empty(self, cwd):
        assert publications.list_published() == []
        assert publications.is_published("agent.my-custom@1.0.0") is False
        assert publications.get_published_manifest("agent.my-custom@1.0.0") is None

    def test_publish_list_get_unpublish(self, cwd, tmp_path):
        src = _make_def_dir(tmp_path)
        publications.publish_from_dir(src, "agent.my-custom@1.0.0")
        assert publications.is_published("agent.my-custom@1.0.0") is True
        assert [m.dir_name for m in publications.list_published()] == ["agent.my-custom@1.0.0"]
        m = publications.get_published_manifest("agent.my-custom@1.0.0")
        assert m is not None and m.agent_id == "agent.my-custom"
        assert publications.unpublish("agent.my-custom@1.0.0") is True
        assert publications.list_published() == []
        assert publications.unpublish("agent.my-custom@1.0.0") is False

    def test_republish_overwrites(self, cwd, tmp_path):
        src = _make_def_dir(tmp_path)
        publications.publish_from_dir(src, "agent.my-custom@1.0.0")
        publications.publish_from_dir(src, "agent.my-custom@1.0.0")  # idempotent
        assert len(publications.list_published()) == 1

    def test_traversal_blocked(self, cwd):
        with pytest.raises((AgentManifestError, Exception)):
            publications.published_agent_dir("../escape@1.0.0")
