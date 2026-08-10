"""dev/67-6 — the one node-context composer: bounded neighborhood, honest
runtime status, no fabrication."""

from __future__ import annotations

from utk_curio.backend.app.agents import node_context
from utk_curio.backend.app.execution import runtime_journal

KEY = "4242"
PID = "proj-ctx"


def _spec(n_chain=3, extra_edges=(), datasets=()):
    nodes = [
        {"id": f"n{i}", "type": "curio.builtin/computation-analysis",
         "goal": f"step {i}", "content": f"code{i}()" if i != 1 else ""}
        for i in range(n_chain)
    ]
    edges = [
        {"id": f"e{i}", "source": f"n{i}", "target": f"n{i+1}"}
        for i in range(n_chain - 1)
    ] + list(extra_edges)
    return {"dataflow": {"nodes": nodes, "edges": edges, "name": "wf",
                         "task": "analyze", "datasets": list(datasets)}}


class TestComposeNodeContext:
    def test_neighborhood_and_summary(self, tmp_curio):
        ctx = node_context.compose_node_context(KEY, PID, _spec(), "n1")
        assert ctx["nodeId"] == "n1"
        assert ctx["intent"] == "step 1"
        assert ctx["currentContent"] == ""  # the empty node, honestly
        assert [r["id"] for r in ctx["upstream"]] == ["n0"]
        assert [r["id"] for r in ctx["downstream"]] == ["n2"]
        assert ctx["upstream"][0]["hasContent"] is True
        assert ctx["upstream"][0]["runtimeStatus"] == "never-executed"
        assert ctx["graphSummary"] == {"name": "wf", "goal": "analyze",
                                       "nodes": 3, "edges": 2}

    def test_runtime_status_from_the_journal(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "n0", code="x", stdout=[], stderr="boom",
            output={"path": "", "dataType": "str"},
            started_at="2026-08-05T00:00:00Z", duration_ms=1,
        )
        ctx = node_context.compose_node_context(KEY, PID, _spec(), "n1")
        assert ctx["upstream"][0]["runtimeStatus"] == "error"

    def test_neighbors_are_nearest_first_and_capped(self, tmp_curio):
        # A 12-node chain upstream of the target: only the nearest 8 survive.
        spec = _spec(n_chain=13)
        ctx = node_context.compose_node_context(KEY, PID, spec, "n12")
        assert len(ctx["upstream"]) == 8
        assert ctx["upstream"][0]["id"] == "n11"  # nearest first

    def test_current_content_is_bounded(self, tmp_curio):
        spec = _spec()
        spec["dataflow"]["nodes"][1]["content"] = "y" * 9000
        ctx = node_context.compose_node_context(KEY, PID, spec, "n1")
        assert len(ctx["currentContent"]) < 9000
        assert "truncated" in ctx["currentContent"]

    def test_missing_node_is_none_and_datasets_project(self, tmp_curio):
        assert node_context.compose_node_context(KEY, PID, _spec(), "ghost") is None
        spec = _spec(datasets=[{"id": "d1", "name": "Heat 2024", "path": "secret"}])
        ctx = node_context.compose_node_context(KEY, PID, spec, "n1")
        assert ctx["datasetRefs"] == [{"id": "d1", "name": "Heat 2024"}]
