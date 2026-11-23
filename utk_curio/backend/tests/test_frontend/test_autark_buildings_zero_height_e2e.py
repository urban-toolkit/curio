"""A map layer that writes ``buildingsZeroHeight``, and one that does not.

autk-grammar's ``buildingsZeroHeight`` draws each part of a buildings layer
that has no height at a random 3 to 7 floors of 3.4 m, where autk-map leaves
such a part out. Curio's loaders hand a building part with no height on with
none, and a map takes it to be 6 m tall where its layer does not write the key
(``utils/autkInput`` ``heightsAtUse``).

An Autark node's data section loads six towers of the Chicago Loop in
EPSG:3395 metres, three 30 m tall and three with no height, after an ``area``
around them, and hands them on to two maps of the towers, read back from
autk-map's own objects (``window.__curio_mapDrawing``, each building's top)
and from what the grammar handed it (``window.__curio_mapHanded``):

- a map whose towers layer writes ``buildingsZeroHeight``: the three with no
  height reach autk-map holding no key of a top, and it raises each at a
  random 3 to 7 floors; the others stand 30 m;
- a map whose towers layer does not: the three with no height reach autk-map
  6 m tall, and stand so.

The heights are random, so no frame is taken: the tops are checked. The maps
need WebGPU, so this test runs on CI's GPU job.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_buildings_zero_height_e2e.py -v
"""
from __future__ import annotations

import json
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

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTARK_TYPE = "curio.builtin/autk-grammar"

#: The tables' south-west corner, in EPSG:3395 metres.
LOOP = (-9755000.0, 5106000.0)
#: How tall the towers with a height are: the even ones.
TOWER_HEIGHT = 30
#: How tall a map draws a tower with no height when its layer does not write the key.
DEFAULT_HEIGHT = 6
#: autk-map's random height of a building part with none: 3 to 7 floors of 3.4 m.
RANDOM_TOPS = (3 * 3.4, 7 * 3.4)
CLOSE = 1e-3


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

#: A map of the towers that raises the three with no height at random.
ZERO_HEIGHTS = {"map": {"layerRefs": [
    {"dataRef": "area", "color": "#e8e8e8"},
    {"dataRef": "towers", "buildingsZeroHeight": True},
]}}

#: The same map, its towers layer without the key.
DEFAULT_HEIGHTS = {"map": {"layerRefs": [
    {"dataRef": "area", "color": "#e8e8e8"},
    {"dataRef": "towers"},
]}}

_DRAWING_JS = "(id) => typeof window.__curio_mapDrawing === 'function' ? window.__curio_mapDrawing(id) : null"
_HANDED_JS = ("([id, table]) => typeof window.__curio_mapHanded === 'function' ? window.__curio_mapHanded(id, table) "
              ": Promise.resolve(null)")


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


def _towers(page, node_id: str, *, timeout: float = 30000) -> tuple[list, list]:
    """The towers layer *node_id*'s map draws, once it draws all six: each
    tower's top, in the order the layer draws them, and the towers as the
    grammar handed them to autk-map, in the same order."""
    deadline = time.monotonic() + timeout / 1000
    while True:
        drawn = page.evaluate(_DRAWING_JS, node_id) or {}
        towers = next((layer for layer in drawn.get("layers", []) if layer["id"] == "towers"), {})
        tops = towers.get("tops") or []
        if len(tops) == 6:
            handed = page.evaluate(_HANDED_JS, [node_id, "towers"]) or []
            return tops, handed
        assert time.monotonic() < deadline, f"Autark node {node_id}'s map draws {json.dumps(drawn)}"
        page.wait_for_timeout(500)


def test_a_map_layer_with_buildings_zero_height_raises_its_buildings_with_no_height_at_random(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    loader, zero, default = "zh-tables", "zh-towers", "zh-default"
    spec = {"dataflow": {
        "name": "AutarkZeroHeights", "task": "",
        "nodes": [
            _node(loader, 120, 160, {"data": DATA}),
            _node(zero, 820, 40, ZERO_HEIGHTS),
            _node(default, 820, 620, DEFAULT_HEIGHTS),
        ],
        "edges": [_edge(loader, zero), _edge(loader, default)],
    }}
    require_project_page()
    require_user_auth()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
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

    # The map whose layer writes the key. Plays the data node first, which hands the towers on.
    play_node(page, zero)
    wait_for_node_done(page, zero, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, zero, timeout=60000, attach_as="a map of towers whose layer writes buildingsZeroHeight")
    tops, handed = _towers(page, zero)
    evidence = f"handed to autk-map as {json.dumps(handed)}, the tops drawn {tops}"
    # The three with no height reach autk-map holding no key of a top, so it raises them.
    assert len(handed) == 6 and sorted(feature["row"] for feature in handed if not feature["tops"]) == [1, 3, 5], (
        f"the towers with no height do not reach autk-map without a height ({evidence}): it raises only a part "
        "that holds none (buildingsZeroHeight)"
    )
    assert all(feature["tops"] == {"height": TOWER_HEIGHT} for feature in handed if feature["tops"]), evidence
    # Each where it was handed: a tower with its height at it, one with none at random, above the ground.
    expected = [(TOWER_HEIGHT, TOWER_HEIGHT) if feature["tops"] else RANDOM_TOPS for feature in handed]
    assert all(top is not None and top > 0 for top in tops), evidence
    assert all(low - CLOSE <= top <= high + CLOSE for top, (low, high) in zip(tops, expected)), (
        f"the towers' tops are {tops}, each not at its own height, {expected} (buildingsZeroHeight); {evidence}"
    )

    # The map whose layer does not: the towers with no height stand 6 m tall.
    play_node(page, default)
    wait_for_node_done(page, default, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, default, timeout=60000, attach_as="a map of towers, some with no height")
    tops, handed = _towers(page, default)
    evidence = f"handed to autk-map as {json.dumps(handed)}, the tops drawn {tops}"
    assert sorted(feature["row"] for feature in handed if feature["tops"] == {"height": DEFAULT_HEIGHT}) == [1, 3, 5], (
        f"the towers with no height do not reach autk-map {DEFAULT_HEIGHT} m tall ({evidence})"
    )
    expected = [feature["tops"].get("height") for feature in handed]
    assert all(top is not None and abs(top - height) < CLOSE for top, height in zip(tops, expected)), (
        f"the towers' tops are {tops}, not the heights they were handed, {expected}; {evidence}"
    )
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
