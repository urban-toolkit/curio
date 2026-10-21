"""Playwright E2E: a Vega-Lite chart that reads its inputs stacked (#662).

A loader of road segments feeds two scenario boxes, "Baseline" and "Twice as
tall", each one node that divides the sunlight by its factor widget; the
dataflow lists "Twice as tall" first. Two Vega-Lite charts outside both boxes
read them on two circles, Baseline's first, and their specs name the dataset
``inputs``: every input's rows in one table, each row named by the box its
input comes from.

- The first, pinned to the dashboard, writes its scenarios through chips: its
  color scale is ``[!! scenario colors !!]`` and its axis's order
  ``[!! scenario order !!]``, which the editor resolves to the boxes' colors and
  names in the order the dataflow lists them.
- The second writes no chip, and draws in Vega-Lite's own colors and order.

1. Run All draws both charts: the first's legend names the two boxes in the
   dataflow's order, each bar in its box's color; the second's in Vega-Lite's
   order and colors.
2. "Twice as tall" is renamed in its details: both charts draw again with no
   run, the first through its chips, its legend naming the new name.
3. "Baseline" is recolored: the first chart draws again, its bar in the new
   color; the second keeps Vega-Lite's colors.
4. After a save, the dashboard draws the first chart the same way.

The charts are read as SVG, from the views the page keeps (``view.toSVG()``).

A second dataflow joins a bar chart of Baseline's rows to a chart that reads
``inputs`` alone by a direct interaction edge. vega-lite builds only the
datasets a spec reads, so that chart's view holds no ``input_0``: a bar
hovered lights Baseline's row in ``inputs``, and nothing on the page fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scenario_inputs_e2e.py -v
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from .utils import (
    api_json,
    assert_in_view,
    close_scenario_details,
    close_scenario_drawer,
    frame_nodes,
    node_locator,
    open_in_project_tab,
    open_scenario_details,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOAD = "si-load"
BASE = "si-base"
TALL = "si-tall"
CHART = "si-chart"
OWN = "si-own"
CHART_TYPE = "curio.builtin/vis-vega"
BASELINE = {"id": "s-base", "name": "Baseline", "color": "#2a9d8f"}
TWICE = {"id": "s-tall", "name": "Twice as tall", "color": "#e76f51"}
RENAMED = "Towers capped"
RECOLORED = "#7b3294"
#: Vega-Lite's own colors for two names, its default scheme's first two.
VEGA_LITE_COLORS = ["#4c78a8", "#f58518"]

LOAD_CODE = (
    "import pandas as pd\n"
    'return pd.DataFrame({"segment": ["r1", "r2", "r3", "r4"], "sunlight": [6.0, 5.0, 7.0, 4.0]})\n'
)
SHADE_CODE = 'df = input_0.copy()\ndf["sunlight"] = df["sunlight"] / [!! factor !!]\nreturn df\n'

#: Mean sunlight per scenario, a bar each, colored by scenario with a legend,
#: through the scenario chips, which are not JSON until the editor resolves them.
CHART_SPEC = """{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "data": {"name": "inputs"},
  "mark": "bar",
  "encoding": {
    "x": {"field": "scenario_name", "type": "nominal", "title": "Scenario", "sort": [!! scenario order !!]},
    "y": {"field": "sunlight", "type": "quantitative", "aggregate": "mean"},
    "color": {"field": "scenario_name", "type": "nominal", "scale": [!! scenario colors !!]}
  }
}"""

#: The same chart with no chip: Vega-Lite's own colors and order.
OWN_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "data": {"name": "inputs"},
    "mark": "bar",
    "encoding": {
        "x": {"field": "scenario_name", "type": "nominal", "title": "Scenario"},
        "y": {"field": "sunlight", "type": "quantitative", "aggregate": "mean"},
        "color": {"field": "scenario_name", "type": "nominal"},
    },
}, indent=2)

SVG = "{http://www.w3.org/2000/svg}"

# Before the page's own scripts: keep every Vega view by the element it draws
# in, whenever the charts' Vega module is set on the window (useVega.ts).
_KEEP_VEGA_VIEWS_INIT = """(() => {
    let vega;
    const keep = (module) => {
        if (!module || !module.View || module.View.prototype.__curioKeepsViews) return;
        const initialize = module.View.prototype.initialize;
        module.View.prototype.initialize = function (element, ...rest) {
            const id = typeof element === "string" ? element.replace(/^#/, "") : element && element.id;
            if (id) (window.__curioVegaViews = window.__curioVegaViews || {})[id] = this;
            return initialize.call(this, element, ...rest);
        };
        module.View.prototype.__curioKeepsViews = true;
    };
    Object.defineProperty(window, "__curio_vega", {
        configurable: true,
        get() { return vega; },
        set(module) { vega = module; keep(module); },
    });
})();"""

# The SVG of the chart's last view.
_CHART_SVG_JS = """async (id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    return view ? await view.toSVG() : null;
}"""


def _factor(value: int) -> dict:
    return {"widgets": [{"name": "factor", "type": "number", "default": 1, "value": value}]}


def _node(node_id, node_type, x, y, content, title=None, metadata=None, **fields) -> dict:
    saved = {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": [], **(metadata or {})}, **fields,
    }
    if title:
        saved["title"] = title
    return saved


def _spec() -> dict:
    node = _node
    return {
        "dataflow": {
            "name": "Scenario inputs",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Scenario inputs",
            "nodes": [
                node(LOAD, "curio.builtin/data-loading", 0, 0, LOAD_CODE, "Roads"),
                node(BASE, "curio.builtin/computation-analysis", 700, 0, SHADE_CODE, "Shade", _factor(1)),
                node(TALL, "curio.builtin/computation-analysis", 700, 500, SHADE_CODE, "Shade",
                     {**_factor(2), "copiedFrom": [BASE]}),
                node(CHART, CHART_TYPE, 1400, 0, CHART_SPEC, "Sunlight", dashboardPinned=True),
                node(OWN, CHART_TYPE, 1400, 600, OWN_SPEC, "Own colors"),
            ],
            "edges": [
                {"id": "e-load-base", "source": LOAD, "target": BASE, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-load-tall", "source": LOAD, "target": TALL, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-base-chart", "source": BASE, "target": CHART, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-tall-chart", "source": TALL, "target": CHART, "sourceHandle": "out", "targetHandle": "in_1"},
                {"id": "e-base-own", "source": BASE, "target": OWN, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-tall-own", "source": TALL, "target": OWN, "sourceHandle": "out", "targetHandle": "in_1"},
            ],
            # Listed Twice as tall first, wired Baseline first.
            "scenarios": [
                {**TWICE, "nodes": [TALL]},
                {**BASELINE, "nodes": [BASE]},
            ],
        }
    }


def _drawn(svg: str) -> tuple[list[str], list[str]]:
    """The legend's labels in order, and the bars' fills, as the chart's SVG draws them."""
    root = ET.fromstring(svg)
    labels: list[str] = []
    fills: list[str] = []
    for group in root.iter(f"{SVG}g"):
        classes = (group.get("class") or "").split()
        if "role-legend-label" in classes:
            labels += ["".join(text.itertext()) for text in group.iter(f"{SVG}text")]
        if "mark-rect" in classes and "role-mark" in classes:
            fills += [(path.get("fill") or "").lower() for path in group.iter(f"{SVG}path")]
    return labels, sorted(fills)


def _assert_drawn(page, labels: list[str], colors: list[str], where: str, node_id: str = CHART,
                  timeout_s: float = 60.0) -> None:
    """The chart *node_id*'s legend names *labels*, in order, and its bars are
    filled in *colors*."""
    fills = sorted(color.lower() for color in colors)
    drawn = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        svg = page.evaluate(_CHART_SVG_JS, node_id)
        if svg:
            drawn = _drawn(svg)
            if drawn == (labels, fills):
                return
        page.wait_for_timeout(250)
    raise AssertionError(f"{where}: {node_id} drew (legend, bar fills) {drawn}, not {(labels, fills)}")


def test_a_chart_reading_inputs_names_and_colors_its_rows_by_their_boxes(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    spec = _spec()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenario Inputs",
        username="scenario_inputs_e2e",
        project_name="Scenario inputs",
        project_spec=spec,
    )
    require_owner_view(page)
    project_id = session["project"]["id"]
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    # 1. Run All: the chart with the chips names both boxes in the dataflow's
    # order, each bar in its box's color; the one without, in Vega-Lite's own.
    run_all_and_wait(page, timeout_ms=240000)
    for node_id in (BASE, TALL, CHART, OWN):
        status = wait_for_node_settled(page, node_id, timeout_ms=120000)
        assert status == "done", f"{node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
    boxes = [TWICE["color"], BASELINE["color"]]
    frame_nodes(page, [CHART])
    _assert_drawn(page, [TWICE["name"], BASELINE["name"]], boxes, "after Run All")
    frame_nodes(page, [OWN])
    _assert_drawn(page, [BASELINE["name"], TWICE["name"]], VEGA_LITE_COLORS, "after Run All", node_id=OWN)

    # 2. A box renamed: both charts draw again, with no run, under the new name.
    open_in_project_tab(page)
    name = open_scenario_details(page, TWICE["id"]).get_by_label("Scenario name")
    name.fill(RENAMED)
    name.press("Enter")
    close_scenario_details(page)
    close_scenario_drawer(page)
    frame_nodes(page, [CHART])
    _assert_drawn(page, [RENAMED, BASELINE["name"]], boxes, "after the rename")
    frame_nodes(page, [OWN])
    _assert_drawn(page, [BASELINE["name"], RENAMED], VEGA_LITE_COLORS, "after the rename", node_id=OWN)

    # 3. A box recolored: the chart with the chips draws its bar in the new
    # color, with no run; the one without keeps Vega-Lite's colors.
    open_in_project_tab(page)
    open_scenario_details(page, BASELINE["id"]).get_by_label(f"Color of {BASELINE['name']}").fill(RECOLORED)
    close_scenario_details(page)
    close_scenario_drawer(page)
    recolored = [TWICE["color"], RECOLORED]
    frame_nodes(page, [CHART])
    _assert_drawn(page, [RENAMED, BASELINE["name"]], recolored, "after the recolor")
    frame_nodes(page, [OWN])
    _assert_drawn(page, [BASELINE["name"], RENAMED], VEGA_LITE_COLORS, "after the recolor", node_id=OWN)

    # 4. Saved, the dashboard draws it the same way.
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{project_id}", session["token"])
    listed = [(scenario["name"], scenario["color"]) for scenario in project["spec"]["dataflow"]["scenarios"]]
    assert listed == [(RENAMED, TWICE["color"]), (BASELINE["name"], RECOLORED)], listed
    page.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
    page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
    node_locator(page, CHART).wait_for(state="visible", timeout=45000)
    _assert_drawn(page, [RENAMED, BASELINE["name"]], recolored, "on the dashboard", timeout_s=90.0)


PICK = "si-pick"
LIT = "si-lit"

#: Baseline's rows as bars: hovering one selects its row.
PICK_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "params": [{"name": "highlight", "select": {"type": "point", "on": "pointerover"}}],
    "mark": {"type": "bar", "stroke": "black"},
    "encoding": {
        "x": {"field": "segment", "type": "nominal"},
        "y": {"field": "sunlight", "type": "quantitative"},
        "color": {"value": "#4c78a8"},
    },
}, indent=2)

#: Every stacked row as a point, red once the selection reaches its row.
LIT_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "data": {"name": "inputs"},
    "mark": {"type": "point", "filled": True, "size": 400, "opacity": 1},
    "encoding": {
        "x": {"field": "segment", "type": "nominal"},
        "y": {"field": "sunlight", "type": "quantitative"},
        "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"},
    },
}, indent=2)


def _linked_spec() -> dict:
    """The two boxes' rows on a chart that reads ``inputs`` alone, joined by a
    direct interaction edge to a bar chart of Baseline's rows."""
    spec = _spec()
    flow = spec["dataflow"]
    flow["name"] = flow["provenance_id"] = "Scenario inputs linked"
    flow["nodes"] = [node for node in flow["nodes"] if node["id"] not in (CHART, OWN)] + [
        _node(PICK, CHART_TYPE, 1400, -400, PICK_SPEC, "Pick"),
        _node(LIT, CHART_TYPE, 1400, 300, LIT_SPEC, "Lit"),
    ]
    flow["edges"] = [edge for edge in flow["edges"] if edge["target"] not in (CHART, OWN)] + [
        {"id": "e-base-pick", "source": BASE, "target": PICK, "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e-base-lit", "source": BASE, "target": LIT, "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e-tall-lit", "source": TALL, "target": LIT, "sourceHandle": "out", "targetHandle": "in_1"},
        {
            "id": f"reactflow__edge-{PICK}in/out-{LIT}in/out", "type": "Interaction",
            "source": PICK, "target": LIT, "sourceHandle": "in/out", "targetHandle": "in/out",
        },
    ]
    return spec


# Where the chart's red points sit: how many bands of columns and how many bands
# of rows its red pixels take. A segment's two rows share its column and sit at
# different heights, so one point lit is one band each way. [-1, -1] before it
# drew.
_RED_BANDS_JS = """(id) => {
    const c = document.querySelector('#vega' + id + ' canvas');
    if (!c || !c.width || !c.height) return [-1, -1];
    const w = c.width, h = c.height;
    const px = c.getContext('2d').getImageData(0, 0, w, h).data;
    const across = new Array(w).fill(0), down = new Array(h).fill(0);
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            const i = (y * w + x) * 4;
            if (px[i] > 200 && px[i + 1] < 60 && px[i + 2] < 60 && px[i + 3] > 200) {
                across[x] += 1;
                down[y] += 1;
            }
        }
    }
    const bands = (counts) => {
        let found = 0, last = -100;
        counts.forEach((count, at) => {
            if (count < 2) return;
            if (at - last > 4) found += 1;
            last = at;
        });
        return found;
    };
    return [bands(across), bands(down)];
}"""


def test_a_selection_from_a_linked_chart_lights_its_row_on_a_chart_reading_inputs_alone(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    failures: list[str] = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.on("console", lambda message: failures.append(message.text) if message.type == "error" else None)
    spec = _linked_spec()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenario Inputs Linked",
        username="scenario_inputs_linked_e2e",
        project_name="Scenario inputs linked",
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    run_all_and_wait(page, timeout_ms=240000)
    for node_id in (BASE, TALL, PICK, LIT):
        status = wait_for_node_settled(page, node_id, timeout_ms=120000)
        assert status == "done", f"{node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
    for node_id in (PICK, LIT):
        page.locator(f"#vega{node_id} canvas").first.wait_for(state="attached", timeout=60000)
    page.wait_for_timeout(1500)
    frame_nodes(page, [PICK, LIT])
    assert page.evaluate(_RED_BANDS_JS, LIT) == [0, 0], "a row was lit before any selection"

    # Hover across the bars until the selection reaches the chart reading inputs.
    box = page.locator(f"#vega{PICK} canvas").first.bounding_box()
    assert box, "the bar chart has no canvas box"
    lit = [0, 0]
    y = box["y"] + box["height"] * 0.75
    for fraction in (0.8, 0.6, 0.4, 0.2):
        page.mouse.move(*assert_in_view(page, box["x"] + box["width"] * fraction, y, f"the bars at {fraction:.0%} across"))
        for _ in range(20):
            page.wait_for_timeout(250)
            lit = page.evaluate(_RED_BANDS_JS, LIT)
            if lit[0] > 0:
                break
        if lit[0] > 0:
            break
    # Let a late redraw, if one comes, land before the chart is read again.
    page.wait_for_timeout(1500)
    lit = page.evaluate(_RED_BANDS_JS, LIT)

    unrecognized = [failure for failure in failures if "Unrecognized data set" in failure]
    assert unrecognized == [], f"a selection reached a dataset the chart's view lacks: {unrecognized}"
    assert page.get_by_text("Something went wrong here.").count() == 0, "a node shows its error screen"
    assert node_locator(page, LIT).is_visible(), "the chart reading inputs is gone from the canvas"
    # Baseline's hovered row is lit, and Twice as tall's row in its column is not.
    assert lit == [1, 1], f"the chart reading inputs shows red in {lit} (column, row) bands, not one row ({failures[-5:]})"
