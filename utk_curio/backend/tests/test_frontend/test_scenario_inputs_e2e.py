"""Playwright E2E: a Vega-Lite chart that reads its inputs stacked (#662).

A loader of road segments feeds two scenario boxes, "Baseline" and "Twice as
tall", each one node that divides the sunlight by its factor widget. A Vega-Lite
chart outside both boxes, pinned to the dashboard, reads them on its two
circles, and its spec names the dataset ``inputs``: every input's rows in one
table, each row named by the box its input comes from. The spec writes colors
of its own for ``scenario_name``, which the boxes' colors replace.

1. Run All draws the chart: its legend names the two boxes, in the order of its
   circles, and each bar is filled in its box's color.
2. "Twice as tall" is renamed in its details: the chart draws again with no
   run, its legend naming the new name, its bars in the same colors.
3. After a save, the dashboard draws the chart the same way.

The chart is read as SVG, from the view the page keeps (``view.toSVG()``).

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
CHART_TYPE = "curio.builtin/vis-vega"
BASELINE = {"id": "s-base", "name": "Baseline", "color": "#2a9d8f"}
TWICE = {"id": "s-tall", "name": "Twice as tall", "color": "#e76f51"}
RENAMED = "Towers capped"

LOAD_CODE = (
    "import pandas as pd\n"
    'return pd.DataFrame({"segment": ["r1", "r2", "r3", "r4"], "sunlight": [6.0, 5.0, 7.0, 4.0]})\n'
)
SHADE_CODE = 'df = input_0.copy()\ndf["sunlight"] = df["sunlight"] / [!! factor !!]\nreturn df\n'

#: Mean sunlight per scenario, a bar each, colored by scenario with a legend.
#: The colors it writes are not the boxes'.
CHART_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "data": {"name": "inputs"},
    "mark": "bar",
    "encoding": {
        "x": {"field": "scenario_name", "type": "nominal", "title": "Scenario"},
        "y": {"field": "sunlight", "type": "quantitative", "aggregate": "mean"},
        "color": {"field": "scenario_name", "type": "nominal", "scale": {"range": ["#000000", "#999999"]}},
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
            ],
            "edges": [
                {"id": "e-load-base", "source": LOAD, "target": BASE, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-load-tall", "source": LOAD, "target": TALL, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-base-chart", "source": BASE, "target": CHART, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-tall-chart", "source": TALL, "target": CHART, "sourceHandle": "out", "targetHandle": "in_1"},
            ],
            "scenarios": [
                {**BASELINE, "nodes": [BASE]},
                {**TWICE, "nodes": [TALL]},
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


def _assert_drawn(page, labels: list[str], where: str, timeout_s: float = 60.0) -> None:
    """The chart's legend names *labels*, in order, and its bars are filled in
    the two boxes' colors."""
    fills = sorted([BASELINE["color"], TWICE["color"]])
    drawn = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        svg = page.evaluate(_CHART_SVG_JS, CHART)
        if svg:
            drawn = _drawn(svg)
            if drawn == (labels, fills):
                return
        page.wait_for_timeout(250)
    raise AssertionError(f"{where}: the chart drew (legend, bar fills) {drawn}, not {(labels, fills)}")


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

    # 1. Run All: the legend names both boxes in circle order, each bar in its box's color.
    run_all_and_wait(page, timeout_ms=240000)
    for node_id in (BASE, TALL, CHART):
        status = wait_for_node_settled(page, node_id, timeout_ms=120000)
        assert status == "done", f"{node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
    frame_nodes(page, [CHART])
    _assert_drawn(page, [BASELINE["name"], TWICE["name"]], "after Run All")

    # 2. A box renamed: the chart draws again, with no run, under the new name.
    open_in_project_tab(page)
    name = open_scenario_details(page, TWICE["id"]).get_by_label("Scenario name")
    name.fill(RENAMED)
    name.press("Enter")
    close_scenario_details(page)
    close_scenario_drawer(page)
    frame_nodes(page, [CHART])
    _assert_drawn(page, [BASELINE["name"], RENAMED], "after the rename")

    # 3. Saved, the dashboard draws it the same way.
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{project_id}", session["token"])
    names = [scenario["name"] for scenario in project["spec"]["dataflow"]["scenarios"]]
    assert names == [BASELINE["name"], RENAMED], names
    page.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
    page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
    node_locator(page, CHART).wait_for(state="visible", timeout=45000)
    _assert_drawn(page, [BASELINE["name"], RENAMED], "on the dashboard", timeout_s=90.0)
