"""Playwright E2E: an Autark map's ``camera`` tilts and turns the view the node
frames it at, and the map's R key gives that view again.

One loader feeds two maps of a 10 x 10 grid of cells, in nodes of one size: one
as the node frames it, straight down on the middle of the grid, and one whose
document writes ``"camera": {"pitch": 50, "bearing": 30}``. The tilted map
draws, and its picture is not the framed one's. Its camera, read through
``window.__curio_mapViews``, looks at the point the framed map looks at, from as
far as the framed map's eye is high, 50 degrees from straight down, facing 30
degrees east of north, with that heading up the screen and its up direction
across its line of sight. A drag pans it; the R key puts it back at that view,
and R again leaves it there. A map whose camera writes ``"pitch": 90``, which
would stand its eye on the ground, fails with autk-grammar's own sentence.

The maps need WebGPU, so this test runs on CI's GPU job and fails without an
adapter.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_camera_e2e.py -v
"""

from __future__ import annotations

import base64
import json
import math
import time
from io import BytesIO
from typing import TYPE_CHECKING

from .utils import (
    assert_autark_map_drawn,
    changed_pixels,
    frame_nodes,
    node_locator,
    park_pointer,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
    webgpu_adapter,
)
from .utils.node_drawings import _AUTK_MAP_PIXELS_IN_FRAME_JS, true_up

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER = "camera-loader"
FRAMED = "camera-framed"
TILTED = "camera-tilted"
PITCH = 50
BEARING = 30

# A 10 x 10 grid of cells over Chicago, each with its own value, so a map of it
# draws many colours.
GRID_LOADER = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "\n"
    "cells, pop = [], []\n"
    "for i in range(10):\n"
    "    for j in range(10):\n"
    "        x, y = -87.70 + 0.006 * i, 41.86 + 0.006 * j\n"
    "        cells.append(box(x, y, x + 0.005, y + 0.005))\n"
    "        pop.append(i * 10 + j)\n"
    'return gpd.GeoDataFrame({"pop": pop}, geometry=cells, crs="EPSG:4326")\n'
)
LAYER = {
    "dataRef": "input_0",
    "getFnv": "pop",
    "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateViridis",
}
FRAMED_MAP = json.dumps({"map": {"layerRefs": [LAYER]}}, indent=2)
TILTED_MAP = json.dumps({"map": {"camera": {"pitch": PITCH, "bearing": BEARING}, "layerRefs": [LAYER]}}, indent=2)

#: Two views are one when their numbers agree to this share of the eye's
#: distance from the point it looks at. autk-map keeps its camera's points in
#: 32-bit floats, rounded to about 1e-7 of their size.
SAME_VIEW = 1e-5
#: Two angles agree to this many degrees: a 32-bit eye turns its angles by a
#: few millionths of a degree.
SAME_ANGLE = 1e-3
#: An up vector's numbers agree to this.
SAME_UP = 1e-6
#: A pixel counts as changed when a channel moves by more than this.
PIXEL_THRESHOLD = 8
#: The tilted map's picture differs from the framed one's on more than this
#: share of the canvas.
TURNED_SHARE = 0.2

# The view of each map an Autark node drew, as Curio reads it
# (adapters/node/autkMapView's mapViews), and its canvas's layout size.
_VIEWS_JS = """(id) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    const hook = typeof window.__curio_mapViews === 'function';
    return {
        hook,
        views: hook ? window.__curio_mapViews(id) : null,
        canvas: canvas ? [canvas.offsetWidth, canvas.offsetHeight] : null,
    };
}"""

# Whether the point is on the map's canvas, as the page hit-tests it now.
_ON_MAP_JS = """({ id, x, y }) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    return !!canvas && document.elementFromPoint(x, y) === canvas;
}"""


def _spec() -> dict:
    """The loader above left of the two maps it feeds, one above the other."""
    node = lambda node_id, node_type, x, y, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    edge = lambda target: {  # noqa: E731
        "id": f"e-{LOADER}-{target}", "source": LOADER, "target": target,
        "sourceHandle": "out", "targetHandle": "in",
    }
    return {
        "dataflow": {
            "name": "Map camera",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Map camera",
            "nodes": [
                node(LOADER, "curio.builtin/data-loading", 0, 0, GRID_LOADER),
                node(FRAMED, "curio.builtin/autk-grammar", 700, 0, FRAMED_MAP),
                node(TILTED, "curio.builtin/autk-grammar", 700, 800, TILTED_MAP),
            ],
            "edges": [edge(FRAMED), edge(TILTED)],
        }
    }


def _open_with_both_maps_drawn(page, app_frontend, current_server, *, username: str) -> None:
    """Open the dataflow, draw both maps and frame them."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Map Camera",
        username=username,
        project_name="Map camera",
        project_spec=_spec(),
    )
    require_owner_view(page)
    for node_id in (LOADER, FRAMED, TILTED):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    adapter = webgpu_adapter(page)
    assert adapter, f"drawing an Autark map needs a WebGPU adapter, which CI's GPU job has: {adapter}"

    run_node_and_wait(page, LOADER, node_type="DATA_LOADING", timeout_ms=120000)
    for map_id in (FRAMED, TILTED):
        play_node(page, map_id)
        status = wait_for_node_settled(page, map_id, node_type="autk-grammar", timeout_ms=120000)
        detail = read_node_error_text(node_locator(page, map_id)) if status == "error" else ""
        assert status == "done", f"the map {map_id} did not draw: {detail}"
        assert_autark_map_drawn(page, map_id)
    frame_nodes(page, [FRAMED, TILTED])


def _read(page, map_id: str) -> dict:
    read = page.evaluate(_VIEWS_JS, map_id)
    assert read["hook"], "the page has no window.__curio_mapViews to read a map's view through"
    return read


def _view_when(page, map_id: str, holds, what: str, *, timeout_ms: float = 30000) -> tuple[dict, list]:
    """The view of the one map *map_id* drew once *holds* is true of it, and its
    canvas's layout size; fails naming *what* when it is not within the wait."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        read = _read(page, map_id)
        views = read["views"] or []
        view = views[0] if len(views) == 1 else None
        if view is not None and holds(view):
            return view, read["canvas"]
        assert time.monotonic() < deadline, f"{what}: Autark node {map_id}'s views are {views} after {timeout_ms} ms"
        page.wait_for_timeout(250)


def _angles(view: dict) -> tuple[float, float, float]:
    """How far the eye is from the point it looks at, and its pitch from
    straight down and its bearing clockwise from north, in degrees."""
    eye, look = view["eye"], view["lookAt"]
    dx, dy, dz = look[0] - eye[0], look[1] - eye[1], look[2] - eye[2]
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    pitch = math.degrees(math.acos(max(-1.0, min(1.0, -dz / distance))))
    bearing = math.degrees(math.atan2(dx, dy)) % 360
    return distance, pitch, bearing


def _apart(a: list, b: list) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def _same_view(a: dict, b: dict) -> bool:
    scale = max(_angles(b)[0], 1.0)
    return all(_apart(a[key], b[key]) <= SAME_VIEW * scale for key in ("eye", "lookAt")) and (
        _apart(a["up"], b["up"]) <= SAME_UP
    )


def _pixels(page, map_id: str):
    from PIL import Image

    url = page.evaluate(_AUTK_MAP_PIXELS_IN_FRAME_JS, map_id)
    assert url, f"Autark node {map_id} has no map canvas"
    return Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def _point_on_map(page, map_id: str) -> tuple[float, float]:
    """A point of the map's canvas that nothing covers, its middle if it can."""
    box = page.locator(f"#autk-grammar-map-{map_id}").bounding_box()
    assert box, f"Autark node {map_id}'s canvas has no layout box"
    for fx, fy in ((0.5, 0.5), (0.3, 0.3), (0.7, 0.3), (0.3, 0.7), (0.7, 0.7)):
        x, y = box["x"] + fx * box["width"], box["y"] + fy * box["height"]
        if page.evaluate(_ON_MAP_JS, {"id": map_id, "x": x, "y": y}):
            return x, y
    raise AssertionError(f"nothing of Autark node {map_id}'s canvas at {box} can be pressed")


def test_a_maps_camera_tilts_and_turns_its_framed_view_and_the_r_key_gives_it_again(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open_with_both_maps_drawn(page, app_frontend, current_server, username="autark_map_camera")

    # The framed map looks straight down, north up the screen.
    framed, framed_canvas = _view_when(
        page, FRAMED, lambda view: _apart(view["eye"][:2], view["lookAt"][:2]) <= SAME_VIEW * view["eye"][2],
        "the map without a camera never looked straight down",
    )
    high = framed["eye"][2] - framed["lookAt"][2]
    assert high > 0 and _apart(framed["up"], [0, 1, 0]) <= SAME_UP, f"the framed map's view is {framed}"

    # The tilted one: the same point, as far away, at the camera's angles.
    tilted, tilted_canvas = _view_when(
        page, TILTED, lambda view: abs(_angles(view)[1] - PITCH) <= SAME_ANGLE,
        f"the map with a camera never stood {PITCH} degrees from straight down",
    )
    assert tilted_canvas == framed_canvas, (
        f"the two maps' canvases are {tilted_canvas} and {framed_canvas}: one framing needs one size"
    )
    distance, pitch, bearing = _angles(tilted)
    problems = []
    if _apart(tilted["lookAt"], framed["lookAt"]) > SAME_VIEW * high:
        problems.append(f"it looks at {tilted['lookAt']}, the framed map at {framed['lookAt']}")
    if abs(distance - high) > SAME_VIEW * high:
        problems.append(f"its eye is {distance} from where it looks, the framed map's {high} above it")
    if abs(pitch - PITCH) > SAME_ANGLE or abs(bearing - BEARING) > SAME_ANGLE:
        problems.append(f"it stands {pitch} degrees from straight down facing {bearing}, not {PITCH} facing {BEARING}")
    # Its up direction lies across its line of sight, toward the far side of
    # the view, facing the camera's heading, as autk-map's own tilt leaves it.
    if _apart(tilted["up"], true_up(PITCH, BEARING)) > SAME_UP:
        problems.append(f"its up is {tilted['up']}, not {true_up(PITCH, BEARING)}, across its line of sight "
                        f"facing the heading {BEARING} degrees east of north")
    assert not problems, "the map's camera did not turn its framed view:\n- " + "\n- ".join(problems)

    # It draws, and not the framed map's picture.
    park_pointer(page)
    straight_down, tilted_picture = _pixels(page, FRAMED), _pixels(page, TILTED)
    assert straight_down.size == tilted_picture.size, (
        f"the two maps' canvases hold {straight_down.size} and {tilted_picture.size} pixels"
    )
    turned_share = changed_pixels(straight_down, tilted_picture, threshold=PIXEL_THRESHOLD) / (
        tilted_picture.width * tilted_picture.height
    )
    assert turned_share > TURNED_SHARE, (
        f"the tilted map's picture differs from the framed one's on {turned_share:.2%} of it: "
        "its camera did not change what it draws"
    )

    # A drag pans it; R puts it back at its camera's view, and R again leaves it there.
    canvas = page.locator(f"#autk-grammar-map-{TILTED}")
    x, y = _point_on_map(page, TILTED)
    page.mouse.move(x, y)
    page.mouse.down()
    for step in range(1, 9):
        page.mouse.move(x + 8 * step, y + 5 * step)
        page.wait_for_timeout(20)
    page.mouse.up()
    _view_when(page, TILTED, lambda view: not _same_view(view, tilted), "a drag on the map did not pan it")
    canvas.press("r")
    back, _ = _view_when(
        page, TILTED, lambda view: _same_view(view, tilted), "the R key did not give the camera's view again",
    )
    canvas.press("r")
    again, _ = _view_when(page, TILTED, lambda view: True, "the map lost its view")
    assert _same_view(again, back), f"a second R moved the map from {back} to {again}"
    assert_autark_map_drawn(page, TILTED)


#: A map whose camera stands its eye on the ground, edge-on to the flat layers.
EDGE_ON = "camera-edge-on"
EDGE_ON_MAP = json.dumps({"map": {"camera": {"pitch": 90, "bearing": BEARING}, "layerRefs": [LAYER]}}, indent=2)
#: What autk-grammar says of that camera, as its run refuses it before the map is made.
EDGE_ON_REFUSAL = (
    "camera.pitch must be at least 0 and less than 90 degrees, not 90: at 90 the eye would sit on the ground, "
    "edge-on to the map's flat layers, and the map could not pan."
)


def test_a_map_whose_camera_pitch_is_90_fails_with_the_grammars_sentence_and_draws_nothing(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """``"pitch": 90`` puts the eye on the ground: autk-grammar refuses it
    before it makes the map, and the node fails with its sentence, where the
    map was drawn edge-on, showing nothing, under a green Done."""
    require_project_page()
    require_user_auth()
    spec = _spec()
    spec["dataflow"]["name"] = spec["dataflow"]["provenance_id"] = "Map camera edge-on"
    spec["dataflow"]["nodes"] = [
        node for node in spec["dataflow"]["nodes"] if node["id"] == LOADER
    ] + [{
        "id": EDGE_ON, "type": "curio.builtin/autk-grammar", "x": 700, "y": 0, "content": EDGE_ON_MAP,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }]
    spec["dataflow"]["edges"] = [{
        "id": f"e-{LOADER}-{EDGE_ON}", "source": LOADER, "target": EDGE_ON,
        "sourceHandle": "out", "targetHandle": "in",
    }]
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Map Camera Edge-on",
        username="autark_map_camera_edge_on",
        project_name="Map camera edge-on",
        project_spec=spec,
    )
    require_owner_view(page)
    for node_id in (LOADER, EDGE_ON):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    adapter = webgpu_adapter(page)
    assert adapter, f"drawing an Autark map needs a WebGPU adapter, which CI's GPU job has: {adapter}"

    run_node_and_wait(page, LOADER, node_type="DATA_LOADING", timeout_ms=120000)
    play_node(page, EDGE_ON)
    status = wait_for_node_settled(page, EDGE_ON, node_type="autk-grammar", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, EDGE_ON)) or ""
    assert status == "error", f"the map with a camera pitch of 90 ran: {status} {detail}"
    assert EDGE_ON_REFUSAL in detail, f"the map with a camera pitch of 90 failed with {detail!r}, not the grammar's sentence"
