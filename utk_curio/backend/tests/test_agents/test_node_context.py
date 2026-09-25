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

    def test_thin_installed_refs_are_read_by_their_real_keys(self, tmp_curio):
        # dev/114: the datasets domain writes ``{datasetId, dirName, origin,
        # …}`` for an installed dataset; reading only the fat ``id``/``name``
        # keys sent every child ``{"id": null, "name": ""}``.
        spec = _spec(datasets=[
            {"datasetId": "ds-acs", "dirName": "census-acs@1", "origin": "hub",
             "producerNodeId": None, "consumerNodeIds": [], "installedAt": "2026-09-08T00:00:00Z"},
        ])
        ctx = node_context.compose_node_context(KEY, PID, spec, "n1")
        assert ctx["datasetRefs"] == [{"id": "ds-acs", "name": "census-acs@1", "origin": "hub"}]


class TestTheRuntimeBlock:
    """dev/135: the status WORD was all a child ever got. The owner's
    `a29d1ad8` had a Vega node visibly red with a message on screen, and the
    agent attached to it was told `never-executed`."""

    VEGA_ERROR = "outputs is not a valid input type for the 2D Plot (Vega-Lite)"

    def test_a_browser_failure_reaches_the_context_with_its_message(self, tmp_curio):
        runtime_journal.record_browser_execution(
            KEY, PID, "n1", status="error", message=self.VEGA_ERROR, duration_ms=12,
        )
        ctx = node_context.compose_node_context(KEY, PID, _spec(), "n1")
        assert ctx["runtimeStatus"] == "error"          # the legacy word, unchanged
        runtime = ctx["runtime"]
        assert runtime["status"] == "error"
        assert runtime["message"] == self.VEGA_ERROR
        assert runtime["origin"] == "browser"
        assert runtime["durationMs"] == 12
        assert runtime["ranAt"]

    def test_a_failed_UPSTREAM_carries_its_reason_too(self, tmp_curio):
        """The commonest reason a node cannot be fixed in isolation."""
        runtime_journal.record_browser_execution(
            KEY, PID, "n0", status="error", message="upstream blew up",
        )
        ctx = node_context.compose_node_context(KEY, PID, _spec(), "n1")
        upstream = ctx["upstream"][0]
        assert upstream["id"] == "n0"
        assert upstream["runtime"]["message"] == "upstream blew up"
        assert upstream["runtime"]["origin"] == "browser"

    def test_a_successful_sandbox_run_reports_what_it_produced(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "n1", code="return df", stdout=["done"], stderr="",
            output={"path": "art-1", "dataType": "geodataframe"},
            started_at="2026-09-10T00:00:00Z", duration_ms=41,
        )
        runtime = node_context.compose_node_context(KEY, PID, _spec(), "n1")["runtime"]
        assert runtime["status"] == "ok"
        assert runtime["outputType"] == "geodataframe"
        assert runtime["origin"] == "sandbox"
        assert runtime["message"] == "done"   # stdout, for a success

    def test_a_node_that_never_ran_says_only_that(self, tmp_curio):
        runtime = node_context.compose_node_context(KEY, PID, _spec(), "n1")["runtime"]
        assert runtime == {"status": "never-executed"}   # nothing invented

    def test_the_message_is_bounded(self, tmp_curio):
        runtime_journal.record_browser_execution(
            KEY, PID, "n1", status="error", message="e" * 5000,
        )
        runtime = node_context.compose_node_context(KEY, PID, _spec(), "n1")["runtime"]
        assert len(runtime["message"]) <= 240


class TestTheRunAndTheRenderTogether:
    """dev/137: two origins describe two different things about one node."""

    def test_a_code_node_keeps_its_run_and_carries_its_render_beside_it(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "n1", code="return df", stdout=[], stderr="",
            output={"path": "art-9", "dataType": "geodataframe"},
            started_at="2026-09-11T00:00:00Z", duration_ms=12,
        )
        runtime_journal.record_browser_execution(
            KEY, PID, "n1", status="error", message="rendered nothing — 0 rows",
            kind="empty-render:no-input-rows",
        )
        runtime = node_context.compose_node_context(KEY, PID, _spec(), "n1")["runtime"]
        # The RUN leads: its artifact type is what the code produced.
        assert runtime["status"] == "ok"
        assert runtime["origin"] == "sandbox"
        assert runtime["outputType"] == "geodataframe"
        # And the render rides beside it, because a run that passed can still
        # have drawn nothing.
        assert runtime["render"]["status"] == "error"
        assert runtime["render"]["kind"] == "empty-render:no-input-rows"
        assert "0 rows" in runtime["render"]["message"]

    def test_a_grammar_node_is_described_by_its_render_alone(self, tmp_curio):
        runtime_journal.record_browser_execution(
            KEY, PID, "n1", status="error", message="rendered nothing — 3 rows arrived",
            kind="empty-render:nothing-drawn",
        )
        runtime = node_context.compose_node_context(KEY, PID, _spec(), "n1")["runtime"]
        assert runtime["origin"] == "browser"
        assert runtime["kind"] == "empty-render:nothing-drawn"
        assert "render" not in runtime      # there is no second thing to report
