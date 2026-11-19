"""What a node a runner does not execute hands the nodes below it, in the
runners that are not the browser: the e2e tests' ground truth
(``test_frontend/utils/sandbox.py``, ``execute_workflow_programmatically``)
and the stress driver, both through ``workflow_spec.propagate_node_input``.

A passive node, a Data Pool or a map, forwards its input, as the canvas hands
it on. An Autark node whose document only loads data hands on the tables its
data section loads and makes, never its input, so it forwards nothing: such a
runner has no output for it, and the nodes below it no ground truth. Its
section may read the node's input (a heatmap of ``input_0``), so it can have
an input to wrongly forward: example 39's Python step, below such a node, ran
in the e2e ground truth on the labels its heatmap read and failed.

Everything is imported inside each test, so a checkout without it fails each
test on its own.
"""
from __future__ import annotations

import json

AUTK = "curio.builtin/autk-grammar"
PYTHON = "curio.builtin/python-computation"
POOL = "curio.builtin/data-pool"

#: A Python node's output, as a runner records it.
POINTS = {"path": "points_artifact", "dataType": "geodataframe"}

#: A data section that bins the node's input into a heatmap, as example 39's
#: heatmap node does, and one whose OSM load reads no input.
HEATMAP_OF_THE_INPUT = {"data": [{
    "type": "heatmap", "joinDataRef": "input_0", "outputTableName": "density",
    "near": {"distance": 134}, "grid": {"rows": 2, "columns": 3},
}]}
OSM_LOAD = {"data": [{
    "type": "osm", "pbfFileUrl": "docs/examples/data/chicago_loop.osm.pbf", "outputTableName": "loop",
    "queryArea": {"bbox": [-87.6382474, 41.8673, -87.6024757, 41.8906361]},
    "autoLoadLayers": {"layers": ["surface", "roads"]},
}]}
#: A map that draws the node's input, which it hands on as it came.
MAP_OF_THE_INPUT = {"map": {"layerRefs": [{"dataRef": "input_0"}]}}


def _below_points(node_type: str, content: str):
    """A dataflow of a Python node, ``points``, feeding *node_type*, ``below``."""
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    return parse_workflow_dict({"dataflow": {
        "nodes": [
            {"id": "points", "type": PYTHON, "content": "return points"},
            {"id": "below", "type": node_type, "content": content},
        ],
        "edges": [{"id": "points-below", "source": "points", "target": "below",
                   "sourceHandle": "out", "targetHandle": "in"}],
    }})


def test_an_autark_node_that_only_loads_data_forwards_nothing_though_its_section_reads_its_input():
    from utk_curio.backend.app.execution.workflow_spec import propagate_node_input

    spec = _below_points(AUTK, json.dumps(HEATMAP_OF_THE_INPUT, indent=2))

    assert propagate_node_input(spec, "below", {"points": dict(POINTS)}) is None


def test_an_autark_node_that_only_loads_its_own_sources_forwards_nothing_either():
    """The same rule for a data section that reads no table of its input."""
    from utk_curio.backend.app.execution.workflow_spec import propagate_node_input

    spec = _below_points(AUTK, json.dumps(OSM_LOAD, indent=2))

    assert propagate_node_input(spec, "below", {"points": dict(POINTS)}) is None


def test_an_autark_map_forwards_its_input():
    """Guard: a node that draws hands on what it was fed."""
    from utk_curio.backend.app.execution.workflow_spec import propagate_node_input

    spec = _below_points(AUTK, json.dumps(MAP_OF_THE_INPUT, indent=2))

    assert propagate_node_input(spec, "below", {"points": dict(POINTS)}) == POINTS


def test_a_data_pool_forwards_its_input():
    """Guard: a passive node hands on what it was fed."""
    from utk_curio.backend.app.execution.workflow_spec import propagate_node_input

    spec = _below_points(POOL, "")

    assert propagate_node_input(spec, "below", {"points": dict(POINTS)}) == POINTS
