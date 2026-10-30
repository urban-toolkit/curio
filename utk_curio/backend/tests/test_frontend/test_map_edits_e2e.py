"""Playwright E2E: the Map Editor node (#662; its type id is still
``curio.builtin/edit-features``).

A small dataflow first. One layer of three building parts, two of them one
building's, so they share its ``building_id``, as Autark's buildings do, feeds
two scenarios: "Every building", whose Map Editor node has no edits, and "One
removed", a copy of it. In each, the loader feeds Map Editor, Map Editor feeds an
Autark map, the map feeds the node that counts the parts (or sums their
heights), and an interaction edge links Map Editor and its map. The node's code
is its only state.

1. A building clicked on the linked map is selected in Map Editor, which sends
   it back for the map to light up. Remove takes it off the map at once, the
   dataflow reads Unsaved and the nodes below keep what they had. Commit edits
   runs them, and the count drops by every part of the building. Saved and
   opened again, the code, the list and the Remove's entry in the node's
   Provenance drawer come back.
2. A rule lights up what it matches on the map, then removes it at once; the
   removal switched off stays in the list and is skipped, and an expression by
   a rule halves the tall part. Commit edits hands the total on.
3. The map lights a pick, both parts of a building, with its own highlight and
   nothing drawn over it; a plain click on another building replaces the pick,
   and the map played draws again with nothing picked.
4. On a zoomed map, building 1 picked: its form is for both its parts, so its
   height is empty and lists both heights. A height set there goes to both
   parts and keeps the map's view, and Commit edits hands it on through the
   map.
5. Each change is an entry in the node's Provenance drawer before any run, and
   putting the first entry's code back restores the map, the panel and the
   list.
6. On a map the node feeds but is not linked to, the edits show, and a click
   selects nothing in the node.

Then the shipped Chicago Loop layers (``chicago-loop-layers.json``): a point
added to the trees, a road reshaped and a property added to the parks, each on
the map; Commit edits runs the node, and its output holds all three. And one
of its buildings of several parts, each part with its own ``osm_id``, reshaped
part by part: Move points shows every part's corners, a dragged corner changes
its own part alone, and the building's other parts keep their shapes. And a
corner of a compact building dragged across a far side of its outline, which
would make the outline cross itself, is refused: no edit is written, the map's
tip says why, and the map keeps drawing the buildings.

Interaction frames take both nodes of a gesture before and after it, and every
Autark map gets a close-up. They run Autark maps, which need WebGPU: without an
adapter they skip, unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job),
where they fail.

Last, building 20449794 of the Chicago Loop layers, of seven parts, each with
its own ``osm_id``: its form is for all its parts, and one part chosen in its
parts menu takes a height, which Commit edits hands on for that part alone.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_map_edits_e2e.py -v
"""

from __future__ import annotations

import ast
import base64
import json
import math
import re
import time
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .test_scenario_drop_e2e import _saved_spec
from .test_widget_tags_e2e import _open_tab
from .utils import (
    _OUTPUT_ARTIFACT_JS,
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    INTERACTION_MIN_CHANGED_PIXELS,
    INTERACTION_SHOWN_TIMEOUT_MS,
    INTERACTION_VIEWPORT,
    REPO_ROOT,
    _compare_images,
    assert_autark_map_drawn,
    assert_in_view,
    autark_map_framing,
    canvas_painted_at_shown_zoom,
    changed_pixels,
    dismiss_toasts,
    drawing_kept,
    dump_browser_log,
    frame_nodes,
    keep_drawing,
    load_artifact_as_dict,
    mark_point,
    node_locator,
    park_pointer,
    play_node,
    read_node_code,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_dataflow,
    save_dataflow_and_settle_header,
    save_interaction_frame,
    save_node_closeup,
    save_workflow_test_screenshot,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_node_capture,
    wait_for_node_run_to_end,
    wait_for_node_settled,
    wait_for_node_still,
    wait_for_run_guard_released,
    watch_node_run,
)
from .utils.node_drawings import _AUTK_MAP_PIXELS_IN_FRAME_JS
from .walkthroughs.steps import PROVENANCE_DRAWER, PROVENANCE_PANEL, await_drawer_at_rest

if TYPE_CHECKING:
    from .utils import FrontendPage

EDIT_TYPE = "curio.builtin/edit-features"
MAP_TYPE = "curio.builtin/autk-grammar"
LOAD = "me-load"
EDIT, EDIT_2 = "me-edit", "me-edit-2"
MAP, MAP_2 = "me-map", "me-map-2"
COUNT, COUNT_2 = "me-count", "me-count-2"
EVERY, LESS = "s-every", "s-less"
#: The layer of the node's one input, as the node and the map call it, and
#: the column that identifies its features.
LAYER = "input_0"
KEY = "building_id"
#: What the maps are called on the canvas, so the node says which one it is linked to.
MAP_TITLE = "Buildings map"
#: The stem of the frames of the small dataflow, which no file holds, and of
#: the Chicago Loop layers' edits.
STEM = "map-edits"
CHICAGO_STEM = "chicago-loop-layers-map-edits"

# Building 1 in two parts, side by side on the left; building 2, one part as
# wide as both, on the right. Near Back Bay, in degrees, about 4 km across, so
# they fill much of the map an Autark node draws a city in.
LOAD_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "x, y, w, h = -71.1000, 42.3400, 0.0120, 0.0250\n"
    "return gpd.GeoDataFrame(\n"
    '    {"building_id": [1, 1, 2], "height": [20.0, 35.0, 50.0], "name": ["North", "North", "South"]},\n'
    "    geometry=[box(x, y, x + w, y + h), box(x + w, y, x + 2 * w, y + h), box(x + 2 * w, y, x + 4 * w, y + h)],\n"
    "    crs=4326,\n"
    ")\n"
)
#: Each building's parts, their heights and their name.
PARTS = {1: 2, 2: 1}
HEIGHTS = {1: [20.0, 35.0], 2: [50.0]}
NAMES = {1: "North", 2: "South"}
COUNT_CODE = "return len(input_0)\n"
#: The last nodes of the tests that sum the parts' heights instead.
TOTAL_CODE = 'return float(input_0["height"].sum())\n'
TOTAL = 20.0 + 35.0 + 50.0
#: The height the tests set on a building.
NEW_HEIGHT = 99

#: The map's document: the layer, coloured by height on a fixed range, and
#: picked by building_id.
MAP_SPEC = json.dumps({"map": {"layerRefs": [{
    "dataRef": "input_0",
    "isPick": True,
    "selectFields": ["building_id"],
    "isColorMap": True,
    "getFnv": "height",
    "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateViridis",
    "colorMapRange": [0, 100],
    "title": "Building height (m)",
}]}}, indent=2)

#: The comment lines a new Map Editor node's code starts with.
NOTE = (
    "# Map Editor writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
)
#: A new node's code: no edits yet.
NO_EDITS = NOTE + "return curio_edit_features(input_0, [])\n"
#: Code as the node writes it for one removal, of building 2.
REMOVE_TWO = NOTE + (
    "return curio_edit_features(input_0, [\n"
    '    {"op": "remove", "ids": [2]},\n'
    '], key="building_id", layer="input_0")\n'
)

#: Where a click is tried on a map, as fractions of the part of it in view.
PICK_SPOTS = ((0.4, 0.5), (0.6, 0.5), (0.45, 0.55), (0.7, 0.5), (0.3, 0.5), (0.5, 0.5), (0.2, 0.6), (0.8, 0.6))
#: Where a click is tried on building 1, the left half of the layer the map
#: frames, and on building 2, its right half.
LEFT_SPOTS = ((0.25, 0.5), (0.3, 0.5), (0.2, 0.55), (0.35, 0.45))
RIGHT_SPOTS = ((0.75, 0.5), (0.7, 0.5), (0.8, 0.55), (0.65, 0.45))
#: How a test zooms a map in: wheel steps over its middle, at most.
ZOOM_STEPS = 12
ZOOM_DELTA = 240
#: The share of a map's pixels a removed building takes away from the
#: drawing, at least: each of the two buildings fills a good part of it.
REMOVED_MIN_SHARE = 0.02
#: The map's background, the colour where it draws nothing (autk-map's style).
MAP_BACKGROUND = (232, 239, 242)
#: autk-map's highlight, #5dade2: the colour the map draws a Map Editor node's
#: tools in, its corners and the shape being drawn or changed.
MAP_HIGHLIGHT = (93, 173, 226)
#: How long a run of the dataflow, or of a node and the nodes below it, may take.
RUN_MS = 300000
#: The Chicago Loop layers' OSM buildings, as the map and the node name them,
#: and the column that tells a building's parts apart: each part's own OSM id.
BUILDINGS = "table_osm_buildings"
PART_KEY = "osm_id"
#: How much room, in page pixels, the map is zoomed in to give a corner to be
#: dragged, and the least a corner needs for a press to take it alone.
CORNER_ROOM = 16
PRESS_ROOM = 6
#: How much of the map a building framed for its close-up spans, its box's
#: longer side to the map's: about a third, so the building and its corners
#: are plain in the frame, with room around it for a corner dragged past its
#: far side, clear of the tip at the top left and the legend at the bottom
#: right.
FRAME_FILL = (0.3, 0.42)
#: What the map's tip says when a corner dragged would make its outline cross
#: itself: autk-db refuses such a shape, and with it the whole layer (#1112).
CROSSED_DRAG = "That would make the outline cross itself, so the corner went back."


def _spec(last_code: str = COUNT_CODE, last_title: str = "Count", *, linked: bool = True) -> dict:
    """The small dataflow, its last nodes running *last_code*; with *linked*
    False, One removed's Map Editor node feeds its map but is not linked to it."""
    def node(node_id, node_type, x, y, content, title, metadata=None):
        return {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content, "title": title,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], **(metadata or {})},
        }

    def edge(source, target):
        return {"id": f"e-{source}-{target}", "source": source, "target": target, "sourceHandle": "out", "targetHandle": "in"}

    def link(source, target):
        return {"id": f"i-{source}-{target}", "source": source, "target": target,
                "sourceHandle": "in/out", "targetHandle": "in/out", "type": "Interaction"}

    # Map Editor nodes are 560 wide and 460 tall, the others 525 by 350.
    edges = [
        edge(LOAD, EDIT), edge(EDIT, MAP), edge(MAP, COUNT), link(EDIT, MAP),
        edge(LOAD, EDIT_2), edge(EDIT_2, MAP_2), edge(MAP_2, COUNT_2),
    ]
    if linked:
        edges.append(link(EDIT_2, MAP_2))
    return {
        "dataflow": {
            "name": "Map Editor",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Map Editor",
            "nodes": [
                node(LOAD, "curio.builtin/data-loading", 0, 300, LOAD_CODE, "Buildings"),
                node(EDIT, EDIT_TYPE, 700, 0, NO_EDITS, "Map Editor"),
                node(MAP, MAP_TYPE, 1400, 0, MAP_SPEC, MAP_TITLE),
                node(COUNT, "curio.builtin/computation-analysis", 2050, 0, last_code, last_title),
                node(EDIT_2, EDIT_TYPE, 700, 700, NO_EDITS, "Map Editor", {"copiedFrom": [EDIT]}),
                node(MAP_2, MAP_TYPE, 1400, 700, MAP_SPEC, MAP_TITLE, {"copiedFrom": [MAP]}),
                node(COUNT_2, "curio.builtin/computation-analysis", 2050, 700, last_code, last_title,
                     {"copiedFrom": [COUNT]}),
            ],
            "edges": edges,
            "scenarios": [
                {"id": EVERY, "name": "Every building", "color": "#3567c7", "nodes": [EDIT, MAP, COUNT]},
                {"id": LESS, "name": "One removed", "color": "#2f8f4a", "nodes": [EDIT_2, MAP_2, COUNT_2]},
            ],
        }
    }


def _enter(page, app_frontend, current_server, spec: dict, username: str, *, name: str = "Map Editor") -> dict:
    """Sign in, open *spec* as one's own dataflow, and wait for its nodes, in a
    page with room to frame a Map Editor node beside its map."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.set_viewport_size(INTERACTION_VIEWPORT)
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=name,
        username=username,
        project_name=name,
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="attached", timeout=45000)
    require_webgpu(page)
    return session


def _done(page, node_id: str, node_type: str = "") -> None:
    status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=180000)
    assert status == "done", f"{node_id} ended {status!r}: {read_node_error_text(node_locator(page, node_id))}"


def _run_all(page) -> None:
    """Run All, and every node of the small dataflow done."""
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node_type in ((LOAD, ""), (EDIT, EDIT_TYPE), (EDIT_2, EDIT_TYPE), (MAP, MAP_TYPE),
                               (MAP_2, MAP_TYPE), (COUNT, ""), (COUNT_2, "")):
        _done(page, node_id, node_type)
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)


def _value(page, node_id: str):
    """What *node_id*'s last run saved: a number."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    stored = load_artifact_as_dict(artifact)
    assert stored["dataType"] in ("int", "float"), stored
    return stored["data"]


def _edits_of(code: str) -> tuple[list, dict]:
    """The edits and the keywords of the one ``curio_edit_features(...)`` call
    *code* returns, as Python reads them."""
    statements = ast.parse(code).body
    assert len(statements) == 1 and isinstance(statements[0], ast.Return), f"not one return of a call:\n{code}"
    call = statements[0].value
    assert isinstance(call, ast.Call) and getattr(call.func, "id", None) == "curio_edit_features", code
    assert len(call.args) == 2, code
    return ast.literal_eval(call.args[1]), {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}


def _wait_for_edits(page, node_id: str, expected: list, what: str) -> tuple[str, dict]:
    """Wait until the node's code holds *expected*, its edits in order; returns
    the code and its keywords."""
    code, edits = "", None
    deadline = time.time() + 15
    while time.time() < deadline:
        code = read_node_code(page, node_id)
        try:
            edits, keywords = _edits_of(code)
        except (AssertionError, SyntaxError, ValueError):
            edits = None
        if edits == expected:
            return code, keywords
        page.wait_for_timeout(250)
    raise AssertionError(f"after {what}, the node's code holds the edits {edits}, not {expected}:\n{code}")


# What a node's interaction edges brought it last: each selection with the
# node it came from, as plain JSON.
_INTERACTIONS_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const got = node && node.data ? node.data.interactions : null;
    return Array.isArray(got) ? JSON.parse(JSON.stringify(got)) : null;
}"""


def _selection(page, receiver: str, sender: str):
    """``(rows, layer)``: the selection *receiver* last got from *sender* over an
    interaction edge, its rows and the layer it names, or None when none came."""
    for entry in page.evaluate(_INTERACTIONS_JS, receiver) or []:
        if entry.get("nodeId") == sender:
            detail = (entry.get("details") or {}).get("autk_selection") or {}
            return detail.get("data") or [], detail.get("layerRef")
    return None


def _ids(rows, key: str = KEY) -> list:
    return [row.get(key) for row in rows or [] if isinstance(row, dict)]


def _wait_for_selection(page, receiver: str, sender: str, ids, what: str, key: str = KEY) -> None:
    """Wait until what *receiver* got from *sender* names the ids *ids* (a set)."""
    got = None
    deadline = time.time() + INTERACTION_SHOWN_TIMEOUT_MS / 1000
    while time.time() < deadline:
        got = _selection(page, receiver, sender)
        if got is not None and set(_ids(got[0], key)) == set(ids):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"{what}: {receiver} got {got} from {sender}, not a selection of {key} {sorted(ids)}")


def _map(node_id: str) -> str:
    """An Autark node's map canvas."""
    return f"#autk-grammar-map-{node_id}"


def _overlay(page, map_id: str):
    """What a Map Editor node draws over the map *map_id* while an action is open."""
    return node_locator(page, map_id).get_by_test_id("map-edit-overlay")


def _map_pixels(page, map_id: str):
    """The map as it draws now, in its canvas's own pixels."""
    from PIL import Image

    url = page.evaluate(_AUTK_MAP_PIXELS_IN_FRAME_JS, map_id)
    assert url, f"the Autark node {map_id} has no map canvas"
    return Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def _changed(before, after) -> float:
    """The share of the map's pixels that differ by more than 10 in some channel."""
    return _compare_images(after, before, 10).ratio


def _drawn(image):
    """Where the map draws something: the pixels more than 8 off its background in some channel."""
    import numpy as np

    pixels = np.asarray(image).astype(int)
    return np.abs(pixels - np.array(MAP_BACKGROUND)).max(axis=2) > 8


def _drawn_share(image) -> float:
    return float(_drawn(image).mean())


def _layout_changed(before, after) -> float:
    """The share of the map's pixels drawn in one image and background in the
    other: what moves when the view does, not when a feature's colour does."""
    import numpy as np

    a, b = _drawn(before), _drawn(after)
    if a.shape != b.shape:
        return 1.0
    return float(np.mean(a != b))


def _assert_framed(page, map_id: str) -> None:
    """The map drew its layers, framed on them."""
    framing = autark_map_framing(page, map_id, timeout=60000)
    assert framing is None, framing


def _wait_for_map_drawn(page, map_id: str, what: str) -> None:
    """Wait until the map's canvas holds a whole drawing: mostly opaque, as
    ``assert_autark_map_drawn`` reads a drawn map, and the same in two reads in
    a row. A draw starts on a new, clear canvas and fills it once its layers
    are read."""
    import numpy as np
    from PIL import Image

    previous = None
    opaque = 0.0
    deadline = time.time() + INTERACTION_SHOWN_TIMEOUT_MS / 1000
    while True:
        url = page.evaluate(_AUTK_MAP_PIXELS_IN_FRAME_JS, map_id)
        if url:
            image = Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGBA")
            opaque = float((np.asarray(image)[:, :, 3] >= 250).mean())
            rgb = image.convert("RGB")
            if opaque > 0.5 and previous is not None and _changed(previous, rgb) <= 0.001:
                return
            previous = rgb if opaque > 0.5 else None
        if time.time() >= deadline:
            raise AssertionError(f"the map {map_id} did not finish drawing after {what}: its canvas is {opaque:.0%} opaque")
        page.wait_for_timeout(500)


def _wait_for_redraw(page, map_id: str, what: str) -> None:
    """Wait until the map drew again after *what*: each draw makes a canvas of
    its own (the old one kept with ``keep_drawing`` before the change)."""
    deadline = time.time() + INTERACTION_SHOWN_TIMEOUT_MS / 1000
    while time.time() < deadline and drawing_kept(page, _map(map_id)):
        page.wait_for_timeout(250)
    assert not drawing_kept(page, _map(map_id)), f"the map {map_id} did not draw again after {what}"
    node_locator(page, map_id).locator(_map(map_id)).wait_for(state="attached", timeout=30000)
    _wait_for_map_drawn(page, map_id, what)


def _assert_linked(page, edit_id: str, map_id: str, title: str = MAP_TITLE) -> None:
    """The node edits on the map it feeds and is linked to, and says so."""
    body = node_locator(page, edit_id).locator(f'[data-edit-body="{edit_id}"]')
    expect(body).to_have_attribute("data-edit-map", map_id, timeout=30000)
    expect(body.get_by_test_id("interaction-connected")).to_have_text(f"Linked to {title}")


def _open(page, edit_id: str, action: str, layer: str = LAYER) -> None:
    """Pick *layer* in the node's list of layers, then *action* for it."""
    box = node_locator(page, edit_id)
    _open_tab(page, edit_id, "output")
    box.get_by_test_id(f"interaction-layer-{layer}").click()
    box.get_by_test_id(f"interaction-action-{action}").click()
    expect(box.get_by_test_id("interaction-active-layer")).to_have_attribute("data-layer", layer)


def _back_to_layers(page, edit_id: str) -> None:
    """Back to the node's list of layers: from an action's form to the
    layer's actions, then to every layer."""
    box = node_locator(page, edit_id)
    back = box.get_by_test_id("interaction-back")
    if back.count():
        back.click()
    box.get_by_role("button", name="← All layers").click()
    box.get_by_test_id("interaction-layers").wait_for(state="visible", timeout=10000)


def _rule(page, edit_id: str, test: str, value: str, column: str = "height") -> None:
    """Write the rule's first condition: *column*, *test*, *value*."""
    row = node_locator(page, edit_id).get_by_test_id("interaction-rule-0")
    row.get_by_label("Property", exact=True).select_option(column)
    row.get_by_label("Test", exact=True).select_option(test)
    row.get_by_test_id("interaction-rule-value-0").fill(value)


#: What would be drawn over a map for a pick or a rule's matches: none, Autark
#: lights them itself.
OUTLINES = "svg path, svg circle"

# What an Autark node's map shows, as autk-map and autk-db hold it: for each
# table its document draws, whether its layer is the one that picks and the
# features that layer lights (window.__curio_mapState).
_MAP_STATE_JS = "(id) => (window.__curio_mapState ? window.__curio_mapState(id) : null)"


def _lit(page, map_id: str, table: str = LAYER, key: str = KEY) -> list | None:
    """The *key* of each row Autark lights on *table* of the map *map_id*,
    sorted: none when *table*'s layer is not the one that picks, where autk-map
    draws no highlight. None when the map reports no such table."""
    state = page.evaluate(_MAP_STATE_JS, map_id)
    if not state or table not in state:
        return None
    layer = state[table]
    return sorted(_ids(layer.get("lit"), key)) if layer.get("pick") else []


def _wait_for_lit(page, map_id: str, expected, what: str, table: str = LAYER, key: str = KEY) -> None:
    """Wait until the map lights exactly the rows *expected* names, a *key*
    per row, on *table*; with *expected* a set, every row holding one of those
    keys and no other, however many rows each has. autk-map holds what it
    lights before it draws it, so no frame is waited for."""
    def matches(got) -> bool:
        if got is None:
            return False
        if isinstance(expected, set):
            return set(got) == expected and (len(got) > 0) == (len(expected) > 0)
        return got == sorted(expected)

    got = None
    deadline = time.time() + 15
    while time.time() < deadline:
        got = _lit(page, map_id, table, key)
        if matches(got):
            return
        page.wait_for_timeout(250)
    shown = sorted(expected) if not isinstance(expected, set) else sorted(expected, key=str)
    # What every table's layer shows, so a failure says whether the layer picks
    # at all, and the selections the map was brought, which it lights.
    state = page.evaluate(_MAP_STATE_JS, map_id) or {}
    layers = {
        name: (layer.get("pick"), _ids(layer.get("lit"), key), layer.get("positions"), layer.get("drawn"), layer.get("rows"))
        for name, layer in state.items()
    }
    brought = [
        (entry.get("nodeId"), ((entry.get("details") or {}).get("autk_selection") or {}).get("layerRef"),
         ((entry.get("details") or {}).get("autk_selection") or {}).get("data"))
        for entry in page.evaluate(_INTERACTIONS_JS, map_id) or []
    ]
    raise AssertionError(
        f"{what}: the map {map_id} lights the {key} {got} on {table}, not {shown}; "
        f"each table as (picks, lit {key}, positions lit, features drawn, rows read back): {layers}; "
        f"selections brought as (from, layer, rows): {brought}"
    )


_SHOWN_JS = """([selector, x, y]) => document.elementFromPoint(x, y) === document.querySelector(selector)"""


def _click_a_building(page, edit_id: str, map_id: str, shown, *, spots=PICK_SPOTS, double: bool = False):
    """Click the map where it draws a building, until *shown*, a locator, is
    visible in the node; returns the page point clicked.

    The buildings fill the layer's extent, which the map frames, so a spot
    along the map's middle lands on one: the marked pixel nearest the spot,
    else the spot itself."""
    canvas = _map(map_id)
    tried = []
    for at in spots:
        dismiss_toasts(page)
        point = mark_point(page, canvas, at)
        if not point:
            box = page.locator(canvas).bounding_box()
            assert box, f"the map {map_id} has no layout box"
            point = {"x": box["x"] + at[0] * box["width"], "y": box["y"] + at[1] * box["height"]}
        x, y = assert_in_view(page, point["x"], point["y"], f"the building near {at} of the map {map_id}")
        if not page.evaluate(_SHOWN_JS, [canvas, x, y]):
            tried.append((at, "covered"))
            continue
        if double:
            page.mouse.dblclick(x, y)
        else:
            page.mouse.click(x, y)
        try:
            shown.wait_for(state="visible", timeout=10000)
            return x, y
        except PlaywrightTimeoutError:
            tried.append((at, (round(x), round(y))))
    raise AssertionError(f"no click on the map {map_id} picked a building in {edit_id}: {tried}")


def _picked_on_the_map(page, edit_id: str, map_id: str) -> int:
    """The building the map's last selection, which the interaction edge
    brought the node, names: one building, of every part it has."""
    got = _selection(page, edit_id, map_id)
    assert got is not None, f"no selection reached {edit_id} from {map_id}"
    rows, layer = got
    ids = set(_ids(rows))
    assert len(ids) == 1 and next(iter(ids)) in PARTS, f"a click on one building selected {rows}"
    assert layer in (None, LAYER), f"the map's selection names the layer {layer!r}, not {LAYER}"
    return next(iter(ids))


def _frame(page, step: str, gesture: str, phase: str, source: str, target: str, *, stem: str = STEM) -> None:
    """Both nodes of a gesture, as they show now, against their baselines."""
    for role, node_id in (("source", source), ("target", target)):
        save_interaction_frame(
            page, stem, node_id,
            test_name=f"{step}_{phase}_{node_id}",
            interaction={
                "workflow": stem, "step": step, "gesture": gesture, "phase": phase,
                "role": role, "node": node_id, "source": source, "target": target,
            },
        )


# Records each state the dataflow's save indicator takes from now on, so an
# Unsaved that the 30 second autosave clears soon after is still seen.
_WATCH_SAVE_STATE_JS = """() => {
    const el = document.querySelector('[data-curio-save-state]');
    if (!el) return null;
    if (window.__curioSaveStateObserver) window.__curioSaveStateObserver.disconnect();
    window.__curioSaveStates = [el.getAttribute('data-curio-save-state')];
    const observer = new MutationObserver(() => {
        window.__curioSaveStates.push(el.getAttribute('data-curio-save-state'));
    });
    observer.observe(el, { attributes: true, attributeFilter: ['data-curio-save-state'] });
    window.__curioSaveStateObserver = observer;
    return window.__curioSaveStates[0];
}"""


def _watch_save_state(page) -> str:
    """Start recording the save indicator's states; returns the one it shows."""
    state = page.evaluate(_WATCH_SAVE_STATE_JS)
    assert state, "the canvas header shows no save state"
    return state


def _wait_for_unsaved(page, what: str) -> None:
    states: list = []
    deadline = time.time() + 10
    while time.time() < deadline:
        states = page.evaluate("() => window.__curioSaveStates || []")
        if "unsaved" in states:
            return
        page.wait_for_timeout(200)
    raise AssertionError(f"after {what}, the dataflow never read Unsaved: its save states were {states}")


# A node's new outcome: "error", or "success" once its output is saved to
# another file than *before*, the one it was saved to before the click.
_NEW_OUTCOME_JS = """([id, before]) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const output = node && node.data && node.data.output;
    if (!output) return false;
    if (output.code === "error") return "error";
    if (output.code !== "success") return false;
    const match = String(output.content || "").match(/Saved to file: (\\S+)/);
    return match && match[1] !== before ? "success" : false;
}"""


def _wait_for_new_outcome(page, node_id: str, before: str, *, node_type: str, timeout_ms: int) -> str:
    """How *node_id*'s next run ended: ``"success"``, its output saved to a new
    file, or ``"error"``.

    A step of a run on the server can start and end between two renders (a
    quick node's takes milliseconds), so the node need never show itself
    running, and ``watch_node_run`` would wait for a run that came and
    went. The new file its output is saved to tells that it ran again. Polls on
    a timer, not on animation frames."""
    try:
        handle = page.wait_for_function(_NEW_OUTCOME_JS, arg=[node_id, before], timeout=timeout_ms, polling=500)
    except PlaywrightTimeoutError:
        box = node_locator(page, node_id)
        status = box.locator("[data-curio-node-status]").first.get_attribute("data-curio-node-status")
        raise AssertionError(
            f"{node_type} {node_id} did not run again within {timeout_ms} ms: its output is still saved to "
            f"{before}, status {status!r}: {read_node_error_text(box)}"
        ) from None
    return handle.json_value()


def _commit(page, edit_id: str, saved: list[str], drawn: list[str], *, below: int) -> None:
    """Commit edits, from the foot of the node's list, which says how many
    nodes below lack the edits: each of *saved* runs again, its output saved to
    a new file, each map of *drawn* ends done, and the foot says committed."""
    frame_nodes(page, [edit_id])
    box = node_locator(page, edit_id)
    foot = box.get_by_test_id("interaction-commit")
    expect(foot).to_have_attribute("data-commit-state", "stale", timeout=10000)
    lacking = (
        "The node below does not have these edits yet." if below == 1
        else f"The {below} nodes below do not have these edits yet."
    )
    expect(foot).to_contain_text(lacking)
    button = box.get_by_test_id("interaction-update")
    expect(button).to_have_text("Commit edits")
    saved_to = {node_id: page.evaluate(_OUTPUT_ARTIFACT_JS, node_id) for node_id in saved}
    assert all(saved_to.values()), f"a node shows no saved output before Commit edits: {saved_to}"
    button.click()
    for node_id in saved:
        outcome = _wait_for_new_outcome(page, node_id, saved_to[node_id], node_type=node_id, timeout_ms=RUN_MS)
        status = wait_for_node_settled(page, node_id, timeout_ms=60000)
        assert (outcome, status) == ("success", "done"), (
            f"{node_id} ran again and ended {outcome}, {status}: {read_node_error_text(node_locator(page, node_id))}"
        )
    for node_id in drawn:
        _done(page, node_id, MAP_TYPE)
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)
    expect(foot).to_have_attribute("data-commit-state", "done", timeout=60000)
    expect(foot).to_contain_text("Edits committed")


def _open_provenance(page, node_id: str):
    """The node's Provenance drawer, opened from the button in its header."""
    node_locator(page, node_id).locator('.nav-link[data-rr-ui-event-key="provenance"]').first.click()
    expect(page.get_by_role("dialog", name="Node provenance")).to_be_visible(timeout=20000)
    await_drawer_at_rest(page)
    return page.locator(PROVENANCE_PANEL)


def _close_provenance(page) -> None:
    """Close the node's Provenance drawer. Closing it hands focus back to the
    button that opened it, whose tooltip would sit in a later capture, so the
    focus and the pointer leave it."""
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    park_pointer(page)
    expect(page.locator('[role="tooltip"]')).to_have_count(0, timeout=5000)


def _entries(panel) -> list[tuple[str, str]]:
    """``(id, text)`` of each entry the drawer lists, in its order."""
    items = panel.locator("[data-provenance-item]")
    ids = items.evaluate_all("(els) => els.map((el) => el.dataset.provenanceItem)")
    return [(entry, items.nth(i).inner_text()) for i, entry in enumerate(ids)]


def test_a_building_picked_on_the_linked_map_is_removed_at_once_and_committed_and_kept(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Each Map Editor node names the map it is linked to and lists its layer.
    In One removed's Remove, a building clicked on the linked map is picked in
    the node, which sends the pick back for the map to light up. Remove writes
    the edit into the node's code by building_id, lists it, and the map draws
    without the building at once; the dataflow reads Unsaved, and the count
    below keeps what it had. Commit edits runs the node, the map and the
    count, which drops by every part of the building, the other scenario's
    staying. Saved and opened again, the code, the list and the Remove's entry
    in the node's Provenance drawer come back."""
    test_name ="test_a_building_picked_on_the_linked_map_is_removed_at_once_and_committed_and_kept"
    session = _enter(page, app_frontend, current_server, _spec(), "map_edits_remove_e2e")
    token, project_id = session["token"], session["project"]["id"]
    _run_all(page)
    assert (_value(page, COUNT), _value(page, COUNT_2)) == (3, 3), "with no edits every part is counted"

    # Each Map Editor node edits on the map it feeds and is linked to, and
    # lists the layer it is fed, which has an id column.
    for edit_id, map_id in ((EDIT, MAP), (EDIT_2, MAP_2)):
        _open_tab(page, edit_id, "output")
        _assert_linked(page, edit_id, map_id)
        card = node_locator(page, edit_id).get_by_test_id(f"interaction-layer-{LAYER}")
        expect(card).to_contain_text("Buildings")
        expect(card).to_contain_text("3 areas")
        expect(card).to_contain_text("properties: height, name")
        expect(card).not_to_contain_text("no id column")
        _assert_framed(page, map_id)
    save_node_closeup(page, STEM, MAP, test_name=f"{test_name}_closeup_{MAP}", sweep_toasts=True)

    # Remove, with nothing picked yet: there is nothing to remove.
    edit = node_locator(page, EDIT_2)
    frame_nodes(page, [EDIT_2, MAP_2])
    _open(page, EDIT_2, "remove")
    remove = edit.get_by_test_id("interaction-remove-picked")
    expect(remove).to_be_disabled()
    expect(edit).to_contain_text("Click areas on the map to pick them.")
    before = _map_pixels(page, MAP_2)

    # A building clicked on the map: the map's selection, which the
    # interaction edge carries to the node, picks it there, and the node's
    # pick goes back to the map, which lights every part of it with its own
    # highlight. Nothing is drawn over the map.
    with canvas_painted_at_shown_zoom(page):
        frame_nodes(page, [EDIT_2, MAP_2])
        target_before = wait_for_node_still(page, EDIT_2)
        _frame(page, "map-pick", "pick", "before", MAP_2, EDIT_2)
        _click_a_building(page, EDIT_2, MAP_2, edit.get_by_text("1 area picked."))
        picked = _picked_on_the_map(page, EDIT_2, MAP_2)
        expect(remove).to_have_text("Remove 1 area")
        expect(remove).to_be_enabled()
        _wait_for_selection(page, MAP_2, EDIT_2, {picked}, "the node's pick")
        _wait_for_lit(page, MAP_2, [picked] * PARTS[picked], f"a pick of building {picked}")
        expect(_overlay(page, MAP_2).locator(OUTLINES)).to_have_count(0)
        _, reached = wait_for_node_capture(
            page, EDIT_2, lambda capture: changed_pixels(target_before, capture) > INTERACTION_MIN_CHANGED_PIXELS,
            timeout_ms=INTERACTION_SHOWN_TIMEOUT_MS,
        )
        assert reached, "the pick on the map left the Map Editor node as it was"
        wait_for_node_still(page, EDIT_2)
        _frame(page, "map-pick", "pick", "after", MAP_2, EDIT_2)

    # Remove takes out every part of it, in the node's code and on the map at
    # once. The dataflow reads Unsaved, and the nodes below keep what they had.
    save_dataflow_and_settle_header(page)
    assert _watch_save_state(page) == "saved"
    counted = page.evaluate(_OUTPUT_ARTIFACT_JS, COUNT_2)
    keep_drawing(page, _map(MAP_2))
    remove.click()
    code, keywords = _wait_for_edits(page, EDIT_2, [{"op": "remove", "ids": [picked]}], f"a Remove of building {picked}")
    assert (keywords.get("key"), keywords.get("layer")) == (KEY, LAYER), keywords
    expect(edit.locator('[data-edit-list="1"] [data-edit-op="remove"]')).to_contain_text(f"Remove building_id {picked}")
    expect(edit.get_by_test_id("interaction-counts")).to_have_text(f"{PARTS[picked]} removed, 0 changed")
    expect(remove).to_be_disabled()
    _wait_for_unsaved(page, f"a Remove of building {picked}")
    _wait_for_redraw(page, MAP_2, f"a Remove of building {picked}")
    gone = _changed(before, _map_pixels(page, MAP_2))
    assert gone >= REMOVED_MIN_SHARE, f"removing building {picked} changed {gone:.2%} of the map: it still draws it"
    assert page.evaluate(_OUTPUT_ARTIFACT_JS, COUNT_2) == counted and _value(page, COUNT_2) == 3, (
        "a node below the map ran before Commit edits"
    )
    save_node_closeup(page, STEM, MAP_2, test_name=f"{test_name}_closeup_{MAP_2}", sweep_toasts=True)

    # Commit edits runs the node, the map and the count below it: the
    # building is gone with every part. The other scenario's count does not move.
    _commit(page, EDIT_2, [EDIT_2, COUNT_2], [MAP_2], below=2)
    expected = 3 - PARTS[picked]
    assert _value(page, COUNT_2) == expected < 3, (
        f"removing building {picked} ({PARTS[picked]} parts) left {_value(page, COUNT_2)} of 3 parts"
    )
    assert _value(page, COUNT) == 3, "the other scenario's count changed"
    save_node_closeup(page, STEM, EDIT_2, test_name=f"{test_name}_closeup_{EDIT_2}", sweep_toasts=True)

    # Saved and opened again: the code, the list and the Remove's entry.
    project = save_dataflow(page)
    saved = {node["id"]: node for node in _saved_spec(current_server, token, project_id)["dataflow"]["nodes"]}
    assert saved[EDIT_2]["content"] == code, saved[EDIT_2]["content"]
    assert saved[EDIT]["content"] == NO_EDITS, "the other scenario's node changed its code"
    assert "editFeatures" not in saved[EDIT_2]["metadata"], saved[EDIT_2]["metadata"]
    page.wait_for_url(f"**/dataflow/{project['id']}", timeout=30000)
    page.reload()
    for node_id in (LOAD, EDIT, EDIT_2, MAP, MAP_2, COUNT, COUNT_2):
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)
    require_owner_view(page)
    frame_nodes(page, [EDIT_2])
    _open_tab(page, EDIT_2, "output")
    assert read_node_code(page, EDIT_2) == code
    expect(edit.locator('[data-edit-list="1"] [data-edit-op="remove"]')).to_contain_text(
        f"Remove building_id {picked}", timeout=15000,
    )
    panel = _open_provenance(page, EDIT_2)
    texts = [text for _entry, text in _entries(panel)]
    assert any(f"Remove building_id {picked}" in text for text in texts), (
        f"the node's Provenance drawer lost the Remove: it lists {texts}"
    )
    _close_provenance(page)


def test_a_rule_lights_its_matches_on_the_map_removes_them_and_a_switched_off_entry_is_skipped(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """A rule, ``height < 40``, matches building 1's two parts: the map lights
    them up as it is written, and Remove takes them off the map at
    once. Switched off, the removal stays in the list and the map draws them
    again. An expression by a rule halves the tall part, ``height > 40``.
    Commit edits runs the node and every node below it: the total drops by
    25 m, the switched-off removal skipped, and the code keeps both entries,
    the first as off."""
    test_name = "test_a_rule_lights_its_matches_on_the_map_removes_them_and_a_switched_off_entry_is_skipped"
    session = _enter(page, app_frontend, current_server, _spec(TOTAL_CODE, "Total height"), "map_edits_rule_e2e")
    token, project_id = session["token"], session["project"]["id"]
    _run_all(page)
    assert (_value(page, COUNT), _value(page, COUNT_2)) == (TOTAL, TOTAL), "with no edits every height is summed"

    edit = node_locator(page, EDIT_2)
    frame_nodes(page, [EDIT_2, MAP_2])
    _open_tab(page, EDIT_2, "output")
    _assert_linked(page, EDIT_2, MAP_2)
    _assert_framed(page, MAP_2)
    before_pixels = _map_pixels(page, MAP_2)
    _open(page, EDIT_2, "remove")
    by_rule = edit.get_by_test_id("interaction-remove-by-rule")
    by_rule.click()
    expect(by_rule).to_have_attribute("aria-checked", "true")
    matching = edit.get_by_test_id("interaction-matching")

    # The rule, written: what it matches lights up on the map, by the
    # selection the node sends over the interaction edge, every part of
    # building 1 and nothing of building 2. Nothing is drawn over the map.
    with canvas_painted_at_shown_zoom(page):
        frame_nodes(page, [EDIT_2, MAP_2])
        dismiss_toasts(page)
        keep_drawing(page, _map(MAP_2))
        before = wait_for_node_still(page, MAP_2)
        _frame(page, "rule-match", "rule", "before", EDIT_2, MAP_2)
        _rule(page, EDIT_2, "<", "40")
        expect(matching).to_have_text("Matches 2 areas of 3")
        _wait_for_selection(page, MAP_2, EDIT_2, {1}, "the rule height < 40")
        _wait_for_lit(page, MAP_2, [1] * PARTS[1], "the rule height < 40")
        expect(_overlay(page, MAP_2).locator(OUTLINES)).to_have_count(0)
        after, reached = wait_for_node_capture(
            page, MAP_2, lambda capture: changed_pixels(before, capture) > INTERACTION_MIN_CHANGED_PIXELS,
            timeout_ms=INTERACTION_SHOWN_TIMEOUT_MS,
        )
        assert reached, f"the rule's matches did not light up on the map ({changed_pixels(before, after)} pixels changed)"
        wait_for_node_still(page, MAP_2)
        assert drawing_kept(page, _map(MAP_2)), "the rule redrew the map instead of lighting its matches up"
        _frame(page, "rule-match", "rule", "after", EDIT_2, MAP_2)

    # Remove: the rule is an entry, and the map draws without the matches at once.
    remove = edit.get_by_test_id("interaction-remove-picked")
    expect(remove).to_have_text("Remove 2 areas")
    keep_drawing(page, _map(MAP_2))
    remove.click()
    removal = {"op": "remove", "where": "height < 40"}
    _wait_for_edits(page, EDIT_2, [removal], "the Remove by a rule")
    expect(edit.locator('[data-edit-list="1"] [data-edit-op="remove"]')).to_contain_text("Remove where height < 40")
    expect(edit.get_by_test_id("interaction-counts")).to_have_text(f"{PARTS[1]} removed, 0 changed")
    _wait_for_redraw(page, MAP_2, "the Remove by a rule")
    removed_pixels = _map_pixels(page, MAP_2)
    gone = _changed(before_pixels, removed_pixels)
    assert gone >= REMOVED_MIN_SHARE, f"removing building 1's parts by a rule changed {gone:.2%} of the map"

    # Switched off, it stays in the list, and the map draws them again.
    keep_drawing(page, _map(MAP_2))
    edit.get_by_label("Use edit 1", exact=True).uncheck()
    expect(edit.locator('[data-edit-op="remove"]')).to_have_attribute("data-edit-enabled", "false", timeout=10000)
    removal_off = {**removal, "enabled": False}
    _wait_for_edits(page, EDIT_2, [removal_off], "the removal switched off")
    _wait_for_redraw(page, MAP_2, "the removal switched off")
    back = _changed(removed_pixels, _map_pixels(page, MAP_2))
    assert back >= REMOVED_MIN_SHARE, f"switching the removal off changed {back:.2%} of the map: it does not draw them again"

    # An expression by a rule: the tall part's height halved.
    edit.get_by_test_id("interaction-back").click()
    edit.get_by_test_id("interaction-action-edit").click()
    edit.get_by_test_id("interaction-edit-by-rule").click()
    _rule(page, EDIT_2, ">", "40")
    expect(matching).to_have_text("Matches 1 area of 3")
    edit.get_by_test_id("interaction-rule-column").select_option("height")
    edit.get_by_test_id("interaction-rule-op").select_option("expr")
    edit.get_by_test_id("interaction-rule-set-value").fill("height * 0.5")
    apply = edit.get_by_test_id("interaction-rule-apply")
    expect(apply).to_have_text("Apply to 1 area")
    apply.click()
    halve = {"op": "expr", "where": "height > 40", "column": "height", "value": "height * 0.5"}
    code, _keywords = _wait_for_edits(page, EDIT_2, [removal_off, halve], "the expression by a rule")
    expect(edit.locator('[data-edit-op="expr"]')).to_contain_text("Compute height as height * 0.5 where height > 40")

    # Commit edits: the total drops by 25 m. Had the switched-off removal run,
    # building 2 alone would be left, 25 m in all.
    _commit(page, EDIT_2, [EDIT_2, COUNT_2], [MAP_2], below=2)
    assert _value(page, COUNT_2) == TOTAL - 25.0, (
        f"halving building 2 (50 m) left a total of {_value(page, COUNT_2)}, not {TOTAL - 25.0}"
    )
    assert _value(page, COUNT) == TOTAL, "the other scenario's total changed"
    save_node_closeup(page, STEM, EDIT_2, test_name=f"{test_name}_closeup_{EDIT_2}", sweep_toasts=True)
    save_node_closeup(page, STEM, MAP_2, test_name=f"{test_name}_closeup_{MAP_2}", sweep_toasts=True)

    # Saved with the dataflow: the code holds both entries, the first as off.
    save_dataflow(page)
    saved = {node["id"]: node for node in _saved_spec(current_server, token, project_id)["dataflow"]["nodes"]}
    assert saved[EDIT_2]["content"] == code, saved[EDIT_2]["content"]
    assert _edits_of(saved[EDIT_2]["content"])[0] == [removal_off, halve]
    assert saved[EDIT]["content"] == NO_EDITS


def test_a_building_of_two_parts_is_lit_by_the_map_a_plain_click_replaces_it_and_a_play_drops_it(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """In Remove, building 1, of two parts, clicked on the map: the map lights
    both parts with its own highlight, and nothing is drawn over it. A plain
    click on building 2 replaces the pick, and the map lights building 2
    alone. The map played: it draws again with nothing picked and nothing lit.
    What is wrong at each step is kept, and the test fails at the end with all
    of it."""
    _enter(page, app_frontend, current_server, _spec(), "map_edits_replace_e2e")
    _run_all(page)
    edit = node_locator(page, EDIT_2)
    frame_nodes(page, [EDIT_2, MAP_2])
    _open_tab(page, EDIT_2, "output")
    _assert_linked(page, EDIT_2, MAP_2)
    _assert_framed(page, MAP_2)
    _open(page, EDIT_2, "remove")
    remove = edit.get_by_test_id("interaction-remove-picked")
    picked = edit.get_by_text("1 area picked.")
    outlines = _overlay(page, MAP_2).locator(OUTLINES)
    wrong: list[str] = []

    def check(step: str, assertion) -> None:
        try:
            assertion()
        except AssertionError as error:
            wrong.append(f"{step}: {error}")

    # Building 1, of two parts, clicked.
    _click_a_building(page, EDIT_2, MAP_2, picked, spots=LEFT_SPOTS)
    first = _picked_on_the_map(page, EDIT_2, MAP_2)
    assert first == 1, f"a click on the left half of the map picked building {first}"
    check("building 1 clicked", lambda: _wait_for_lit(page, MAP_2, [1] * PARTS[1], "building 1 clicked"))
    check("building 1 clicked", lambda: expect(outlines).to_have_count(0))

    # A plain click on building 2 replaces the pick.
    _click_a_building(page, EDIT_2, MAP_2, picked, spots=RIGHT_SPOTS)
    check("building 2 clicked", lambda: _wait_for_selection(page, EDIT_2, MAP_2, {2}, "building 2 clicked"))
    check("building 2 clicked", lambda: expect(remove).to_have_text("Remove 1 area"))
    check("building 2 clicked", lambda: _wait_for_lit(page, MAP_2, [2] * PARTS[2], "building 2 clicked"))
    check("building 2 clicked", lambda: expect(outlines).to_have_count(0))

    # The map played: drawn again, with nothing picked and nothing lit.
    frame_nodes(page, [MAP_2])
    keep_drawing(page, _map(MAP_2))
    watch_node_run(page, MAP_2)
    play_node(page, MAP_2)
    status = wait_for_node_run_to_end(page, MAP_2, node_type=MAP_TYPE)
    assert status == "done", f"the map's play ended {status}: {read_node_error_text(node_locator(page, MAP_2))}"
    _wait_for_redraw(page, MAP_2, "a play of the map")
    check("the map played", lambda: _wait_for_lit(page, MAP_2, [], "the map played"))
    check("the map played", lambda: expect(remove).to_be_disabled())
    check("the map played", lambda: expect(outlines).to_have_count(0))
    assert not wrong, "\n".join(wrong)


def test_a_height_set_on_a_zoomed_map_keeps_the_view_and_commit_edits_hands_it_on(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The map frames its layers when it first draws. Zoomed in with the
    wheel, building 1, of two parts 20 and 35 m tall, picked on it: the
    node's form is for both parts, so its height is empty with both heights
    listed beside it, and the name they share shows. A height set there,
    Apply changes writes it into the node's code for every part of the
    building, and the map draws again in the view it was zoomed to: not framed
    on its layers again, and nearer the zoomed view than the framed one.
    Commit edits runs the node, the map and the total below the map, which
    holds the new height for both parts: the map hands it on."""
    test_name = "test_a_height_set_on_a_zoomed_map_keeps_the_view_and_commit_edits_hands_it_on"
    _enter(page, app_frontend, current_server, _spec(TOTAL_CODE, "Total height"), "map_edits_zoom_e2e")
    _run_all(page)
    assert (_value(page, COUNT), _value(page, COUNT_2)) == (TOTAL, TOTAL), "with no edits every height is summed"

    frame_nodes(page, [MAP_2])
    _assert_framed(page, MAP_2)
    framed = _map_pixels(page, MAP_2)

    # Zoomed in with the wheel over the map's middle, until the drawing runs
    # past the canvas's edges.
    box = page.locator(_map(MAP_2)).bounding_box()
    assert box, "the map has no layout box"
    x, y = assert_in_view(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, "the middle of the map")
    page.mouse.move(x, y)
    delta = -ZOOM_DELTA
    share = _drawn_share(framed)
    zoomed = None
    for step in range(ZOOM_STEPS):
        page.mouse.wheel(0, delta)
        page.wait_for_timeout(500)
        if step == 0 and _drawn_share(_map_pixels(page, MAP_2)) < share:
            # This wheel zooms out the other way round.
            delta = -delta
            continue
        if autark_map_framing(page, MAP_2, timeout=0) is not None:
            zoomed = _map_pixels(page, MAP_2)
            break
    assert zoomed is not None, f"{ZOOM_STEPS} wheel steps over the map did not zoom it in past its layers"
    zoom = _layout_changed(framed, zoomed)

    # Building 1, of two parts, picked on the map in the node's Edit: its
    # form is for both parts. They share a name, which shows once the form
    # holds the building's values; they differ in height, so that field is
    # empty and a note lists both heights.
    edit = node_locator(page, EDIT_2)
    frame_nodes(page, [EDIT_2, MAP_2])
    _open(page, EDIT_2, "edit")
    _click_a_building(page, EDIT_2, MAP_2, edit.get_by_test_id("interaction-selection"), spots=LEFT_SPOTS)
    picked = _picked_on_the_map(page, EDIT_2, MAP_2)
    assert picked == 1, f"a click on the left half of the zoomed map picked building {picked}"
    expect(edit.get_by_test_id("interaction-field-name")).to_have_value(NAMES[1])
    field = edit.get_by_test_id("interaction-field-height")
    shown = field.input_value()
    assert shown == "", (
        f"the form of building 1 shows the height {shown}, its first part's, as the building's: "
        f"its {PARTS[1]} parts are {' and '.join(_literal(height) for height in HEIGHTS[1])} m tall"
    )
    expect(edit.get_by_test_id("interaction-mixed-height")).to_have_text("2 values: 20, 35")

    # A height typed there goes to both parts.
    keep_drawing(page, _map(MAP_2))
    field.fill(str(NEW_HEIGHT))
    submit = edit.get_by_test_id("interaction-form-submit")
    expect(submit).to_have_text("Apply changes")
    expect(submit).to_be_enabled()
    submit.click()
    _wait_for_edits(
        page, EDIT_2, [{"op": "set", "ids": [picked], "column": "height", "value": NEW_HEIGHT}],
        f"an Apply of height {NEW_HEIGHT} on building {picked}",
    )
    expect(edit.locator('[data-edit-op="set"]')).to_contain_text(f"Set height to {NEW_HEIGHT} on building_id {picked}")
    _wait_for_redraw(page, MAP_2, "the Apply")

    # The map keeps the view it was zoomed to. Back on the list of layers,
    # nothing is lit up on it, so only the building's colour has changed.
    framing = autark_map_framing(page, MAP_2, timeout=5000)
    assert framing is not None, "the map framed its layers again after the Apply, though it was zoomed in"
    _back_to_layers(page, EDIT_2)
    _wait_for_selection(page, MAP_2, EDIT_2, set(), "going back to the list of layers")
    wait_for_node_still(page, MAP_2)
    after = _map_pixels(page, MAP_2)
    assert _layout_changed(zoomed, after) < _layout_changed(framed, after), (
        f"after the Apply the map's drawing is {_layout_changed(framed, after):.2%} off its framed view and "
        f"{_layout_changed(zoomed, after):.2%} off the view it was zoomed to ({zoom:.2%} apart): "
        "a draw after an edit keeps the view"
    )
    card = edit.get_by_test_id(f"interaction-layer-{LAYER}")
    expect(card).to_contain_text("3 areas")

    # Commit edits: the map hands the new height on to the total below it,
    # for every part of the building.
    _commit(page, EDIT_2, [EDIT_2, COUNT_2], [MAP_2], below=2)
    expected = TOTAL - sum(HEIGHTS[picked]) + PARTS[picked] * NEW_HEIGHT
    assert _value(page, COUNT_2) == expected, (
        f"after the Apply of height {NEW_HEIGHT} on building {picked} ({PARTS[picked]} parts), "
        f"the total height below the map is {_value(page, COUNT_2)}, not {expected}"
    )
    assert _value(page, COUNT) == TOTAL, "the other scenario's total changed"
    assert autark_map_framing(page, MAP_2, timeout=5000) is not None, "Commit edits framed the zoomed map again"
    save_node_closeup(page, STEM, EDIT_2, test_name=f"{test_name}_closeup_{EDIT_2}", sweep_toasts=True)


def test_each_change_is_an_entry_in_the_node_provenance_and_putting_one_back_restores_its_edits(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Once the dataflow ran, two Apply changes and a Remove on one building,
    with no run between them, each add an entry to the node's Provenance
    drawer at once, named by what it changed, each after the one before. The
    first one's code put back opens the Code tab and adds no entry; on the
    Output tab, only the first change is left: the map draws the building
    again, the layer counts every part, and the list holds the one entry."""
    test_name = "test_each_change_is_an_entry_in_the_node_provenance_and_putting_one_back_restores_its_edits"
    _enter(page, app_frontend, current_server, _spec(), "map_edits_provenance_e2e")
    _run_all(page)
    frame_nodes(page, [EDIT_2, MAP_2])
    panel = _open_provenance(page, EDIT_2)
    ran = _entries(panel)
    assert ran, "the node's run is not in its Provenance drawer"
    _close_provenance(page)

    edit = node_locator(page, EDIT_2)
    frame_nodes(page, [EDIT_2, MAP_2])
    _open(page, EDIT_2, "edit")
    spot = _click_a_building(page, EDIT_2, MAP_2, edit.get_by_test_id("interaction-selection"))
    picked = _picked_on_the_map(page, EDIT_2, MAP_2)
    other = NAMES[2 if picked == 1 else 1]
    labels = [
        f"Set height to {NEW_HEIGHT} on building_id {picked}",
        f"Set name to {other} on building_id {picked}",
        f"Remove building_id {picked}",
    ]
    set_height = {"op": "set", "ids": [picked], "column": "height", "value": NEW_HEIGHT}
    set_name = {"op": "set", "ids": [picked], "column": "name", "value": other}
    submit = edit.get_by_test_id("interaction-form-submit")
    edit.get_by_test_id("interaction-field-height").fill(str(NEW_HEIGHT))
    submit.click()
    first, _keywords = _wait_for_edits(page, EDIT_2, [set_height], "the first Apply")
    expect(edit.get_by_test_id("interaction-field-height")).to_have_value(str(NEW_HEIGHT))
    edit.get_by_test_id("interaction-field-name").select_option(other)
    submit.click()
    _wait_for_edits(page, EDIT_2, [set_height, set_name], "the second Apply")

    # The Remove: the same building, clicked where it was picked.
    edit.get_by_test_id("interaction-back").click()
    edit.get_by_test_id("interaction-action-remove").click()
    remove = edit.get_by_test_id("interaction-remove-picked")
    expect(remove).to_be_disabled()
    page.mouse.click(*spot)
    expect(remove).to_have_text("Remove 1 area", timeout=10000)
    assert _picked_on_the_map(page, EDIT_2, MAP_2) == picked
    keep_drawing(page, _map(MAP_2))
    remove.click()
    _wait_for_edits(page, EDIT_2, [set_height, set_name, {"op": "remove", "ids": [picked]}], "the Remove")
    _wait_for_redraw(page, MAP_2, "the Remove")
    without = _map_pixels(page, MAP_2)
    edit.get_by_test_id("interaction-back").click()
    actions = edit.get_by_test_id("interaction-active-layer")
    expect(actions).to_contain_text(f"areas · {3 - PARTS[picked]}")

    # Three entries more, before any run, each named by what it changed, one
    # after the other on one line, the Remove the newest.
    panel = _open_provenance(page, EDIT_2)
    entries = _entries(panel)
    assert len(entries) == len(ran) + 3, f"the drawer lists {entries}: not the node's run and the three changes"
    made = entries[-3:]
    for (_entry, text), label in zip(made, labels):
        assert label in text, f"an entry reads {text!r}, not {label!r}: {entries}"
    lines = {entry: panel.locator(f'[data-provenance-item="{entry}"]').evaluate(
        "(el) => el.closest('ol').dataset.provenanceLine") for entry, _text in made}
    assert len(set(lines.values())) == 1, f"the three changes are not on one line: {lines}"
    expect(panel.locator(f'[data-provenance-item="{made[2][0]}"]')).to_have_attribute("data-provenance-current", "true")

    # The first change's code put back: the Code tab opens, and nothing is added.
    item = panel.locator(f'[data-provenance-item="{made[0][0]}"]')
    head = item.locator("button").first
    if head.get_attribute("aria-expanded") != "true":
        head.click()
    keep_drawing(page, _map(MAP_2))
    item.get_by_role("button", name="Put this code back in the node", exact=True).click()
    expect(item).to_have_attribute("data-provenance-current", "true")
    # The put back writes the node's code, which records no change of its own.
    page.wait_for_timeout(1000)
    assert len(_entries(panel)) == len(entries), f"putting an entry's code back added an entry: {_entries(panel)}"
    _close_provenance(page)
    expect(edit.locator('.nav-link[data-rr-ui-event-key="code"]').first).to_have_class(re.compile(r"\bactive\b"))
    assert _wait_for_edits(page, EDIT_2, [set_height], "the first entry's code was put back")[0] == first

    # On the Output tab: only the first change, on the map, in the panel and in the list.
    _open_tab(page, EDIT_2, "output")
    _wait_for_redraw(page, MAP_2, "the first entry's code was put back")
    drawn_again = _changed(without, _map_pixels(page, MAP_2))
    assert drawn_again >= REMOVED_MIN_SHARE, (
        f"putting the first entry's code back changed {drawn_again:.2%} of the map: building {picked} is not drawn again"
    )
    expect(actions).to_contain_text("areas · 3")
    expect(edit.locator("[data-edit-list]")).to_have_attribute("data-edit-list", "1")
    expect(edit.locator('[data-edit-op="set"]')).to_contain_text(labels[0])
    assert edit.locator('[data-edit-op="remove"]').count() == 0, "the Remove is still listed"
    save_node_closeup(page, STEM, EDIT_2, test_name=f"{test_name}_closeup_{EDIT_2}", sweep_toasts=True)
    save_node_closeup(page, STEM, MAP_2, test_name=f"{test_name}_closeup_{MAP_2}", sweep_toasts=True)


def test_a_map_fed_but_not_linked_shows_the_edits_and_a_click_there_selects_nothing(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """One removed's Map Editor node feeds its map, and no interaction edge
    links the two: the node says it is not linked to a map, offers no layer to
    work on, and keeps its list. Edits written into its code show on the map at
    once. A double-click on that map selects nothing in the node, while the
    same double-click on Every building's map, which its node is linked to,
    reaches that node."""
    test_name = "test_a_map_fed_but_not_linked_shows_the_edits_and_a_click_there_selects_nothing"
    _enter(page, app_frontend, current_server, _spec(linked=False), "map_edits_unlinked_e2e")
    _run_all(page)

    edit = node_locator(page, EDIT_2)
    frame_nodes(page, [EDIT_2, MAP_2])
    _open_tab(page, EDIT_2, "output")
    unlinked = edit.locator('[data-curio-node-empty="unlinked"]')
    expect(unlinked).to_be_visible(timeout=30000)
    expect(unlinked).to_contain_text("Not linked to a map")
    assert edit.get_by_test_id("interaction-workbench").count() == 0, "an unlinked node offers its layers"
    expect(edit.locator("[data-edit-list]")).to_have_attribute("data-edit-list", "0")
    _assert_linked(page, EDIT, MAP)
    _assert_framed(page, MAP_2)
    before = _map_pixels(page, MAP_2)

    # Edits written into its code show on the map it feeds, at once.
    keep_drawing(page, _map(MAP_2))
    set_node_code(page, EDIT_2, REMOVE_TWO)
    _open_tab(page, EDIT_2, "output")
    expect(edit.locator('[data-edit-list="1"] [data-edit-op="remove"]')).to_contain_text("Remove building_id 2")
    _wait_for_redraw(page, MAP_2, "the code's removal of building 2")
    gone = _changed(before, _map_pixels(page, MAP_2))
    assert gone >= REMOVED_MIN_SHARE, f"removing building 2 changed {gone:.2%} of the map it feeds: it still draws it"
    assert _overlay(page, MAP_2).count() == 0, "an unlinked node's tools are on the map"
    save_node_closeup(page, STEM, MAP_2, test_name=f"{test_name}_closeup_{MAP_2}", sweep_toasts=True)
    save_node_closeup(page, STEM, EDIT_2, test_name=f"{test_name}_closeup_{EDIT_2}", sweep_toasts=True)

    # A double-click on the map it is not linked to selects nothing in it.
    with canvas_painted_at_shown_zoom(page):
        frame_nodes(page, [EDIT_2, MAP_2])
        dismiss_toasts(page)
        target_before = wait_for_node_still(page, EDIT_2)
        _frame(page, "unlinked-pick", "pick", "before", MAP_2, EDIT_2)
        point = mark_point(page, _map(MAP_2), (0.5, 0.5))
        assert point, "the unlinked map shows no building to double-click"
        page.mouse.dblclick(*assert_in_view(page, point["x"], point["y"], "a building of the unlinked map"))
        page.wait_for_timeout(2000)
        assert _selection(page, EDIT_2, MAP_2) is None, (
            f"a pick on a map it is not linked to reached the node: {page.evaluate(_INTERACTIONS_JS, EDIT_2)}"
        )
        target_after = wait_for_node_still(page, EDIT_2)
        assert changed_pixels(target_before, target_after) <= INTERACTION_MIN_CHANGED_PIXELS, (
            "a pick on a map it is not linked to changed the node"
        )
        _frame(page, "unlinked-pick", "pick", "after", MAP_2, EDIT_2)

    # The same double-click on a map its node is linked to reaches that node.
    frame_nodes(page, [EDIT, MAP])
    dismiss_toasts(page)
    point = mark_point(page, _map(MAP), (0.5, 0.5))
    assert point, "the linked map shows no building to double-click"
    page.mouse.dblclick(*assert_in_view(page, point["x"], point["y"], "a building of the linked map"))
    got = None
    deadline = time.time() + 15
    while time.time() < deadline and not got:
        got = _selection(page, EDIT, MAP)
        page.wait_for_timeout(250)
    assert got and _ids(got[0]) and set(_ids(got[0])) <= set(PARTS), (
        f"a pick on the linked map did not reach its node: {got}"
    )


def test_the_chicago_loop_layers_take_a_point_a_reshaped_road_and_a_property_on_the_map(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The shipped Chicago Loop layers: every layer through one Map Editor node
    to one Autark map, the two linked. On the map, as a person does:

    1. a point added to the trees, its properties filled in the node;
    2. a road picked, with only the roads shown, and one of its corners
       dragged, with Move points; Pan takes the map back;
    3. a property added to every park.

    Each is an entry of the list and of the code, the trees' by the layer the
    node edits first and the others naming their layer and its id column,
    ``osm_id``. Commit edits runs the node and the map, and the node's output
    holds the new tree where it was placed, the road in its new shape and the
    parks with the property."""
    test_name = "test_the_chicago_loop_layers_take_a_point_a_reshaped_road_and_a_property_on_the_map"
    path = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-loop-layers.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    (edit_id,) = [n for n, node in nodes.items() if node["type"] == EDIT_TYPE]
    (map_id,) = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and '"map"' in node["content"]]
    title = nodes[map_id]["title"]
    _enter(page, app_frontend, current_server, spec, "map_edits_chicago_e2e", name=spec["dataflow"]["name"])
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node in nodes.items():
        _done(page, node_id, node["type"])
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)

    edit = node_locator(page, edit_id)
    frame_nodes(page, [edit_id, map_id])
    _open_tab(page, edit_id, "output")
    _assert_linked(page, edit_id, map_id, title)
    layers = ["input_0", "table_osm_parks", "table_osm_water", "table_osm_roads", "table_osm_buildings",
              "input_2", "input_3", "input_4"]
    for layer in layers:
        expect(edit.get_by_test_id(f"interaction-layer-{layer}")).to_be_attached(timeout=30000)
    for layer in ("table_osm_parks", "table_osm_roads", "input_3"):
        expect(edit.get_by_test_id(f"interaction-layer-{layer}")).not_to_contain_text("no id column")

    # 1. A tree: Add, a click on the map places it, and its properties.
    _open(page, edit_id, "add", "input_3")
    expect(edit).to_contain_text("Click on the map to place a point.")
    box = page.locator(_map(map_id)).bounding_box()
    assert box, "the map has no layout box"
    place = assert_in_view(page, box["x"] + 0.55 * box["width"], box["y"] + 0.55 * box["height"], "the map's middle")
    assert page.evaluate(_SHOWN_JS, [_map(map_id), *place]), "something lies over the middle of the map"
    form = edit.get_by_test_id("interaction-property-form")
    with canvas_painted_at_shown_zoom(page):
        frame_nodes(page, [edit_id, map_id])
        dismiss_toasts(page)
        _frame(page, "add-point", "click", "before", map_id, edit_id, stem=CHICAGO_STEM)
        page.mouse.click(*place)
        form.wait_for(state="visible", timeout=10000)
        wait_for_node_still(page, edit_id)
        _frame(page, "add-point", "click", "after", map_id, edit_id, stem=CHICAGO_STEM)
    expect(form).to_contain_text("New point: its properties")
    _fill_every_field(form)
    keep_drawing(page, _map(map_id))
    submit = form.get_by_test_id("interaction-form-submit")
    expect(submit).to_have_text("Add point")
    expect(submit).to_be_enabled()
    submit.click()
    code, keywords = _wait_for_count_of_edits(page, edit_id, 1, "the tree's add")
    (tree,) = _edits_of(code)[0]
    assert tree["op"] == "add" and tree["geometry"]["type"] == "Point" and "layer" not in tree, tree
    assert (keywords.get("layer"), keywords.get("key"), keywords.get("by_input")) == ("input_3", "osm_id", True), keywords
    expect(edit.locator('[data-edit-op="add"]')).to_contain_text(f"Add a point ({tree['id']})")
    _wait_for_redraw(page, map_id, "the tree's add")
    # The tree just added is lit by the map itself: the trees are the layer
    # the action works on, the one that picks.
    _wait_for_lit(page, map_id, [tree["id"]], "the tree's add", table="input_3", key="osm_id")

    # 2. A road: Edit, only the roads shown, one picked with a click, and one
    # of its corners dragged with Move points.
    _back_to_layers(page, edit_id)
    _open(page, edit_id, "edit", "table_osm_roads")
    everything = _drawn_share(_map_pixels(page, map_id))
    edit.get_by_test_id("interaction-solo").check()
    deadline = time.time() + 30
    while time.time() < deadline and _drawn_share(_map_pixels(page, map_id)) >= 0.9 * everything:
        page.wait_for_timeout(500)
    roads_only = _drawn_share(_map_pixels(page, map_id))
    assert roads_only < 0.9 * everything, f"Show only this layer left {roads_only:.0%} of the map drawn, as before ({everything:.0%})"
    road_point = page.evaluate(_DRAWN_POINT_JS, {"id": map_id, "at": [0.5, 0.5], "background": list(MAP_BACKGROUND)})
    assert road_point, "the map shows no road to pick"
    page.mouse.click(*assert_in_view(page, road_point["x"], road_point["y"], "a road on the map"))
    edit.get_by_test_id("interaction-selection").wait_for(state="visible", timeout=10000)
    rows, layer = _selection(page, edit_id, map_id)
    assert layer == "table_osm_roads", (rows, layer)
    (road_id,) = set(_ids(rows, "osm_id"))
    # The picked road is lit by the map itself, every piece of it.
    _wait_for_lit(page, map_id, {road_id}, "a road picked", table="table_osm_roads", key="osm_id")
    reshape = edit.get_by_test_id("interaction-reshape")
    reshape.click()
    expect(reshape).to_have_attribute("aria-checked", "true")
    # A second click keeps it on; Pan turns it off.
    reshape.click()
    expect(reshape).to_have_attribute("aria-checked", "true")
    with canvas_painted_at_shown_zoom(page):
        frame_nodes(page, [edit_id, map_id])
        dismiss_toasts(page)
        wait_for_node_still(page, map_id)
        handle = _corner_to_drag(page, map_id)
        assert handle, "Move points shows no corner of the road on the map to drag"
        drop = assert_in_view(page, handle["x"] + 24, handle["y"] + 16, "where the road's corner is dropped")
        _frame(page, "reshape-road", "drag", "before", map_id, edit_id, stem=CHICAGO_STEM)
        keep_drawing(page, _map(map_id))
        page.mouse.move(handle["x"], handle["y"])
        page.mouse.down()
        page.mouse.move(*drop, steps=8)
        page.mouse.up()
        code, keywords = _wait_for_count_of_edits(page, edit_id, 2, "the road's reshape")
        road = _edits_of(code)[0][1]
        assert (road["op"], road.get("layer"), road.get("ids")) == ("geometry", "table_osm_roads", [road_id]), road
        assert road["geometry"]["type"] in ("LineString", "MultiLineString"), road
        assert keywords.get("keys", {}).get("table_osm_roads") == "osm_id", keywords
        _wait_for_redraw(page, map_id, "the road's reshape")
        moved = page.evaluate(_HANDLE_AT_JS, {"id": map_id, "ring": handle["ring"], "index": handle["index"]})
        assert moved and math.hypot(moved["x"] - drop[0], moved["y"] - drop[1]) < 4, (
            f"the corner dragged to {drop} is drawn at {moved}"
        )
        wait_for_node_still(page, edit_id)
        _frame(page, "reshape-road", "drag", "after", map_id, edit_id, stem=CHICAGO_STEM)
    expect(edit.locator('[data-edit-op="geometry"]')).to_contain_text(f"Redraw osm_id {road_id}")
    pan = edit.get_by_test_id("interaction-pan")
    pan.click()
    expect(pan).to_have_attribute("aria-checked", "true")
    expect(reshape).to_have_attribute("aria-checked", "false")
    expect(_overlay(page, map_id)).to_have_attribute("data-corners", "[]")
    expect(_overlay(page, map_id).locator("svg")).to_have_count(0)
    edit.get_by_test_id("interaction-solo").uncheck()

    # 3. A property on every park.
    _back_to_layers(page, edit_id)
    _open(page, edit_id, "property", "table_osm_parks")
    edit.get_by_test_id("interaction-property-name").fill("surveyed")
    edit.get_by_test_id("interaction-property-value").fill("no")
    keep_drawing(page, _map(map_id))
    edit.get_by_test_id("interaction-property-add").click()
    code, keywords = _wait_for_count_of_edits(page, edit_id, 3, "the parks' new property")
    # The map draws the edits again, as after each edit: the close-up waits for it.
    _wait_for_redraw(page, map_id, "the parks' new property")
    survey = _edits_of(code)[0][2]
    assert survey == {"op": "add_column", "layer": "table_osm_parks", "column": "surveyed", "value": "no"}, survey
    assert keywords.get("keys", {}).get("table_osm_parks") == "osm_id", keywords
    expect(edit.locator('[data-edit-op="add_column"]')).to_contain_text("Add a property surveyed")
    _back_to_layers(page, edit_id)
    save_node_closeup(page, CHICAGO_STEM, map_id, test_name=f"{test_name}_closeup_{map_id}",
                      sweep_toasts=True)

    # Commit edits runs the node and the map, and the node hands on all three.
    _commit(page, edit_id, [edit_id], [map_id], below=1)
    layers_out = _handed_layers(load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, edit_id)))
    trees = [f for f in layers_out["input_3"]["features"] if (f.get("properties") or {}).get("osm_id") == tree["id"]]
    assert len(trees) == 1, f"the node handed on {len(trees)} trees with osm_id {tree['id']}, not the one added"
    _assert_same_shape(trees[0]["geometry"], tree["geometry"], f"the tree {tree['id']}")
    roads = [f for f in layers_out["table_osm_roads"]["features"] if (f.get("properties") or {}).get("osm_id") == road_id]
    assert len(roads) == 1, f"the node handed on {len(roads)} roads with osm_id {road_id}"
    _assert_same_shape(roads[0]["geometry"], road["geometry"], f"the road {road_id}")
    parks = layers_out["table_osm_parks"]["features"]
    assert parks and all((f.get("properties") or {}).get("surveyed") == "no" for f in parks), (
        "a park was handed on without the property surveyed"
    )
    save_node_closeup(page, CHICAGO_STEM, edit_id, test_name=f"{test_name}_closeup_{edit_id}",
                      sweep_toasts=True)


def test_a_chicago_building_of_several_parts_is_reshaped_one_part_at_a_time(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The shipped Chicago Loop layers: OSM's buildings come one row per part,
    each part with its building's ``building_id`` and an ``osm_id`` of its
    own, and autk-db's crop keeps buildings the map draws two or more parts of.
    Such a building near the middle of the map, whose parts have corners with
    room around them, picked on it in the node's Edit, the map zoomed in on it:

    1. Move points shows the corners of every part;
    2. a corner of one part, dragged, is one edit that names that part alone,
       ``where building_id == <building> and osm_id == <part>``; the building
       stays picked across it, the node's first edit, which names its layer
       and key in its code (#1111), and the map shows its other parts where
       they were;
    3. Commit edits runs the node, which hands that part on reshaped and the
       building's other parts as they came.

    What is wrong at each step is kept, and the test fails with all of it
    before its first capture."""
    test_name = "test_a_chicago_building_of_several_parts_is_reshaped_one_part_at_a_time"
    path = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-loop-layers.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    (edit_id,) = [n for n, node in nodes.items() if node["type"] == EDIT_TYPE]
    (map_id,) = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and '"map"' in node["content"]]
    title = nodes[map_id]["title"]
    _enter(page, app_frontend, current_server, spec, "map_edits_parts_e2e", name=spec["dataflow"]["name"])
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node in nodes.items():
        _done(page, node_id, node["type"])
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)

    # The buildings as the node hands them on before any edit, each one's
    # rows in the layer's order, and the parts of each that the map draws
    # after autk-db's crop.
    handed = _handed_layers(load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, edit_id)))
    rows_of: dict = {}
    for feature in handed[BUILDINGS]["features"]:
        rows_of.setdefault((feature.get("properties") or {}).get(KEY), []).append(feature)
    drawn = page.evaluate(_DRAWN_PARTS_JS, {"id": map_id, "table": BUILDINGS, "key": KEY, "part": PART_KEY})
    assert drawn, f"the map {map_id} reports no rows of {BUILDINGS} that it draws"
    drawn_parts: dict = {}
    for building, part in drawn:
        if building is not None and part is not None:
            drawn_parts.setdefault(building, set()).add(part)
    parted = [
        building for building, rows in rows_of.items()
        if building is not None and _told_apart(rows) and len(drawn_parts.get(building, ())) >= 2
    ]
    assert parted, (
        f"autk-db's crop keeps no building the map draws two or more parts of, each part with an {PART_KEY}: "
        f"it draws {len(drawn)} rows of {len(drawn_parts)} buildings, "
        f"{sum(len(parts) >= 2 for parts in drawn_parts.values())} of them in two or more parts"
    )
    # First the buildings whose first part, and whose other parts, each have a
    # corner with the most room around it: a press takes that corner alone.
    parted.sort(key=lambda building: -_drag_room(rows_of[building]))

    edit = node_locator(page, edit_id)
    frame_nodes(page, [edit_id, map_id])
    _open_tab(page, edit_id, "output")
    _assert_linked(page, edit_id, map_id, title)
    expect(edit.get_by_test_id(f"interaction-layer-{BUILDINGS}")).to_be_attached(timeout=30000)
    _open(page, edit_id, "edit", BUILDINGS)
    box = page.locator(_map(map_id)).bounding_box()
    assert box, "the map has no layout box"
    reshape = edit.get_by_test_id("interaction-reshape")

    # Each building in turn picked on the map, as the map's own pick is sent,
    # with Move points on, until one sits near the middle of the map.
    building, corners, tried = None, [], []
    for candidate in parted[:8]:
        page.evaluate(_SEND_JS, [map_id, _map_pick(candidate)])
        _wait_for_lit(page, map_id, {candidate}, f"building {candidate} picked", table=BUILDINGS)
        if reshape.get_attribute("aria-checked") != "true":
            reshape.click()
            expect(reshape).to_have_attribute("aria-checked", "true")
        # The corners of this building, not of the one picked before.
        seen = [(c["x"], c["y"]) for c in corners]
        shown = _wait_for_corners(
            page, map_id, lambda now: bool(now) and [(c["x"], c["y"]) for c in now] != seen, f"building {candidate} picked",
        )
        x, y = _middle(shown)
        tried.append((candidate, round(x), round(y)))
        corners = shown
        if box["x"] + 0.2 * box["width"] < x < box["x"] + 0.8 * box["width"] and \
                box["y"] + 0.2 * box["height"] < y < box["y"] + 0.8 * box["height"]:
            building = candidate
            break
    assert building is not None, f"no building of several parts lies near the middle of the map: {tried}"
    rows = rows_of[building]
    wrong: list[str] = []

    # 1. Move points shows the corners of every part.
    expected_corners = sum(_corner_count(row.get("geometry")) for row in rows)
    if len(corners) != expected_corners or {corner["part"] for corner in corners} != set(range(len(rows))):
        wrong.append(
            f"Move points shows {len(corners)} corners of the parts {sorted({str(c['part']) for c in corners})} of "
            f"building {building}, not the {expected_corners} corners of its {len(rows)} parts"
        )

    # Zoomed in on it with the wheel, at its middle, in half steps, until a
    # corner to drag has CORNER_ROOM pixels around it, the whole building kept
    # well inside the map.
    page.mouse.move(*_middle(corners))
    delta = -ZOOM_DELTA // 2
    for step in range(2 * ZOOM_STEPS):
        if _best_room(corners) >= CORNER_ROOM:
            break
        page.mouse.wheel(0, delta)
        page.wait_for_timeout(500)
        now = _wait_for_corners(page, map_id, bool, "a zoom of the map")
        if step == 0 and _spread(now) < _spread(corners):
            # This wheel zooms out the other way round.
            delta = -delta
        elif not _within(now, box, 40):
            # Zoomed past the map's edges: a step back, and no further.
            page.mouse.wheel(0, -delta)
            page.wait_for_timeout(500)
            corners = _wait_for_corners(page, map_id, bool, "a zoom back")
            break
        corners = now

    # 2. A corner of a part other than the first, with no other corner near
    # it, dragged with Move points: one a press reaches, inside the map with
    # nothing over it, drawn in the map's highlight when one such is. A press
    # takes the corner nearest it, wherever the map draws its buildings over.
    # It is dropped a little out from its neighbours' middle, or in toward
    # it, where no side of its part crosses another: a drag that would make
    # an outline cross itself is refused and writes no edit (#1112), since
    # autk-db refuses such a shape, and with it the whole layer.
    dismiss_toasts(page)
    corners = _wait_for_corners(page, map_id, bool, "the zoom")
    roomy = [c for c in _to_drag(corners) if c["inside"] and c["onTop"] and _room(c, corners) >= PRESS_ROOM]
    roomy.sort(key=lambda c: (c["lit"], _room(c, corners)), reverse=True)
    corner, drop = next(((c, d) for c in roomy for d in [_drop_keeping_shape(c, corners)] if d), (None, None))
    assert corner and drop, (
        f"Move points shows no corner of building {building} to drag with {PRESS_ROOM} pixels around it and its "
        f"part's sides kept apart (the most room a corner has is {_best_room(corners):.1f}): {corners}"
    )
    part = corner["part"] or 0
    part_id = (rows[part].get("properties") or {}).get(PART_KEY)
    where = f"{KEY} == {_literal(building)} and {PART_KEY} == {_literal(part_id)}"
    drop = assert_in_view(page, drop[0], drop[1], "where the part's corner is dropped")
    keep_drawing(page, _map(map_id))
    page.mouse.move(corner["x"], corner["y"])
    page.mouse.down()
    page.mouse.move(*drop, steps=8)
    page.mouse.up()
    code, keywords = _wait_for_count_of_edits(page, edit_id, 1, f"a corner of building {building}'s part {part_id} dragged")
    (redraw,) = _edits_of(code)[0]
    if redraw.get("op") != "geometry" or "ids" in redraw or redraw.get("where") != where:
        wrong.append(
            f"a corner of building {building}'s part {part_id} dragged wrote {_shown_edit(redraw)}, not a redraw "
            f"where {where}: an edit by {KEY} {building} gives every one of its {len(rows)} parts that one shape"
        )
    if (keywords.get("layer"), keywords.get("key")) != (BUILDINGS, KEY):
        wrong.append(f"the node's code names the layer {keywords.get('layer')} and the key {keywords.get('key')}")
    try:
        expect(edit.locator('[data-edit-op="geometry"]')).to_contain_text(f"Redraw where {where}", timeout=5000)
    except AssertionError as error:
        wrong.append(f"the list does not name the part: {error}")

    # The map draws the edit, and shows the building's other parts where they
    # were. The drag is the node's first edit, which names its layer and key
    # in its code, and the building stays picked across it: with no pick sent
    # again, Move points shows its corners and the map lights it (#1111).
    _wait_for_redraw(page, map_id, "the part's corner dragged")
    try:
        shown = _wait_for_corners(page, map_id, bool, "the drag")
    except AssertionError as error:
        raise AssertionError("\n".join([*wrong, (
            f"after the drag, building {building} is no longer picked: the node's first edit, which names the layer "
            f"{BUILDINGS} and the key {KEY} in its code, dropped the pick, and with no pick sent again Move points "
            f"shows none of its corners (#1111): {error}"
        )])) from None
    _wait_for_lit(page, map_id, {building}, f"building {building} kept picked across the drag", table=BUILDINGS)
    after = {(c["part"], c["ring"], c["index"]): c for c in shown}
    for before in corners:
        now = after.get((before["part"], before["ring"], before["index"]))
        dragged = (before["part"], before["ring"], before["index"]) == (corner["part"], corner["ring"], corner["index"])
        target = drop if dragged else (before["x"], before["y"])
        if now is None or math.hypot(now["x"] - target[0], now["y"] - target[1]) > (4 if dragged else 1.5):
            wrong.append(
                f"after the drag, the corner {before['ring']}.{before['index']} of part {before['part']} is shown at "
                f"{now and (round(now['x'], 1), round(now['y'], 1))}, not at {tuple(round(v, 1) for v in target)}"
            )

    # 3. Commit edits: the node hands that part on reshaped, and the
    # building's other parts as they came.
    _commit(page, edit_id, [edit_id], [map_id], below=1)
    out = _handed_layers(load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, edit_id)))[BUILDINGS]["features"]
    committed = [row for row in out if (row.get("properties") or {}).get(KEY) == building]
    if len(committed) != len(rows):
        wrong.append(f"Commit edits handed on {len(committed)} rows of building {building}, not its {len(rows)} parts")
    for row, kept in zip(rows, committed):
        osm = (row.get("properties") or {}).get(PART_KEY)
        shape = redraw.get("geometry") if osm == part_id else row.get("geometry")
        try:
            _assert_same_shape(kept.get("geometry") or {}, shape or {}, f"building {building}'s part {osm}")
        except AssertionError as error:
            wrong.append(f"after Commit edits, part {osm} of building {building}: {error}")
    assert not wrong, "\n".join(wrong)

    # The building picked again, as the map shows it with Move points on,
    # and the node with the edit in its list.
    _picked_with_corners(page, map_id, building, f"building {building} picked after Commit edits")
    save_node_closeup(page, CHICAGO_STEM, map_id, test_name=f"{test_name}_closeup_{map_id}", sweep_toasts=True)
    save_node_closeup(page, CHICAGO_STEM, edit_id, test_name=f"{test_name}_closeup_{edit_id}", sweep_toasts=True)


def test_a_chicago_building_corner_dragged_across_its_far_side_is_refused_and_the_layer_keeps_drawing(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The shipped Chicago Loop layers: a compact building of one part, its
    outline one ring of four to eight corners, near the middle of the map,
    picked on it in the node's Edit, Move points on, the map zoomed in on it
    and panned until it sits in the middle, about a third of the map across.
    One of its corners dragged across a side of the outline that it does not
    end would make the outline cross itself, which autk-db refuses, and with
    it the whole buildings layer (#1112). Let go, the drag is refused:

    1. the node's code gains no edit;
    2. the map's tip says why, and the corner is back where it was;
    3. the map draws on, the buildings with it, and the browser log holds no
       layer that failed to load.

    What is wrong is kept, and the test fails with all of it before its
    capture: a close-up of the map, its tip saying why."""
    test_name = "test_a_chicago_building_corner_dragged_across_its_far_side_is_refused_and_the_layer_keeps_drawing"
    log = _browser_log(page)
    path = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-loop-layers.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    (edit_id,) = [n for n, node in nodes.items() if node["type"] == EDIT_TYPE]
    (map_id,) = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and '"map"' in node["content"]]
    title = nodes[map_id]["title"]
    _enter(page, app_frontend, current_server, spec, "map_edits_crossing_e2e", name=spec["dataflow"]["name"])
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node in nodes.items():
        _done(page, node_id, node["type"])
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)

    # The compact buildings of one part the map draws: each outline one ring
    # of four to eight corners, its box on the ground at most twice as long as
    # it is wide. The larger half of them, which the map zooms in on least,
    # nearest the middle of all of them first.
    handed = _handed_layers(load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, edit_id)))
    rows_of: dict = {}
    for feature in handed[BUILDINGS]["features"]:
        rows_of.setdefault((feature.get("properties") or {}).get(KEY), []).append(feature)
    drawn = page.evaluate(_DRAWN_PARTS_JS, {"id": map_id, "table": BUILDINGS, "key": KEY, "part": PART_KEY})
    assert drawn, f"the map {map_id} reports no rows of {BUILDINGS} that it draws"
    shown = {building for building, _part in drawn if building is not None}
    outlines = {
        building: ring for building, rows in rows_of.items() if building in shown
        for ring in [_one_outline(rows)] if ring and _compact(ring)
    }
    assert outlines, (
        f"the map draws no compact building of one part, its outline one ring of 4 to 8 corners, "
        f"of the {len(shown)} it draws"
    )
    boxes = {building: _extent(ring) for building, ring in outlines.items()}
    x0, y0, x1, y1 = _extent([point for ring in outlines.values() for point in ring])
    sizes = {building: max(b[2] - b[0], b[3] - b[1]) for building, b in boxes.items()}
    median = sorted(sizes.values())[len(sizes) // 2]
    compact = sorted(
        (building for building in outlines if sizes[building] >= median),
        key=lambda building: math.hypot(
            (boxes[building][0] + boxes[building][2] - x0 - x1) / 2, (boxes[building][1] + boxes[building][3] - y0 - y1) / 2,
        ),
    )

    edit = node_locator(page, edit_id)
    frame_nodes(page, [edit_id, map_id])
    _open_tab(page, edit_id, "output")
    _assert_linked(page, edit_id, map_id, title)
    expect(edit.get_by_test_id(f"interaction-layer-{BUILDINGS}")).to_be_attached(timeout=30000)
    _open(page, edit_id, "edit", BUILDINGS)
    box = page.locator(_map(map_id)).bounding_box()
    assert box, "the map has no layout box"
    reshape = edit.get_by_test_id("interaction-reshape")

    # Each in turn picked on the map, as the map's own pick is sent, with Move
    # points on, until one sits near the middle of the map. The map is then
    # zoomed in on it and panned until it sits in the middle, about a third of
    # the map across: plain, with its corners, in the close-up.
    building, corners, tried = _pick_near_the_middle(page, map_id, reshape, compact, box)
    assert building is not None, f"no compact building of one part lies near the middle of the map: {tried}"
    corners = _framed(page, map_id, corners, box)

    # A corner a press takes alone, inside the map with nothing over it, and
    # a drop past the middle of a side of its outline that it does not end,
    # on the map too: a side the corner ends then crosses another.
    dismiss_toasts(page)
    corners = _wait_for_corners(page, map_id, bool, "the zoom")
    roomy = [c for c in _to_drag(corners) if c["inside"] and c["onTop"] and _room(c, corners) >= PRESS_ROOM]
    roomy.sort(key=lambda c: (c["lit"], _room(c, corners)), reverse=True)
    corner, drop = next(
        ((c, d) for c in roomy for d in _drops_crossing_shape(c, corners) if _on_the_map(page, map_id, d, box)),
        (None, None),
    )
    assert corner and drop, (
        f"Move points shows no corner of building {building} with {PRESS_ROOM} pixels around it that a drag can take "
        f"across a far side of its outline, inside the map (the most room a corner has is {_best_room(corners):.1f}): "
        f"{corners}"
    )
    drop = assert_in_view(page, drop[0], drop[1], "where the corner is dropped")
    handle = {"id": map_id, "ring": corner["ring"], "index": corner["index"], "part": corner["part"]}

    # The drag, the map's drawing kept first to tell whether it draws again.
    # While the drag lasts, Move points shows the corner under the pointer:
    # the press took it.
    start = len(log)
    keep_drawing(page, _map(map_id))
    page.mouse.move(corner["x"], corner["y"])
    page.mouse.down()
    page.mouse.move(*drop, steps=8)
    held, deadline = None, time.time() + 3
    while time.time() < deadline:
        held = page.evaluate(_HANDLE_AT_JS, handle)
        if held and math.hypot(held["x"] - drop[0], held["y"] - drop[1]) < 4:
            break
        page.wait_for_timeout(100)
    page.mouse.up()
    assert held and math.hypot(held["x"] - drop[0], held["y"] - drop[1]) < 4, (
        f"the press on the corner {corner['ring']}.{corner['index']} of building {building} at "
        f"{(round(corner['x'], 1), round(corner['y'], 1))} did not take it: dragged to "
        f"{tuple(round(v, 1) for v in drop)}, it is shown at {held}"
    )
    wrong: list[str] = []

    # 1. The node's code gains no edit; a drag's edit is written as it ends.
    edits, deadline = [], time.time() + 5
    while time.time() < deadline and not edits:
        page.wait_for_timeout(250)
        try:
            edits = _edits_of(read_node_code(page, edit_id))[0]
        except (AssertionError, SyntaxError, ValueError):
            edits = []
    if edits:
        wrong.append(f"the self-crossing reshape was written as an edit: {[_shown_edit(e) for e in edits]}")

    # 2. The map's tip says why, and the corner is back where it was.
    tip = _overlay(page, map_id).get_by_test_id("map-edit-tip")
    try:
        expect(tip).to_contain_text(CROSSED_DRAG, timeout=5000)
    except AssertionError:
        wrong.append(f"the map's tip does not say why the reshape was refused: it reads {tip.all_inner_texts()}")
    back = page.evaluate(_HANDLE_AT_JS, handle)
    if not back or math.hypot(back["x"] - corner["x"], back["y"] - corner["y"]) > 1.5:
        wrong.append(
            f"after the refused drag, the corner {corner['ring']}.{corner['index']} of building {building} is shown at "
            f"{back and (round(back['x'], 1), round(back['y'], 1))}, not back at "
            f"{(round(corner['x'], 1), round(corner['y'], 1))}"
        )

    # 3. The map draws on, the buildings with it. Nothing changed, so it is
    # not drawn again; a draw that comes, as an edit's does, is waited for to
    # its end: the map drawn whole, or a layer that failed to load.
    if not drawing_kept(page, _map(map_id)):
        deadline = time.time() + INTERACTION_SHOWN_TIMEOUT_MS / 1000
        while time.time() < deadline and not _failed_loads(log[start:]):
            try:
                assert_autark_map_drawn(page, map_id, timeout=1000)
                break
            except AssertionError:
                page.wait_for_timeout(500)
    try:
        assert_autark_map_drawn(page, map_id)
    except AssertionError as error:
        wrong.append(f"the map draws nothing after the drag: {error}")
    failed = _failed_loads(log[start:])
    if failed:
        wrong.append(f"autk-db refused a layer after the drag, so the map draws none of it: {failed[0]}")
    if wrong:
        dump_browser_log(CHICAGO_STEM, test_name, log)
    assert not wrong, "\n".join(wrong)

    # The map, its tip saying why the corner went back.
    save_node_closeup(page, CHICAGO_STEM, map_id, test_name=f"{test_name}_closeup_{map_id}", sweep_toasts=True)


#: The text a node shows of its last run: the lines it printed, then where it
#: saved its output (``executionResultOutput``); null before a run.
_OUTPUT_TEXT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const content = node && node.data && node.data.output && node.data.output.content;
    return typeof content === "string" ? content : null;
}"""


def _drawn_wrong(page, map_id: str, building, log: list[dict], when: str, what: str) -> list[str]:
    """What is wrong with the Chicago map *when*, after *what*: it draws
    nothing, a layer failed to load, or it draws no row of *building* among the
    buildings. The canvas is read in the frame that renders it, as captures
    read it: Chrome can read an idle WebGPU canvas back as transparent."""
    wrong = []
    try:
        _wait_for_map_drawn(page, map_id, what)
    except AssertionError as error:
        wrong.append(f"{when}, the map draws nothing: {error}")
    failed = _failed_loads(log)
    if failed:
        wrong.append(f"{when}, autk-db refused a layer, so the map draws none of it: {failed[0]}")
    drawn = page.evaluate(_DRAWN_PARTS_JS, {"id": map_id, "table": BUILDINGS, "key": KEY, "part": PART_KEY})
    if drawn is None:
        wrong.append(f"{when}, the map draws no {BUILDINGS} at all")
    elif not any(key == building for key, _part in drawn):
        wrong.append(f"{when}, the map draws {len(drawn)} rows of {BUILDINGS}, none of building {building}")
    return wrong


def test_a_chicago_building_redrawn_as_a_bow_tie_in_the_nodes_code_is_skipped_and_the_layer_keeps_drawing(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The steps of #1121, on the shipped Chicago Loop layers, run whole: a
    redraw of a building of one part as a bow tie, an outline that crosses
    itself, in the building's own coordinates, typed into the Map Editor
    node's code, as an agent writes one or Provenance puts one back. autk-db
    would refuse it, and with it the whole buildings layer.

    1. The map draws the node's code at once, before Commit edits: the
       buildings, that one among them, and the browser log holds no layer
       that failed to load.
    2. Commit edits runs the node: its output says it skips the redraw,
       naming the building, and it hands the building on with its own shape.
    3. The map draws on, the buildings with it, and the browser log holds no
       layer that failed to load.

    What is wrong at each step is kept, and the test fails with all of it."""
    test_name = "test_a_chicago_building_redrawn_as_a_bow_tie_in_the_nodes_code_is_skipped_and_the_layer_keeps_drawing"
    log = _browser_log(page)
    path = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-loop-layers.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    (edit_id,) = [n for n, node in nodes.items() if node["type"] == EDIT_TYPE]
    (map_id,) = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and '"map"' in node["content"]]
    _enter(page, app_frontend, current_server, spec, "map_edits_typed_bow_tie_e2e", name=spec["dataflow"]["name"])
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node in nodes.items():
        _done(page, node_id, node["type"])
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)

    # A building of one part the map draws, its outline one ring, and a bow
    # tie across the box around it, in the building's own coordinates.
    handed = _handed_layers(load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, edit_id)))
    rows_of: dict = {}
    for feature in handed[BUILDINGS]["features"]:
        rows_of.setdefault((feature.get("properties") or {}).get(KEY), []).append(feature)
    drawn = page.evaluate(_DRAWN_PARTS_JS, {"id": map_id, "table": BUILDINGS, "key": KEY, "part": PART_KEY}) or []
    shown = [building for building, _part in drawn if building is not None]
    building = next((b for b in shown if _one_outline(rows_of.get(b, [])) is not None), None)
    assert building is not None, f"the map draws no building of one part whose outline is one ring, of {len(set(shown))}"
    (row,) = rows_of[building]
    x0, y0, x1, y1 = _extent(_one_outline([row]))
    bow_tie = {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y1], [x1, y0], [x0, y1], [x0, y0]]]}
    redraw = {"op": "geometry", "ids": [building], "geometry": bow_tie}
    code = read_node_code(page, edit_id)
    typed = code.replace(
        "], [], by_input=True)",
        f"], [\n    {json.dumps(redraw)},\n], key={json.dumps(KEY)}, layer={json.dumps(BUILDINGS)}, by_input=True)",
    )
    assert typed != code, f"the Map Editor node's code is not the call with no edits the example ships: {code!r}"

    # 1. The bow tie typed into the node's code: the map draws it at once.
    frame_nodes(page, [edit_id, map_id])
    start = len(log)
    keep_drawing(page, _map(map_id))
    set_node_code(page, edit_id, typed)
    wrong: list[str] = []
    try:
        _wait_for_redraw(page, map_id, "the bow tie typed into the node's code")
    except AssertionError as error:
        wrong.append(str(error))
    wrong += _drawn_wrong(
        page, map_id, building, log[start:], "before Commit edits", "the bow tie typed into the node's code",
    )

    # 2. Commit edits, at the foot of the node's list, on its Output tab (the
    # code was typed on its Code tab): the run skips the redraw and says so.
    _open_tab(page, edit_id, "output")
    try:
        _commit(page, edit_id, [edit_id], [map_id], below=1)
    except (AssertionError, PlaywrightTimeoutError) as error:
        wrong.append(f"Commit edits did not run the node and the map: {error}")
    said = page.evaluate(_OUTPUT_TEXT_JS, edit_id) or ""
    line = (
        f"Map Editor: layer {BUILDINGS}: the geometry would make the outline of {KEY} {building} cross itself, "
        "an area the map cannot draw; the geometry skips it."
    )
    if line not in said:
        wrong.append(f"the node's run does not say it skips the redraw ({line!r}); it says: {said[-1500:]!r}")
    out = _handed_layers(load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, edit_id)))[BUILDINGS]["features"]
    kept = [feature.get("geometry") for feature in out if (feature.get("properties") or {}).get(KEY) == building]
    if kept != [row.get("geometry")]:
        wrong.append(f"after Commit edits, the node hands building {building} on as {kept}, not with its own shape")

    # 3. The map draws on, the buildings with it.
    wrong += _drawn_wrong(page, map_id, building, log[start:], "after Commit edits", "Commit edits")
    if wrong:
        dump_browser_log(CHICAGO_STEM, test_name, log)
    assert not wrong, "\n".join(wrong)


# The value of *key* and of *part* of each row the map draws of the table
# *table*, in the order it draws them (window.__curio_mapFeatureAt).
_DRAWN_PARTS_JS = """async ({ id, table, key, part }) => {
    const state = window.__curio_mapState ? await window.__curio_mapState(id) : null;
    const layer = state && state[table];
    if (!layer) return null;
    const out = [];
    for (let position = 0; position < layer.drawn; position++) {
        const feature = await window.__curio_mapFeatureAt(id, table, position);
        out.push(feature ? [feature[key] ?? null, feature[part] ?? null] : [null, null]);
    }
    return out;
}"""

# A selection sent as the node *id*'s own, through its node's
# interactionsCallback, which the interaction edges carry: a map's pick.
_SEND_JS = """([id, selection]) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    node.data.interactionsCallback(selection, id);
}"""


def _map_pick(building) -> dict:
    """The selection a pick of *building* on the Chicago map is sent as."""
    return {"autk_selection": {
        "type": "POINT", "data": [{KEY: building}], "priority": 1, "source": MAP_TYPE, "layerRef": BUILDINGS,
    }}


def _told_apart(rows: list[dict]) -> bool:
    """Whether a building's rows are two parts or more, each with a shape and
    an ``osm_id`` of its own."""
    ids = [(row.get("properties") or {}).get(PART_KEY) for row in rows]
    return len(rows) >= 2 and all(row.get("geometry") for row in rows) and None not in ids and len(set(ids)) == len(ids)


def _rings_of(geometry: dict | None) -> list[list[tuple[float, float]]]:
    """A shape's corners, ring by ring, as Move points shows them: an area's
    rings without the corner that closes each."""
    kind, coordinates = (geometry or {}).get("type"), (geometry or {}).get("coordinates") or []
    rings = {
        "Point": [[coordinates]], "MultiPoint": [[point] for point in coordinates],
        "LineString": [coordinates], "MultiLineString": coordinates,
        "Polygon": coordinates, "MultiPolygon": [ring for polygon in coordinates for ring in polygon],
    }.get(kind, [])
    out = []
    for ring in rings:
        points = [(float(point[0]), float(point[1])) for point in ring]
        if kind in ("Polygon", "MultiPolygon") and len(points) > 1 and points[0] == points[-1]:
            points = points[:-1]
        out.append(points)
    return out


def _corner_count(geometry: dict | None) -> int:
    """How many corners Move points shows for a shape."""
    return sum(len(ring) for ring in _rings_of(geometry))


def _drag_room(rows: list[dict]) -> float:
    """How much room, in its layer's units, a building gives a corner to drag:
    the most a corner of its first part has from every other corner of the
    building, and the most a corner of its other parts has, whichever is less."""
    corners = [(part, point) for part, row in enumerate(rows) for ring in _rings_of(row.get("geometry")) for point in ring]

    def room(i: int) -> float:
        x, y = corners[i][1]
        return min((math.hypot(x - ox, y - oy) for j, (_, (ox, oy)) in enumerate(corners) if j != i), default=math.inf)

    first = max((room(i) for i, (part, _) in enumerate(corners) if part == 0), default=0.0)
    others = max((room(i) for i, (part, _) in enumerate(corners) if part > 0), default=0.0)
    return min(first, others)


def _to_drag(corners: list[dict]) -> list[dict]:
    """The corners a test drags: those of the parts after the first, when the
    overlay names their parts, else every one."""
    parts = {corner["part"] for corner in corners}
    return [corner for corner in corners if len(parts) < 2 or corner["part"] != 0]


def _best_room(corners: list[dict]) -> float:
    """The most room, in page pixels, a corner to drag has from every other corner."""
    return max((_room(corner, corners) for corner in _to_drag(corners)), default=0.0)


def _picked_with_corners(page, map_id: str, building, what: str) -> list[dict]:
    """Pick *building* on the map *map_id*, as the map's own pick is sent, and
    wait until Move points shows its corners."""
    page.evaluate(_SEND_JS, [map_id, _map_pick(building)])
    _wait_for_lit(page, map_id, {building}, what, table=BUILDINGS)
    return _wait_for_corners(page, map_id, bool, what)


def _crosses(a, b, c, d) -> bool:
    """Whether the segments *a* to *b* and *c* to *d* cross or touch."""
    def turn(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on(p, q, r):
        return min(p[0], q[0]) - 1e-9 <= r[0] <= max(p[0], q[0]) + 1e-9 and min(p[1], q[1]) - 1e-9 <= r[1] <= max(p[1], q[1]) + 1e-9

    t1, t2, t3, t4 = turn(c, d, a), turn(c, d, b), turn(a, b, c), turn(a, b, d)
    if ((t1 > 0) != (t2 > 0)) and ((t3 > 0) != (t4 > 0)) and t1 and t2 and t3 and t4:
        return True
    return any(t == 0 and on(p, q, r) for t, p, q, r in ((t1, c, d, a), (t2, c, d, b), (t3, a, b, c), (t4, a, b, d)))


def _drop_keeping_shape(corner: dict, corners: list[dict]) -> tuple[float, float] | None:
    """Where to drag *corner*, in page coordinates, so that no side of its part
    crosses another (autk-db checks each part with ``ST_IsValid``): a little
    out from the middle of its two neighbours in its ring, else in toward it,
    at least 5 pixels from where it is; None when neither keeps the sides
    apart."""
    rings: dict = {}
    indexes: dict = {}
    for c in sorted(corners, key=lambda c: c["index"]):
        if c["part"] == corner["part"]:
            rings.setdefault(c["ring"], []).append((c["x"], c["y"]))
            indexes.setdefault(c["ring"], []).append(c["index"])
    ring = rings.get(corner["ring"], [])
    if len(ring) < 3:
        return None
    at = indexes[corner["ring"]].index(corner["index"])
    before, after = ring[at - 1], ring[(at + 1) % len(ring)]
    middle = ((before[0] + after[0]) / 2, (before[1] + after[1]) / 2)
    away = (corner["x"] - middle[0], corner["y"] - middle[1])
    # Every side of the part but the two the corner ends, which move with it.
    sides = [
        (points[i], points[(i + 1) % len(points)], key, i)
        for key, points in rings.items() for i in range(len(points))
        if not (key == corner["ring"] and i in (at, (at - 1) % len(ring)))
    ]
    for share in (0.6, -0.5):
        drop = (corner["x"] + share * away[0], corner["y"] + share * away[1])
        if math.hypot(drop[0] - corner["x"], drop[1] - corner["y"]) < 5:
            continue
        moved = [(before, drop), (drop, after)]
        if not any(
            _crosses(a, b, p, q) for a, b in moved for p, q, key, i in sides
            # A moved side meets its neighbouring sides at their shared corner.
            if not (key == corner["ring"] and (i == (at - 2) % len(ring) and a == before or i == (at + 1) % len(ring) and b == after))
        ):
            return drop
    return None


def _drops_crossing_shape(corner: dict, corners: list[dict]) -> list[tuple[float, float]]:
    """Where to drag *corner*, in page coordinates, so that a side it ends
    crosses another side of its part, as no drop of ``_drop_keeping_shape``
    does: past the middle of each side of its ring that it does not end, by
    half the way there from the corner, each drop kept when ``_crosses`` finds
    a moved side crossing another. No drop for a ring of fewer than four
    corners, where a corner dragged anywhere crosses no side."""
    rings: dict = {}
    indexes: dict = {}
    for c in sorted(corners, key=lambda c: c["index"]):
        if c["part"] == corner["part"]:
            rings.setdefault(c["ring"], []).append((c["x"], c["y"]))
            indexes.setdefault(c["ring"], []).append(c["index"])
    ring = rings.get(corner["ring"], [])
    if len(ring) < 4:
        return []
    at = indexes[corner["ring"]].index(corner["index"])
    before, after = ring[at - 1], ring[(at + 1) % len(ring)]
    # Every side of the part but the two the corner ends, which move with it.
    sides = [
        (points[i], points[(i + 1) % len(points)], key, i)
        for key, points in rings.items() for i in range(len(points))
        if not (key == corner["ring"] and i in (at, (at - 1) % len(ring)))
    ]
    drops = []
    for p, q, key, _i in sides:
        if key != corner["ring"]:
            continue
        middle = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        drop = (middle[0] + (middle[0] - corner["x"]) / 2, middle[1] + (middle[1] - corner["y"]) / 2)
        moved = [(before, drop), (drop, after)]
        if any(
            _crosses(a, b, s, t) for a, b in moved for s, t, k, j in sides
            # A moved side meets its neighbouring sides at their shared corner.
            if not (k == corner["ring"] and (j == (at - 2) % len(ring) and a == before or j == (at + 1) % len(ring) and b == after))
        ):
            drops.append(drop)
    return drops


def _on_the_map(page, map_id: str, point, box: dict, margin: float = 30) -> bool:
    """Whether *point*, in page coordinates, lies *margin* pixels inside the
    canvas of the map *map_id*, laid out at *box*, with nothing over the map
    there: neither its tip nor a button."""
    x, y = point
    inside = box["x"] + margin < x < box["x"] + box["width"] - margin and \
        box["y"] + margin < y < box["y"] + box["height"] - margin
    return inside and bool(page.evaluate(_SHOWN_JS, [_map(map_id), x, y]))


def _one_outline(rows: list[dict]) -> list[tuple[float, float]] | None:
    """The outline of a building of one row whose shape is one ring of four to
    eight corners, as Move points shows them, in its layer's units; None for
    any other building."""
    geometry = rows[0].get("geometry") if len(rows) == 1 else None
    if (geometry or {}).get("type") not in ("Polygon", "MultiPolygon"):
        return None
    rings = _rings_of(geometry)
    return rings[0] if len(rings) == 1 and 4 <= len(rings[0]) <= 8 else None


def _extent(points) -> tuple[float, float, float, float]:
    """The box around *points*: its least x and y, then its most."""
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _pick_near_the_middle(page, map_id: str, reshape, candidates: list, box: dict) -> tuple:
    """Pick each of the first eight *candidates*, buildings, on the map
    *map_id* in turn, as the map's own pick is sent, with Move points
    (*reshape*) on, until one sits near the middle of the map (*box*), in its
    middle three fifths both ways. Returns that building, or None, the corners
    Move points shows of the last one picked, and where each one tried sat."""
    corners: list[dict] = []
    tried = []
    for candidate in candidates[:8]:
        page.evaluate(_SEND_JS, [map_id, _map_pick(candidate)])
        _wait_for_lit(page, map_id, {candidate}, f"building {candidate} picked", table=BUILDINGS)
        if reshape.get_attribute("aria-checked") != "true":
            reshape.click()
            expect(reshape).to_have_attribute("aria-checked", "true")
        # The corners of this building, not of the one picked before.
        seen = [(c["x"], c["y"]) for c in corners]
        corners = _wait_for_corners(
            page, map_id, lambda now: bool(now) and [(c["x"], c["y"]) for c in now] != seen, f"building {candidate} picked",
        )
        x, y = _middle(corners)
        tried.append((candidate, round(x), round(y)))
        if box["x"] + 0.2 * box["width"] < x < box["x"] + 0.8 * box["width"] and \
                box["y"] + 0.2 * box["height"] < y < box["y"] + 0.8 * box["height"]:
            return candidate, corners, tried
    return None, corners, tried


def _compact(ring: list[tuple[float, float]]) -> bool:
    """Whether an outline, in its layer's units, is compact: its box on the
    ground at most twice as long as it is wide. A degree of longitude is
    shorter on the ground than one of latitude, by the cosine of the latitude."""
    x0, y0, x1, y1 = _extent(ring)
    degrees = all(abs(x) <= 180 and abs(y) <= 90 for x, y in ring)
    across = (x1 - x0) * (math.cos(math.radians((y0 + y1) / 2)) if degrees else 1.0)
    up = y1 - y0
    return min(across, up) > 0 and max(across, up) <= 2 * min(across, up)


def _fill(corners: list[dict], box: dict) -> float:
    """How much of the map, laid out at *box*, the box around *corners* spans:
    the larger of its width's share and its height's."""
    xs, ys = [c["x"] for c in corners], [c["y"] for c in corners]
    return max((max(xs) - min(xs)) / box["width"], (max(ys) - min(ys)) / box["height"])


def _handles_of(corners: list[dict]) -> list[tuple[float, float]]:
    """Where Move points shows a handle a press takes, in page coordinates:
    each corner, and the middle of each side between two corners of a ring."""
    rings: dict = {}
    for c in sorted(corners, key=lambda c: c["index"]):
        rings.setdefault((c["part"], c["ring"]), []).append((c["x"], c["y"]))
    points = [(c["x"], c["y"]) for c in corners]
    for ring in rings.values():
        points += [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(ring, ring[1:] + ring[:1])]
    return points


def _pan_start(page, map_id: str, corners: list[dict], box: dict, by: tuple[float, float]) -> tuple[float, float] | None:
    """Where a drag that pans the map *map_id* by *by* can start and end: on
    the map with nothing over it, the start at least 40 pixels from every
    handle Move points shows (*corners*), so the press takes none of them.
    The feature's own middle first, then the point of the map nearest its
    middle; None when no such point is."""
    clear = 40
    handles = _handles_of(corners)
    middle = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    grid = [(box["x"] + fx / 10 * box["width"], box["y"] + fy / 10 * box["height"]) for fx in range(2, 9) for fy in range(2, 9)]
    for start in [_middle(corners)] + sorted(grid, key=lambda p: math.hypot(p[0] - middle[0], p[1] - middle[1])):
        end = (start[0] + by[0], start[1] + by[1])
        if all(math.hypot(start[0] - hx, start[1] - hy) >= clear for hx, hy in handles) and \
                _on_the_map(page, map_id, start, box, clear) and _on_the_map(page, map_id, end, box, clear):
            return start
    return None


def _framed(page, map_id: str, corners: list[dict], box: dict) -> list[dict]:
    """Frame the feature whose corners Move points shows on the map *map_id*
    (*corners*) for its close-up: the map zoomed with the wheel at the
    feature's middle, in half steps, until the feature spans FRAME_FILL of the
    map (*box*), then panned, by drags clear of its handles, until its middle
    is near the map's. Returns its corners then."""
    low, high = FRAME_FILL
    # +1 while a negative wheel delta zooms in, as autk-map's does.
    sign = 1
    for step in range(4 * ZOOM_STEPS):
        fill = _fill(corners, box)
        if low <= fill <= high:
            break
        closer = fill < low
        page.mouse.move(*_middle(corners))
        page.mouse.wheel(0, sign * (-(ZOOM_DELTA // 2) if closer else ZOOM_DELTA // 2))
        page.wait_for_timeout(500)
        now = _wait_for_corners(page, map_id, bool, "a zoom of the map")
        if step == 0 and (_fill(now, box) > fill) != closer:
            # This wheel zooms the other way round.
            sign = -sign
        corners = now
    # A drag pans the map with the pointer, about: from a point clear of the
    # handles by the way from the feature's middle to the map's, again until
    # the two are near.
    middle = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(4):
        x, y = _middle(corners)
        by = (middle[0] - x, middle[1] - y)
        if abs(by[0]) <= 0.04 * box["width"] and abs(by[1]) <= 0.04 * box["height"]:
            break
        start = _pan_start(page, map_id, corners, box, by)
        if start is None:
            break
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(start[0] + by[0], start[1] + by[1], steps=12)
        page.mouse.up()
        page.wait_for_timeout(500)
        corners = _wait_for_corners(page, map_id, bool, "a pan of the map")
    return corners


def _browser_log(page) -> list[dict]:
    """Every console message and page error of *page* from now on, as the
    class pages of the workflow tests keep them, for ``dump_browser_log``."""
    log: list[dict] = []
    page.on("console", lambda message: log.append({"kind": "console", "type": message.type, "text": message.text}))
    page.on("pageerror", lambda error: log.append({"kind": "pageerror", "message": str(error)}))
    return log


def _failed_loads(log: list[dict]) -> list[str]:
    """What *log*, a browser log, says of layers that failed to load: the words
    autk-grammar logs when autk-db refuses a layer, as it refuses one with a
    shape that crosses itself."""
    texts = [entry.get("text") or entry.get("message") or "" for entry in log]
    return [text for text in texts if "Failed to load GeoJSON layer" in text]


def _within(corners: list[dict], box: dict, margin: float) -> bool:
    """Whether every one of *corners* lies *margin* pixels inside *box*."""
    return all(
        box["x"] + margin < c["x"] < box["x"] + box["width"] - margin
        and box["y"] + margin < c["y"] < box["y"] + box["height"] - margin
        for c in corners
    )


def _wait_for_corners(page, map_id: str, ready, what: str) -> list[dict]:
    """The corners Move points shows on the map *map_id*, once *ready* holds for them."""
    corners: list[dict] = []
    deadline = time.time() + 15
    while time.time() < deadline:
        corners = _corners(page, map_id)
        if ready(corners):
            return corners
        page.wait_for_timeout(250)
    raise AssertionError(f"after {what}, Move points shows the corners {corners} on the map {map_id}")


def _middle(corners: list[dict]) -> tuple[float, float]:
    """The middle of the box around *corners*, in page coordinates."""
    xs, ys = [c["x"] for c in corners], [c["y"] for c in corners]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def _spread(corners: list[dict]) -> float:
    """The longer side of the box around *corners*, in page pixels."""
    xs, ys = [c["x"] for c in corners], [c["y"] for c in corners]
    return max(max(xs) - min(xs), max(ys) - min(ys)) if xs else 0.0


def _room(corner: dict, corners: list[dict]) -> float:
    """How far, in page pixels, the nearest other corner lies from *corner*."""
    return min((math.hypot(c["x"] - corner["x"], c["y"] - corner["y"]) for c in corners if c is not corner), default=math.inf)


def _literal(value) -> str:
    """*value* as a node's condition writes it: a number as JavaScript writes it, a text in quotes."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)


def _shown_edit(edit: dict) -> dict:
    """An edit as a failure shows it: its shape left out."""
    return {name: value for name, value in edit.items() if name != "geometry"}


def _wait_for_count_of_edits(page, node_id: str, count: int, what: str) -> tuple[str, dict]:
    """Wait until the node's code holds *count* edits; returns the code and its keywords."""
    code, edits = "", None
    deadline = time.time() + 15
    while time.time() < deadline:
        code = read_node_code(page, node_id)
        try:
            edits, keywords = _edits_of(code)
        except (AssertionError, SyntaxError, ValueError):
            edits = None
        if edits is not None and len(edits) == count:
            return code, keywords
        page.wait_for_timeout(250)
    raise AssertionError(f"after {what}, the node's code holds the edits {edits}, not {count}:\n{code}")


def _fill_every_field(form) -> None:
    """Give each field of a new feature's form a value, so every required one
    is filled: a list's first choice, a group's first non-empty one, or a text."""
    fields = form.locator('[data-testid^="interaction-field-"]')
    for i in range(fields.count()):
        field = fields.nth(i)
        tag = field.evaluate("(el) => el.tagName.toLowerCase()")
        if tag == "select":
            values = field.locator("option").evaluate_all("(options) => options.map((o) => o.value)")
            choice = next((value for value in values if value and value != "__other__"), None)
            if choice is not None:
                field.select_option(choice)
        elif tag == "input":
            kind, mode = field.get_attribute("type"), field.get_attribute("inputmode")
            field.fill("2026-01-01" if kind == "date" else "1" if mode == "decimal" else "Test")
        else:
            radios = field.locator('input[type="radio"]')
            values = radios.evaluate_all("(inputs) => inputs.map((r) => r.value)")
            index = next((k for k, value in enumerate(values) if value), None)
            if index is not None:
                radios.nth(index).check()


# A pixel of an Autark node's map canvas where it draws something, in page
# coordinates: more than 20 off the map's background in some channel, with its
# eight neighbours drawn too when such a pixel exists, nearest *at* of the
# canvas, and shown there (nothing lies over it).
_DRAWN_POINT_JS = """async ({ id, at, background }) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    if (!canvas) return null;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    if (window.__curio_renderMapsForReading) await window.__curio_renderMapsForReading();
    const img = new Image();
    img.src = canvas.toDataURL('image/png');
    await img.decode();
    const w = img.width, h = img.height;
    const scratch = document.createElement('canvas');
    scratch.width = w;
    scratch.height = h;
    const ctx = scratch.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const px = ctx.getImageData(0, 0, w, h).data;
    const box = canvas.getBoundingClientRect();
    const sx = box.width / w, sy = box.height / h;
    const drawn = (x, y) => {
        if (x < 0 || y < 0 || x >= w || y >= h) return false;
        const i = (y * w + x) * 4;
        return px[i + 3] >= 250 && Math.max(Math.abs(px[i] - background[0]), Math.abs(px[i + 1] - background[1]),
            Math.abs(px[i + 2] - background[2])) > 20;
    };
    const solid = (x, y) => {
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) if (!drawn(x + dx, y + dy)) return false;
        return true;
    };
    const cx = at[0] * w, cy = at[1] * h;
    for (const inside of [solid, drawn]) {
        let best = null;
        for (let y = 0; y < h; y++) {
            for (let x = 0; x < w; x++) {
                if (!inside(x, y)) continue;
                const d = (x - cx) ** 2 + (y - cy) ** 2;
                if (best && d >= best.d) continue;
                const pageX = box.left + (x + 0.5) * sx, pageY = box.top + (y + 0.5) * sy;
                if (document.elementFromPoint(pageX, pageY) !== canvas) continue;
                best = { d, x: pageX, y: pageY };
            }
        }
        if (best) return { x: best.x, y: best.y };
    }
    return null;
}"""

# Each corner Move points shows, in page coordinates, as the map's overlay
# lists them (data-corners, in the map's own pixels, which its box scales to
# the page): its part (the row of the feature it is a corner of, null when
# the overlay names none), its ring and index in that part, whether its
# middle is well inside the map's canvas, room left for the drag (inside),
# with the map on top there (onTop) and drawing it in its highlight (lit),
# and all three (usable).
_CORNERS_JS = """async ({ id, highlight }) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const canvas = document.getElementById('autk-grammar-map-' + id);
    const overlay = node && node.querySelector('[data-testid="map-edit-overlay"]');
    if (!overlay || !canvas) return null;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    if (window.__curio_renderMapsForReading) await window.__curio_renderMapsForReading();
    const img = new Image();
    img.src = canvas.toDataURL('image/png');
    await img.decode();
    const scratch = document.createElement('canvas');
    scratch.width = img.width;
    scratch.height = img.height;
    const ctx = scratch.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const px = ctx.getImageData(0, 0, img.width, img.height).data;
    const area = canvas.getBoundingClientRect();
    const box = overlay.getBoundingClientRect();
    const sx = box.width / Number(overlay.getAttribute('data-map-width'));
    const sy = box.height / Number(overlay.getAttribute('data-map-height'));
    const lit = (x, y) => {
        const cx = Math.floor((x - area.left) * img.width / area.width);
        const cy = Math.floor((y - area.top) * img.height / area.height);
        if (cx < 0 || cy < 0 || cx >= img.width || cy >= img.height) return false;
        const i = (cy * img.width + cx) * 4;
        return px[i + 3] >= 250 && Math.max(Math.abs(px[i] - highlight[0]), Math.abs(px[i + 1] - highlight[1]),
            Math.abs(px[i + 2] - highlight[2])) <= 16;
    };
    return JSON.parse(overlay.getAttribute('data-corners') || '[]').map((corner) => {
        const x = box.left + corner.x * sx, y = box.top + corner.y * sy;
        const inside = x > area.left + 30 && x < area.right - 30 && y > area.top + 30 && y < area.bottom - 30;
        const onTop = document.elementFromPoint(x, y) === canvas;
        const shown = lit(x, y);
        return {
            part: corner.part === undefined ? null : corner.part, ring: corner.ring, index: corner.index, x, y,
            inside, onTop, lit: shown, usable: inside && onTop && shown,
        };
    });
}"""

# Where the corner *ring*, *index* is shown now, in page coordinates: of the
# part *part*, when it is given.
_HANDLE_AT_JS = """({ id, ring, index, part }) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const overlay = node && node.querySelector('[data-testid="map-edit-overlay"]');
    if (!overlay) return null;
    const corner = JSON.parse(overlay.getAttribute('data-corners') || '[]')
        .find((c) => c.ring === ring && c.index === index && (part === undefined || part === null || c.part === part));
    if (!corner) return null;
    const box = overlay.getBoundingClientRect();
    return {
        x: box.left + corner.x * box.width / Number(overlay.getAttribute('data-map-width')),
        y: box.top + corner.y * box.height / Number(overlay.getAttribute('data-map-height')),
    };
}"""


def _corners(page, map_id: str) -> list[dict]:
    """Every corner Move points shows on the map *map_id* now (``_CORNERS_JS``)."""
    return page.evaluate(_CORNERS_JS, {"id": map_id, "highlight": list(MAP_HIGHLIGHT)}) or []


def _corner_to_drag(page, map_id: str) -> dict | None:
    """A corner of the feature Move points shows on the map *map_id* to drag:
    the first a press can take, once the map draws one, or None after 10 s."""
    deadline = time.time() + 10
    while True:
        handle = next((corner for corner in _corners(page, map_id) if corner["usable"]), None)
        if handle or time.time() >= deadline:
            return handle
        page.wait_for_timeout(250)


def _handed_layers(stored: dict) -> dict:
    """The layers a node's output holds, by name: each a FeatureCollection."""
    payload = stored
    while isinstance(payload, dict) and payload.get("dataType") != "outputs" and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    assert isinstance(payload, dict) and payload.get("dataType") == "outputs", f"not a node's layers: {str(stored)[:300]}"
    out = {}
    for item in payload["data"]:
        data = item.get("data")
        if isinstance(data, str):
            data = json.loads(data)
        out[item.get("layerName")] = data
    return out


def _coordinates(geometry: dict) -> list[float]:
    """Every number of a GeoJSON geometry's coordinates, in order."""
    flat: list[float] = []

    def walk(value):
        if isinstance(value, (int, float)):
            flat.append(float(value))
        else:
            for item in value:
                walk(item)

    walk(geometry.get("coordinates") or [])
    return flat


def _assert_same_shape(handed: dict, drawn: dict, what: str) -> None:
    """*handed*, a shape a run handed on, is *drawn*, the shape the node's code holds."""
    a, b = _coordinates(handed), _coordinates(drawn)
    assert handed.get("type", "").replace("Multi", "") == drawn.get("type", "").replace("Multi", ""), (handed, drawn)
    assert len(a) == len(b) and all(math.isfinite(v) for v in a), (
        f"the run handed {what} on as {handed}, not as drawn on the map: {drawn}"
    )
    assert all(math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-6) for x, y in zip(a, b)), (
        f"the run handed {what} on at {a[:4]}..., not where it was drawn on the map: {b[:4]}..."
    )


#: A building of the Chicago Loop layers in seven parts, each with an
#: ``osm_id`` of its own, near the middle of the map.
PARTED_BUILDING = 20449794
#: The column Autark tags each OSM feature with, naming the layer it came
#: from: no property of the feature, so the node's form leaves it out (#1122).
AUTARK_LAYER = "__autk_layer"


def test_a_chicago_building_of_several_parts_takes_a_height_on_one_part_chosen_in_its_form(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The shipped Chicago Loop layers: building 20449794, of seven parts,
    each with an ``osm_id`` of its own, picked on the map in the node's Edit.

    1. Its form is for all its parts: a height they differ in is empty, with
       a note that lists their heights, and osm_id cannot be changed.
    2. Its parts menu offers all the parts, then each part by its osm_id. A
       part after the first, of another height, chosen there: the field shows
       that part's height, the map still lights the whole building, and a
       height typed and applied is one edit that names that part alone,
       ``where building_id == <building> and osm_id == <part>``.
    3. Commit edits runs the node, which hands that part on with the new
       height and the building's other parts with their own.

    What is wrong at each step is kept, and the test fails with all of it
    before its capture: the node's body, without its header, scrolled to the
    building's properties, its parts menu on all of them."""
    test_name = "test_a_chicago_building_of_several_parts_takes_a_height_on_one_part_chosen_in_its_form"
    path = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-loop-layers.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    (edit_id,) = [n for n, node in nodes.items() if node["type"] == EDIT_TYPE]
    (map_id,) = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and '"map"' in node["content"]]
    title = nodes[map_id]["title"]
    _enter(page, app_frontend, current_server, spec, "map_edits_parts_form_e2e", name=spec["dataflow"]["name"])
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node in nodes.items():
        _done(page, node_id, node["type"])
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)

    # The building's parts as the node hands them on before any edit, in the
    # layer's order, and the rows of it the map draws, which it lights.
    building = PARTED_BUILDING
    handed = _handed_layers(load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, edit_id)))
    rows = [row for row in handed[BUILDINGS]["features"] if (row.get("properties") or {}).get(KEY) == building]
    assert _told_apart(rows), (
        f"the node hands on {len(rows)} rows of building {building}, not two parts or more, each with a shape and "
        f"an {PART_KEY} of its own"
    )
    parts = [(row.get("properties") or {}).get(PART_KEY) for row in rows]
    heights = [(row.get("properties") or {}).get("height") for row in rows]
    drawn = page.evaluate(_DRAWN_PARTS_JS, {"id": map_id, "table": BUILDINGS, "key": KEY, "part": PART_KEY}) or []
    lit_rows = [building] * sum(1 for key, _part in drawn if key == building)
    assert len(lit_rows) >= 2, f"the map draws {len(lit_rows)} rows of building {building}, not two parts or more"
    # The part chosen: the first after the first part whose height differs
    # from the first part's, else the last; the height it is given, none of
    # its parts' heights.
    chosen = next((i for i in range(1, len(rows)) if not _same_number(heights[i], heights[0])), len(rows) - 1)
    part_id = parts[chosen]
    part = _as_text(part_id)
    where = f"{KEY} == {_literal(building)} and {PART_KEY} == {_literal(part_id)}"
    new_height = NEW_HEIGHT
    while any(_same_number(new_height, height) for height in heights):
        new_height += 1
    every = f"All {len(rows)} parts"

    edit = node_locator(page, edit_id)
    frame_nodes(page, [edit_id, map_id])
    _open_tab(page, edit_id, "output")
    _assert_linked(page, edit_id, map_id, title)
    expect(edit.get_by_test_id(f"interaction-layer-{BUILDINGS}")).to_be_attached(timeout=30000)
    _open(page, edit_id, "edit", BUILDINGS)
    page.evaluate(_SEND_JS, [map_id, _map_pick(building)])
    _wait_for_lit(page, map_id, {building}, f"building {building} picked", table=BUILDINGS)
    field = edit.get_by_test_id("interaction-field-height")
    expect(field).to_be_attached(timeout=10000)
    wait_for_node_still(page, edit_id)
    menu = edit.get_by_test_id("interaction-parts-menu")
    wrong: list[str] = []

    def text_of(test_id: str) -> str | None:
        """The words of the node's element *test_id*, or None when it shows none."""
        found = edit.get_by_test_id(test_id)
        return (found.first.text_content() or "").strip() if found.count() else None

    # 1. The form is for all its parts: a height they differ in is empty, with
    # a note that lists their heights, and osm_id cannot be changed.
    if len(set(heights)) > 1:
        shown = field.input_value()
        if shown != "":
            wrong.append(
                f"the form shows the height {shown}, building {building}'s first part's, as the building's: its "
                f"{len(rows)} parts are {', '.join(_as_text(height) for height in heights)} m tall"
            )
        listed = text_of("interaction-mixed-height")
        if not re.match(rf"{len(set(heights))} values: ", listed or ""):
            wrong.append(
                f"no note beside the height lists the {len(set(heights))} heights of building {building}'s parts: "
                f"it reads {listed!r}"
            )
    if edit.get_by_test_id(f"interaction-field-{PART_KEY}").count():
        wrong.append(
            f"{PART_KEY}, which tells the parts apart, is a field a value can be typed into, showing the first part's"
        )
    fixed = text_of(f"interaction-fixed-{PART_KEY}")
    if fixed != f"{len(rows)} values, cannot be changed":
        wrong.append(f"beside {PART_KEY}, the form reads {fixed!r}, not '{len(rows)} values, cannot be changed'")
    # Autark's own column, naming the layer each OSM feature came from, is no
    # property of the building: the form has no row for it (#1122).
    autark_rows = [
        kind for kind in ("field", "fixed", "mixed") if edit.get_by_test_id(f"interaction-{kind}-{AUTARK_LAYER}").count()
    ]
    if autark_rows:
        carried = any(AUTARK_LAYER in (row.get("properties") or {}) for row in rows)
        where_from = ", which the building's parts carry" if carried else ""
        wrong.append(
            f"the form of building {building} has a row for {AUTARK_LAYER} (its {', '.join(autark_rows)}), the column "
            f"Autark names each feature's layer by{where_from}"
        )

    # 2. The parts menu, on all the parts; one part chosen in it.
    if not menu.count():
        wrong.append(
            f"there is no parts menu: the form of building {building}, of {len(rows)} parts, works on its first "
            f"part, {PART_KEY} {_as_text(parts[0])}, alone, and a value typed in it goes to every part"
        )
    else:
        labels = menu.locator("option").evaluate_all("(options) => options.map((o) => o.textContent)")
        named = [re.compile(rf"^{PART_KEY} {re.escape(_as_text(osm))}(,|$)") for osm in parts]
        if labels[:1] != [every] or len(labels) != len(rows) + 1 or not all(
            pattern.match(label or "") for pattern, label in zip(named, labels[1:])
        ):
            wrong.append(f"the parts menu offers {labels}, not {every!r} and then each part by its {PART_KEY}: {parts}")
        selected = menu.evaluate("(menu) => (menu.selectedOptions[0] ? menu.selectedOptions[0].textContent : null)")
        if selected != every:
            wrong.append(f"the parts menu opens on {selected!r}, not {every!r}")
        label = next((label for label in labels if named[chosen].match(label or "")), None)
        if label is None:
            wrong.append(f"the parts menu offers no option for part {part}: {labels}")
        else:
            menu.select_option(label=label)
            shown = _wait_for_field(field, heights[chosen])
            if not _shows(shown, heights[chosen]):
                wrong.append(
                    f"with part {part} chosen in the parts menu, the height field shows {shown!r}, not that part's "
                    f"{_as_text(heights[chosen])}"
                )
            fixed = text_of(f"interaction-fixed-{PART_KEY}")
            if fixed != f"{part}, cannot be changed":
                wrong.append(
                    f"with part {part} chosen, the form reads {fixed!r} beside {PART_KEY}, not '{part}, cannot be changed'"
                )
            try:
                _wait_for_lit(page, map_id, lit_rows, f"part {part} of building {building} chosen", table=BUILDINGS)
            except AssertionError as error:
                wrong.append(f"with one part chosen, the map no longer lights the whole building: {error}")

    # A height typed and applied: one edit, of that part alone.
    keep_drawing(page, _map(map_id))
    field.fill(str(new_height))
    submit = edit.get_by_test_id("interaction-form-submit")
    expect(submit).to_be_enabled()
    submit.click()
    code, keywords = _wait_for_count_of_edits(
        page, edit_id, 1, f"a height of {new_height} applied to building {building}",
    )
    (applied,) = _edits_of(code)[0]
    expected = {"op": "set", "ids": None, "where": where, "column": "height", "value": new_height}
    if {name: applied.get(name) for name in expected} != expected:
        why = f": a set by {KEY} {building} goes to every one of its {len(rows)} parts" if applied.get("ids") else ""
        wrong.append(f"Apply wrote {applied}, not a set of the height where {where}{why}")
    if (keywords.get("layer"), keywords.get("key")) != (BUILDINGS, KEY):
        wrong.append(f"the node's code names the layer {keywords.get('layer')} and the key {keywords.get('key')}")
    try:
        expect(edit.locator('[data-edit-op="set"]')).to_contain_text(
            f"Set height to {new_height} where {where}", timeout=5000,
        )
    except AssertionError as error:
        wrong.append(f"the list does not name the part: {error}")
    _wait_for_redraw(page, map_id, "the Apply")

    # 3. Commit edits: the node hands that part on with the new height, and
    # the building's other parts with their own.
    _commit(page, edit_id, [edit_id], [map_id], below=1)
    out = _handed_layers(load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, edit_id)))[BUILDINGS]["features"]
    now = {
        (row.get("properties") or {}).get(PART_KEY): (row.get("properties") or {}).get("height")
        for row in out if (row.get("properties") or {}).get(KEY) == building
    }
    if sorted(map(str, now)) != sorted(map(str, parts)):
        wrong.append(f"Commit edits handed on the parts {sorted(map(str, now))} of building {building}, not {parts}")
    if not _same_number(now.get(part_id), new_height):
        wrong.append(
            f"after Commit edits, part {part} of building {building} is {now.get(part_id)} m tall, not the "
            f"{new_height} typed for it"
        )
    others = [
        f"part {_as_text(osm)} is {_as_text(now.get(osm))} m tall, not its own {_as_text(height)}"
        for osm, height in zip(parts, heights)
        if osm != part_id and osm in now and not _same_number(now.get(osm), height)
    ]
    if others:
        wrong.append(
            f"after Commit edits, the height typed for part {part} went to other parts of building {building} "
            f"too: {'; '.join(others)}"
        )
    assert not wrong, "\n".join(wrong)

    # The building picked again, since the map's run dropped the pick, and its
    # form on all its parts, as the node's body shows it without the node's
    # header, scrolled to the building's properties.
    for _ in range(3):
        page.evaluate(_SEND_JS, [map_id, _map_pick(building)])
        _wait_for_lit(page, map_id, {building}, f"building {building} picked after Commit edits", table=BUILDINGS)
        try:
            expect(menu).to_be_visible(timeout=5000)
            break
        except AssertionError:
            continue
    expect(menu).to_be_visible(timeout=5000)
    menu.select_option(label=every)
    # The part given a height of its own, the parts differ in height.
    expect(field).to_have_value("")
    wait_for_node_still(page, edit_id)
    with canvas_painted_at_shown_zoom(page):
        frame_nodes(page, [edit_id])
        assert page.evaluate(_PROPERTIES_ON_TOP_JS, edit_id), (
            f"the node {edit_id} shows no properties of building {building}"
        )
        park_pointer(page)
        save_workflow_test_screenshot(
            page, CHICAGO_STEM, test_name=f"{test_name}_closeup_{edit_id}",
            pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
            clip_selector=f'[data-edit-body="{edit_id}"]', fit_reactflow=False, sweep_toasts=True, closeup=True,
        )


def _as_text(value) -> str:
    """*value* as a form shows it: a number as JavaScript writes it, a text as it is."""
    return value if isinstance(value, str) else _literal(value)


def _same_number(a, b) -> bool:
    """Whether *a* and *b* are one value: both none, or the same number."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    except (TypeError, ValueError):
        return a == b


def _shows(text: str, value) -> bool:
    """Whether a field's *text* shows *value*: empty for none, else the same number or text."""
    if value is None or text == "":
        return value is None and text == ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _same_number(text, value)
    return text == _as_text(value)


def _wait_for_field(field, value, timeout_s: float = 5) -> str:
    """What the field *field* shows, once it shows *value*, or after *timeout_s* seconds."""
    deadline = time.time() + timeout_s
    while True:
        text = field.input_value()
        if _shows(text, value) or time.time() >= deadline:
            return text
        field.page.wait_for_timeout(250)


# Scrolls the body of the Map Editor node *id* until the properties of the
# feature its form edits are at the body's top, so a capture of the body
# starts with them; false when the body shows none.
_PROPERTIES_ON_TOP_JS = """(id) => {
    const body = document.querySelector(`[data-edit-body="${id}"]`);
    const properties = body && body.querySelector('[data-testid="interaction-properties"]');
    if (!properties) return false;
    const box = body.getBoundingClientRect();
    const scale = body.offsetHeight > 0 ? box.height / body.offsetHeight : 1;
    body.scrollTop += (properties.getBoundingClientRect().top - box.top) / scale;
    return true;
}"""
