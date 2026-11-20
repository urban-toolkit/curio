"""autk-grammar 5.3.0's map keys and 5.4.0's camera keys, drawn by Autark nodes.

An Autark node's data section loads tables of the Chicago Loop in EPSG:3395
metres: an ``area`` around them all, which a map draws first so autk-db keeps
every later table whole, four ``zones`` with their riders, three ``lanes``
each with its own width ``w``, and four ``stops`` with a ``load``. It hands
them on to maps, each read back from autk-map's own objects
(``window.__curio_mapDrawing``):

- a map of every layer key a node runs: the zones colored by their riders, in
  the legend (``legend``), two of them picked from the start (``isPick``,
  ``pickedComps``) and kept lit while nothing comes into the node; the lanes
  drawn as roads (``layerType``), each as wide as its ``w`` (``widthBy``);
  and the stops colored by their load, after the zones, two of them hidden
  (``skippedComps``). A node refuses ``buildingsZeroHeight``
  (``test_autark_buildings_zero_height_e2e.py``);
- a map in a style of its own (``style``'s colors), its zones colored by their
  riders, without autk-map's menu and legend (``showUi``);
- a map whose ground rises to a band of a GeoTIFF its own data section loads
  (``terrain``).

A second dataflow's map looks at a point (``camera.center``) and plays a tour
(``camera.motion``) that turns its heading 90 degrees; once the tour ends
(``window.__curio_mapTourEnded``, the grammar's ``tours``), the view looks at
the point, at the zoom's distance, tilted as the camera says, facing east.

The maps need WebGPU, so this test runs on CI's GPU job.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_map_keys_e2e.py -v
"""
from __future__ import annotations

import json
import math
import time
from typing import TYPE_CHECKING

from .utils import (
    assert_autark_map_drawn,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)
from .utils.node_drawings import true_up

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTARK_TYPE = "curio.builtin/autk-grammar"

#: The tables' south-west corner, in EPSG:3395 metres.
LOOP = (-9755000.0, 5106000.0)
RIDERS = [0, 25, 50, 100]
WIDTHS = [4, 12, 24]
PICKED = [1, 3]
HIDDEN = [0, 2]


def _square(x: float, y: float, side: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x, y], [x + side, y], [x + side, y + side], [x, y + side], [x, y]]]}


def _source(name: str, features: list[dict], **more) -> dict:
    return {
        "type": "geojson", "outputTableName": name, "coordinateFormat": "EPSG:3395",
        "geojsonObject": {"type": "FeatureCollection", "features": features}, **more,
    }


def _feature(geometry: dict, **properties) -> dict:
    return {"type": "Feature", "properties": properties, "geometry": geometry}


DATA = [
    # Loaded first: autk-db keeps in a workspace what lies in its first table's box.
    _source("area", [_feature({"type": "Polygon", "coordinates": [[
        [LOOP[0] - 300, LOOP[1] - 700], [LOOP[0] + 2300, LOOP[1] - 700],
        [LOOP[0] + 2300, LOOP[1] + 1300], [LOOP[0] - 300, LOOP[1] + 1300], [LOOP[0] - 300, LOOP[1] - 700],
    ]]}, name="Loop")]),
    _source("zones", [_feature(_square(LOOP[0] + 500 * i, LOOP[1], 400), riders=riders) for i, riders in enumerate(RIDERS)]),
    _source("lanes", [
        _feature({"type": "LineString", "coordinates": [
            [LOOP[0] + 600 * i, LOOP[1] + 700], [LOOP[0] + 600 * i + 500, LOOP[1] + 700],
        ]}, w=width)
        for i, width in enumerate(WIDTHS)
    ]),
    _source("stops", [
        _feature({"type": "Point", "coordinates": [LOOP[0] + 500 * i + 200, LOOP[1] + 1000]}, load=i + 1)
        for i in range(4)
    ]),
]

EVERY_LAYER_KEY = {"map": {"highlightColor": "#ff7f0e", "layerRefs": [
    {"dataRef": "area", "color": "#e8e8e8"},
    {"dataRef": "zones", "getFnv": "riders", "legend": True, "isPick": True, "pickedComps": PICKED},
    {"dataRef": "lanes", "layerType": "roads", "widthBy": "w"},
    {"dataRef": "stops", "getFnv": "load", "skippedComps": HIDDEN},
]}}

#: The zones colored by their riders, which would put them in the legend, on the area in the style's polygons
#: color, and the lanes and the stops in the style's own colors.
NO_CONTROLS = {"map": {
    "showUi": False,
    "style": {
        "background": "#0b1a2a", "surface": "#13263a", "parks": "#1f4d3a", "water": "#08121d", "roads": "#3a5068",
        "buildings": "#5b7083", "points": "#f2c14e", "polylines": "#7f97ad", "polygons": "#2a3d52",
    },
    "layerRefs": [{"dataRef": "area"}, {"dataRef": "zones", "getFnv": "riders"}, {"dataRef": "lanes"}, {"dataRef": "stops"}],
}}

#: A GeoTIFF of Niteroi's land surface temperatures, a band a year from 2001 to 2024.
RAISED = {
    "data": [{"type": "geotiff", "outputTableName": "lst",
              "geotiffFileUrl": "docs/examples/data/niteroi_lst_verao_2001_2024.tif"}],
    "map": {
        "terrain": {"dataRef": "lst", "band": "band_24"},
        "camera": {"pitch": 45},
        "layerRefs": [{"dataRef": "lst", "getFnv": "band_24", "colorMapInterpolator": "interpolateViridis"}],
    },
}

#: Where the toured map looks: between the first two zones, about 500 m west
#: of the middle of what it draws, where Curio frames it. And its camera.
CENTER = (-87.6262, 41.8243)
ZOOM = 13
PITCH = 30
TOURED = {"map": {
    "camera": {
        "center": list(CENTER), "zoom": ZOOM, "pitch": PITCH,
        "motion": [{"type": "bearing", "amount": 90, "seconds": 1}],
    },
    "layerRefs": [
        {"dataRef": "area"},
        {"dataRef": "zones", "getFnv": "riders", "colorMapInterpolator": "interpolateViridis"},
    ],
}}

_DRAWING_JS = "(id) => typeof window.__curio_mapDrawing === 'function' ? window.__curio_mapDrawing(id) : null"
_TOUR_ENDED_JS = ("(id) => typeof window.__curio_mapTourEnded === 'function' ? window.__curio_mapTourEnded(id) "
                  ": Promise.resolve(null)")
_VIEWS_JS = "(id) => typeof window.__curio_mapViews === 'function' ? window.__curio_mapViews(id) : null"


def _world_mercator(lon: float, lat: float) -> tuple[float, float]:
    """*lon*, *lat* in EPSG:3395, World Mercator on the WGS84 ellipsoid, the CRS of a map's default workspace."""
    a, e = 6378137.0, 0.0818191908426215
    phi = math.radians(lat)
    ratio = ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2)
    return a * math.radians(lon), a * math.log(math.tan(math.pi / 4 + phi / 2) * ratio)


def _node(node_id: str, x: int, y: int, document: dict) -> dict:
    return {
        "id": node_id, "type": AUTARK_TYPE, "x": x, "y": y, "content": json.dumps(document, indent=2),
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}in",
        "source": source, "target": target, "sourceHandle": "out", "targetHandle": "in",
    }


def _open(page, app_frontend, current_server: str, name: str, nodes: list, edges: list) -> list[str]:
    """Open a dataflow of *nodes* and *edges* as its owner; return the console's errors as they come."""
    spec = {"dataflow": {"name": name.replace(" ", ""), "task": "", "nodes": nodes, "edges": edges}}
    require_project_page()
    require_user_auth()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=name,
        username=name.lower().replace(" ", "_"),
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    return errors


def _drawing(page, node_id: str, holds, what: str, *, timeout: float = 30000) -> dict:
    """What *node_id*'s map draws once *holds* is true of it; fails naming *what* otherwise."""
    deadline = time.monotonic() + timeout / 1000
    while True:
        drawn = page.evaluate(_DRAWING_JS, node_id)
        if drawn is not None and holds(drawn):
            return drawn
        assert time.monotonic() < deadline, f"{what}: Autark node {node_id}'s map draws {json.dumps(drawn)}"
        page.wait_for_timeout(500)


def _layer(drawn: dict, layer_id: str) -> dict:
    return next((layer for layer in drawn.get("layers", []) if layer["id"] == layer_id), {})


def test_a_map_draws_its_terrain_layer_types_widths_hidden_and_picked_features_legend_style_and_controls(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    loader, keys, plain, raised = "mk-tables", "mk-every-layer-key", "mk-no-controls", "mk-terrain"
    errors = _open(page, app_frontend, current_server, "Autark Map Keys", [
        _node(loader, 120, 160, {"data": DATA}),
        _node(keys, 820, 40, EVERY_LAYER_KEY),
        _node(plain, 820, 620, NO_CONTROLS),
        _node(raised, 1520, 40, RAISED),
    ], [_edge(loader, keys), _edge(loader, plain)])

    # Every layer key. Plays the data node first.
    play_node(page, keys)
    wait_for_node_done(page, keys, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, keys, timeout=60000, attach_as="a map of every layer key autk-grammar 5.3.0 adds")
    drawn = _drawing(page, keys, lambda d: len(d.get("layers", [])) >= 4, "four layers")

    # The zones in the legend, though the stops are colored after them.
    assert drawn["legend"] == "zones", f"the legend shows {drawn['legend']!r}, not the zones, which set legend"
    # The lanes drawn as roads, each line as wide as its w.
    lanes = _layer(drawn, "lanes")
    assert lanes.get("type") == "roads", f"the lanes are drawn as {lanes.get('type')!r}, not as roads (layerType)"
    assert sorted(lanes.get("widths") or []) == WIDTHS, f"the lanes' widths are {lanes.get('widths')}, not {WIDTHS} (widthBy)"
    # Two stops hidden.
    assert _layer(drawn, "stops").get("skipped") == HIDDEN, (
        f"the stops hide {_layer(drawn, 'stops').get('skipped')}, not {HIDDEN} (skippedComps)"
    )
    # The zones picked from the start, and still lit once the node settles: nothing came in to clear them.
    picked = _drawing(page, keys, lambda d: _layer(d, "zones").get("highlighted") == PICKED,
                      f"zones {PICKED} lit from the start (pickedComps)")
    page.wait_for_timeout(1000)
    _drawing(page, keys, lambda d: _layer(d, "zones").get("highlighted") == PICKED,
             f"zones {PICKED} still lit with nothing coming in", timeout=5000)
    assert picked["controls"], "a map that sets no showUi shows autk-map's menu and legend"

    # A style of its own and no controls.
    play_node(page, plain)
    wait_for_node_done(page, plain, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, plain, timeout=60000, attach_as="a map in a style of its own without its controls")
    bare = _drawing(page, plain, lambda d: len(d.get("layers", [])) >= 4, "four layers")
    assert bare["controls"] is False, "a map whose showUi is false shows autk-map's menu or legend"

    # The ground raised to the GeoTIFF's 2024 band.
    play_node(page, raised)
    wait_for_node_done(page, raised, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, raised, timeout=90000, attach_as="a map raised on a GeoTIFF's band (terrain)")
    ground = _drawing(page, raised, lambda d: d.get("terrain") is not None, "a terrain's heightfield (terrain)")["terrain"]
    assert ground["width"] >= 2 and ground["height"] >= 2, f"the terrain's heightfield is {ground}"
    assert math.isfinite(ground["minHeight"]) and ground["maxHeight"] > ground["minHeight"], (
        f"the terrain rises from {ground['minHeight']} to {ground['maxHeight']}: the band's temperatures, not flat ground"
    )
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors


def test_a_camera_looks_at_its_center_and_ends_its_tour_where_its_steps_add_up(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    loader, toured = "tour-tables", "tour-map"
    errors = _open(page, app_frontend, current_server, "Autark Camera Tour", [
        _node(loader, 120, 160, {"data": DATA[:2]}),
        _node(toured, 820, 40, TOURED),
    ], [_edge(loader, toured)])

    play_node(page, toured)
    wait_for_node_done(page, toured, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, toured, timeout=60000, attach_as="a map that looks at its center and tours")
    # The tour the map plays once Curio framed it, read when it ends (the grammar's tours).
    ended = page.evaluate(_TOUR_ENDED_JS, toured)
    assert ended is True, f"the map's tour never ended or never played (camera.motion): {ended!r}"

    [view] = page.evaluate(_VIEWS_JS, toured)
    eye, look, origin = view["eye"], view["lookAt"], view["origin"]
    center = _world_mercator(*CENTER)
    looks_at = (look[0] + origin[0], look[1] + origin[1])
    assert math.dist(looks_at, center) < 2, (
        f"the map looks at {looks_at}, {math.dist(looks_at, center):.1f} m from its center {center} (camera.center)"
    )
    dx, dy, dz = look[0] - eye[0], look[1] - eye[1], look[2] - eye[2]
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    pitch = math.degrees(math.acos(max(-1.0, min(1.0, -dz / distance))))
    bearing = math.degrees(math.atan2(dx, dy)) % 360
    assert abs(distance - 10000 / 2 ** (ZOOM - 10)) < 1, f"the eye is {distance:.1f} units from the center, not zoom {ZOOM}'s"
    assert abs(pitch - PITCH) < 0.5 and abs(bearing - 90) < 0.5, (
        f"after the tour the view is tilted {pitch:.2f} degrees facing {bearing:.2f}: the camera's {PITCH}, turned 90"
    )
    assert all(abs(a - b) < 0.02 for a, b in zip(view["up"], true_up(PITCH, 90))), (
        f"the view's up is {view['up']}, not across its line of sight facing east: {true_up(PITCH, 90)}"
    )
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
