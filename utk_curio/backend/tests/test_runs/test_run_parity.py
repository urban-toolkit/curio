"""The two server paths run a node the same way.

A run on the server (``run_engine``) and the headless runner behind Solve's
validation and an agent's run through a node (``runner.run_through_node``)
execute the same nodes, hand each the same upstream artifacts in circle order,
and resolve the same code. They differ only where this test normalizes, each
for a reason:

- **Transport.** The engine posts through ``node_exec`` as Play does: one
  upstream's reference as it is, several as an ``outputs`` bundle. The runner
  posts to the sandbox directly: a path, or the bundle's list as a string.
- **Seed.** The runner prepends a fixed random seed, so a validation run is
  repeatable; Play does not.
- **Indentation.** The engine indents every line as ``PythonInterpreter.ts``
  does; the runner uses ``textwrap.indent``.

Outside this test they also differ by design: the runner runs one node after
another and stops at the first failure, and the engine runs a level at once
and skips only what a failure feeds.
"""
from __future__ import annotations

import ast
import textwrap

import pytest

from utk_curio.backend.tests.test_runs.test_run_engine import Recorder, edge, node, spec

POOL = "curio.builtin/data-pool"

SCENARIOS = {
    "a chain": (spec([node("a"), node("b")], [edge("a", "b")]), "b"),
    "a fan-in on two circles": (
        spec(
            [node("a", content="return 1"), node("b", content="return 2"),
             node("c", content="return [!! input 0 !!] + [!! input 1 !!]")],
            [edge("a", "c", "in_1"), edge("b", "c", "in")],
        ),
        "c",
    ),
    "a widget reference": (
        spec([node(
            "a", content="return [!! n !!] * 2",
            metadata={"widgets": [{"name": "n", "type": "number", "default": 10, "value": 4}]},
        )]),
        "a",
    ),
    "a pool in the middle": (
        spec([node("a"), node("pool", POOL, ""), node("b")], [edge("a", "pool"), edge("pool", "b")]),
        "b",
    ),
}


def _through_runner(spec_dict, target):
    from utk_curio.backend.app.execution import runner

    current = {}
    calls = {}

    def progress(node_id, index, total):
        current["id"] = node_id

    def exec_fn(endpoint, payload):
        node_id = current["id"]
        calls[node_id] = payload
        return {"stdout": [], "stderr": "",
                "output": {"path": f"art-{node_id}", "dataType": "dataframe"}}

    report = runner.run_through_node(
        "4242", "parity", spec_dict, target,
        exec_fn=exec_fn, progress=progress, as_validation=False,
    )
    assert report["ok"], report
    return calls


def _runner_code(payload) -> str:
    from utk_curio.backend.app.execution.workflow_spec import seed_node_code

    seed = seed_node_code("", 42)
    code = textwrap.dedent(payload["code"])
    assert code.startswith(seed)
    return code[len(seed):]


def _runner_inputs(payload) -> list:
    if payload.get("dataType") == "outputs":
        return [ref["path"] for ref in ast.literal_eval(payload["file_path"])]
    return [payload["file_path"]] if payload.get("file_path") else []


def _engine_code(code: str) -> str:
    lines = code.split("\n")
    assert lines[-1] == "" and all(line.startswith("    ") for line in lines[:-1])
    return "\n".join(line[4:] for line in lines[:-1])


def _engine_inputs(input_ref) -> list:
    if input_ref is None:
        return []
    if input_ref.get("dataType") == "outputs":
        return [ref["path"] for ref in input_ref["data"]]
    return [input_ref["path"]]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_both_paths_run_a_node_the_same_way(name, tmp_curio):
    from utk_curio.backend.app.execution.run_engine import plan_run, run_events

    spec_dict, target = SCENARIOS[name]
    by_runner = _through_runner(spec_dict, target)
    recorder = Recorder()
    list(run_events(plan_run(spec_dict, target_node_id=target), recorder))
    by_engine = recorder.calls

    assert set(by_engine) == set(by_runner)
    for node_id in by_runner:
        assert _engine_inputs(by_engine[node_id]["input"]) == _runner_inputs(by_runner[node_id]), node_id
        assert _engine_code(by_engine[node_id]["code"]) == _runner_code(by_runner[node_id]), node_id
