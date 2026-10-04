"""The run engine walks a saved dataflow the way Run All does, with a recording
executor in place of the sandbox.

``run_engine`` is imported inside each test, so a checkout without it fails each
test on its own.
"""
from __future__ import annotations

import json
import threading

import pytest

CODE = "curio.builtin/computation-analysis"
DATA_SPEC = json.dumps({"data": [{"type": "osm"}]})


def node(node_id, node_type=CODE, content="return arg", **fields):
    return {"id": node_id, "type": node_type, "content": content, **fields}


def edge(source, target, handle=None, **fields):
    saved = {"id": f"{source}-{target}-{handle or 'in'}", "source": source, "target": target}
    if handle:
        saved["targetHandle"] = handle
    saved.update(fields)
    return saved


def spec(nodes, edges=()):
    return {"dataflow": {"nodes": list(nodes), "edges": list(edges)}}


class Recorder:
    """Stands in for the sandbox: records each call and answers with an
    artifact named after the node, or a failure for the nodes in *fail*."""

    def __init__(self, fail=(), unreachable=(), on_call=None):
        self.fail = set(fail)
        self.unreachable = set(unreachable)
        self.on_call = on_call
        self.calls = {}
        self.lock = threading.Lock()

    def __call__(self, step, code, input_ref):
        with self.lock:
            self.calls[step.node_id] = {"code": code, "input": input_ref, "engine": step.engine}
        if self.on_call:
            self.on_call(step)
        if step.node_id in self.unreachable:
            from utk_curio.backend.app.execution.sandbox_client import SandboxTransportError

            raise SandboxTransportError(
                {"error": "sandbox_timeout", "message": "The sandbox did not respond."}, 504,
            )
        if step.node_id in self.fail:
            return {"stdout": [], "stderr": "Traceback: ZeroDivisionError",
                    "output": {"path": "", "dataType": "str"}}
        return {"stdout": [f"ran {step.node_id}"], "stderr": "",
                "output": {"path": f"art-{step.node_id}", "dataType": "dataframe"}}


def run(spec_dict, recorder=None, **plan_args):
    from utk_curio.backend.app.execution.run_engine import plan_run, run_events

    recorder = recorder or Recorder()
    cancelled = plan_args.pop("cancelled", None)
    plan = plan_run(spec_dict, **plan_args)
    events = list(run_events(plan, recorder, cancelled=cancelled))
    finished = {p["nodeId"]: p for kind, p in events if kind == "step_finished"}
    return recorder, events, finished


def outcome(events):
    return next(p for kind, p in events if kind == "run_finished")


class TestPlayShapesEachNode:
    def test_a_chain_runs_in_order_and_feeds_each_node_its_upstream(self):
        recorder, events, finished = run(spec(
            [node("a"), node("b")], [edge("a", "b")],
        ))
        assert [p["nodeId"] for k, p in events if k == "step_started"] == ["a", "b"]
        assert recorder.calls["a"]["input"] is None
        assert recorder.calls["b"]["input"] == {"path": "art-a", "dataType": "dataframe"}
        assert finished["b"]["status"] == "ok"
        assert outcome(events) == {"status": "succeeded", "ok": 2, "failed": 0, "skipped": 0, "waiting": 0}

    def test_every_line_is_indented_as_the_browser_indents_it(self):
        recorder, _, _ = run(spec([node("a", content="x = 1\n\nreturn x")]))
        assert recorder.calls["a"]["code"] == "    x = 1\n    \n    return x\n"

    def test_several_inputs_arrive_as_one_bundle_in_circle_order(self):
        recorder, _, _ = run(spec(
            [node("a"), node("b"), node("c", content="return [!! input 0 !!], [!! input 1 !!]")],
            # The second circle's edge first: circle order, not edge order, decides.
            [edge("a", "c", "in_1"), edge("b", "c", "in")],
        ))
        assert recorder.calls["c"]["input"] == {"dataType": "outputs", "data": [
            {"path": "art-b", "dataType": "dataframe"},
            {"path": "art-a", "dataType": "dataframe"},
        ]}
        assert recorder.calls["c"]["code"] == "    return arg[0], arg[1]\n"

    def test_a_widget_reference_is_resolved_before_the_run(self):
        recorder, _, _ = run(spec([node(
            "a", content="return [!! n !!]",
            metadata={"widgets": [{"name": "n", "type": "number", "default": 10, "value": 3}]},
        )]))
        assert recorder.calls["a"]["code"] == "    return 3\n"

    def test_a_parameter_nodes_value_reaches_the_nodes_that_name_it(self):
        # #662: a Parameter node has no edge; [!! @name !!] reads its widget.
        recorder, events, finished = run(spec([
            node("p", "curio.builtin/parameter@1", "",
                 metadata={"widgets": [{"name": "factor", "type": "number", "default": 2, "value": 5}]}),
            node("a", content="return [!! @factor !!] * 10"),
            node("j", "curio.builtin/js-computation", "return [!! @factor !!] + 1;"),
        ]))
        assert recorder.calls["a"]["code"] == "    return 5 * 10\n"
        assert "return 5 + 1;" in recorder.calls["j"]["code"]
        # The Parameter node itself is never sent to the sandbox: it has
        # nothing to run, and holds nothing up.
        assert "p" not in recorder.calls
        assert finished["p"]["status"] == "forwarded"
        assert outcome(events)["status"] == "succeeded"

    def test_a_reference_that_cannot_resolve_fails_the_node_without_the_sandbox(self):
        recorder, _, finished = run(spec([node("a", content="return [!! input 1 !!]")]))
        assert "a" not in recorder.calls
        assert finished["a"]["status"] == "error" and finished["a"]["stderrTail"]

    def test_a_javascript_node_runs_as_javascript(self):
        recorder, _, _ = run(spec([node("j", "curio.builtin/js-computation", "return 1;")]))
        assert recorder.calls["j"]["engine"] == "javascript"

    def test_a_javascript_nodes_code_is_sent_as_written(self):
        # As JavaScriptInterpreter.ts posts it: an indented import is no longer
        # a module's own (example 08's join).
        code = "import { AutkDb } from '@urban-toolkit/autk-db';\n\nreturn 1;"
        recorder, _, _ = run(spec([node("j", "curio.builtin/js-computation", code)]))
        assert recorder.calls["j"]["code"] == code


class TestFailuresStayOnTheirBranch:
    def test_a_failure_skips_what_it_feeds_and_the_other_branch_finishes(self):
        recorder, events, finished = run(spec(
            [node("a"), node("bad", title="Clean rows"), node("after"), node("other")],
            [edge("a", "bad"), edge("bad", "after"), edge("a", "other")],
        ), Recorder(fail={"bad"}))
        assert finished["bad"]["status"] == "error"
        assert finished["after"]["status"] == "skipped"
        assert '"Clean rows", failed' in finished["after"]["skipReason"]
        assert "after" not in recorder.calls
        assert finished["other"]["status"] == "ok"
        assert outcome(events)["status"] == "failed"

    def test_an_unreachable_sandbox_fails_that_node_only(self):
        recorder, events, finished = run(spec(
            [node("a"), node("b")], [],
        ), Recorder(unreachable={"a"}))
        assert finished["a"]["status"] == "error"
        assert "did not respond" in finished["a"]["stderrTail"]
        assert finished["b"]["status"] == "ok"
        assert outcome(events)["failed"] == 1

    def test_a_node_in_a_cycle_is_skipped_with_a_reason(self):
        from utk_curio.backend.app.execution.run_engine import CYCLE_REASON

        recorder, _, finished = run(spec(
            [node("a"), node("b"), node("c")], [edge("a", "b"), edge("b", "a")],
        ))
        assert finished["a"]["skipReason"] == CYCLE_REASON
        assert finished["b"]["status"] == "skipped"
        assert finished["c"]["status"] == "ok"


class TestNodesTheServerDoesNotRun:
    def test_a_pool_passes_its_input_on(self):
        recorder, _, finished = run(spec(
            [node("a"), node("pool", "curio.builtin/data-pool", ""), node("b")],
            [edge("a", "pool"), edge("pool", "b")],
        ))
        assert finished["pool"]["status"] == "forwarded"
        assert recorder.calls["b"]["input"] == {"path": "art-a", "dataType": "dataframe"}

    def test_data_only_the_browser_makes_leaves_the_run_needing_the_canvas(self):
        recorder, events, finished = run(spec(
            [node("osm", "curio.builtin/autk-grammar", DATA_SPEC, title="Load OSM"),
             node("count"), node("chart", "curio.builtin/vis-vega", "{}")],
            [edge("osm", "count"), edge("count", "chart")],
        ))
        assert finished["osm"]["status"] == "browser"
        assert finished["count"]["status"] == "waiting"
        assert '"Load OSM"' in finished["count"]["skipReason"]
        assert finished["chart"]["status"] == "waiting"
        assert "count" not in recorder.calls
        assert outcome(events)["status"] == "needs_canvas"

    def test_a_chart_at_the_end_does_not_hold_the_run(self):
        _, events, finished = run(spec(
            [node("a"), node("chart", "curio.builtin/vis-vega", "{}")], [edge("a", "chart")],
        ))
        assert finished["chart"]["status"] == "forwarded"
        assert outcome(events)["status"] == "succeeded"


class TestRunningUpToANode:
    def test_it_runs_the_node_and_the_ancestors_the_canvas_could_not_reuse(self):
        recorder, _, finished = run(
            spec([node("a"), node("b"), node("c"), node("d")],
                 [edge("a", "b"), edge("b", "c"), edge("c", "d")]),
            target_node_id="c",
            reuse={"a": {"path": "art-a-kept", "dataType": "dataframe"}},
        )
        assert set(recorder.calls) == {"b", "c"}
        assert recorder.calls["b"]["input"] == {"path": "art-a-kept", "dataType": "dataframe"}
        assert set(finished) == {"b", "c"}

    def test_a_reused_bundle_reaches_the_target_whole(self):
        bundle = {"dataType": "outputs", "data": [
            {"path": "art-a", "dataType": "dataframe"},
            {"path": "art-b", "dataType": "dataframe"},
        ]}
        # A pool on two circles forwards its inputs as one bundle.
        recorder, _, _ = run(
            spec([node("a"), node("b"), node("m", "curio.builtin/data-pool", ""), node("c")],
                 [edge("a", "m", "in"), edge("b", "m", "in_1"), edge("m", "c")]),
            target_node_id="c",
            reuse={"a": {"path": "art-a", "dataType": "dataframe"},
                   "b": {"path": "art-b", "dataType": "dataframe"},
                   "m": bundle},
        )
        assert set(recorder.calls) == {"c"}
        assert recorder.calls["c"]["input"] == bundle

    def test_the_target_runs_even_when_its_output_was_offered(self):
        recorder, _, _ = run(
            spec([node("a"), node("b")], [edge("a", "b")]),
            target_node_id="b",
            reuse={"b": {"path": "art-b-old", "dataType": "dataframe"}},
        )
        assert set(recorder.calls) == {"a", "b"}

    def test_a_target_not_in_the_dataflow_is_refused(self):
        from utk_curio.backend.app.execution.run_engine import PlanError, plan_run

        with pytest.raises(PlanError):
            plan_run(spec([node("a")]), target_node_id="ghost")


class TestCancel:
    def test_nothing_starts_once_cancelled(self):
        cancelled = threading.Event()
        cancelled.set()
        recorder, events, finished = run(
            spec([node("a"), node("b")], [edge("a", "b")]), cancelled=cancelled,
        )
        assert recorder.calls == {}
        assert {p["status"] for p in finished.values()} == {"cancelled"}
        assert outcome(events)["status"] == "cancelled"

    def test_the_running_node_finishes_and_its_output_is_dropped(self):
        cancelled = threading.Event()
        recorder, events, finished = run(
            spec([node("a"), node("b")], [edge("a", "b")]),
            Recorder(on_call=lambda step: cancelled.set()),
            cancelled=cancelled,
        )
        assert set(recorder.calls) == {"a"}
        assert finished["a"]["status"] == "cancelled" and "output" not in finished["a"]
        assert finished["b"]["status"] == "cancelled"
        assert outcome(events)["status"] == "cancelled"
