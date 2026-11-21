"""Every polygon of a building part casts its shadow in the shadow examples' pass.

OpenStreetMap maps some buildings as one element of several polygons, such as
an elevated station's two platforms, one on each side of the tracks. Curio's
loaders hand on such a part as one row, a MultiPolygon, as autk-db keeps it.
The shadow pass of examples 06, 07 and 38 reads every building part of a table
as the box of its outline (`geometry.coordinates.0`, packed by autk-grammar's
batched `fromFeature`), so each polygon of a part must cast the shadow a part of
that one polygon casts.

An Autark node's data section loads a scene of the Chicago Loop in EPSG:3395
metres: a building part of two squares 400 m apart, 60 m tall; a tower of the
same square, a part of one polygon, 400 m further east; a road 10 m north of
each square; and a road in the open. Example 07's pass, as the example ships
it, runs over the roads and the building parts, in the two places a pass runs:

- a compute step of its own, between the data node and a map node, as
  examples 06 and 07 run it;
- the node that draws its map, as example 38 runs it.

Each road's minutes of sun are read from the features the map drew
(``window.__curio_mapFeatureAt``): the roads by the part's two squares get the
minutes of the road by the tower, which a square of the same size at the same
distance shades, and less sun than the road in the open. No frame is taken.
The maps need WebGPU, so this test runs on CI's GPU job.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_building_part_shadows_e2e.py -v
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .utils import (
    REPO_ROOT,
    assert_autark_map_drawn,
    dismiss_toasts,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTARK_TYPE = "curio.builtin/autk-grammar"
#: Example 07, whose compute step runs the shadow pass this test runs.
EXAMPLE_07 = "07-autark-gpu-shader.json"
EXAMPLE_07_PASS = "sh-compute"
#: How long the small dataflow's run may take.
RUN_MS = 240000

#: The scene's south-west corner in the Chicago Loop, in EPSG:3395 metres.
LOOP = (-9755000.0, 5113000.0)
SIDE = 40.0
HEIGHT = 60
#: From one square to the next, west to east: the part's two, then the tower.
GAP = 400.0
#: How far north of its square each road runs.
ROAD_OFFSET = 10.0

FIRST, SECOND, TOWER, OPEN = "by the first polygon", "by the second polygon", "by the tower", "in the open"


def _ring(x: float, y: float) -> list:
    return [[x, y], [x + SIDE, y], [x + SIDE, y + SIDE], [x, y + SIDE], [x, y]]


def _feature(geometry: dict, **properties) -> dict:
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def _source(name: str, features: list, **more) -> dict:
    return {
        "type": "geojson", "outputTableName": name, "coordinateFormat": "EPSG:3395",
        "geojsonObject": {"type": "FeatureCollection", "features": features}, **more,
    }


def _road(x: float, name: str) -> dict:
    y = LOOP[1] + SIDE + ROAD_OFFSET
    return _feature({"type": "LineString", "coordinates": [[x, y], [x + SIDE, y]]}, name=name)


_X = [LOOP[0] + GAP * i for i in range(4)]

DATA = [
    # Loaded first: autk-db keeps in a workspace what lies in its first table's box.
    _source("area", [_feature({"type": "Polygon", "coordinates": [[
        [LOOP[0] - 200, LOOP[1] - 200], [LOOP[0] + 1600, LOOP[1] - 200],
        [LOOP[0] + 1600, LOOP[1] + 300], [LOOP[0] - 200, LOOP[1] + 300], [LOOP[0] - 200, LOOP[1] - 200],
    ]]}, name="Loop")]),
    _source("parts", [
        _feature({"type": "MultiPolygon", "coordinates": [[_ring(_X[0], LOOP[1])], [_ring(_X[1], LOOP[1])]]},
                 name="two platforms", height=HEIGHT),
        _feature({"type": "Polygon", "coordinates": [_ring(_X[2], LOOP[1])]}, name="tower", height=HEIGHT),
    ], layerType="buildings"),
    _source("roads", [_road(_X[0], FIRST), _road(_X[1], SECOND), _road(_X[2], TOWER), _road(_X[3], OPEN)],
            layerType="roads"),
]


def _example_pass() -> dict:
    """Example 07's shadow pass as the example ships it, over this scene's roads and building parts."""
    dataflow = json.loads(Path(REPO_ROOT, "docs", "examples", EXAMPLE_07).read_text(encoding="utf-8"))["dataflow"]
    content = next(node["content"] for node in dataflow["nodes"] if node["id"] == EXAMPLE_07_PASS)
    (shadow,) = json.loads(content)["compute"]
    shadow = copy.deepcopy(shadow)
    assert shadow["uniformMatrices"]["ring"]["fromFeature"]["path"] == "geometry.coordinates.0", shadow
    shadow["dataRef"] = "roads"
    shadow["uniforms"]["bld_height"]["fromFeature"]["layer"] = "parts"
    shadow["uniformMatrices"]["ring"]["fromFeature"]["layer"] = "parts"
    return shadow


def _map(roads: str, sun: str) -> dict:
    return {"map": {"layerRefs": [
        {"dataRef": "area", "color": "#e8e8e8"},
        {"dataRef": "parts"},
        {"dataRef": roads, "isColorMap": True, "getFnv": sun, "getFnvType": "quantitative", "defaultFnv": 0},
    ]}}


def _node(node_id: str, x: int, document: dict, **size) -> dict:
    return {
        "id": node_id, "type": AUTARK_TYPE, "x": x, "y": 120, "content": json.dumps(document, indent=2),
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []}, **size,
    }


def _edge(source: str, target: str) -> dict:
    return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target,
            "sourceHandle": "out", "targetHandle": "in"}


def _dataflow(where: str) -> tuple[dict, str, str]:
    """The scene's dataflow with the pass *where* it runs, the node whose map draws the roads with
    their minutes of sun, and the table it draws them from."""
    size = {"width": 760, "height": 520}
    if where == "compute_step":
        nodes = [
            _node("bp-data", 0, {"data": DATA}),
            _node("bp-sun", 640, {"compute": [_example_pass()]}),
            # A compute step lifts what its pass computed to the roads' own properties.
            _node("bp-map", 1280, _map("roads", "sunlight"), **size),
        ]
        edges = [_edge("bp-data", "bp-sun"), _edge("bp-sun", "bp-map")]
        flow = {"name": "AutarkPartShadowsStep", "task": "", "nodes": nodes, "edges": edges}
        return {"dataflow": flow}, "bp-map", "roads"
    # As example 38's passes: into a table of the roads of its own, under the features' `compute`.
    shadow = {**_example_pass(), "outputTableName": "road_sun", "layerType": "roads"}
    document = {"data": DATA, "compute": [shadow], **_map("road_sun", "compute.sunlight")}
    flow = {"name": "AutarkPartShadowsOne", "task": "", "nodes": [_node("bp-one", 0, document, **size)], "edges": []}
    return {"dataflow": flow}, "bp-one", "road_sun"


# Each road's minutes of sun, by its name, read from the features the map of
# node *id* drew of *table*: under the feature's `compute`, where a pass of the
# node's own document writes them, else as the road's own property, where a
# compute step upstream lifted them.
_SUN_BY_ROAD_JS = """async ([id, table]) => {
    const state = await window.__curio_mapState(id);
    const drawn = (state && state[table] && state[table].drawn) || 0;
    const roads = {};
    for (let at = 0; at < drawn; at++) {
        const feature = await window.__curio_mapFeatureAt(id, table, at);
        if (!feature) continue;
        const value = (feature.compute || {}).sunlight ?? feature.sunlight;
        roads[String(feature.name)] = typeof value === 'number' ? value : null;
    }
    return roads;
}"""


def _sun_by_road(page, node_id: str, table: str, *, timeout_s: float = 60.0) -> dict:
    """Each road's minutes of sun, once the map of *node_id* draws all four roads of *table* with theirs."""
    deadline = time.monotonic() + timeout_s
    while True:
        roads = page.evaluate(_SUN_BY_ROAD_JS, [node_id, table]) or {}
        if sorted(roads) == sorted([FIRST, SECOND, TOWER, OPEN]) and all(v is not None for v in roads.values()):
            return roads
        assert time.monotonic() < deadline, f"the map of {node_id} draws the roads of {table} with the minutes {roads}"
        page.wait_for_timeout(500)


@pytest.mark.parametrize("where", ["compute_step", "one_node"])
def test_a_shadow_pass_shades_the_road_by_each_polygon_of_a_building_part(
    app_frontend: "FrontendPage", current_server: str, page, record_property, where: str,
):
    spec, map_node, table = _dataflow(where)
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Part Shadows",
        username=f"autk_part_shadows_{where}",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    require_webgpu(page)
    run_all_and_wait(page, timeout_ms=RUN_MS)
    dismiss_toasts(page)
    assert_autark_map_drawn(page, map_node, timeout=120000, attach_as="a map of the scene's roads by their minutes of sun")

    roads = _sun_by_road(page, map_node, table)
    for name, minutes in sorted(roads.items()):
        record_property(f"sun_minutes_{name.replace(' ', '_')}", minutes)
    evidence = ", ".join(f"the road {name} {roads[name]:g}" for name in (FIRST, SECOND, TOWER, OPEN))
    # The pass runs and shades: a part of one polygon shades the road by it.
    assert roads[TOWER] < roads[OPEN], f"the tower shades no road ({evidence} minutes of sun)"
    # Each polygon of the part of two shades the road by it as the tower, a
    # square of the same size at the same distance, shades its own.
    assert roads[SECOND] == roads[TOWER] and roads[FIRST] == roads[TOWER], (
        f"a building part of two polygons does not shade the roads by its polygons as a part of one polygon "
        f"shades the road by it: {evidence} minutes of sun"
    )
