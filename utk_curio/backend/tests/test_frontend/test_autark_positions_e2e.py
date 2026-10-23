"""Playwright E2E: an Autark map lights the features autk-db drew, on the
shipped Chicago Loop layers (``chicago-loop-layers.json``).

autk-db leaves a few features out of some layers it loads and keeps the others
in an order of its own: on this map, trees, buildings and parks lose a few, and
parks, water and roads come back in another order. Curio hands each feature to
autk-db with its input row and reads the rows back from what autk-db exported.

1. A selection of the last building the map draws, then of the first park,
   lights that feature on the map, and only features named as it is.
2. Every layer of the map reads back an input row for each feature it draws,
   and each tree and station autk-db exported lies where the map draws it.

The test records each finding and fails at the end with all of them. It runs an
Autark map, which needs WebGPU: without an adapter it skips, unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_positions_e2e.py -v
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .test_map_edits_e2e import EDIT_TYPE, MAP_TYPE, RUN_MS, _done, _enter
from .utils import REPO_ROOT, run_all_and_wait, wait_for_run_guard_released

if TYPE_CHECKING:
    from .utils import FrontendPage

#: Every table the map of the Chicago Loop layers draws.
LAYERS = ("input_0", "table_osm_parks", "table_osm_water", "table_osm_roads", "table_osm_buildings",
          "input_2", "input_3", "input_4")
#: Its layers of points: the trees and the CTA stations.
POINTS = ("input_3", "input_4")
#: The columns a feature of these layers is known by: the first it has.
KEYS = ("osm_id", "building_id")
#: How far, in metres, a point autk-db exported may lie from where the map
#: draws it: autk-map holds each point less the map's origin, in 32-bit floats.
POINT_TOLERANCE = 0.5

# What an Autark node's map draws and lights, as autk-map and autk-db hold it
# (window.__curio_mapState), and the feature it draws at a position
# (window.__curio_mapFeatureAt).
_STATE_JS = "(id) => (window.__curio_mapState ? window.__curio_mapState(id) : null)"
_FEATURE_AT_JS = """([id, table, position]) => (
    window.__curio_mapFeatureAt ? window.__curio_mapFeatureAt(id, table, position) : null
)"""
# A selection sent by a node over its interaction edges, as its own pick is.
_SEND_JS = """([id, selection]) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    node.data.interactionsCallback(selection, id);
}"""


def _named(feature: dict) -> tuple[str, object] | None:
    """The column a feature is known by, and its value there."""
    for key in KEYS:
        if feature.get(key) is not None:
            return key, feature[key]
    return None


def _lit_finding(page, map_id: str, table: str, key: str, value, position: int) -> str | None:
    """Wait until *table*'s layer lights the feature it draws at *position* and
    only features whose *key* is *value*; what it lights instead, if it never does."""
    layer: dict = {}
    deadline = time.time() + 30
    while time.time() < deadline:
        layer = (page.evaluate(_STATE_JS, map_id) or {}).get(table) or {}
        lit = [feature.get(key) for feature in layer.get("lit") or []]
        if lit and all(got == value for got in lit) and position in (layer.get("positions") or []):
            return None
        page.wait_for_timeout(250)
    lit = [feature.get(key) for feature in layer.get("lit") or []]
    return (f"a selection of {key} {value} on {table} lights the {key} {lit} at positions "
            f"{layer.get('positions')}, not the feature drawn at position {position}")


def test_the_chicago_loop_layers_light_the_features_autk_db_drew(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The shipped Chicago Loop layers, run: a selection of a building and of a
    park, each named by its id as the Map Edits node names what it picks, lights
    that feature on the map; and every layer reads back the input row of each
    feature it draws, its points where autk-db has them."""
    path = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-loop-layers.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    (edit_id,) = [n for n, node in nodes.items() if node["type"] == EDIT_TYPE]
    (map_id,) = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and '"map"' in node["content"]]
    _enter(page, app_frontend, current_server, spec, "autark_positions_e2e", name=spec["dataflow"]["name"])
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node in nodes.items():
        _done(page, node_id, node["type"])
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)

    state = page.evaluate(_STATE_JS, map_id) or {}
    assert sorted(state) == sorted(LAYERS), f"the map reports the tables {sorted(state)}, not {sorted(LAYERS)}"
    findings: list[str] = []

    # 1. The last building the map draws, then the first park, each selected
    # by its id from the Map Edits node linked to the map.
    for table, position in (("table_osm_buildings", -1), ("table_osm_parks", 0)):
        feature = page.evaluate(_FEATURE_AT_JS, [map_id, table, position]) or {}
        named = _named(feature)
        assert named, f"the feature drawn at position {position} of {table} has none of {KEYS}: {feature}"
        key, value = named
        page.evaluate(_SEND_JS, [edit_id, {"autk_selection": {
            "type": "POINT", "data": [{key: value}], "priority": 1, "source": EDIT_TYPE, "layerRef": table,
        }}])
        drawn_at = position if position >= 0 else state[table]["drawn"] + position
        finding = _lit_finding(page, map_id, table, key, value, drawn_at)
        if finding:
            findings.append(finding)

    # 2. An input row for each feature drawn, and the points where autk-db has them.
    for table in LAYERS:
        layer = state[table]
        if not layer["drawn"] or layer["rows"] != layer["drawn"]:
            findings.append(f"{table} draws {layer['drawn']} features and reads back an input row for {layer['rows']}")
    for table in POINTS:
        drift = state[table]["pointDrift"]
        if drift is None or drift > POINT_TOLERANCE:
            findings.append(f"a point of {table} autk-db exported lies {drift} m from where the map draws it")

    assert not findings, "\n".join(findings)
