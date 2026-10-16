"""Playwright E2E: a drag that only passes over an Autark map leaves the map's view.

autk-map pans its camera when the pointer moves over its canvas with a button
held, wherever the press began. So an edge drawn across a map, a node dragged
across one and a selection box drawn over one all moved the map (found by the
feature tour, #938). A drag that begins on the map still pans it.

Each test draws a 10 x 10 grid on a map, reads the map's canvas in the frame
that renders it, makes its drag across the map and reads the canvas again: the
same pixels. Then a drag that begins on the map moves them, which shows the
canvas takes the pointer again once the press across it ends.

The map needs WebGPU, so these tests run on CI's GPU job and fail without an
adapter.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_map_drags_e2e.py -v
"""

from __future__ import annotations

import base64
import json
import time
from io import BytesIO
from typing import TYPE_CHECKING

import allure

from .utils import (
    assert_autark_map_drawn,
    changed_pixels,
    connect_nodes,
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
from .utils.node_drawings import _AUTK_MAP_PIXELS_IN_FRAME_JS

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER = "drags-loader"
MAP = "drags-map"
CODE = "drags-code"

# A 10 x 10 grid of cells, each with its own value: a map that a pan changes
# nearly everywhere.
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
MAP_ON_INPUT = json.dumps({"map": {"layerRefs": [{"dataRef": "input_0"}]}}, indent=2)

#: A pixel counts as changed when a channel moves by more than this.
PIXEL_THRESHOLD = 8
#: At most this share of the map changes between two reads of a map at rest.
STILL_SHARE = 0.002
#: A pan changes more than this share of the map.
PANNED_SHARE = 0.05

#: The empty pane below left of the map and above right of it, in canvas
#: units: a box drawn from one to the other crosses the map.
BOX_FROM, BOX_TO = (350, 900), (1450, 300)

# Whether each point is on the map's canvas: what a press or a move there would
# reach, as the page hit-tests it now.
_ON_MAP_JS = """({ id, points }) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    return points.map(([x, y]) => !!canvas && document.elementFromPoint(x, y) === canvas);
}"""

# Whether the point is on the empty pane, clear of every node.
_ON_PANE_JS = """([x, y]) => {
    const hit = document.elementFromPoint(x, y);
    return !!hit && !!hit.closest('.react-flow__pane') && !hit.closest('.react-flow__node');
}"""


def _spec() -> dict:
    """The loader above left of the map, which it feeds, and a Python node below
    right of it. An edge from the loader to the Python node crosses the map, and
    so does the Python node dragged across it to its left."""
    node = lambda node_id, node_type, x, y, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    return {
        "dataflow": {
            "name": "Map drags",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Map drags",
            "nodes": [
                node(LOADER, "curio.builtin/data-loading", 0, 0, GRID_LOADER),
                node(MAP, "curio.builtin/autk-grammar", 645, 400, MAP_ON_INPUT),
                node(CODE, "curio.builtin/computation-analysis", 1290, 800, ""),
            ],
            "edges": [{
                "id": f"reactflow__edge-{LOADER}out-{MAP}in",
                "source": LOADER,
                "target": MAP,
            }],
        }
    }


def _open_with_the_map_drawn(page, app_frontend, current_server, *, username: str) -> None:
    """Open the dataflow, draw the grid on the map and frame the three nodes."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Map Drags",
        username=username,
        project_name="Map drags",
        project_spec=_spec(),
    )
    require_owner_view(page)
    for node_id in (LOADER, MAP, CODE):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    adapter = webgpu_adapter(page)
    assert adapter, f"drawing an Autark map needs a WebGPU adapter, which CI's GPU job has: {adapter}"

    run_node_and_wait(page, LOADER, node_type="DATA_LOADING", timeout_ms=120000)
    play_node(page, MAP)
    status = wait_for_node_settled(page, MAP, node_type="autk-grammar", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, MAP)) if status == "error" else ""
    assert status == "done", f"the map did not draw: {detail}"
    assert_autark_map_drawn(page, MAP)
    frame_nodes(page, [LOADER, MAP, CODE])


def _map_pixels(page):
    from PIL import Image

    url = page.evaluate(_AUTK_MAP_PIXELS_IN_FRAME_JS, MAP)
    assert url, f"Autark node {MAP} has no map canvas"
    return Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def _changed_share(before, after) -> float:
    return changed_pixels(before, after, threshold=PIXEL_THRESHOLD) / (after.width * after.height)


def _map_at_rest(page, moment: str, *, timeout: float = 15000):
    """The map's pixels once two reads 300 ms apart agree, read with the
    pointer parked off the map."""
    park_pointer(page)
    previous = _map_pixels(page)
    deadline = time.monotonic() + timeout / 1000
    while True:
        page.wait_for_timeout(300)
        current = _map_pixels(page)
        share = _changed_share(previous, current)
        if share <= STILL_SHARE:
            break
        assert time.monotonic() < deadline, (
            f"the map did not come to rest {moment}: {share:.2%} of it changed between two reads"
        )
        previous = current
    buffer = BytesIO()
    current.save(buffer, format="PNG")
    allure.attach(buffer.getvalue(), name=f"the map {moment}", attachment_type=allure.attachment_type.PNG)
    return current


def _on_map(page, points) -> list[bool]:
    return page.evaluate(_ON_MAP_JS, {"id": MAP, "points": [list(point) for point in points]})


def _steps(start, end, steps: int) -> list[tuple[float, float]]:
    """Where ``page.mouse.move(*end, steps=steps)`` from *start* sends the pointer."""
    return [
        (start[0] + (end[0] - start[0]) * i / steps, start[1] + (end[1] - start[1]) * i / steps)
        for i in range(1, steps + 1)
    ]


def _assert_crosses_the_map(page, start, end, steps: int, what: str) -> None:
    hits = sum(_on_map(page, _steps(start, end, steps)))
    assert hits >= 2, (
        f"{what} from {start} to {end} reaches the map's canvas at {hits} of its {steps} steps, "
        f"so it would not show whether a drag across the map moves it"
    )


def _assert_same_view(before, after, what: str) -> None:
    share = _changed_share(before, after)
    assert share <= STILL_SHARE, f"{what} changed {share:.2%} of the map: the drag moved the map"


def _center(locator) -> tuple[float, float]:
    box = locator.bounding_box()
    assert box, "no layout box"
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _handle(page, node_id: str, handle_id: str) -> tuple[float, float]:
    return _center(page.locator(
        f'.react-flow__node[data-id="{node_id}"] .react-flow__handle[data-handleid="{handle_id}"]'
    ))


def _map_canvas(page):
    return page.locator(f"#autk-grammar-map-{MAP}")


def _uncovered_point_on_map(page) -> tuple[float, float]:
    """A point of the map's canvas that nothing covers, its middle if it can."""
    box = _map_canvas(page).bounding_box()
    assert box, "the map's canvas has no layout box"
    fractions = [(0.5, 0.5), (0.3, 0.3), (0.7, 0.3), (0.3, 0.7), (0.7, 0.7), (0.5, 0.2), (0.2, 0.5)]
    points = [(box["x"] + fx * box["width"], box["y"] + fy * box["height"]) for fx, fy in fractions]
    for point, hit in zip(points, _on_map(page, points)):
        if hit:
            return point
    raise AssertionError(f"nothing of the map's canvas at {box} can be pressed: every point tried is covered")


def _node_position(page, node_id: str) -> tuple[float, float]:
    at = page.evaluate(
        "(id) => window.__curio_reactFlow.getNodes().find((n) => n.id === id).position", node_id
    )
    return at["x"], at["y"]


def _screen(page, point) -> tuple[float, float]:
    at = page.evaluate("([x, y]) => window.__curio_reactFlow.flowToScreenPosition({ x, y })", list(point))
    return at["x"], at["y"]


def _assert_a_drag_on_the_map_pans_it(page, before) -> None:
    """A drag that begins on the map's canvas pans the map, as before: the
    canvas takes the pointer again once the press across it has ended."""
    x, y = _uncovered_point_on_map(page)
    page.mouse.move(x, y)
    page.mouse.down()
    for i in range(1, 9):
        page.mouse.move(x + 8 * i, y + 5 * i)
        page.wait_for_timeout(20)
    page.mouse.up()
    after = _map_at_rest(page, "after a drag that began on it")
    share = _changed_share(before, after)
    assert share > PANNED_SHARE, (
        f"a drag that began on the map changed {share:.2%} of it, so it did not pan the map"
    )


def test_an_edge_drawn_across_a_map_leaves_its_view(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open_with_the_map_drawn(page, app_frontend, current_server, username="map_drags_edge")
    # connect_nodes draws the edge straight, in 16 steps.
    _assert_crosses_the_map(page, _handle(page, LOADER, "out"), _handle(page, CODE, "in"), 16, "the edge")

    before = _map_at_rest(page, "before the edge")
    connect_nodes(page, LOADER, CODE)
    after = _map_at_rest(page, "after the edge")
    _assert_same_view(before, after, "drawing an edge across the map")
    _assert_a_drag_on_the_map_pans_it(page, after)


def test_a_node_dragged_across_a_map_leaves_its_view(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open_with_the_map_drawn(page, app_frontend, current_server, username="map_drags_node")
    zoom = page.evaluate("() => window.__curio_reactFlow.getViewport().zoom")
    box = node_locator(page, CODE).bounding_box()
    canvas = _map_canvas(page).bounding_box()
    assert box and canvas, "the Python node or the map's canvas has no layout box"
    header = (box["x"] + box["width"] / 2, box["y"] + 15 * zoom)
    onto = _center(_map_canvas(page))
    assert _on_map(page, [onto]) == [True], f"the middle of the map's canvas, {onto}, is covered"
    # Left of the map, where the node ends clear of it, on the empty pane.
    beyond = (canvas["x"] - box["width"] / 2 - 40, onto[1])
    assert beyond[0] > 0, f"the drag would end at {beyond}, outside the window"
    start = _node_position(page, CODE)

    before = _map_at_rest(page, "before the node drag")
    # A quick drag by the header, as a node is flicked across a map: the first
    # move lands on the map before the node follows it there. The node then
    # crosses the map and ends left of it.
    page.mouse.move(*header)
    page.mouse.down()
    page.mouse.move(*onto)
    page.mouse.move(*beyond, steps=max(1, round((onto[0] - beyond[0]) / 15)))
    page.mouse.up()
    moved = _node_position(page, CODE)
    assert moved[0] < start[0] - 500, (
        f"the drag by node {CODE}'s header did not carry it across the map: {start} then {moved}"
    )
    after = _map_at_rest(page, "after the node drag")
    _assert_same_view(before, after, "dragging a node across the map")
    _assert_a_drag_on_the_map_pans_it(page, after)


def test_a_selection_box_drawn_across_a_map_leaves_its_view(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open_with_the_map_drawn(page, app_frontend, current_server, username="map_drags_box")
    start, end = _screen(page, BOX_FROM), _screen(page, BOX_TO)
    for point in (start, end):
        assert page.evaluate(_ON_PANE_JS, list(point)), f"{point} is not on the empty pane"
    _assert_crosses_the_map(page, start, end, 20, "the selection box's corner")

    before = _map_at_rest(page, "before the selection box")
    page.mouse.move(*start)
    page.keyboard.down("Shift")
    page.mouse.down()
    page.mouse.move(*end, steps=20)
    page.mouse.up()
    page.keyboard.up("Shift")
    selected = page.evaluate(
        "() => window.__curio_reactFlow.getNodes().filter((n) => n.selected).map((n) => n.id)"
    )
    assert MAP in selected, f"the Shift-drag did not select the map; it selected {selected}"
    after = _map_at_rest(page, "after the selection box")
    _assert_same_view(before, after, "drawing a selection box across the map")

    # A click on the pane drops the selection and the box React Flow draws
    # around it, which covers the map.
    page.mouse.click(*start)
    _assert_a_drag_on_the_map_pans_it(page, after)
