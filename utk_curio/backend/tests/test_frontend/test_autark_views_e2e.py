"""Playwright E2E: several views in one Autark node, arranged by its `layout`
and linked by its `links`.

1. A map and a plot linked by `links`, over a table whose first row has no
   geometry: a pick on the map's middle square selects the bar that holds it,
   and a brush on the plot's first bar lights exactly that bar's rows on the
   map. The row with no place is one of them: Curio hands it to autk-db with an
   empty geometry, so the map holds it and draws nothing of it, and the west
   square is all that shows. autk-map picks on a double click.
2. Two maps of one table, side by side: the R key on the second reframes it
   alone, and a pick on the first is sent under the first map's key
   (`autk_selection@<id>`) to a node linked to the views' node.
3. The views' node pinned to a dashboard: its one tile draws both views.
4. Example 38, Back Bay and the Chicago Loop in one node: each map draws in its
   own pane, framed on its layers (#773), each histogram draws in its own, and
   the mean minutes of sun per road of each area are recorded on the test
   (``record_property``), the numbers the example's walkthrough states.

Map k of a node draws on `autk-grammar-map-<node>` for k = 0, else
`autk-grammar-map-<node>-<k>`, and plots likewise, so the drawing checks read
a view by that element (`_element`). It runs Autark maps, which need WebGPU:
without an adapter it skips, unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's
GPU job), where it fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_views_e2e.py -v
"""
from __future__ import annotations

import json
import math
import time
import uuid
from typing import TYPE_CHECKING

from .utils import (
    AUTK_PLOT_HIGHLIGHT,
    assert_autark_map_drawn,
    assert_autark_plot_drawn,
    autark_map_framing,
    bar_boxes,
    brush_area,
    dismiss_toasts,
    frame_nodes,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTK = "curio.builtin/autk-grammar"
DATA = "views-data"
VIEWS = "views-node"
RECEIVER = "views-receiver"
#: How long a draw of the small dataflows below may take.
RUN_MS = 240000

#: Three squares side by side in the Loop, west to east, and first a row with
#: no place: the plot holds four rows, the map draws three.
ROWS = '''import geopandas as gpd
from shapely.geometry import box

squares = gpd.GeoDataFrame(
    {
        "name": ["no place", "west", "middle", "east"],
        "value": [1, 1, 2, 3],
        "geometry": [
            None,
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
#: A map and a histogram of its squares' values in three bins, one value each,
#: linked: the plot names the map by its id.
LINKED = {
    "layout": {"type": "horizontal", "gap": 8},
    "map": {"id": "city", "layerRefs": [LAYER]},
    "plot": {
        "id": "values", "dataRef": "input_0", "mark": "bar", "axis": ["value", "@transform"],
        "transform": {"preset": "binning-1d", "options": {"bins": 3}}, "events": ["brushX"],
    },
    "links": [{"source": "values", "target": "city"}],
}
#: Two maps of the squares, side by side; the first picks.
TWO_MAPS = {
    "layout": {"type": "horizontal", "gap": 8},
    "map": [{"id": "north", "layerRefs": [LAYER]}, {"id": "south", "layerRefs": [{**LAYER, "isPick": False}]}],
}

# What a map of a node draws and lights (window.__curio_mapState), and each
# map's view (window.__curio_mapViews).
_STATE_JS = "([id, view]) => (window.__curio_mapState ? window.__curio_mapState(id, view) : null)"
_VIEWS_JS = "(id) => (window.__curio_mapViews ? window.__curio_mapViews(id) : null)"
# What *id* got over its interaction edges (node.data.interactions).
_INTERACTIONS_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const got = node && node.data ? node.data.interactions : null;
    return Array.isArray(got) ? JSON.parse(JSON.stringify(got)) : null;
}"""
# The bars of the plot in *selector*, left to right, and which show its highlight.
_BARS_LIT_JS = """({ selector, highlight }) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    return [...el.querySelectorAll('.autkMark')]
        .map((m) => ({ x: m.getBoundingClientRect().left, lit: getComputedStyle(m).fill === highlight }))
        .sort((a, b) => a.x - b.x)
        .map((m) => m.lit);
}"""
# Every value of *column* the roads of map *view* of node *id* hold, read from
# the features it drew (window.__curio_mapFeatureAt).
_DRAWN_VALUES_JS = """async ([id, table, view, column]) => {
    const state = await window.__curio_mapState(id, view);
    const drawn = (state && state[table] && state[table].drawn) || 0;
    const values = [];
    for (let at = 0; at < drawn; at++) {
        const feature = await window.__curio_mapFeatureAt(id, table, at, view);
        const value = feature ? (feature.compute || {})[column] : undefined;
        if (typeof value === 'number') values.push(value);
    }
    return { drawn, values };
}"""


def _element(node_id: str, view: int) -> str:
    """The id the drawing checks read view *view* of a kind of *node_id* by."""
    return node_id if view == 0 else f"{node_id}-{view}"


def _node(node_id: str, node_type: str, x: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": 120, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _data_edge(source: str, target: str) -> dict:
    return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target,
            "sourceHandle": "out", "targetHandle": "in"}


def _spec(views: dict, *, receiver: bool = False) -> dict:
    nodes = [_node(DATA, "curio.builtin/data-loading", 0, ROWS), _node(VIEWS, AUTK, 700, json.dumps(views, indent=2))]
    edges = [_data_edge(DATA, VIEWS)]
    if receiver:
        nodes.append(_node(RECEIVER, AUTK, 1500, json.dumps({"map": {"layerRefs": [LAYER]}}, indent=2)))
        edges += [
            _data_edge(DATA, RECEIVER),
            {"id": f"reactflow__edge-{VIEWS}in/out-{RECEIVER}in/out", "type": "Interaction",
             "source": VIEWS, "target": RECEIVER, "sourceHandle": "in/out", "targetHandle": "in/out"},
        ]
    for node in nodes:
        if node["type"] == AUTK:
            node.update({"width": 900, "height": 420})
    return {"dataflow": {"name": "AutarkViews", "task": "", "nodes": nodes, "edges": edges}}


def _enter(page, app_frontend, current_server, spec: dict, prefix: str) -> dict:
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Views",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    require_webgpu(page)
    run_all_and_wait(page, timeout_ms=RUN_MS)
    dismiss_toasts(page)
    return session


def _lit_names(page, view: str) -> list | None:
    state = page.evaluate(_STATE_JS, [VIEWS, view]) or {}
    layer = state.get("input_0")
    return None if layer is None else sorted(str(feature.get("name")) for feature in layer.get("lit") or [])


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


def test_a_plot_linked_by_links_lights_on_its_map_exactly_the_rows_it_brushes_and_a_pick_selects_its_bar(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, _spec(LINKED), "autk_links")
    assert_autark_map_drawn(page, _element(VIEWS, 0), timeout=60000)
    assert_autark_plot_drawn(page, _element(VIEWS, 0), timeout=60000)
    frame_nodes(page, [VIEWS])
    plot = f"#autk-grammar-plot-{VIEWS}"

    # A pick on the middle square selects the second bar alone.
    page.mouse.dblclick(*_center(page, f"autk-grammar-map-{VIEWS}"))
    lit_bars = _wait_for(
        lambda: page.evaluate(_BARS_LIT_JS, {"selector": plot, "highlight": AUTK_PLOT_HIGHLIGHT}),
        [False, True, False],
    )
    assert lit_bars == [False, True, False], f"a pick on the middle square lit the bars {lit_bars}, not the second"

    # The first bar holds the row with no place and the west square: the map
    # lights exactly those two rows, and draws only the west square of them.
    area, bars = brush_area(page, plot), bar_boxes(page, plot)
    assert area and len(bars) == 3, f"the histogram drew {len(bars)} bars, not 3, or no brush: {area}"
    y = area["y"] + area["height"] / 2
    page.mouse.move(area["x"] + 1, y)
    page.mouse.down()
    page.mouse.move((bars[0]["right"] + bars[1]["left"]) / 2, y, steps=12)
    page.mouse.up()
    lit = _wait_for(lambda: _lit_names(page, "city"), ["no place", "west"])
    assert lit == ["no place", "west"], (
        f"a brush of the first bar lit {lit} on the linked map, not exactly its rows ['no place', 'west']"
    )


def test_two_maps_of_one_table_each_reframe_alone_and_a_pick_is_sent_under_the_map_s_key(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, _spec(TWO_MAPS, receiver=True), "autk_two_maps")
    first, second = f"autk-grammar-map-{VIEWS}", f"autk-grammar-map-{VIEWS}-1"
    for view in (0, 1):
        assert_autark_map_drawn(page, _element(VIEWS, view), timeout=60000)
    frame_nodes(page, [VIEWS])

    def eyes():
        return [tuple(view["eye"]) if view else None for view in (page.evaluate(_VIEWS_JS, VIEWS) or [])]

    framed = eyes()
    assert len(framed) == 2 and all(framed), f"the node's two maps have the views {framed}"
    # Zoom into each map, then click the second and press R: it alone goes back.
    for canvas in (first, second):
        page.mouse.move(*_center(page, canvas))
        page.mouse.wheel(0, -400)
    zoomed = _wait_for(lambda: [eye != start for eye, start in zip(eyes(), framed)], [True, True])
    assert zoomed == [True, True], f"a wheel over each map moved {zoomed}"
    held = eyes()
    x, y = _center(page, second)
    page.mouse.click(x, y)
    page.keyboard.press("r")

    def close(a, b) -> bool:
        return a is not None and b is not None and math.dist(a, b) <= 1e-3 * max(1.0, abs(b[2]))

    reframed = _wait_for(lambda: [close(eye, start) for eye, start in zip(eyes(), framed)], [False, True])
    assert reframed == [False, True], f"R after a click on the second map reframed {reframed}, not the second alone"
    assert close(eyes()[0], held[0]), f"R on the second map moved the first: {eyes()[0]} from {held[0]}"

    # A pick (a double click, as autk-map picks) on the first map's middle
    # square reaches the linked node under the first map's key, naming the
    # middle square's row of the input.
    page.mouse.dblclick(*_center(page, first))

    def sent():
        for entry in page.evaluate(_INTERACTIONS_JS, RECEIVER) or []:
            if entry.get("nodeId") == VIEWS:
                details = entry.get("details") or {}
                return sorted(details), (details.get("autk_selection@north") or {}).get("data")
        return None

    got = _wait_for(sent, (["autk_selection@north"], [2]))
    assert got == (["autk_selection@north"], [2]), (
        f"a pick on the first map reached the linked node as {got}, not autk_selection@north naming row 2"
    )


def test_a_node_of_two_views_pinned_to_a_dashboard_draws_both_in_its_one_tile(
    app_frontend: "FrontendPage", current_server: str, page,
):
    from .test_dashboard_page_e2e import _open_dashboard, _pin, _save

    session = _enter(page, app_frontend, current_server, _spec(LINKED), "autk_views_tile")
    _pin(page, VIEWS)
    _save(page)
    _open_dashboard(page, app_frontend.base_url, session["project"]["id"])
    assert_autark_map_drawn(page, _element(VIEWS, 0), timeout=120000)
    assert_autark_plot_drawn(page, _element(VIEWS, 0), timeout=120000)
    tile = page.locator(f'.react-flow__node[data-id="{VIEWS}"]')
    assert tile.count() == 1, "the dashboard shows the node in more than one tile, or none"
    assert tile.locator(f"#autk-grammar-map-{VIEWS}").count() == 1
    assert tile.locator(f"#autk-grammar-plot-{VIEWS}").count() == 1
    # The tile arranges them as the canvas does: side by side.
    map_box = page.locator(f"#autk-grammar-map-{VIEWS}").bounding_box()
    plot_box = page.locator(f"#autk-grammar-plot-{VIEWS}").bounding_box()
    assert map_box and plot_box and map_box["x"] + map_box["width"] <= plot_box["x"] + 1, (
        f"the tile's map {map_box} is not left of its plot {plot_box}"
    )


EXAMPLE_38 = "38-autark-solstice-sun-two-cities.json"
EXAMPLE_38_NODE = "two-cities-sun"


def test_example_38_draws_each_view_in_its_pane_and_records_each_area_s_sun(
    app_frontend: "FrontendPage", current_server: str, page, record_property,
):
    from .walkthroughs import load_example_spec

    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Two Cities",
        username=f"autk_two_cities_{uuid.uuid4().hex[:8]}",
        project_name="Back Bay or the Loop",
        project_spec=load_example_spec(EXAMPLE_38),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    require_webgpu(page)
    run_all_and_wait(page, timeout_ms=600000)
    dismiss_toasts(page)
    frame_nodes(page, [EXAMPLE_38_NODE])
    problems = []
    for view in (0, 1):
        element = _element(EXAMPLE_38_NODE, view)
        assert_autark_map_drawn(page, element, timeout=120000)
        assert_autark_plot_drawn(page, element, timeout=120000)
        problem = autark_map_framing(page, element)
        if problem:
            problems.append(problem)
    assert not problems, "; ".join(problems)
    for view, table in (("back_bay", "back_bay_road_sun"), ("loop", "loop_road_sun")):
        read = page.evaluate(_DRAWN_VALUES_JS, [EXAMPLE_38_NODE, table, view, "sunlight"])
        values = read["values"]
        assert read["drawn"] > 0 and len(values) == read["drawn"], (
            f"map {view} drew {read['drawn']} roads, {len(values)} of them with their minutes of sun"
        )
        assert all(0 <= value <= 780 for value in values), f"map {view}'s roads hold sun past 0 to 780 minutes"
        mean = sum(values) / len(values)
        record_property(f"{view}_roads", len(values))
        record_property(f"{view}_mean_sun_minutes", round(mean, 1))
        record_property(f"{view}_all_day_share", round(sum(1 for v in values if v >= 780) / len(values), 3))
