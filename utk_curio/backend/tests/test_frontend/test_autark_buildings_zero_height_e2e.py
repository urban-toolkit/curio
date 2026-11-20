"""A map layer that writes ``buildingsZeroHeight``, refused by its Autark node.

autk-grammar's ``buildingsZeroHeight`` draws each part of a buildings layer
that has no height at a random 3 to 7 floors. Curio makes a building without a
height 6 m tall when it loads the data, so the key would change nothing, and a
node refuses it with that reason before anything runs (``notRunYet`` in
``src/contracts/autkGrammar.json``).

An Autark node's data section loads six towers of the Chicago Loop in
EPSG:3395 metres, three 30 m tall and three with no height, after an ``area``
around them, and hands them on to a map of the towers that writes the key. The
map's node ends in error with the node's sentence, and draws no map
(``window.__curio_mapDrawing``).

The map needs WebGPU, so this test runs on CI's GPU job.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_buildings_zero_height_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTARK_TYPE = "curio.builtin/autk-grammar"

#: The tables' south-west corner, in EPSG:3395 metres.
LOOP = (-9755000.0, 5106000.0)
#: How tall the towers with a height are: the even ones.
TOWER_HEIGHT = 30


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
    _source("area", [_feature(_square(LOOP[0] - 300, LOOP[1] - 700, 2600), name="Loop")]),
    _source("towers", [
        _feature(_square(LOOP[0] + 300 * i, LOOP[1] - 500, 60), **({"height": TOWER_HEIGHT} if i % 2 == 0 else {}))
        for i in range(6)
    ], layerType="buildings"),
]

#: A map of the towers that would raise the three with no height at random.
ZERO_HEIGHTS = {"map": {"layerRefs": [
    {"dataRef": "area", "color": "#e8e8e8"},
    {"dataRef": "towers", "buildingsZeroHeight": True},
]}}

#: What the node says of it, in the words of src/contracts/autkGrammar.json.
SAID = ('This spec uses "buildingsZeroHeight" (Curio makes a building without a height 6 m tall when it loads the '
        "data, so the key would change nothing) at map.layerRefs[1], which Curio does not run yet.")

_DRAWING_JS = "(id) => typeof window.__curio_mapDrawing === 'function' ? window.__curio_mapDrawing(id) : null"


def _node(node_id: str, x: int, y: int, document: dict) -> dict:
    return {
        "id": node_id, "type": AUTARK_TYPE, "x": x, "y": y, "content": json.dumps(document, indent=2),
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def test_a_map_layer_that_writes_buildings_zero_height_is_refused_with_the_reason(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    loader, towers = "zh-tables", "zh-towers"
    spec = {"dataflow": {
        "name": "AutarkZeroHeights", "task": "",
        "nodes": [_node(loader, 120, 160, {"data": DATA}), _node(towers, 820, 40, ZERO_HEIGHTS)],
        "edges": [{
            "id": f"reactflow__edge-{loader}out-{towers}in",
            "source": loader, "target": towers, "sourceHandle": "out", "targetHandle": "in",
        }],
    }}
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Zero Heights",
        username="autark_zero_heights",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)

    # Plays the data node first, which hands the towers on.
    play_node(page, towers)
    status = wait_for_node_settled(page, towers, node_type=AUTARK_TYPE, timeout_ms=120000)
    error = read_node_error_text(node_locator(page, towers)) or ""
    assert status == "error" and SAID in error, (
        f"the map of the towers ended {status!r}, saying {error!r}: a map layer that writes buildingsZeroHeight "
        "is refused with the reason"
    )
    # Refused before anything ran: the node drew no map.
    assert page.evaluate(_DRAWING_JS, towers) is None, "the refused map's node drew a map"
