"""dev/126: the plan-created node's agents — the ONE attach helper both apply
paths use.

The Node Builder attaches to any node; the Dataset Finder only to a
``data-loading`` one, which is its manifest's own declaration
(``compatibleTargets[].requires``) rather than a second predicate here.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import services

DF = "agent.dataset-finder@1.0.0"
NB = "agent.node-builder@1.0.0"


def _spec(*coords, node_type="curio.builtin/data-loading"):
    return {
        "dataflow": {
            "nodes": [{"id": "n1", "type": node_type}],
            "edges": [],
            "agents": list(coords),
            "agentAttachments": [],
        }
    }


class TestAttachPlanNodeAgents:
    def test_data_loading_node_gets_both(self):
        spec = _spec(NB, DF)
        out = services._attach_plan_node_agents("1", spec, "n1", "curio.builtin/data-loading")
        assert sorted(r["agentId"] for r in out["attached"]) == [
            "agent.dataset-finder", "agent.node-builder",
        ]
        assert out["skipped"] == []
        coords = {a["coord"] for a in spec["dataflow"]["agentAttachments"]}
        assert coords == {NB, DF}
        for record in spec["dataflow"]["agentAttachments"]:
            assert record["target"] == {"kind": "node", "targetId": "n1"}

    def test_non_data_loading_node_gets_only_the_builder(self):
        spec = _spec(NB, DF, node_type="curio.builtin/vis-vega")
        out = services._attach_plan_node_agents("1", spec, "n1", "curio.builtin/vis-vega")
        assert [r["agentId"] for r in out["attached"]] == ["agent.node-builder"]
        assert [r["agentId"] for r in out["skipped"]] == ["agent.dataset-finder"]
        assert "does not attach to vis-vega nodes" in out["skipped"][0]["reason"]
        assert [a["coord"] for a in spec["dataflow"]["agentAttachments"]] == [NB]

    def test_versioned_and_legacy_types_still_match(self):
        for node_type in ("curio.builtin/data-loading@2", "DATA_LOADING"):
            spec = _spec(NB, DF, node_type=node_type)
            out = services._attach_plan_node_agents("1", spec, "n1", node_type)
            assert len(out["attached"]) == 2, node_type

    def test_idempotent(self):
        spec = _spec(NB, DF)
        first = services._attach_plan_node_agents("1", spec, "n1", "curio.builtin/data-loading")
        second = services._attach_plan_node_agents("1", spec, "n1", "curio.builtin/data-loading")
        assert len(spec["dataflow"]["agentAttachments"]) == 2
        assert {r["status"] for r in second["attached"]} == {"existing"}
        assert second["byAgent"] == first["byAgent"]

    def test_uninstalled_agent_is_skipped_with_a_reason(self):
        spec = _spec(NB)  # no Dataset Finder in the lockfile
        out = services._attach_plan_node_agents("1", spec, "n1", "curio.builtin/data-loading")
        assert [r["agentId"] for r in out["attached"]] == ["agent.node-builder"]
        assert out["skipped"][0]["reason"] == "not installed in this dataflow"

    def test_missing_node_never_raises(self):
        spec = _spec(NB, DF)
        spec["dataflow"]["nodes"] = []
        out = services._attach_plan_node_agents("1", spec, "ghost", "curio.builtin/data-loading")
        assert out["attached"] == []
        assert len(out["skipped"]) == 2

    def test_legacy_wrapper_keeps_its_signature(self):
        spec = _spec(NB, DF)
        att_id = services._attach_node_builder(spec, "n1")
        assert att_id
        assert [a["coord"] for a in spec["dataflow"]["agentAttachments"]] == [NB]

    def test_the_remedy_sentence_has_one_source(self):
        spec = _spec(NB, DF)
        assert services._ungrounded_remedy(None).endswith("or give the path")
        services._attach_plan_node_agents("1", spec, "n1", "curio.builtin/data-loading")
        att_id = services._dataset_finder_attachment_id(spec, "n1")
        assert att_id
        assert "open Dataset Finder on this node" in services._ungrounded_remedy(att_id)
