"""Tests for :mod:`utk_curio.backend.app.agents.manifest`.

Mirrors the node-package manifest tests: a valid baseline plus one failing
case per invariant, with special attention to the capability-id rules (the
point of this module) and the prompt-asset path containment.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.manifest import (
    AgentManifestError,
    load_agent_manifest,
    parse_agent_manifest,
)


def _valid_manifest() -> dict:
    """A minimal-but-complete valid agent manifest (Node Explainer shape)."""
    return {
        "$schema": "../../docs/schemas/agent-package.v1.json",
        "id": "agent.node-explainer",
        "name": "Node Explainer",
        "category": "node",
        "version": "1.0.0",
        "purpose": "Explain what a node or its output does.",
        "roles": ["explanation"],
        "capabilities": [
            {"id": "node.explain", "contractVersion": "1"},
            {"id": "node.output.interpret", "contractVersion": "1"},
        ],
        "delegatesTo": ["agent.node-builder"],
        "prompts": {
            "system": {"path": "prompts/default_preamble.txt", "sha256": "abc", "variables": []},
            "instruction": {
                "path": "prompts/single_box_explanation.txt",
                "sha256": "def",
                "variables": ["nodeContext"],
            },
        },
        "compatibleTargets": [{"kind": "node", "requires": ["code-or-output"]}],
        "inputs": {"reads": ["nodeContext"], "requiredConfig": []},
        "outputs": ["explanation"],
        "runtime": {"execution": "foreground", "reviewPolicy": "report-only"},
        "providerRequirements": {"capabilities": ["structured-output"]},
        "tools": [{"id": "catalog.search", "required": False}],
        "settingsDefaults": {"profileId": "interactive-report", "profileVersion": "1"},
        "provenance": {"publisher": "curio", "license": "MIT", "trust": "built-in"},
    }


class TestValidManifest:
    def test_parses_core_fields(self):
        m = parse_agent_manifest(_valid_manifest())
        assert m.agent_id == "agent.node-explainer"
        assert m.version == "1.0.0"
        assert m.category == "node"
        assert m.capability_ids == ["node.explain", "node.output.interpret"]
        assert m.delegates_to == ["agent.node-builder"]
        assert m.dir_name == "agent.node-explainer@1.0.0"

    def test_parses_prompts_targets_runtime(self):
        m = parse_agent_manifest(_valid_manifest())
        assert set(m.prompts) == {"system", "instruction"}
        assert m.prompts["instruction"].variables == ["nodeContext"]
        assert m.compatible_targets[0].kind == "node"
        assert m.execution == "foreground"
        assert m.review_policy == "report-only"
        assert m.settings_profile_id == "interactive-report"
        assert m.provenance.trust == "built-in"

    def test_composite_capability_ids_accepted(self):
        raw = _valid_manifest()
        raw["id"] = "agent.dataflow-builder"
        raw["category"] = "canvas"
        raw["capabilities"] = [{"id": "dataflow.orchestrate", "contractVersion": "1"}]
        raw["delegatesTo"] = ["agent.dataset-finder", "agent.node-builder"]
        raw.pop("compatibleTargets")
        m = parse_agent_manifest(raw)
        assert m.capability_ids == ["dataflow.orchestrate"]

    def test_package_capability_ids_accepted(self):
        raw = _valid_manifest()
        raw["id"] = "agent.package-recommendation"
        raw["category"] = "package"
        raw["capabilities"] = [
            {"id": "package.recommend", "contractVersion": "1"},
            {"id": "package.identify", "contractVersion": "1"},
        ]
        m = parse_agent_manifest(raw)
        assert m.capability_ids == ["package.recommend", "package.identify"]


class TestAgentId:
    def test_missing_agent_prefix_rejected(self):
        raw = _valid_manifest()
        raw["id"] = "curio.node-explainer"
        with pytest.raises(AgentManifestError, match="must begin with 'agent.'"):
            parse_agent_manifest(raw)

    def test_uppercase_rejected(self):
        raw = _valid_manifest()
        raw["id"] = "agent.NodeExplainer"
        with pytest.raises(AgentManifestError):
            parse_agent_manifest(raw)

    def test_delegates_to_self_rejected(self):
        raw = _valid_manifest()
        raw["delegatesTo"] = ["agent.node-explainer"]
        with pytest.raises(AgentManifestError, match="must not reference the agent itself"):
            parse_agent_manifest(raw)

    def test_delegates_to_non_agent_id_rejected(self):
        raw = _valid_manifest()
        raw["delegatesTo"] = ["curio.builtin"]
        with pytest.raises(AgentManifestError, match="must be an agent id"):
            parse_agent_manifest(raw)


class TestRequiresAgents:
    """dev/106: hard dependencies are a validated subset of delegatesTo."""

    def test_absent_defaults_to_empty(self):
        assert parse_agent_manifest(_valid_manifest()).requires_agents == []

    def test_subset_of_delegates_parses(self):
        raw = _valid_manifest()
        raw["delegatesTo"] = ["agent.node-content-builder", "agent.node-researcher"]
        raw["requiresAgents"] = ["agent.node-content-builder"]
        assert parse_agent_manifest(raw).requires_agents == ["agent.node-content-builder"]

    def test_not_in_delegates_rejected(self):
        raw = _valid_manifest()
        raw["delegatesTo"] = ["agent.node-researcher"]
        raw["requiresAgents"] = ["agent.node-content-builder"]
        with pytest.raises(AgentManifestError, match="must also be listed in delegatesTo"):
            parse_agent_manifest(raw)

    def test_self_rejected(self):
        raw = _valid_manifest()
        raw["requiresAgents"] = ["agent.node-explainer"]
        with pytest.raises(AgentManifestError, match="must not reference the agent itself"):
            parse_agent_manifest(raw)

    def test_non_agent_id_rejected(self):
        raw = _valid_manifest()
        raw["delegatesTo"] = ["agent.node-content-builder"]
        raw["requiresAgents"] = ["curio.builtin"]
        with pytest.raises(AgentManifestError, match="must be an agent id"):
            parse_agent_manifest(raw)

    def test_duplicate_rejected(self):
        raw = _valid_manifest()
        raw["delegatesTo"] = ["agent.node-content-builder"]
        raw["requiresAgents"] = ["agent.node-content-builder", "agent.node-content-builder"]
        with pytest.raises(AgentManifestError, match="duplicate"):
            parse_agent_manifest(raw)

    def test_not_a_list_rejected(self):
        raw = _valid_manifest()
        raw["requiresAgents"] = "agent.node-content-builder"
        with pytest.raises(AgentManifestError, match="must be a list"):
            parse_agent_manifest(raw)


class TestCapabilityIdRules:
    """The core invariant: capability ids are behavior contracts, never asset paths."""

    @pytest.mark.parametrize(
        "bad_id",
        [
            "node_explain_prompt",       # underscore + prompt token
            "prompts/single_box.txt",    # path separator + .txt
            "single_box_explanation.txt",  # prompt filename
            "explain",                   # single segment (no namespace)
            "Node.Explain",              # uppercase
            "node..explain",             # empty segment
            "node.explain.",             # trailing dot
        ],
    )
    def test_rejected_capability_ids(self, bad_id):
        raw = _valid_manifest()
        raw["capabilities"] = [{"id": bad_id, "contractVersion": "1"}]
        with pytest.raises(AgentManifestError):
            parse_agent_manifest(raw)

    def test_underscore_message_mentions_forbidden_token(self):
        raw = _valid_manifest()
        raw["capabilities"] = [{"id": "node_explain", "contractVersion": "1"}]
        with pytest.raises(AgentManifestError, match="not contain"):
            parse_agent_manifest(raw)

    def test_missing_contract_version_rejected(self):
        raw = _valid_manifest()
        raw["capabilities"] = [{"id": "node.explain"}]
        with pytest.raises(AgentManifestError, match="contractVersion"):
            parse_agent_manifest(raw)

    def test_empty_capabilities_rejected(self):
        raw = _valid_manifest()
        raw["capabilities"] = []
        with pytest.raises(AgentManifestError, match="non-empty list"):
            parse_agent_manifest(raw)

    def test_duplicate_capabilities_rejected(self):
        raw = _valid_manifest()
        raw["capabilities"] = [
            {"id": "node.explain", "contractVersion": "1"},
            {"id": "node.explain", "contractVersion": "2"},
        ]
        with pytest.raises(AgentManifestError, match="duplicate capability id"):
            parse_agent_manifest(raw)


class TestPromptAssetPaths:
    def test_absolute_path_rejected(self):
        raw = _valid_manifest()
        raw["prompts"]["system"]["path"] = "/etc/passwd"
        with pytest.raises(AgentManifestError, match="not absolute"):
            parse_agent_manifest(raw)

    def test_parent_escape_rejected(self):
        raw = _valid_manifest()
        raw["prompts"]["system"]["path"] = "../../secrets.txt"
        with pytest.raises(AgentManifestError, match="escape the package"):
            parse_agent_manifest(raw)


class TestOtherFields:
    def test_bad_category_rejected(self):
        raw = _valid_manifest()
        raw["category"] = "widget"
        with pytest.raises(AgentManifestError, match="category"):
            parse_agent_manifest(raw)

    def test_bad_version_rejected(self):
        raw = _valid_manifest()
        raw["version"] = "v1"
        with pytest.raises(AgentManifestError, match="semver"):
            parse_agent_manifest(raw)

    def test_bad_execution_rejected(self):
        raw = _valid_manifest()
        raw["runtime"]["execution"] = "async"
        with pytest.raises(AgentManifestError, match="execution"):
            parse_agent_manifest(raw)

    def test_bad_review_policy_rejected(self):
        raw = _valid_manifest()
        raw["runtime"]["reviewPolicy"] = "auto-apply"
        with pytest.raises(AgentManifestError, match="reviewPolicy"):
            parse_agent_manifest(raw)

    def test_missing_publisher_rejected(self):
        raw = _valid_manifest()
        raw["provenance"] = {"license": "MIT"}
        with pytest.raises(AgentManifestError, match="publisher"):
            parse_agent_manifest(raw)

    def test_bad_trust_tier_rejected(self):
        raw = _valid_manifest()
        raw["provenance"]["trust"] = "trusted"
        with pytest.raises(AgentManifestError, match="trust"):
            parse_agent_manifest(raw)


class TestToolRequirements:
    """Manifest tools are typed, allowlisted requirements (dev/39, DEC-017):
    capability-id grammar, no duplicates, never grants."""

    def test_valid_tools_parse_with_required_flag(self):
        raw = _valid_manifest()
        raw["tools"] = [{"id": "catalog.search"}, {"id": "dataset.read", "required": True}]
        m = parse_agent_manifest(raw)
        assert [(t.id, t.required) for t in m.tools] == [
            ("catalog.search", False),
            ("dataset.read", True),
        ]

    def test_tool_id_must_match_the_capability_grammar(self):
        for bad in ("Search", "catalog", "catalog/search", "catalog_search", "fetch_prompt.txt"):
            raw = _valid_manifest()
            raw["tools"] = [{"id": bad}]
            with pytest.raises(AgentManifestError, match="tools"):
                parse_agent_manifest(raw)

    def test_duplicate_tool_ids_rejected(self):
        raw = _valid_manifest()
        raw["tools"] = [{"id": "catalog.search"}, {"id": "catalog.search", "required": True}]
        with pytest.raises(AgentManifestError, match="duplicate tool id"):
            parse_agent_manifest(raw)

    def test_required_must_be_boolean(self):
        raw = _valid_manifest()
        raw["tools"] = [{"id": "catalog.search", "required": "yes"}]
        with pytest.raises(AgentManifestError, match="required"):
            parse_agent_manifest(raw)


class TestLoadFromDisk:
    def test_loads_valid_dir(self, tmp_path):
        d = tmp_path / "agent.node-explainer@1.0.0"
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps(_valid_manifest()), encoding="utf-8")
        m = load_agent_manifest(d)
        assert m.agent_id == "agent.node-explainer"

    def test_dir_name_mismatch_rejected(self, tmp_path):
        d = tmp_path / "agent.node-explainer@2.0.0"
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps(_valid_manifest()), encoding="utf-8")
        with pytest.raises(AgentManifestError, match="does not match"):
            load_agent_manifest(d)

    def test_missing_manifest_rejected(self, tmp_path):
        d = tmp_path / "agent.node-explainer@1.0.0"
        d.mkdir()
        with pytest.raises(AgentManifestError, match="missing manifest.json"):
            load_agent_manifest(d)

    def test_invalid_json_rejected(self, tmp_path):
        d = tmp_path / "agent.node-explainer@1.0.0"
        d.mkdir()
        (d / "manifest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(AgentManifestError, match="invalid JSON"):
            load_agent_manifest(d)
