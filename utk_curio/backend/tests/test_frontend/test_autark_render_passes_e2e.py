"""Autark render passes: a map draws the table a render pass writes, and a
compute step hands it on.

A render pass draws the tables its ``layers`` name on the GPU, from each
feature of its ``viewpoints`` table, and writes, for each viewpoint, the share
of its frames each layer type covers (``compute.render.classes``). An Autark
node's own data section loads a square of ground near the Loop, two towers
150 m tall with a street 20 m wide between them, and two spots: one in that
street and one a kilometer west. Each pass looks up at 45 degrees from each
spot, in four directions, and counts what no layer covers as the sky:

- a map whose own pass writes ``sky`` draws that table: every spot, each
  naming its input row and holding its shares;
- a compute step hands ``sky`` on beside the tables it holds, as the sandbox
  stores it, typed as its viewpoints.

Each check reads what the map draws or what the sandbox stores, not a frame:
every share lies between 0 and 1, a spot's shares add up to 1, and the spot
between the towers sees more of them, and less sky, than the far one.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_render_passes_e2e.py -v
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
DATA = "rp-data"
MAP = "rp-map"
STEP = "rp-step"
#: The classes each spot's frames are counted in: the layers' types, and the sky.
CLASSES = {"surface", "buildings", "sky"}


def _square(name: str, west: float, south: float, east: float, north: float, **properties) -> dict:
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"name": name, **properties}}


def _collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


#: The ground everything stands on, loaded first: autk-db clips every later
#: table to the first, so the spots and the towers lie inside it.
GROUND = _collection(_square("ground", -87.66, 41.87, -87.62, 41.89))
#: Two towers 150 m tall and 40 m wide, 200 m long north to south, with a street 20 m wide between them.
TOWERS = _collection(
    _square("west", -87.635, 41.88, -87.63452, 41.8818, height=150),
    _square("east", -87.63428, 41.88, -87.6338, 41.8818, height=150),
)
#: A spot in the street between the towers, and one a kilometer west of them.
SPOTS = _collection(
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-87.6344, 41.8809]}, "properties": {"spot": "street"}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-87.647, 41.8809]}, "properties": {"spot": "far"}},
)

#: The render pass both nodes run: the ground and the towers seen from each spot.
SKY_PASS = {
    "type": "render",
    "outputTableName": "sky",
    "layers": [
        {"id": "ground", "dataRef": "ground", "type": "surface"},
        {"id": "towers", "dataRef": "towers", "type": "buildings"},
    ],
    "viewpoints": {"dataRef": "spots", "sampling": {"directions": 4, "pitchDeg": 45}},
    "aggregation": {"type": "classes", "includeBackground": True, "backgroundLayerType": "sky"},
    "tileSize": 64,
}

DOCUMENTS = {
    DATA: {"data": [
        {"type": "geojson", "outputTableName": "ground", "geojsonObject": GROUND},
        {"type": "geojson", "outputTableName": "towers", "geojsonObject": TOWERS},
        {"type": "geojson", "outputTableName": "spots", "geojsonObject": SPOTS},
    ]},
    MAP: {
        "compute": [SKY_PASS],
        "map": {"layerRefs": [
            {"dataRef": "ground"},
            {"dataRef": "towers"},
            {"dataRef": "sky", "getFnv": "compute.render.classes.sky", "getFnvType": "quantitative",
             "colorMapInterpolator": "interpolateViridis", "isPick": True},
        ]},
    },
    STEP: {"compute": [SKY_PASS]},
}


#: The nodes whose output a save records: those whose Save toggle is on, which
#: is off by default (``CURIO_DEFAULT_SAVE_NODE_OUTPUT``).
SAVED = {STEP}


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
    "name": "Autark render passes",
    "task": "",
    "nodes": [_node(DATA, 80, 160), _node(MAP, 760, 40), _node(STEP, 760, 620)],
    "edges": [_edge(DATA, MAP), _edge(DATA, STEP)],
}}


def _enter(page, app_frontend, current_server, username: str) -> tuple[str, str]:
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark render passes",
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


def _assert_shares(by_spot: dict) -> None:
    """Each spot's frames counted in every class, each share between 0 and 1
    and together 1, and the spot between the towers seeing more of them, and
    less sky, than the far one."""
    assert sorted(by_spot) == ["far", "street"], by_spot
    for spot, classes in by_spot.items():
        assert set(classes) == CLASSES, (spot, classes)
        assert all(0 <= share <= 1 for share in classes.values()), (spot, classes)
        assert abs(sum(classes.values()) - 1) < 1e-4, (spot, classes)
    street, far = by_spot["street"], by_spot["far"]
    assert street["buildings"] > far["buildings"], by_spot
    assert street["sky"] < far["sky"], by_spot


def test_a_map_draws_the_table_its_render_pass_writes(app_frontend, current_server, page):
    _enter(page, app_frontend, current_server, "autark_render_passes_map")

    _play(page, MAP)
    frame_nodes(page, [MAP])
    assert_autark_map_drawn(page, MAP, timeout=60000)

    # The map draws the table the pass writes: every spot, each naming its input row.
    state = page.evaluate("(id) => window.__curio_mapState(id)", MAP)
    assert state and "sky" in state, state
    drawn = state["sky"]
    spots = len(SPOTS["features"])
    assert (drawn["drawn"], drawn["rows"], drawn["pick"]) == (spots, spots, True), drawn
    # Each drawn spot holds what its frames showed.
    by_spot = {}
    for position in range(spots):
        feature = page.evaluate("([id, table, at]) => window.__curio_mapFeatureAt(id, table, at)",
                                [MAP, "sky", position])
        assert feature, f"no spot is drawn at {position}"
        by_spot[feature["spot"]] = feature["compute"]["render"]["classes"]
    _assert_shares(by_spot)


def test_a_compute_step_hands_the_table_its_render_pass_writes_on(app_frontend, current_server, page):
    token, project_id = _enter(page, app_frontend, current_server, "autark_render_passes_step")

    _play(page, STEP)

    layers = _layers(_stored(page, current_server, token, project_id, STEP))
    assert sorted(layers) == ["ground", "sky", "spots", "towers"], sorted(layers)
    sky = layers["sky"]
    # The table the pass writes is typed as its viewpoints, and the spots are handed on as they were.
    assert sky["layerType"] == layers["spots"]["layerType"] == "points", (sky["layerType"], layers["spots"]["layerType"])
    assert [f["properties"].get("compute") for f in layers["spots"]["data"]["features"]] == [None, None]
    _assert_shares({f["properties"]["spot"]: f["properties"]["compute"]["render"]["classes"]
                    for f in sky["data"]["features"]})
