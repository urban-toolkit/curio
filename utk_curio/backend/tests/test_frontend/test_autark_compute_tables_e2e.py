"""Autark compute passes that write a new table, and data with compute and no view.

A GPGPU pass with an ``outputTableName`` writes its result as a new table and
leaves the table it computed over as it was; its ``layerType`` is the type the
new table is drawn and handed on as. Four city blocks near the Loop, each with
a ``value`` from 1 to 4, come from an Autark node's own data section, and each
pass doubles the value into ``twice``:

- a map whose own pass writes ``blocks_twice`` draws that table, each drawn
  block holding its doubled value and naming its input row;
- a compute step hands the new table on beside its source, as the sandbox
  stores it, the source without the doubled value and the new table as its
  ``layerType``;
- a node with data and compute and no view runs its compute: it hands on the
  doubled values, as the browser's part of a run on the server.

Each check reads what the map draws or what the sandbox stores, not a frame.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_compute_tables_e2e.py -v
"""
from __future__ import annotations

import json
import time

from .utils import (
    api_json,
    assert_autark_map_drawn,
    frame_nodes,
    load_artifact_as_dict,
    node_execution_timeout_ms,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow,
    stub_login_and_enter_workflow,
    wait_for_node_done,
    wait_for_run_all_to_end,
    watch_run_all,
)

AUTK = "curio.builtin/autk-grammar"
DATA = "ct-data"
MAP = "ct-map"
STEP = "ct-step"
DATA_STEP = "ct-data-step"
VALUES = [1, 2, 3, 4]


def _blocks() -> dict:
    """Four squares of about 80 m in a row near the Loop, valued 1 to 4."""
    features = []
    for i, value in enumerate(VALUES):
        west, south = -87.634 + 0.0015 * i, 41.878
        ring = [[west, south], [west + 0.001, south], [west + 0.001, south + 0.001], [west, south + 0.001], [west, south]]
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                         "properties": {"block": i, "value": value}})
    return {"type": "FeatureCollection", "features": features}


#: The blocks, as an Autark data section loads them.
SOURCE = {"type": "geojson", "outputTableName": "blocks", "geojsonObject": _blocks()}


def _pass(**more) -> dict:
    """A pass that doubles each block's value into ``twice``."""
    return {"dataRef": "blocks", "attributes": {"v": "value"}, "wgslFunction": "return v * 2.0;",
            "outputColumnName": "twice", **more}


DOCUMENTS = {
    DATA: {"data": [SOURCE]},
    MAP: {
        "compute": [_pass(outputTableName="blocks_twice", layerType="polygons")],
        "map": {"layerRefs": [{"dataRef": "blocks_twice", "getFnv": "compute.twice", "getFnvType": "quantitative",
                               "colorMapInterpolator": "interpolateViridis", "isPick": True}]},
    },
    STEP: {"compute": [_pass(outputTableName="blocks_twice", layerType="buildings")]},
    DATA_STEP: {"data": [SOURCE], "compute": [_pass()]},
}


#: The nodes whose output a save records: those whose Save toggle is on, which
#: is off by default (``CURIO_DEFAULT_SAVE_NODE_OUTPUT``).
SAVED = {STEP, DATA_STEP}


def _node(node_id: str, x: int, y: int) -> dict:
    return {
        "id": node_id, "type": AUTK, "x": x, "y": y, "content": json.dumps(DOCUMENTS[node_id], indent=2),
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
        **({"saveOutputDataset": True} if node_id in SAVED else {}),
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}in",
        "source": source, "target": target, "sourceHandle": "out", "targetHandle": "in",
    }


FLOW = {"dataflow": {
    "name": "Autark compute tables",
    "task": "",
    "nodes": [_node(DATA, 80, 160), _node(MAP, 760, 40), _node(STEP, 760, 620), _node(DATA_STEP, 80, 760)],
    "edges": [_edge(DATA, MAP), _edge(DATA, STEP)],
}}


def _enter(page, app_frontend, current_server, username: str) -> tuple[str, str]:
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark compute tables",
        username=username,
        project_name=FLOW["dataflow"]["name"],
        project_spec=FLOW,
    )
    require_owner_view(page)
    return session["token"], session["project"]["id"]


def _play(page, node_id: str) -> None:
    """Play *node_id*, which runs the nodes above it too, and wait for the run
    it started to end, then for the node to read Done."""
    watch_run_all(page)
    play_node(page, node_id)
    wait_for_run_all_to_end(page, timeout_ms=node_execution_timeout_ms(AUTK))
    wait_for_node_done(page, node_id, node_type=AUTK)


def _stored(page, current_server: str, token: str, project_id: str, node_id: str, *, timeout_s: float = 60) -> dict:
    """What *node_id* handed on, as the sandbox stores it: the output a save
    of the dataflow records for it, its Save toggle being on (``SAVED``)."""
    save_dataflow(page)
    deadline = time.monotonic() + timeout_s
    while True:
        project = api_json(f"{current_server}/api/projects/{project_id}", token)
        recorded = {o["node_id"]: o["filename"] for o in project.get("outputs") or []}
        if node_id in recorded:
            return load_artifact_as_dict(recorded[node_id])["data"]
        assert time.monotonic() < deadline, f"{node_id}'s output was never recorded: {sorted(recorded)}"
        time.sleep(0.5)


def _layers(handed: dict) -> dict:
    """The layers a node handed on, by name: one layer, or several."""
    layers = handed["data"] if handed["dataType"] == "outputs" else [handed]
    return {layer["layerName"]: layer for layer in layers}


def _values(layer: dict, column: str) -> list:
    return [feature["properties"].get(column) for feature in layer["data"]["features"]]


def test_a_map_draws_the_table_its_pass_writes(app_frontend, current_server, page):
    _enter(page, app_frontend, current_server, "autark_compute_tables_map")

    _play(page, MAP)
    frame_nodes(page, [MAP])
    assert_autark_map_drawn(page, MAP, timeout=60000)

    # The map draws the new table: every block, each naming its input row.
    state = page.evaluate("(id) => window.__curio_mapState(id)", MAP)
    assert state and "blocks_twice" in state, state
    drawn = state["blocks_twice"]
    assert (drawn["drawn"], drawn["rows"], drawn["pick"]) == (len(VALUES), len(VALUES), True), drawn
    # Each drawn block holds its value doubled by the pass.
    for position in range(len(VALUES)):
        feature = page.evaluate("([id, table, at]) => window.__curio_mapFeatureAt(id, table, at)",
                                [MAP, "blocks_twice", position])
        assert feature, f"no feature is drawn at {position}"
        assert feature["compute"]["twice"] == 2 * feature["value"], feature


def test_a_compute_step_hands_the_new_table_on_beside_its_source(app_frontend, current_server, page):
    token, project_id = _enter(page, app_frontend, current_server, "autark_compute_tables_step")

    _play(page, STEP)

    layers = _layers(_stored(page, current_server, token, project_id, STEP))
    assert sorted(layers) == ["blocks", "blocks_twice"], sorted(layers)
    source, written = layers["blocks"], layers["blocks_twice"]
    # The source as it was loaded, the new table as the pass's layerType.
    assert (source["layerType"], written["layerType"]) == ("polygons", "buildings")
    assert _values(source, "value") == VALUES
    assert _values(source, "twice") == [None] * len(VALUES)
    assert _values(written, "twice") == [2 * value for value in VALUES]


def test_data_with_compute_and_no_view_hands_on_computed_rows(app_frontend, current_server, page):
    token, project_id = _enter(page, app_frontend, current_server, "autark_compute_tables_data")

    _play(page, DATA_STEP)

    # A run on the server leaves the node to the page, which runs its compute.
    runs = api_json(f"{current_server}/api/projects/{project_id}/runs?limit=1", token)["runs"]
    assert runs, "playing the node started no run on the server"
    run = api_json(f"{current_server}/api/runs/{runs[0]['id']}", token, dataflow=project_id)
    step = {s["nodeId"]: s for s in run["steps"]}[DATA_STEP]
    assert step["role"] == "browser", step

    layers = _layers(_stored(page, current_server, token, project_id, DATA_STEP))
    assert sorted(layers) == ["blocks"], sorted(layers)
    assert _values(layers["blocks"], "twice") == [2 * value for value in VALUES]
