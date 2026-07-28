"""Tests for tool contracts + grant resolution (memo dev/39, DEC-017)."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import tools
from utk_curio.backend.app.agents.manifest import ToolRequirement
from utk_curio.backend.app.agents.tools import ToolContract


def _req(tool_id: str, required: bool = False) -> ToolRequirement:
    return ToolRequirement(id=tool_id, required=required)


class TestRegistry:
    def test_registry_ships_empty(self):
        # v1 deliberately has no contracts: no consumer exists yet (dev/39 §4.4).
        assert tools.REGISTRY == {}

    def test_contract_validates_effect(self):
        with pytest.raises(ValueError):
            ToolContract(id="x.y", contract_version="1", effect="write", description="")


class TestGrantResolution:
    def test_empty_registry_grants_nothing(self):
        assert tools.resolve_grants([_req("dataset.read"), _req("node.read")]) == []

    def test_read_effect_contract_is_grantable(self, monkeypatch):
        monkeypatch.setitem(
            tools.REGISTRY,
            "dataset.read",
            ToolContract(id="dataset.read", contract_version="1", effect="read", description="d"),
        )
        assert tools.resolve_grants([_req("dataset.read")]) == ["dataset.read"]

    def test_mutate_effect_is_never_grantable(self, monkeypatch):
        # DEC-006 / REQ-REVIEW-001: no mutation grant until review-before-apply exists.
        monkeypatch.setitem(
            tools.REGISTRY,
            "node.create",
            ToolContract(id="node.create", contract_version="1", effect="mutate", description="d"),
        )
        assert tools.resolve_grants([_req("node.create")]) == []

    def test_unregistered_requests_resolve_silently(self, monkeypatch):
        monkeypatch.setitem(
            tools.REGISTRY,
            "dataset.read",
            ToolContract(id="dataset.read", contract_version="1", effect="read", description="d"),
        )
        granted = tools.resolve_grants([_req("dataset.read"), _req("ghost.tool")])
        assert granted == ["dataset.read"]


class TestMissingRequired:
    def test_optional_ungranted_is_not_missing(self):
        assert tools.missing_required([_req("ghost.tool", required=False)]) == []

    def test_required_ungranted_is_missing(self):
        assert tools.missing_required([_req("ghost.tool", required=True)]) == ["ghost.tool"]

    def test_required_granted_is_satisfied(self, monkeypatch):
        monkeypatch.setitem(
            tools.REGISTRY,
            "dataset.read",
            ToolContract(id="dataset.read", contract_version="1", effect="read", description="d"),
        )
        assert tools.missing_required([_req("dataset.read", required=True)]) == []

    def test_required_mutate_is_missing_even_when_registered(self, monkeypatch):
        monkeypatch.setitem(
            tools.REGISTRY,
            "node.create",
            ToolContract(id="node.create", contract_version="1", effect="mutate", description="d"),
        )
        assert tools.missing_required([_req("node.create", required=True)]) == ["node.create"]
