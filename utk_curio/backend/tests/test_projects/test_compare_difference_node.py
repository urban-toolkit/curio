"""The Compare Scenarios node's Difference (#662) where the backend meets it.

- ``metadata.compareScenarios`` in the trill schema takes the view the user
  chose (``mode``, exactly the modes the frontend offers) and what Difference
  joins rows on and maps (``difference``), and refuses anything else.
- The code the node writes in Difference, ``compareDifference.cases.json``,
  which the frontend's Jest test pins its writer to, runs as a run on the
  server runs it: its chips resolve through ``WorkflowSpec.node_code``, and the
  result subtracts the inputs through the sandbox's difference step.

Every file is read inside its test, so a checkout without them fails test by
test rather than at collection.
"""
from __future__ import annotations

import copy
import json
import os
import re
import textwrap

import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from utk_curio.backend.app.projects.seed import _repo_root
from utk_curio.sandbox.util.input_names import call_as_node

REPO_ROOT = str(_repo_root())
COMPARE_DIR = os.path.join(REPO_ROOT, "utk_curio", "frontend", "urban-workflows", "src", "utils", "compare")
SCHEMA_PATH = os.path.join(REPO_ROOT, "docs", "schemas", "trill.v1.json")

LABELS = [
    {"scenario": "s-base", "name": "Baseline", "color": "#2a9d8f"},
    {"scenario": "s-tall", "name": "Twice as tall", "color": "#e76f51"},
]


def _read_json(name: str) -> dict:
    with open(os.path.join(COMPARE_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def _schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _frontend_list(name: str) -> list[str]:
    with open(os.path.join(COMPARE_DIR, "compareSettings.ts"), encoding="utf-8") as fh:
        text = fh.read()
    block = re.search(rf"export const {name} = \[(.*?)\] as const;", text, re.S)
    assert block, f"could not find {name} in compareSettings.ts"
    return re.findall(r'"([^"]+)"', block.group(1))


def _doc(compare_settings) -> dict:
    """A spec that validates but for a Compare Scenarios node's settings."""
    return {
        "dataflow": {
            "nodes": [
                {
                    "id": "cmp",
                    "type": "curio.builtin/compare-scenarios@1",
                    "x": 0,
                    "y": 0,
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "content": "return curio_difference_scenarios([])\n",
                    "metadata": {"keywords": [], "compareScenarios": compare_settings},
                }
            ],
            "edges": [],
            "name": "Fixture",
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": "Fixture",
        }
    }


def _errors(doc: dict) -> list:
    return list(Draft202012Validator(_schema()).iter_errors(doc))


def test_the_schema_lists_the_modes_the_frontend_offers():
    compare = _schema()["$defs"]["nodeMetadata"]["properties"]["compareScenarios"]["properties"]
    assert compare["mode"]["enum"] == _frontend_list("COMPARE_MODES")


@pytest.mark.parametrize(
    "settings",
    [
        {"inputs": LABELS, "mode": "difference", "difference": {"key": "osm_id", "value": "sunlight"}},
        {"mode": "chart", "chart": {"preset": "bar"}},
        {"inputs": LABELS, "difference": {"value": "band_1"}},
    ],
    ids=["difference with a key and a value", "chart chosen", "a value alone"],
)
def test_the_schema_takes_a_chosen_view_and_what_difference_joins_on(settings):
    assert _errors(_doc(copy.deepcopy(settings))) == []


@pytest.mark.parametrize(
    "settings",
    [
        {"mode": "map"},
        {"mode": ""},
        {"difference": {"key": ""}},
        {"difference": {"key": "osm_id", "band": 1}},
        {"difference": "osm_id"},
    ],
    ids=["a view the node does not have", "an empty view", "an empty key", "a field the format does not have",
         "difference as a name"],
)
def test_the_schema_refuses_what_the_node_does_not_write(settings):
    assert _errors(_doc(settings)) != []


def _spec_for(case: dict) -> dict:
    """A dataflow whose Compare Scenarios node holds the case's code, fed on
    the case's circles."""
    nodes = [
        {"id": f"src-{input['slot']}", "type": "curio.builtin/computation-analysis", "x": 0, "y": 0, "content": "return 1"}
        for input in case["inputs"]
    ]
    nodes.append({"id": "compare", "type": "curio.builtin/compare-scenarios@1", "x": 0, "y": 0, "content": case["code"]})
    edges = [
        {
            "id": f"e-{input['slot']}",
            "source": f"src-{input['slot']}",
            "target": "compare",
            "sourceHandle": "out",
            "targetHandle": "in" if input["slot"] == 0 else f"in_{input['slot']}",
        }
        for input in case["inputs"]
    ]
    return {"dataflow": {"name": "Compare", "nodes": nodes, "edges": edges}}


def _run(code: str, arg, slots=None):
    from utk_curio.sandbox.util.scenario_difference import difference_scenarios

    namespace = {"curio_difference_scenarios": difference_scenarios}
    return call_as_node(textwrap.indent(code, "    "), namespace, arg, slots)


def test_the_written_difference_code_runs_as_a_server_run_resolves_it():
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    cases = _read_json("compareDifference.cases.json")["cases"]
    assert [case["name"] for case in cases if not case["inputs"]] == ["no inputs"]
    for case in cases:
        if not case["inputs"]:
            continue
        workflow = parse_workflow_dict(_spec_for(case))
        compare = next(node for node in workflow.nodes if node.id == "compare")
        resolved = workflow.node_code(compare, "python")
        assert "[!!" not in resolved, f"{case['name']}: a chip was left in the code:\n{resolved}"
        key = case.get("key", "osm_id")
        reference = pd.DataFrame({key: ["a", "b"], "sunlight": [6.0, 5.0]})
        comparison = pd.DataFrame({key: ["b", "c"], "sunlight": [2.5, 1.0]})
        out = _run(resolved, [reference, comparison], [input["slot"] for input in case["inputs"]])
        assert out[key].tolist() == ["a", "b", "c"], case["name"]
        assert out["change"].tolist() == ["removed", "changed", "added"], case["name"]
        change = 2.5 if case.get("absolute") else -2.5
        assert [None if pd.isna(v) else v for v in out["sunlight"]] == [None, change, None], case["name"]


def test_the_difference_code_for_no_inputs_asks_for_two():
    cases = _read_json("compareDifference.cases.json")["cases"]
    empty = next(case for case in cases if not case["inputs"])
    with pytest.raises(ValueError, match="compares two inputs, a reference and a comparison, and it has 0"):
        _run(empty["code"], None)
