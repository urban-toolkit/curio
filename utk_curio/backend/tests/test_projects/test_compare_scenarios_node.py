"""The Compare Scenarios node (#662) where the backend meets it.

- Its chart presets are valid Vega-Lite, and read only columns the stacked
  table has: each spec in ``comparePresets.cases.json``, which the frontend's
  Jest test pins its presets to, goes through the validator agents' documents
  go through.
- ``metadata.compareScenarios`` in the trill schema lists exactly the presets
  and aggregates the frontend offers.
- The code the node writes, ``compareCode.cases.json``, which the frontend's
  Jest test pins its writer to, runs as a run on the server runs it: its chips
  resolve through ``WorkflowSpec.node_code``, and the result stacks the inputs
  through the sandbox's stacking step.

Every file is read inside its test, so a checkout without them fails test by
test rather than at collection.
"""
from __future__ import annotations

import json
import os
import re
import textwrap

import pandas as pd
import pytest

from utk_curio.backend.app.projects.seed import _repo_root
from utk_curio.sandbox.util.input_names import call_as_node

REPO_ROOT = str(_repo_root())
COMPARE_DIR = os.path.join(REPO_ROOT, "utk_curio", "frontend", "urban-workflows", "src", "utils", "compare")
SCHEMA_PATH = os.path.join(REPO_ROOT, "docs", "schemas", "trill.v1.json")


def _read_json(name: str) -> dict:
    with open(os.path.join(COMPARE_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def _frontend_list(name: str) -> list[str]:
    with open(os.path.join(COMPARE_DIR, "compareSettings.ts"), encoding="utf-8") as fh:
        text = fh.read()
    block = re.search(rf"export const {name} = \[(.*?)\] as const;", text, re.S)
    assert block, f"could not find {name} in compareSettings.ts"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_every_chart_preset_is_valid_vega_lite_over_the_stacked_tables_columns():
    from utk_curio.backend.app.agents.domain.document_validation import STATUS_VALID, validate_vega_lite

    doc = _read_json("comparePresets.cases.json")
    columns = ["scenario", "scenario_name"] + [column["name"] for column in doc["columns"]]
    results = {case["name"]: validate_vega_lite(json.dumps(case["spec"]), columns=columns) for case in doc["cases"]}
    assert set(_frontend_list("COMPARE_PRESETS")) <= {case["resolved"]["preset"] for case in doc["cases"]}
    # "unchecked" (the schema could not be read) is not a pass.
    assert {name: r for name, r in results.items() if r.get("status") != STATUS_VALID} == {}


def test_a_preset_reading_a_column_the_table_lacks_is_refused():
    """The column check above bites: the same spec over a table without the
    column it plots is refused, naming the column."""
    from utk_curio.backend.app.agents.domain.document_validation import STATUS_INVALID, validate_vega_lite

    doc = _read_json("comparePresets.cases.json")
    bar = next(case for case in doc["cases"] if case["name"] == "bar")
    plotted = bar["spec"]["encoding"]["y"]["field"]
    columns = ["scenario", "scenario_name"] + [c["name"] for c in doc["columns"] if c["name"] != plotted]
    result = validate_vega_lite(json.dumps(bar["spec"]), columns=columns)
    assert result["status"] == STATUS_INVALID
    assert repr(plotted) in result["detail"]


def test_the_schema_lists_the_presets_and_aggregates_the_frontend_offers():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    chart = schema["$defs"]["nodeMetadata"]["properties"]["compareScenarios"]["properties"]["chart"]["properties"]
    assert chart["preset"]["enum"] == _frontend_list("COMPARE_PRESETS")
    assert chart["aggregate"]["enum"] == _frontend_list("COMPARE_AGGREGATES")


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
    from utk_curio.sandbox.util.scenario_stack import stack_scenarios

    namespace = {"curio_stack_scenarios": stack_scenarios}
    return call_as_node(textwrap.indent(code, "    "), namespace, arg, slots)


def test_the_written_code_runs_as_a_server_run_resolves_it():
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    cases = _read_json("compareCode.cases.json")["cases"]
    assert [case["name"] for case in cases if not case["inputs"]] == ["no inputs"]
    for case in cases:
        if not case["inputs"]:
            continue
        workflow = parse_workflow_dict(_spec_for(case))
        compare = next(node for node in workflow.nodes if node.id == "compare")
        resolved = workflow.node_code(compare, "python")
        assert "[!!" not in resolved, f"{case['name']}: a chip was left in the code:\n{resolved}"
        frames = [pd.DataFrame({"value": [input["slot"] * 10]}) for input in case["inputs"]]
        arg = frames[0] if len(frames) == 1 else frames
        stacked = _run(resolved, arg, [input["slot"] for input in case["inputs"]])
        expected = [
            [input["label"].get("scenario"), input["label"]["name"], input["slot"] * 10] for input in case["inputs"]
        ]
        assert stacked[["scenario", "scenario_name", "value"]].values.tolist() == expected, case["name"]


def test_a_run_on_the_server_runs_it_as_the_template_roster_says():
    """A run on the server reads what a node does from the template roster,
    built from the shipped manifest: the node's code runs in the sandbox."""
    from pathlib import Path

    from utk_curio.backend.app.execution.run_plan import node_role
    from utk_curio.backend.app.packages.application.templates import template_content_kind, template_is_executable
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    manifest = load_package_manifest(Path(REPO_ROOT) / "packages" / "curio.builtin@1")
    template = next(t for t in manifest.templates if t.template_id == "compare-scenarios")
    roster = {"curio.builtin/compare-scenarios": {"executable": template_is_executable(template), "engine": template.engine}}
    assert node_role({"id": "cmp", "type": "curio.builtin/compare-scenarios@1"}, roster) == "run"
    assert template_content_kind(template) == "code"


def test_the_code_for_no_inputs_asks_for_them():
    cases = _read_json("compareCode.cases.json")["cases"]
    empty = next(case for case in cases if not case["inputs"])
    with pytest.raises(ValueError, match="has no inputs"):
        _run(empty["code"], None)
