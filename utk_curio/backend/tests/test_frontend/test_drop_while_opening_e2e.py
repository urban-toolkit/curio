"""Playwright E2E: what is dropped while a dataflow opens lands once it has.

Each test holds the tab's read of the dataflow at the network until its drop
is made, so the drop comes while the dataflow opens on every run.

alice owns a dataflow with one node and invited bob to edit it. bob opens its
link. His tab asks for the dataflow, and the dataflow's room names his tab its
role apart from that answer, often first. Until the answer was in, the canvas
was titled "DefaultDataflow" and took drops the owner's way: a file bob
dropped then was refused as the dataflow still opening, with no node and no
import (#1251's e2e met it, and waited for the title to step around it).

The answer is held at the network until his drop is made, so the drop comes
while the dataflow opens on every run. While it opens, the title says so;
once it is in, his file goes his way, as a drop made then would: into his own
Data Catalog, with alice asked to add it, and a Data Loading node of it on
his canvas, beside alice's node, and in the dataflow the server keeps.

An owner drops a Data Loading node on her empty dataflow while it opens, as
``test_data_pool_hscroll_e2e`` does on a slow runner. The load asked for its
fit even when it brought no node, and that fit runs a frame after the load,
after the kept drop has made its node, so it framed that node alone: the
canvas moved and zoomed onto it, and the Data Pool dropped next, 610 px to the
right, landed on top of it and covered its output handle (#1377's run
42326757917). Now the node stays where it was dropped, the view as it was, and
the next node lands beside it. The page's animation frames are held from just
before the load until the dropped node is on the canvas, so the fit's frame
comes after that node on every run, as it did there.

An owner drops two Data Loading nodes on her dataflow of one node while it
opens. Her canvas shows none of the dataflow then, and each drop's place was
read over it, so once the load framed the dataflow's node, her nodes were
anywhere: one of them on top of the dataflow's node. Now each waits for that
fit and lands at the point of the window it was dropped on, in the view the
canvas then shows: the far one there, the one in the middle just below the
node it would have covered, as the canvas moves a node off another.

The drop helpers wait for a dataflow that takes long to open. A drop made
while it opens makes its node only once the load is in, and the load takes as
long as the server takes: 24 s on arcade during a host stall (#1391's run
42342733844), where ``drag_builtin_to_canvas`` gave the node 15 s from the drop
and failed with "Drop produced no node". Here the page holds its load until
20 s after the drop, and the helper still returns the node.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_drop_while_opening_e2e.py -v
"""
from __future__ import annotations

import math
import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_computed_json_output_e2e import _record_toasts
from .test_data_loading_drop_e2e import _drop_file
from .utils import (
    CANVAS_DROP_TARGET,
    _DRAG_TO_CANVAS_JS,
    api_json,
    canvas_nodes,
    close_after_routes,
    close_tools_palette,
    connect_nodes,
    dataset_widget_state,
    drag_builtin_to_canvas,
    end_routes,
    open_tools_palette,
    require_owner_view,
    require_project_page,
    require_user_auth,
    settled_viewport,
    stub_db_login,
    stub_db_user,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

OWNER = "opening_owner_e2e"
EDITOR = "opening_editor_e2e"
NAME = "Bus plan"
TITLE = "[data-curio-canvas-title] h1"
#: What the title says while the dataflow is opening.
OPENING = "Opening dataflow…"
#: alice's node, and the node bob's file makes.
LOADED = "curio.builtin/python-computation"
LOADER = "curio.builtin/data-loading"
BUS_STOPS = "stop_id,routes\n1,22\n2,29\n3,36\n"
#: What refused a drop while the dataflow opened.
STILL_OPENING = "still opening"

#: The owner's empty dataflow, and the nodes the hscroll test drops on it, at
#: its offsets: 610 px apart at the zoom the canvas opens at, so the facing
#: handles of both are in sight.
EMPTY = "Empty plan"
LOADING_TILE = "#tile-data-loading"
POOL_TILE = "#tile-data-pool"
FIRST_DROP = (150, 150)
NEXT_DROP = (760, 150)

#: The page's animation frames, held: a request waits until the test lets the
#: frames go, then gets its frame, in order. The load's fit asks for one as the
#: load lands, and the node a drop made while the dataflow opened is made just
#: after it, so held until that node is on the canvas, the fit's frame comes
#: after the node on every run.
_HOLD_FRAMES_JS = r"""() => {
    const ask = window.requestAnimationFrame;
    const cancel = window.cancelAnimationFrame;
    const held = new Map();
    let next = 0;
    window.__curioFramesRan = 0;
    window.requestAnimationFrame = (callback) => {
        next -= 1;
        held.set(next, callback);
        return next;
    };
    window.cancelAnimationFrame = (id) => {
        if (!held.delete(id)) cancel.call(window, id);
    };
    window.__curioLetFramesGo = () => {
        window.requestAnimationFrame = ask;
        window.cancelAnimationFrame = cancel;
        const callbacks = [...held.values()];
        held.clear();
        for (const callback of callbacks) {
            ask.call(window, (time) => {
                try { callback(time); } finally { window.__curioFramesRan += 1; }
            });
        }
        return callbacks.length;
    };
}"""

#: Lets held frames go, if any are held, and says how many requests it handed back.
_LET_FRAMES_GO_JS = "() => (window.__curioLetFramesGo ? window.__curioLetFramesGo() : 0)"

#: Whether React Flow has measured the node.
_MEASURED_JS = """(id) => {
    const node = window.__curio_reactFlow.getNode(id);
    return !!node && node.width > 0 && node.height > 0;
}"""

#: The owner's dataflow with one node, framed when it opens, and where she
#: drops two Data Loading nodes while it opens (from the pane's top left): far
#: right, where the framed node does not reach, then the middle of the canvas,
#: where it is.
WITH_A_NODE = "Plan with a node"
ITS_NODE = "opening-placed"
FAR_RIGHT_DROP = (1250, 100)
MIDDLE_DROP = (640, 420)
#: The clear space the canvas keeps between two nodes (`NODE_GUTTER_X`, `NODE_GUTTER_Y`).
GUTTER = 8

#: Every node on the canvas as React Flow holds it: its place and its measured size.
_BOXES_JS = """() => window.__curio_reactFlow.getNodes().map((node) => ({
    id: node.id, x: node.position.x, y: node.position.y, w: node.width || 0, h: node.height || 0,
}))"""

#: Whether React Flow has measured every node.
_ALL_MEASURED_JS = "() => window.__curio_reactFlow.getNodes().every((node) => node.width > 0 && node.height > 0)"

#: The point of the canvas under a point of the window, in the view the canvas shows now.
_UNDER_JS = "([x, y]) => window.__curio_reactFlow.screenToFlowPosition({x, y})"


def _spec() -> dict:
    return {
        "name": NAME,
        "dataflow": {
            "name": NAME,
            "nodes": [{"id": "opening-stops", "type": LOADED, "x": 0, "y": 0, "content": "stops = 3\n"}],
            "edges": [],
        },
    }


def _held_load(page, project_id: str) -> list:
    """Hold the read of the dataflow an editor's link falls through to
    (``GET /api/projects/<id>/shared``) until the test lets it go."""
    held: list = []

    def hold(route) -> None:
        held.append(route)

    page.route(re.compile(rf".*/api/projects/{project_id}/shared(\?.*)?$"), hold)
    return held


def _held_owner_load(page, project_id: str) -> list:
    """Hold the owner's canvas's read of her dataflow
    (``GET /api/projects/<id>?results=last``) until the test lets it go."""
    held: list = []

    def hold(route) -> None:
        if route.request.method == "GET" and not held:
            held.append(route)
        else:
            route.continue_()

    page.route(re.compile(rf".*/api/projects/{project_id}\?results=last$"), hold)
    return held


def _drop_tile(page, tile: str, at: tuple[float, float]) -> tuple[float, float]:
    """Drop a tile of the open Built-in palette on the canvas at *at*, from the
    pane's top left, as ``drag_to_canvas`` does, but wait for no node: a drop
    made while the dataflow opens makes none until it is in. Returns the
    point of the window it was dropped on."""
    source = page.locator(tile)
    source.wait_for(state="visible", timeout=15000)
    pane = page.locator(CANVAS_DROP_TARGET).bounding_box()
    assert pane, f"{CANVAS_DROP_TARGET} has no layout box"
    point = (pane["x"] + at[0], pane["y"] + at[1])
    dropped = page.evaluate(_DRAG_TO_CANVAS_JS, {
        "source": source.element_handle(),
        "targetSelector": CANVAS_DROP_TARGET,
        "clientX": point[0],
        "clientY": point[1],
    })
    assert dropped == "ok", f"drag to canvas failed: {dropped}"
    return point


def _within(page, seconds: float, read, done):
    """What *read* returns once *done* says so, or after *seconds*."""
    deadline = time.monotonic() + seconds
    seen = read()
    while not done(seen) and time.monotonic() < deadline:
        page.wait_for_timeout(500)
        seen = read()
    return seen


def test_a_file_dropped_while_the_link_opens_lands_once_the_dataflow_is_in(
    app_frontend: "FrontendPage", current_server: str, browser,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    owner = stub_db_user(
        current_server, username=OWNER, name="Alice", project_name=NAME, project_spec=_spec(),
    )
    project_id, owner_token = owner["project"]["id"], owner["token"]

    def dataflow_nodes() -> list:
        return sorted(
            node.get("type") for node in
            api_json(f"{current_server}/api/projects/{project_id}", owner_token)["spec"]["dataflow"]["nodes"]
        )

    def asked_of_alice() -> list:
        requests = api_json(f"{current_server}/api/dataflows/{project_id}/datasets/requests", owner_token)
        return [(r["datasetId"], r["by"]["name"]) for r in requests["requests"]]

    context = browser.new_context(viewport={"width": 1280, "height": 768}, reduced_motion="reduce")
    held: list = []
    try:
        page = context.new_page()
        stub_db_login(page, frontend_url=base, backend_url=current_server, username=EDITOR, name="Bob")
        api_json(f"{current_server}/api/projects/{project_id}/editors", owner_token,
                 method="POST", payload={"username": EDITOR})
        held = _held_load(page, project_id)
        page.goto(f"{base}/dataflow/{project_id}", timeout=120000)
        page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=60000)
        asked = _within(page, 60, lambda: len(held), lambda count: count > 0)
        assert asked, "bob's tab never asked for the dataflow its link names"
        # The room names his tab its role apart from the load: here, first.
        try:
            page.locator('[data-curio-room-role="editor"]').wait_for(state="attached", timeout=30000)
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError("the dataflow's room never named bob's tab its editor") from exc
        _record_toasts(page)
        title_while_opening = page.locator(TITLE).inner_text()

        # He drops a file of his on the canvas while the dataflow opens.
        _drop_file(page, CANVAS_DROP_TARGET, "bus_stops.csv", BUS_STOPS, at=(760, 300))

        # The dataflow comes in.
        held.pop(0).continue_()
        try:
            expect(page.locator(TITLE)).to_have_text(NAME, timeout=60000)
        except AssertionError as exc:
            raise AssertionError("bob's tab never loaded the dataflow its link names") from exc
        on_his_canvas = _within(
            page, 60,
            lambda: sorted(node["nodeType"] for node in canvas_nodes(page)),
            lambda types: LOADER in types,
        )
        his_loaders = [node["id"] for node in canvas_nodes(page) if node["nodeType"] == LOADER]
        his_datasets = [dataset_widget_state(page, node)["value"] for node in his_loaders]
        in_the_dataflow = _within(page, 30, dataflow_nodes, lambda types: LOADER in types)
        asked_for = _within(page, 30, asked_of_alice, lambda asks: len(asks) > 0)
        told = page.evaluate("() => window.__curioToastLog || []")
    finally:
        # A load still held (the test failed before letting it go) goes on,
        # so taking the routes off waits for nothing.
        for route in held:
            try:
                route.continue_()
            except Exception:  # noqa: BLE001 - already let go
                pass
        close_after_routes(context)

    seen = {
        "title while the dataflow opened": title_while_opening,
        "on bob's canvas": on_his_canvas,
        "in the dataflow": in_the_dataflow,
        "his node loads a dataset he imported": [str(value).split(".")[0] for value in his_datasets],
        "alice is asked for that dataset, by bob": asked_for == [(value, "Bob") for value in his_datasets],
        "refused as still opening": [toast for toast in told if STILL_OPENING in toast],
    }
    assert seen == {
        "title while the dataflow opened": OPENING,
        "on bob's canvas": sorted([LOADED, LOADER]),
        "in the dataflow": sorted([LOADED, LOADER]),
        "his node loads a dataset he imported": ["imported"],
        "alice is asked for that dataset, by bob": True,
        "refused as still opening": [],
    }, f"his nodes load {his_datasets}, alice is asked for {asked_for}; bob's tab said {told}"


def test_a_node_dropped_while_an_empty_dataflow_opens_stays_where_it_was_dropped(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_login(
        page, frontend_url=base, backend_url=current_server,
        username="opening_owner_drop_e2e", name="Olive", project_name=EMPTY,
    )
    project_id = login["project"]["id"]
    held = _held_owner_load(page, project_id)
    try:
        page.goto(f"{base}/dataflow/{project_id}", timeout=120000)
        page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=60000)
        asked = _within(page, 60, lambda: len(held), lambda count: count > 0)
        assert asked, "the owner's tab never asked for the dataflow its link names"
        view_before = settled_viewport(page)

        # She drops a Data Loading node while the dataflow opens.
        open_tools_palette(page, "builtin")
        _drop_tile(page, LOADING_TILE, FIRST_DROP)
        made_while_opening = len(canvas_nodes(page))

        # The dataflow comes in, and the node her drop was kept for is made.
        # No wait here may need a frame while frames are held.
        page.evaluate(_HOLD_FRAMES_JS)
        held[0].continue_()
        page.wait_for_function(
            "() => window.__curio_reactFlow.getNodes().length > 0",
            polling=100, timeout=60000,
        )
        handed_back = page.evaluate(_LET_FRAMES_GO_JS)
        page.wait_for_function(
            "(n) => window.__curioFramesRan >= n", arg=handed_back, polling=100, timeout=30000,
        )
        made = canvas_nodes(page)
        assert len(made) == 1, f"her one drop made {made}"
        loading = made[0]["id"]
        page.wait_for_function(_MEASURED_JS, arg=loading, polling=100, timeout=30000)
        close_tools_palette(page, "builtin")
        view_after = settled_viewport(page)
        require_owner_view(page)

        # She drops a Data Pool 610 px to the right and connects the two.
        pool = drag_builtin_to_canvas(page, POOL_TILE, at=NEXT_DROP)
        try:
            connect_nodes(page, loading, pool)
            connected = True
        except AssertionError as exc:  # said in the test's words
            connected = str(exc).split(". Space")[0]
    finally:
        try:
            page.evaluate(_LET_FRAMES_GO_JS)
        except Exception:  # noqa: BLE001 - the page may be gone
            pass
        # A load still held (the test failed before letting it go) goes on,
        # so taking the routes off waits for nothing.
        for route in held:
            try:
                route.continue_()
            except Exception:  # noqa: BLE001 - already let go
                pass
        end_routes(page)

    seen = {
        "nodes on the canvas while the dataflow opened": made_while_opening,
        "the view once her node is in": view_after,
        "the next node connects to it": connected,
    }
    assert seen == {
        "nodes on the canvas while the dataflow opened": 0,
        "the view once her node is in": view_before,
        "the next node connects to it": True,
    }, f"the view was {view_before} when she dropped her node"


def _with_a_node_spec() -> dict:
    return {
        "name": WITH_A_NODE,
        "dataflow": {
            "name": WITH_A_NODE,
            "nodes": [{"id": ITS_NODE, "type": LOADED, "x": 400, "y": 250, "content": "stops = 3\n"}],
            "edges": [],
        },
    }


def _overlap(a: dict, b: dict) -> bool:
    """Whether two nodes' boxes share any of the canvas."""
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def _where_it_landed(node: dict, under: dict, others: list) -> str:
    """Where a node a drop made landed, against the point of the canvas under
    the drop: there, or moved straight down or right just clear of one of
    *others*, as the canvas moves a node off another."""
    same_x = abs(node["x"] - under["x"]) <= 1
    same_y = abs(node["y"] - under["y"]) <= 1
    if same_x and same_y:
        return "under the pointer"
    if same_x and node["y"] > under["y"] and any(
        abs(node["y"] - math.ceil(other["y"] + other["h"] + GUTTER)) <= 1 for other in others
    ):
        return "just below a node"
    if same_y and node["x"] > under["x"] and any(
        abs(node["x"] - math.ceil(other["x"] + other["w"] + GUTTER)) <= 1 for other in others
    ):
        return "just right of a node"
    return f"at ({node['x']:.0f}, {node['y']:.0f}), with ({under['x']:.0f}, {under['y']:.0f}) under the pointer"


def test_nodes_dropped_while_a_dataflow_opens_land_under_the_pointer_in_its_view_clear_of_its_node(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_login(
        page, frontend_url=base, backend_url=current_server,
        username="opening_owner_place_e2e", name="Olive",
        project_name=WITH_A_NODE, project_spec=_with_a_node_spec(),
    )
    project_id = login["project"]["id"]
    held = _held_owner_load(page, project_id)
    try:
        page.goto(f"{base}/dataflow/{project_id}", timeout=120000)
        page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=60000)
        asked = _within(page, 60, lambda: len(held), lambda count: count > 0)
        assert asked, "the owner's tab never asked for the dataflow its link names"

        # While the dataflow opens, her canvas shows none of it. She drops a
        # Data Loading node far right, then one in the middle of the canvas.
        open_tools_palette(page, "builtin")
        points = [_drop_tile(page, LOADING_TILE, at) for at in (FAR_RIGHT_DROP, MIDDLE_DROP)]
        made_while_opening = len(canvas_nodes(page))
        # The palette closes first, so the fit frames the node in the whole canvas.
        close_tools_palette(page, "builtin")

        # The dataflow comes in and its node is framed, then hers are made.
        held[0].continue_()
        require_owner_view(page)
        page.wait_for_function("() => window.__curio_reactFlow.getNodes().length >= 3", timeout=60000)
        page.wait_for_function(_ALL_MEASURED_JS, timeout=30000)
        settled_viewport(page)
        boxes = page.evaluate(_BOXES_JS)
        under = [page.evaluate(_UNDER_JS, list(point)) for point in points]
    finally:
        # A load still held (the test failed before letting it go) goes on,
        # so taking the routes off waits for nothing.
        for route in held:
            try:
                route.continue_()
            except Exception:  # noqa: BLE001 - already let go
                pass
        end_routes(page)

    its = [box for box in boxes if box["id"] == ITS_NODE]
    hers = [box for box in boxes if box["id"] != ITS_NODE]
    assert (len(its), len(hers)) == (1, 2), f"the canvas holds {boxes}"
    seen = {
        "nodes on the canvas while the dataflow opened": made_while_opening,
        "her nodes on the dataflow's node": [
            index for index, node in enumerate(hers) if _overlap(node, its[0])
        ],
        "where her nodes landed": [
            _where_it_landed(node, under[index], its + hers[:index])
            for index, node in enumerate(hers)
        ],
    }
    assert seen == {
        "nodes on the canvas while the dataflow opened": 0,
        "her nodes on the dataflow's node": [],
        "where her nodes landed": ["under the pointer", "just below a node"],
    }, f"the canvas holds {boxes}; under her drops: {under}"


#: How long the page holds its dataflow's load after the first drop: longer
#: than the 15 s a drop helper gives the node, as arcade's 24 s was.
SLOW_LOAD_MS = 20000

#: The page's load of its dataflow (``GET /api/projects/<id>?results=last``),
#: held in the page until SLOW_LOAD_MS after the first drop on it: a server
#: that answers late, whenever the test drops. Held here, not with
#: ``page.route``, which this thread could not let go while the drop helper
#: it calls is waiting.
_SLOW_LOAD_JS = r"""(() => {
    const realFetch = window.fetch.bind(window);
    const load = /\/api\/projects\/[0-9a-f-]{36}\?results=last$/;
    let letGo;
    const goes = new Promise((resolve) => { letGo = resolve; });
    let dropped = false;
    window.addEventListener("drop", () => {
        if (dropped) return;
        dropped = true;
        setTimeout(letGo, %d);
    }, true);
    window.__curioHeldLoads = 0;
    window.fetch = (input, init) => {
        const url = typeof input === "string" ? input : (input && input.url) || "";
        if (!load.test(url)) return realFetch(input, init);
        window.__curioHeldLoads += 1;
        return goes.then(() => realFetch(input, init));
    };
})();""" % SLOW_LOAD_MS


def test_a_drop_helper_waits_for_a_dataflow_that_opens_slowly(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_SLOW_LOAD_JS)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Slow Opener",
        username="opening_slow_e2e",
        project_name="Slow plan",
    )
    require_owner_view(page)

    # Dropped while the dataflow opens, its node is made once the load lands,
    # SLOW_LOAD_MS after the drop.
    loading = drag_builtin_to_canvas(page, LOADING_TILE, at=FIRST_DROP)

    seen = {
        "loads the page held": page.evaluate("() => window.__curioHeldLoads"),
        "the canvas title": page.locator(TITLE).inner_text(),
        "nodes": [node["id"] for node in canvas_nodes(page)],
    }
    assert seen == {
        "loads the page held": 1,
        "the canvas title": "Slow plan",
        "nodes": [loading],
    }
