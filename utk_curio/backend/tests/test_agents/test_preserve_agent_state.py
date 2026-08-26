"""Unit tests for ``project_agents.preserve_agent_state`` — the guard that keeps
the backend-owned agent sections from being wiped by a canvas save that omits
them."""

from utk_curio.backend.app.agents.project_agents import preserve_agent_state

AGENTS = ["agent.node-explainer@1.0.0"]
ATTACH = [{"attachmentId": "a1", "coord": "agent.node-explainer@1.0.0", "target": {"kind": "canvas"}}]


def _existing():
    return {"dataflow": {"nodes": [], "edges": [], "agents": list(AGENTS), "agentAttachments": list(ATTACH)}}


def test_carries_agents_and_attachments_when_client_omits_them():
    # Client save: a fresh dataflow with no agent sections.
    effective = {"dataflow": {"nodes": [{"id": "n1"}], "packages": ["curio.builtin@1"]}}
    out = preserve_agent_state(effective, _existing())
    assert out["dataflow"]["agents"] == AGENTS
    assert out["dataflow"]["agentAttachments"] == ATTACH
    # Client-authored sections are left intact.
    assert out["dataflow"]["nodes"] == [{"id": "n1"}]
    assert out["dataflow"]["packages"] == ["curio.builtin@1"]


def test_creates_dataflow_when_effective_has_none():
    out = preserve_agent_state({}, _existing())
    assert out["dataflow"]["agents"] == AGENTS
    assert out["dataflow"]["agentAttachments"] == ATTACH


def test_honors_an_explicitly_sent_section():
    # A client that DOES manage agents (even to empty) wins — no override.
    effective = {"dataflow": {"agents": [], "nodes": []}}
    out = preserve_agent_state(effective, _existing())
    assert out["dataflow"]["agents"] == []  # not clobbered by existing
    # The omitted attachments section is still carried forward.
    assert out["dataflow"]["agentAttachments"] == ATTACH


def test_noop_when_existing_has_no_agent_sections():
    effective = {"dataflow": {"nodes": [{"id": "n1"}]}}
    out = preserve_agent_state(effective, {"dataflow": {"nodes": []}})
    assert "agents" not in out["dataflow"]
    assert "agentAttachments" not in out["dataflow"]


def test_noop_for_missing_specs():
    assert preserve_agent_state(None, _existing()) is None
    same = {"dataflow": {"nodes": []}}
    assert preserve_agent_state(same, None) is same


def test_carries_agent_defaults_forward():
    # The per-template defaults section (memo dev/23) is backend-owned too.
    existing = {
        "dataflow": {
            "agents": ["agent.x@1.0.0"],
            "agentDefaults": {"agent.x@1.0.0": {"revision": 3, "settings": {"k": "v"}}},
        }
    }
    effective = {"dataflow": {"nodes": [{"id": "n1"}]}}
    out = preserve_agent_state(effective, existing)
    assert out["dataflow"]["agentDefaults"] == {
        "agent.x@1.0.0": {"revision": 3, "settings": {"k": "v"}}
    }
