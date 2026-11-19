"""Playwright E2E: interaction edges that name a view of an Autark node.

An Autark node of several views has a dot per view with an ``id``, beside its
own, along its top edge (``in/out@<id>``). Here a node of a map ``city`` and a
histogram ``values`` of three squares (VIEWS) is linked to a map of the same
squares, a node of one view (SENDER), and a pick on the sender's middle square
(a double click, as autk-map picks) reaches VIEWS:

1. on the histogram's dot, without ``links``: the histogram's middle bar is
   selected, and the map lights nothing;
2. on the histogram's dot, with a link from the histogram to the map: the bar,
   and the map's middle square, which the link carries the bar's rows to;
3. on VIEWS's own dot, an edge as every dataflow saved before views had dots,
   without ``links``: the bar and the map's middle square, as each view
   receives the pick.
4. VIEWS shows a dot per view, right of its own, in the order of its panes,
   and SENDER its own alone. Hovering the histogram's dot names the view in
   Curio's tooltip and rings the histogram's pane: two new frames, the node's
   top edge with its dots and the ringed pane with its tooltip.

Map k of a node draws on ``autk-grammar-map-<node>`` for k = 0, else
``autk-grammar-map-<node>-<k>``, and plots likewise. It runs Autark maps,
which need WebGPU: without an adapter it skips, unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_view_edges_e2e.py -v
"""
from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING

from .utils import (
    AUTK_PLOT_HIGHLIGHT,
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    assert_autark_map_drawn,
    assert_autark_plot_drawn,
    dismiss_toasts,
    frame_nodes,
    hover_until_tooltip_says,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    tooltip_close_up,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTK = "curio.builtin/autk-grammar"
DATA = "edges-data"
VIEWS = "edges-views"
SENDER = "edges-sender"
#: The frames' names start here.
STEM = "autark-view-edges"
#: How long a draw of the small dataflow below may take.
RUN_MS = 240000

#: Three squares side by side in the Loop, west to east, valued 1, 2 and 3.
ROWS = '''import geopandas as gpd
from shapely.geometry import box

squares = gpd.GeoDataFrame(
    {
        "name": ["west", "middle", "east"],
        "value": [1, 2, 3],
        "geometry": [
            box(-87.6360, 41.8800, -87.6340, 41.8820),
            box(-87.6340, 41.8800, -87.6320, 41.8820),
            box(-87.6320, 41.8800, -87.6300, 41.8820),
        ],
    },
    crs="EPSG:4326",
)
squares.metadata = {"layerType": "polygons"}
return squares
'''

LAYER = {"dataRef": "input_0", "isPick": True, "getFnv": "value", "getFnvType": "quantitative"}
#: A map `city` and a histogram `values` of the squares' values in three bins, one value each.
VIEWS_SPEC = {
    "layout": {"type": "horizontal", "gap": 8},
    "map": {"id": "city", "layerRefs": [LAYER]},
    "plot": {
        "id": "values", "dataRef": "input_0", "mark": "bar", "axis": ["value", "@transform"],
        "transform": {"preset": "binning-1d", "options": {"bins": 3}}, "events": ["brushX"],
    },
}
#: The same, the histogram linked to the map.
LINKED_SPEC = {**VIEWS_SPEC, "links": [{"source": "values", "target": "city"}]}

# What a map of a node draws and lights (window.__curio_mapState).
_STATE_JS = "([id, view]) => (window.__curio_mapState ? window.__curio_mapState(id, view) : null)"
# The bars of the plot in *selector*, left to right, and which show its highlight.
_BARS_LIT_JS = """({ selector, highlight }) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    return [...el.querySelectorAll('.autkMark')]
        .map((m) => ({ x: m.getBoundingClientRect().left, lit: getComputedStyle(m).fill === highlight }))
        .sort((a, b) => a.x - b.x)
        .map((m) => m.lit);
}"""
# Each interaction dot of node *id*: its handle and its box, left to right.
_DOTS_JS = """(id) => [...document.querySelectorAll(`.react-flow__node[data-id="${id}"] .react-flow__handle`)]
    .map((h) => ({ handle: h.getAttribute('data-handleid'), box: h.getBoundingClientRect().toJSON() }))
    .filter((dot) => dot.handle && dot.handle.startsWith('in/out'))
    .sort((a, b) => a.box.left - b.box.left)"""
# Whether each pane of node *id* is ringed, by its view's id.
_RINGED_JS = """(id) => Object.fromEntries([...document.querySelectorAll(
    `.react-flow__node[data-id="${id}"] [data-curio-autk-pane]`)].map((p) => [p.dataset.viewId, p.dataset.curioRinged === 'true']))"""
# The box of node *id*.
_NODE_BOX_JS = """(id) => document.querySelector(`.react-flow__node[data-id="${id}"]`).getBoundingClientRect().toJSON()"""
# The box of the pane *pane* (`<kind>-<index>`) of node *id*.
_PANE_BOX_JS = """([id, pane]) => {
    const el = document.querySelector(`.react-flow__node[data-id="${id}"] [data-curio-autk-pane="${pane}"]`);
    return el ? el.getBoundingClientRect().toJSON() : null;
}"""


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _data_edge(source: str, target: str) -> dict:
    return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target,
            "sourceHandle": "out", "targetHandle": "in"}


def _spec(views: dict, *, view: str | None) -> dict:
    """The squares, VIEWS drawing *views*, and SENDER linked to VIEWS's dot of
    the view *view* (none: VIEWS's own dot)."""
    handle = "in/out" if view is None else f"in/out@{view}"
    nodes = [
        _node(DATA, "curio.builtin/data-loading", 0, 120, ROWS),
        _node(VIEWS, AUTK, 700, 120, json.dumps(views, indent=2)),
        _node(SENDER, AUTK, 700, 640, json.dumps({"map": {"layerRefs": [LAYER]}}, indent=2)),
    ]
    for node in nodes[1:]:
        node.update({"width": 900, "height": 420})
    edges = [
        _data_edge(DATA, VIEWS),
        _data_edge(DATA, SENDER),
        {"id": f"reactflow__edge-{SENDER}in/out-{VIEWS}{handle}", "type": "Interaction",
         "source": SENDER, "target": VIEWS, "sourceHandle": "in/out", "targetHandle": handle},
    ]
    return {"dataflow": {"name": "AutarkViewEdges", "task": "", "nodes": nodes, "edges": edges}}


def _enter(page, app_frontend, current_server, spec: dict, prefix: str) -> None:
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark View Edges",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    require_webgpu(page)
    run_all_and_wait(page, timeout_ms=RUN_MS)
    dismiss_toasts(page)
    assert_autark_map_drawn(page, VIEWS, timeout=60000)
    assert_autark_plot_drawn(page, VIEWS, timeout=60000)
    assert_autark_map_drawn(page, SENDER, timeout=60000)
    frame_nodes(page, [VIEWS, SENDER])


def _wait_for(read, wanted, *, timeout_s: float = 30.0):
    """*read()*, asked until it returns *wanted*; the last answer."""
    deadline = time.monotonic() + timeout_s
    got = read()
    while got != wanted and time.monotonic() < deadline:
        time.sleep(0.25)
        got = read()
    return got


def _center(page, element_id: str) -> tuple[float, float]:
    box = page.locator(f"#{element_id}").bounding_box()
    assert box, f"#{element_id} is not on the page"
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _lit_names(page) -> list | None:
    """The squares VIEWS's map `city` lights."""
    state = page.evaluate(_STATE_JS, [VIEWS, "city"]) or {}
    layer = state.get("input_0")
    return None if layer is None else sorted(str(feature.get("name")) for feature in layer.get("lit") or [])


def _bars_lit(page) -> list | None:
    return page.evaluate(_BARS_LIT_JS, {"selector": f"#autk-grammar-plot-{VIEWS}", "highlight": AUTK_PLOT_HIGHLIGHT})


def _pick_the_middle_square(page) -> None:
    """A pick on SENDER's middle square, in the middle of its map."""
    page.mouse.dblclick(*_center(page, f"autk-grammar-map-{SENDER}"))


def test_an_edge_on_a_plot_s_dot_selects_its_bar_and_lights_nothing_on_the_map_of_its_node(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, _spec(VIEWS_SPEC, view="values"), "autk_view_edge")
    assert _lit_names(page) == [], f"VIEWS's map lights {_lit_names(page)} before any pick"

    _pick_the_middle_square(page)

    bars = _wait_for(lambda: _bars_lit(page), [False, True, False])
    assert bars == [False, True, False], f"a pick sent to the histogram's dot lit the bars {bars}, not the second"
    # The histogram has received the pick; the map is no view the edge names.
    time.sleep(2.0)
    assert _lit_names(page) == [], f"a pick sent to the histogram's dot lit {_lit_names(page)} on the map of its node"


def test_an_edge_on_a_plot_s_dot_reaches_the_map_its_links_join_it_to(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, _spec(LINKED_SPEC, view="values"), "autk_view_edge_links")

    _pick_the_middle_square(page)

    bars = _wait_for(lambda: _bars_lit(page), [False, True, False])
    assert bars == [False, True, False], f"a pick sent to the histogram's dot lit the bars {bars}, not the second"
    lit = _wait_for(lambda: _lit_names(page), ["middle"])
    assert lit == ["middle"], f"the histogram's link to the map lit {lit}, not exactly ['middle']"


def test_an_edge_on_the_node_s_own_dot_reaches_every_view_of_a_node_of_several(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, _spec(VIEWS_SPEC, view=None), "autk_view_edge_old")

    _pick_the_middle_square(page)

    bars = _wait_for(lambda: _bars_lit(page), [False, True, False])
    assert bars == [False, True, False], f"a pick sent to the node's own dot lit the bars {bars}, not the second"
    lit = _wait_for(lambda: _lit_names(page), ["middle"])
    assert lit == ["middle"], f"a pick sent to the node's own dot lit {lit} on its map, not exactly ['middle']"


def test_a_node_of_two_views_shows_a_dot_per_view_and_a_dot_s_hover_names_its_view_and_rings_its_pane(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, _spec(VIEWS_SPEC, view="values"), "autk_view_dots")

    dots = page.evaluate(_DOTS_JS, VIEWS)
    assert [dot["handle"] for dot in dots] == ["in/out", "in/out@city", "in/out@values"], (
        f"VIEWS shows the interaction dots {[dot['handle'] for dot in dots]}, left to right"
    )
    node = page.evaluate(_NODE_BOX_JS, VIEWS)
    for dot in dots:
        box = dot["box"]
        x, y = (box["left"] + box["right"]) / 2, (box["top"] + box["bottom"]) / 2
        assert node["left"] < x < node["right"], f"{dot['handle']} is off the node's top edge: {box}, node {node}"
        assert y < node["top"], f"{dot['handle']} is not on the node's top edge: {box}, node {node}"
    sender = [dot["handle"] for dot in page.evaluate(_DOTS_JS, SENDER)]
    assert sender == ["in/out"], f"SENDER, a node of one view, shows the interaction dots {sender}"

    frame_nodes(page, [VIEWS])
    top = page.evaluate(_NODE_BOX_JS, VIEWS)
    save_workflow_test_screenshot(
        page, STEM, test_name="two-views-dots",
        fit_reactflow=False, clip_rect={
            "x": max(0, round(top["left"] + top["width"] / 2 - 60)), "y": max(0, round(top["top"] - 40)),
            "width": 240, "height": 80,
        },
        pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO, closeup=True,
    )

    selector = f'.react-flow__node[data-id="{VIEWS}"] .react-flow__handle[data-handleid="in/out@values"]'
    tip = hover_until_tooltip_says(page, selector, "the histogram's dot", ["interaction · values"])
    ringed = _wait_for(lambda: page.evaluate(_RINGED_JS, VIEWS), {"city": False, "values": True})
    assert ringed == {"city": False, "values": True}, f"a hover of the histogram's dot rang the panes {ringed}"
    # The dot, its tooltip and the histogram's pane, the map left out.
    dot = page.locator(selector).bounding_box()
    pane = page.evaluate(_PANE_BOX_JS, [VIEWS, "plot-0"])
    assert dot and pane, f"the histogram's dot {dot} or pane {pane} is not on the page"
    shown = {
        "left": min(dot["x"], pane["left"]), "top": min(dot["y"], pane["top"]),
        "right": max(dot["x"] + dot["width"], pane["right"]), "bottom": max(dot["y"] + dot["height"], pane["bottom"]),
    }
    save_workflow_test_screenshot(
        page, STEM, test_name="dot-rings-its-pane",
        fit_reactflow=False, keep_tooltip=True, clip_rect=tooltip_close_up(page, tip, shown),
        pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO, closeup=True,
    )
