"""Scenario chips as the server resolves them (#662).

A chart or a map writes the scenarios of its inputs through chips:
``[!! scenario colors !!]``, ``[!! scenario order !!]``,
``[!! scenario text_colors !!]`` and ``[!! scenario input_1 !!]``. Each wired
input's label is the box its feeding node is in, ranked by the dataflow's list
of boxes, else that node's title, renamed header or type, in grey.

``scenarioChips.cases.json`` holds dataflows, a node of each, and the spec its
chips resolve to. ``WorkflowSpec.node_code``, which a server run and the agents'
check resolve a node's references with, must write exactly that, as the
notebook export writes it in the browser (``src/tests/NotebookConvertor.test.ts``
reads the same cases).

The modules are imported inside each test, so a missing name fails its own test.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CASES = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "scenarios" / "scenarioChips.cases.json"


def _cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def test_the_server_writes_each_spec_as_the_notebook_export_writes_it():
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    cases = _cases()
    assert cases
    assert len({c["name"] for c in cases}) == len(cases), "two cases share a name"
    wrong = []
    for case in cases:
        # The template labels a case names an untitled node by, as a run reads
        # them for its project (``node_names.template_labels``).
        spec = parse_workflow_dict({"dataflow": case["dataflow"]}, labels=case.get("labels"))
        (node,) = [n for n in spec.nodes if n.id == case["node"]]
        try:
            got = spec.node_code(node, "json", grammar=case.get("grammar"))
        except Exception as exc:  # one case that raises is a mismatch, the others are still read
            wrong.append(f"{case['name']}: raised {exc!r}")
            continue
        if got != case["expected"]:
            wrong.append(f"{case['name']}: wrote {got!r}, the table says {case['expected']!r}")
    assert not wrong, "\n".join(wrong)


def test_a_box_renamed_or_recolored_is_what_the_chips_write_next():
    """The chips read the boxes as the dataflow holds them now: a rename and a
    recolor are what the next resolution writes."""
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    case = _cases()[0]
    dataflow = json.loads(json.dumps(case["dataflow"]))
    tall, base = dataflow["scenarios"]
    tall["name"] = "Towers capped"
    base["color"] = "#d81b60"
    spec = parse_workflow_dict({"dataflow": dataflow})
    (node,) = [n for n in spec.nodes if n.id == case["node"]]
    encoding = json.loads(spec.node_code(node, "json", grammar=case["grammar"]))["encoding"]
    assert encoding["color"]["scale"] == {
        "domain": ["Towers capped", "Baseline", "Roof survey"],
        "range": ["#e76f51", "#d81b60", "#8a8f98"],
    }
    assert encoding["x"]["sort"] == ["Towers capped", "Baseline", "Roof survey"]


def test_a_node_of_a_type_written_the_old_way_is_named_as_a_saved_node_is_named():
    """An untitled input from no box whose node holds its type the old way
    (``COMPUTATION_ANALYSIS``) is named by its template's label, looked up by
    the canonical template id as ``node_names.saved_node_label`` looks it up for
    the node's computed dataset and a run's steps."""
    from utk_curio.backend.app.execution.node_names import saved_node_label
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    labels = {"curio.builtin/computation-analysis": "Python Computation"}
    saved = {"id": "py", "type": "COMPUTATION_ANALYSIS", "content": "return 1"}
    dataflow = {
        "nodes": [saved, {"id": "chart", "type": "curio.builtin/vis-vega", "content": '{"sort": [!! scenario order !!]}'}],
        "edges": [{"id": "e-py", "source": "py", "target": "chart", "sourceHandle": "out", "targetHandle": "in"}],
    }
    spec = parse_workflow_dict({"dataflow": dataflow}, labels=labels)
    assert spec.node_label("py") == saved_node_label(saved, labels) == "Python Computation"
    (chart,) = [n for n in spec.nodes if n.id == "chart"]
    assert json.loads(spec.node_code(chart, "json")) == {"sort": ["Python Computation"]}
