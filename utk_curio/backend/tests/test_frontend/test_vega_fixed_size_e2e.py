"""Playwright E2E: a Vega-Lite chart whose author set its size draws its plot at that size.

komar41 reported in #1097 that a Vega-Lite chart whose author set both its
width and its height, and no ``autosize``, draws smaller than its author asked
and shrinks under the pointer.

Main sizes a Vega-Lite spec in ``utils/vegaSpecSizing.ts``, which ``useVega``'s
``compileGrammar`` calls. A width or a height the author left out follows the
node, and a spec that sets no ``autosize`` gets ``{"type": "fit", "contains":
"padding", "resize": true}``, even when its author set both sizes. ``fit``
fits the whole chart, axes, title and legend included, into the given size,
and ``resize: true`` has Vega lay the view out again on every update. A hover
is an update, and so is the ``view.resize()`` the node's resize observer calls.

A chart whose author set its size must draw its plot at that size, with its
axes, title and legend around it, and keep it there. The plot is the view's
``width`` and ``height`` signals, and its root group's box, which Vega draws
them as. Each chart's plot must equal its spec's width and height:

* at its first draw, once it has stopped moving;
* after each of 20 hovers. The pointer moves onto one of the chart's marks,
  found where the view's scene graph draws it now, and stays until Vega's own
  pointer state holds that mark and, on a chart with tooltips, the tooltip Vega
  writes on the chart's element names it (on a rule, the ``hover`` select holds
  its tract too). Then it leaves the chart, until Vega holds no mark and the
  tooltip clears;
* after each of 20 ``view.resize().runAsync()`` calls made in the page, the
  call the node's resize observer makes.

The charts:

* komar41's two FloodRisk charts from his #914, typed again here: their titles
  and subtitles, sizes, layers, tooltips, the ``hover`` select and the
  scenario legend.

  * Average flood depth, with and without NbS: 440x280, a bar per period and
    scenario with a label above, colored by scenario.
  * Social vulnerability against average flood depth: 520x320, a rule per
    tract from its No NbS depth to its All NbS depth, which the pointer
    darkens, under a circle per tract and scenario. It reads ``inputs``, the
    dataset a chart stacks its inputs in (each input's rows, with its circle
    under ``__input__``), as on his #914: a loader of the tracts' No NbS
    depths feeds the chart's first input, and one of their All NbS depths its
    second.

* komar41's two charts from #1097:

  * grouped bars, 420x220, exactly as the issue writes them: a bar per period
    and method, with a tooltip and a color legend;
  * a layered area and line on two y axes, 460x220. The issue describes it but
    gives no spec, so this one is built from that description: the share of a
    park in shade as an area on the left axis, and the sun hours lost so far
    as a line with points and tooltips on the right axis.

* Example 03's bar chart, 320x260 with a legend, read from
  ``docs/examples/03-vega-lite-linked-temporal-charts.json``, on rows of the
  shape its computation node returns. It has no tooltip.

His FloodRisk charts are in nodes of the sizes he gave them, and the others in
nodes big enough to show the whole chart at its author's size, so every mark
can be hovered.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_vega_fixed_size_e2e.py -v
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    REPO_ROOT,
    assert_in_view,
    assert_vega_canvas_rendered,
    dismiss_toasts,
    frame_nodes,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: How many times each chart is hovered, and how many times it is resized.
HOVERS = 20
RESIZES = 20
SCENARIOS = ["No NbS", "All NbS"]
COLORS = ["#e76f51", "#2a9d8f"]
#: The minus sign his labels start with.
MINUS = "\N{MINUS SIGN}"

#: His Average depth by period node's rows: the average flood depth over the
#: riverside tracts' land, per period and scenario.
PERIOD_DEPTHS = [
    ["2020 - 2050", "No NbS", 0.412], ["2020 - 2050", "All NbS", 0.305],
    ["2050 - 2080", "No NbS", 0.538], ["2050 - 2080", "All NbS", 0.401],
    ["2080 - 2100", "No NbS", 0.627], ["2080 - 2100", "All NbS", 0.466],
]

#: Riverside tracts: FIPS, name, SVI percentile, and the average depth with No
#: NbS and with All NbS. Named as the census names them, which his chart
#: shortens to "Tract 101".
TRACTS = [
    ["19163010100", "Census Tract 101, Scott County, Iowa", 0.08, [0.42, 0.21]],
    ["19163010200", "Census Tract 102, Scott County, Iowa", 0.16, [0.95, 0.71]],
    ["19163010300", "Census Tract 103, Scott County, Iowa", 0.24, [0.61, 0.38]],
    ["19163010400", "Census Tract 104, Scott County, Iowa", 0.32, [1.21, 0.88]],
    ["19163010500", "Census Tract 105, Scott County, Iowa", 0.40, [0.77, 0.52]],
    ["19163010600", "Census Tract 106, Scott County, Iowa", 0.48, [1.36, 1.02]],
    ["17161020100", "Census Tract 201, Rock Island County, Illinois", 0.56, [0.54, 0.33]],
    ["17161020200", "Census Tract 202, Rock Island County, Illinois", 0.64, [1.08, 0.79]],
    ["17161020300", "Census Tract 203, Rock Island County, Illinois", 0.72, [0.88, 0.61]],
    ["17161020400", "Census Tract 204, Rock Island County, Illinois", 0.80, [1.29, 0.97]],
    ["17073030100", "Census Tract 301, Henry County, Illinois", 0.88, [0.69, 0.47]],
    ["17073030200", "Census Tract 302, Henry County, Illinois", 0.95, [1.17, 0.86]],
]

DEPTH_BY_PERIOD = (
    "import pandas as pd\n"
    "\n"
    "# One row per period and scenario, as his Average depth by period node returns them.\n"
    f"depths = {json.dumps(PERIOD_DEPTHS)}\n"
    "return pd.DataFrame([\n"
    '    {"period": period, "scenario_name": scenario, "mean_depth_m": depth, "land_km2": 61.84}\n'
    "    for period, scenario, depth in depths\n"
    "])\n"
)

def _tract_depth(k: int) -> str:
    """The code of a loader of each tract's average depth with scenario *k*: the
    chart stacks its inputs' rows in ``inputs``, input *k*'s under
    ``__input__`` *k*."""
    return (
        "import pandas as pd\n"
        "\n"
        f"# Each tract's average depth with {SCENARIOS[k]}.\n"
        f"tracts = {json.dumps(TRACTS)}\n"
        "return pd.DataFrame([\n"
        f'    {{"tract_fips": fips, "tract": name, "svi": svi, "mean_depth_m": depths[{k}]}}\n'
        "    for fips, name, svi, depths in tracts\n"
        "])\n"
    )

#: The rows of komar41's grouped bars from #1097: the sun hours a park loses,
#: per period of the day and per method that computes them.
SUN_METHODS = ["Ray casting", "Shadow map", "Sky view"]
SUN_LOST = [
    ["Morning", "Ray casting", 1.6], ["Morning", "Shadow map", 1.4], ["Morning", "Sky view", 1.1],
    ["Midday", "Ray casting", 2.9], ["Midday", "Shadow map", 2.7], ["Midday", "Sky view", 2.2],
    ["Afternoon", "Ray casting", 3.4], ["Afternoon", "Shadow map", 3.1], ["Afternoon", "Sky view", 2.6],
    ["Evening", "Ray casting", 1.2], ["Evening", "Shadow map", 0.9], ["Evening", "Sky view", 0.8],
]

SUN_LOST_BY_PERIOD = (
    "import pandas as pd\n"
    "\n"
    "# The sun hours the park loses, per period of the day and per method.\n"
    f"rows = {json.dumps(SUN_LOST)}\n"
    "return pd.DataFrame([\n"
    '    {"period": period, "method": method, "sun_lost_h": hours}\n'
    "    for period, method, hours in rows\n"
    "])\n"
)

#: The rows of the layered chart: per hour of the day, the share of the park in
#: shade and the sun hours it has lost so far.
SHADE_BY_HOUR = [
    [6, 92, 0.2], [7, 85, 0.5], [8, 74, 0.9], [9, 61, 1.2], [10, 48, 1.5],
    [11, 37, 1.7], [12, 30, 1.9], [13, 28, 2.1], [14, 33, 2.4], [15, 45, 2.8],
    [16, 58, 3.3], [17, 70, 3.9], [18, 81, 4.6], [19, 89, 5.3], [20, 95, 6.0],
]

SHADE_AND_SUN_BY_HOUR = (
    "import pandas as pd\n"
    "\n"
    "# Per hour of the day: the share of the park in shade, and the sun hours lost so far.\n"
    f"rows = {json.dumps(SHADE_BY_HOUR)}\n"
    "return pd.DataFrame([\n"
    '    {"hour": hour, "shaded_pct": shaded, "sun_lost_h": lost}\n'
    "    for hour, shaded, lost in rows\n"
    "])\n"
)

#: Rows of the shape example 03's computation node returns: a row per camera
#: and year, its total violations, for the five cameras with the most.
CAMERAS = ["CHI003", "CHI021", "CHI045", "CHI079", "CHI120"]
CAMERA_YEARS = list(range(2017, 2025))
CAMERA_VIOLATIONS = [
    [camera, year, 18000 + 4100 * c + 2300 * ((7 * year + 3 * c) % 9)]
    for c, camera in enumerate(CAMERAS)
    for year in CAMERA_YEARS
]

VIOLATIONS_BY_CAMERA = (
    "import pandas as pd\n"
    "\n"
    "# One row per camera and year, as example 03's computation node returns them.\n"
    f"rows = {json.dumps(CAMERA_VIOLATIONS)}\n"
    "return pd.DataFrame([\n"
    '    {"CAMERA ID": camera, "Year": year, "total_violations": total}\n'
    "    for camera, year, total in rows\n"
    "])\n"
)

_SCENARIO_COLOR = {
    "field": "scenario_name", "type": "nominal", "title": "Scenario",
    "scale": {"domain": SCENARIOS, "range": COLORS},
}
_PERIOD_X = {"field": "period", "type": "nominal", "title": None, "axis": {"labelAngle": 0}}
_SCENARIO_OFFSET = {"field": "scenario_name", "type": "nominal", "sort": SCENARIOS}
_DEPTH_Y = {"field": "mean_depth_m", "type": "quantitative", "title": "Average flood depth (m)"}
_SVI_X = {
    "field": "svi", "type": "quantitative", "title": "Social vulnerability (SVI percentile)",
    "scale": {"domain": [0, 1]},
}

#: His "Average flood depth, with and without NbS".
DEPTH_CHART = {
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "title": {
        "text": "Average flood depth, with and without NbS",
        "subtitle": "Land of the riverside tracts. Label: how much All NbS lowers it.",
    },
    "width": 440,
    "height": 280,
    "transform": [
        {"calculate": "datum.scenario_name == 'No NbS' ? datum.mean_depth_m : 0", "as": "none_m"},
        {"joinaggregate": [{"op": "sum", "field": "none_m", "as": "none_m"}], "groupby": ["period"]},
        {"calculate": "datum.none_m - datum.mean_depth_m", "as": "lowered_m"},
        {
            "calculate": "datum.scenario_name == 'All NbS' && datum.none_m > 0"
                         " ? '" + MINUS + "' + format(datum.lowered_m, '.2f') + ' m (" + MINUS + "'"
                         " + format(datum.lowered_m / datum.none_m, '.0%') + ')' : ''",
            "as": "less",
        },
    ],
    "layer": [
        {
            "mark": {"type": "bar"},
            "encoding": {
                "x": _PERIOD_X,
                "xOffset": _SCENARIO_OFFSET,
                "y": _DEPTH_Y,
                "color": _SCENARIO_COLOR,
                "tooltip": [
                    {"field": "period", "title": "Period"},
                    {"field": "scenario_name", "title": "Scenario"},
                    {"field": "mean_depth_m", "title": "Average depth (m)", "format": ".2f"},
                    {"field": "lowered_m", "title": "Lower than No NbS (m)", "format": ".2f"},
                ],
            },
        },
        {
            "mark": {"type": "text", "dy": -7, "fontWeight": "bold", "fontSize": 11},
            "encoding": {"x": _PERIOD_X, "xOffset": _SCENARIO_OFFSET, "y": _DEPTH_Y, "text": {"field": "less"}},
        },
    ],
}

#: His "Social vulnerability against average flood depth".
SVI_CHART = {
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "data": {"name": "inputs"},
    "transform": [
        {"calculate": "['No NbS', 'All NbS'][datum.__input__]", "as": "scenario_name"},
        {"filter": "isValid(datum.svi) && isValid(datum.mean_depth_m)"},
        {
            "calculate": "replace(replace(datum.tract, /, (Scott|Rock Island|Henry) County.*$/, ''),"
                         " 'Census Tract ', 'Tract ')",
            "as": "tract_short",
        },
    ],
    "title": {
        "text": "Social vulnerability against average flood depth",
        "subtitle": "Each riverside tract: its depth with No NbS and All NbS, joined.",
    },
    "width": 520,
    "height": 320,
    "layer": [
        {
            "transform": [
                {"pivot": "scenario_name", "value": "mean_depth_m", "groupby": ["tract_fips", "tract_short", "svi"]},
                {"calculate": "datum['No NbS'] - datum['All NbS']", "as": "lowered"},
            ],
            "params": [{
                "name": "hover",
                "select": {"type": "point", "fields": ["tract_fips"], "on": "pointerover", "clear": "pointerout"},
            }],
            "mark": {"type": "rule", "strokeWidth": 2},
            "encoding": {
                "x": _SVI_X,
                "y": {"field": "No NbS", "type": "quantitative"},
                "y2": {"field": "All NbS"},
                "color": {"condition": {"param": "hover", "empty": False, "value": "#333"}, "value": "#bbb"},
                "tooltip": [
                    {"field": "tract_short", "title": "Tract"},
                    {"field": "svi", "title": "SVI percentile", "format": ".2f"},
                    {"field": "No NbS", "title": "Average depth, No NbS (m)", "format": ".2f"},
                    {"field": "All NbS", "title": "Average depth, All NbS (m)", "format": ".2f"},
                    {"field": "lowered", "title": "Lowered by NbS (m)", "format": ".2f"},
                ],
            },
        },
        {
            "mark": {"type": "circle", "size": 70, "opacity": 0.9, "stroke": "#fff", "strokeWidth": 0.5},
            "encoding": {
                "x": _SVI_X,
                "y": {
                    "field": "mean_depth_m", "type": "quantitative",
                    "title": "Average flood depth over the tract's land (m)",
                },
                "color": _SCENARIO_COLOR,
                "tooltip": [
                    {"field": "tract_short", "title": "Tract"},
                    {"field": "scenario_name", "title": "Scenario"},
                    {"field": "svi", "title": "SVI percentile", "format": ".2f"},
                    {"field": "mean_depth_m", "title": "Average depth (m)", "format": ".2f"},
                ],
            },
        },
    ],
}

#: komar41's grouped bars, exactly as #1097 writes them.
SUN_LOST_BARS = {
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "width": 420,
    "height": 220,
    "mark": {"type": "bar", "tooltip": True},
    "encoding": {
        "x": {"field": "period", "type": "nominal"},
        "xOffset": {"field": "method", "type": "nominal"},
        "y": {"field": "sun_lost_h", "type": "quantitative"},
        "color": {"field": "method", "type": "nominal"},
    },
}

#: komar41's "layered area + line, 460x220, two y axes" from #1097, built from
#: that description, since the issue gives no spec for it: an area on the left
#: axis, and a line with points and tooltips on an independent right axis.
SHADE_AND_SUN = {
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "width": 460,
    "height": 220,
    "encoding": {
        "x": {"field": "hour", "type": "quantitative", "title": "Hour of the day", "scale": {"domain": [5, 21]}},
    },
    "layer": [
        {
            "mark": {"type": "area", "color": "#8fb3d9", "opacity": 0.6},
            "encoding": {"y": {"field": "shaded_pct", "type": "quantitative", "title": "Park in shade (%)"}},
        },
        {
            "mark": {"type": "line", "color": "#e76f51", "point": {"filled": True, "size": 50, "color": "#e76f51"}},
            "encoding": {
                "y": {"field": "sun_lost_h", "type": "quantitative", "title": "Sun lost so far (h)"},
                "tooltip": [
                    {"field": "hour", "type": "quantitative", "title": "Hour"},
                    {"field": "sun_lost_h", "type": "quantitative", "title": "Sun lost so far (h)", "format": ".1f"},
                ],
            },
        },
    ],
    "resolve": {"scale": {"y": "independent"}},
}


def _example_chart(path: str, node_id: str) -> dict:
    """The Vega-Lite spec of node *node_id* in the example at *path*."""
    with open(os.path.join(REPO_ROOT, path), encoding="utf-8") as fh:
        nodes = json.load(fh)["dataflow"]["nodes"]
    return json.loads(next(node["content"] for node in nodes if node["id"] == node_id))


#: Example 03's bar chart, as the example ships it.
EXAMPLE_03_BARS = _example_chart(
    "docs/examples/03-vega-lite-linked-temporal-charts.json", "c2ba6e0e-e239-4167-a382-ffd1993cb3d1",
)


def _flood_says(mark: dict, marktype: str) -> list[str]:
    """What the tooltip of one of his FloodRisk marks says about it."""
    if marktype == "rect":
        return [f"Period: {mark['period']}", f"Scenario: {mark['scenario']}"]
    if marktype == "rule":
        return [f"Tract: {mark['tract']}", "Lowered by NbS (m): "]
    return [f"Tract: {mark['tract']}", f"Scenario: {mark['scenario']}"]


def _sun_lost_says(mark: dict, marktype: str) -> list[str]:
    """What the tooltip of one of his grouped bars says about it: with
    ``"tooltip": true``, each encoded field, by its name."""
    return [f"period: {mark['datum']['period']}", f"method: {mark['datum']['method']}"]


def _shade_says(mark: dict, marktype: str) -> list[str]:
    """What the tooltip of a point on the layered chart's line says about it."""
    return [f"Hour: {mark['datum']['hour']}", "Sun lost so far (h): "]


@dataclass(frozen=True)
class Chart:
    slug: str
    title: str
    #: The loaders that feed the chart, each an id and its code, in the order
    #: of the chart's inputs.
    loaders: tuple[tuple[str, str], ...]
    node_id: str
    spec: dict
    #: The node's box: his, or big enough for the whole chart at its author's
    #: size.
    box: tuple[int, int]
    #: The scene graph's mark types hovered in turn: a bar is a ``rect``, a
    #: circle or a point a ``symbol``.
    hovered: tuple[str, ...]
    #: How many marks of each type the chart draws from these rows.
    marks: dict
    #: The fields of a hovered mark's datum that tell it from the others.
    keys: dict
    #: What the tooltip of a hovered mark says about it; None for a chart
    #: without tooltips.
    says: Callable[[dict, str], list[str]] | None
    #: The field marks of each type are colored by, and the values they name.
    colored: dict
    #: Whether the chart draws a legend.
    legend: bool

    @property
    def fixed(self) -> tuple[int, int]:
        return self.spec["width"], self.spec["height"]


CHARTS = [
    Chart(
        slug="depth-by-period",
        title="Average flood depth, with and without NbS",
        loaders=(("fixed-size-depth-loader", DEPTH_BY_PERIOD),),
        node_id="fixed-size-depth-chart",
        spec=DEPTH_CHART,
        box=(754, 432),
        hovered=("rect",),
        marks={"rect": len(PERIOD_DEPTHS)},
        keys={"rect": ("period", "scenario_name")},
        says=_flood_says,
        colored={"rect": ("scenario_name", SCENARIOS)},
        legend=True,
    ),
    Chart(
        slug="svi-against-depth",
        title="Social vulnerability against average flood depth",
        loaders=(("fixed-size-svi-loader", _tract_depth(0)), ("fixed-size-svi-loader-all-nbs", _tract_depth(1))),
        node_id="fixed-size-svi-chart",
        spec=SVI_CHART,
        box=(748, 476),
        hovered=("rule", "symbol"),
        marks={"rule": len(TRACTS), "symbol": 2 * len(TRACTS)},
        keys={"rule": ("tract_fips",), "symbol": ("tract_fips", "scenario_name")},
        says=_flood_says,
        colored={"symbol": ("scenario_name", SCENARIOS)},
        legend=True,
    ),
    Chart(
        slug="sun-lost-bars",
        title="Sun hours lost by period and method",
        loaders=(("fixed-size-sun-loader", SUN_LOST_BY_PERIOD),),
        node_id="fixed-size-sun-chart",
        spec=SUN_LOST_BARS,
        box=(780, 440),
        hovered=("rect",),
        marks={"rect": len(SUN_LOST)},
        keys={"rect": ("period", "method")},
        says=_sun_lost_says,
        colored={"rect": ("method", SUN_METHODS)},
        legend=True,
    ),
    Chart(
        slug="shade-and-sun",
        title="Park in shade and sun lost over the day",
        loaders=(("fixed-size-shade-loader", SHADE_AND_SUN_BY_HOUR),),
        node_id="fixed-size-shade-chart",
        spec=SHADE_AND_SUN,
        box=(800, 440),
        hovered=("symbol",),
        marks={"symbol": len(SHADE_BY_HOUR)},
        keys={"symbol": ("hour",)},
        says=_shade_says,
        colored={},
        legend=False,
    ),
    Chart(
        slug="example-03-bars",
        title="Total violations by camera and year",
        loaders=(("fixed-size-camera-loader", VIOLATIONS_BY_CAMERA),),
        node_id="fixed-size-camera-chart",
        spec=EXAMPLE_03_BARS,
        box=(720, 480),
        hovered=("rect",),
        marks={"rect": len(CAMERA_VIOLATIONS)},
        keys={"rect": ("Year", "CAMERA ID")},
        says=None,
        colored={"rect": ("CAMERA ID", CAMERAS)},
        legend=True,
    ),
]

# Before the page's own scripts: keep every Vega view by the element it draws
# in, whenever useVega.ts sets the charts' Vega module on the window.
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

# The chart's plot: the view's width and height signals, which size the plot,
# and its root group's box, which Vega draws them as; then what sizes the rest:
# the view size Vega lays the chart out in (_width, _height), the canvas's CSS
# size, the mount's visible and scrolled size, the origin, and the autosize the
# view runs with. With *resize*, the view is first resized as the node's resize
# observer resizes it. With *settle*, the view runs twice before the read: with
# resize: true each run asks for another layout, which the next update does.
_PLOT_JS = """async ([id, settle, resize]) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    const mount = document.getElementById("vega" + id);
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!view || !canvas || !mount) return null;
    if (resize) await view.resize().runAsync();
    if (settle) {
        await view.runAsync();
        await view.runAsync();
    }
    const root = view.scenegraph().root;
    const group = (root && root.items && root.items[0]) || {};
    return {
        plot: [view.width(), view.height()],
        group: [group.width ?? null, group.height ?? null],
        viewSize: [view._width ?? null, view._height ?? null],
        canvas: [canvas.offsetWidth, canvas.offsetHeight],
        mount: [mount.clientWidth, mount.clientHeight, mount.scrollWidth, mount.scrollHeight],
        origin: view.origin(),
        autosize: view.autosize(),
    };
}"""

# The marks of one type the chart draws, where the page shows each one's
# middle, from the view's scene graph as it is now: an item's bounds are in its
# group's coordinates, and the canvas draws the root group at the view's origin
# plus its padding, scaled as the canvas is (the canvas zooms with the dataflow).
# Each comes with its datum's plain fields.
_MARKS_JS = """([id, marktype]) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!view || !canvas || !canvas.offsetWidth || !canvas.offsetHeight) return null;
    const box = canvas.getBoundingClientRect();
    const sx = box.width / canvas.offsetWidth, sy = box.height / canvas.offsetHeight;
    const pad = view.padding(), origin = view.origin();
    const plain = (d) => {
        const fields = {};
        for (const [k, v] of Object.entries(d || {})) {
            if (v === null || ["string", "number", "boolean"].includes(typeof v)) fields[k] = v;
        }
        return fields;
    };
    const found = [];
    const visit = (mark, dx, dy) => {
        if (!mark) return;
        if (mark.marktype === marktype && mark.role === "mark") {
            for (const item of mark.items || []) {
                const b = item.bounds;
                if (!b || !(b.x2 >= b.x1) || !(b.y2 >= b.y1)) continue;
                const d = item.datum || {};
                found.push({
                    x: box.left + (pad.left + origin[0] + dx + (b.x1 + b.x2) / 2) * sx,
                    y: box.top + (pad.top + origin[1] + dy + (b.y1 + b.y2) / 2) * sy,
                    width: (b.x2 - b.x1) * sx,
                    height: (b.y2 - b.y1) * sy,
                    period: d.period ?? null,
                    scenario: d.scenario_name ?? null,
                    tract: d.tract_short ?? null,
                    fips: d.tract_fips ?? null,
                    datum: plain(d),
                });
            }
            return;
        }
        if (mark.marktype === "group") {
            for (const group of mark.items || []) {
                for (const child of group.items || []) visit(child, dx + (group.x || 0), dy + (group.y || 0));
            }
        }
    };
    visit(view.scenegraph().root, 0, 0);
    return found;
}"""

# How many legends the chart draws.
_LEGENDS_JS = """(id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    if (!view) return null;
    let legends = 0;
    const visit = (mark) => {
        if (!mark) return;
        if (mark.role === "legend") legends += (mark.items || []).length;
        if (mark.marktype !== "group") return;
        for (const group of mark.items || []) for (const child of group.items || []) visit(child);
    };
    visit(view.scenegraph().root);
    return legends;
}"""

# Vega's tooltip, which Curio's handler writes as the data-tooltip of the
# element the chart draws in: the hovered mark's fields, one "Title: value" per
# line.
_TOOLTIP_JS = """(id) => {
    const el = document.getElementById("vega" + id);
    return el ? (el.getAttribute("data-tooltip") || "") : null;
}"""
_TOOLTIP_NAMES_JS = """([id, parts]) => {
    const el = document.getElementById("vega" + id);
    const tip = el && el.getAttribute("data-tooltip");
    return !!tip && parts.every((part) => tip.includes(part));
}"""
_TOOLTIP_CLEARED_JS = """(id) => {
    const el = document.getElementById("vega" + id);
    return !!el && !el.getAttribute("data-tooltip");
}"""

# The item Vega holds under the pointer: the one its canvas handler picked on
# the last pointer move over the canvas, null once the pointer left it. A hover
# runs the view on that item whether or not the chart has a tooltip.
_UNDER_POINTER_JS = """(id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    const item = view && view._handler && view._handler._active;
    if (!item || !item.mark) return null;
    const datum = {};
    for (const [k, v] of Object.entries(item.datum || {})) {
        if (v === null || ["string", "number", "boolean"].includes(typeof v)) datum[k] = v;
    }
    return {mark: item.mark.marktype, datum};
}"""
_POINTER_ON_JS = """([id, marktype, key]) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    const item = view && view._handler && view._handler._active;
    return !!item && !!item.mark && item.mark.marktype === marktype && !!item.datum
        && Object.entries(key).every(([field, value]) => item.datum[field] === value);
}"""
_POINTER_OFF_JS = """(id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    return !!view && !!view._handler && !view._handler._active;
}"""

# What the rules' hover select holds.
_HOVER_SELECT_JS = """(id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    try {
        return view ? JSON.stringify(view.signal("hover")) : null;
    } catch (e) {
        return null;
    }
}"""

_CANVAS_AT_JS = """([id, x, y]) =>
    document.elementFromPoint(x, y) === document.querySelector(`#vega${id} canvas`)"""

# A point in the window beside the chart's canvas, off every mark.
_OFF_CHART_JS = """(id) => {
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!canvas) return null;
    const box = canvas.getBoundingClientRect();
    const middle = [box.left + box.width / 2, box.top + box.height / 2];
    for (const [x, y] of [[box.left - 24, middle[1]], [box.right + 24, middle[1]],
                          [middle[0], box.bottom + 24], [middle[0], box.top - 24]]) {
        if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) continue;
        const el = document.elementFromPoint(x, y);
        if (el && el !== canvas) return [x, y];
    }
    return null;
}"""


def _dataflow(chart: Chart) -> dict:
    def node(node_id: str, node_type: str, x: int, y: int, content: str, **box) -> dict:
        return {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []}, **box,
        }

    def handle(k: int) -> str:
        """The chart's *k*-th input circle."""
        return "in" if k == 0 else f"in_{k}"

    name = f"{chart.title}, fixed size"
    return {"dataflow": {
        "name": name,
        "task": "",
        "timestamp": 1789193389280,
        "provenance_id": name,
        "nodes": [
            *(node(loader_id, "curio.builtin/data-loading", 0, 420 * k, code)
              for k, (loader_id, code) in enumerate(chart.loaders)),
            node(chart.node_id, "curio.builtin/vis-vega", 620, 0, json.dumps(chart.spec, indent=2),
                 title=chart.title, width=chart.box[0], height=chart.box[1]),
        ],
        "edges": [
            {
                "id": f"reactflow__edge-{loader_id}out-{chart.node_id}{handle(k)}",
                "source": loader_id, "target": chart.node_id, "sourceHandle": "out", "targetHandle": handle(k),
            }
            for k, (loader_id, _code) in enumerate(chart.loaders)
        ],
    }}


def _size(plot: dict) -> tuple:
    """What the test holds the chart to: the plot's size, and its group's box."""
    return tuple(plot["plot"]), tuple(plot["group"])


def _settled_plot(page, node_id: str, *, reads: int = 5, timeout_s: float = 30) -> tuple[dict, list[dict]]:
    """The chart's plot once it has stopped moving: the same in *reads* reads in
    a row, 200 ms apart, read without running the view. A drawn chart is
    resized once more after its first draw, and again by its mount's resize
    observer. Returns that plot and no reads; or, for a plot that kept moving,
    its last read and the last *reads* reads, which the test reports once it
    has measured the rest."""
    def drawn(plot: dict) -> tuple:
        return _size(plot) + (tuple(plot["canvas"]),)

    seen: list[dict] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        plot = page.evaluate(_PLOT_JS, [node_id, False, False])
        if plot:
            seen.append(plot)
            last = seen[-reads:]
            if len(last) == reads and all(drawn(p) == drawn(plot) for p in last):
                return plot, []
        page.wait_for_timeout(200)
    assert seen, f"chart {node_id} has no view or no canvas"
    return seen[-1], seen[-reads:]


def _plot_after(page, node_id: str) -> dict:
    """The chart's plot once the view has run the layouts it asked for."""
    plot = page.evaluate(_PLOT_JS, [node_id, True, False])
    assert plot, f"chart {node_id} has no view or no canvas"
    return plot


def _marks(page, node_id: str, marktype: str) -> list[dict]:
    marks = page.evaluate(_MARKS_JS, [node_id, marktype])
    assert marks is not None, f"chart {node_id} has no view or no canvas"
    return marks


def _targets(marks: list[dict], marktype: str) -> list[dict]:
    """The marks a hover can land on, left to right: a rule long enough that its
    middle is clear of its two circles, a circle clear of every other one."""
    if marktype == "rule":
        marks = [m for m in marks if m["height"] >= 20]
    elif marktype == "symbol":
        marks = [m for m in marks
                 if all((m["x"] - o["x"]) ** 2 + (m["y"] - o["y"]) ** 2 >= 12 ** 2 for o in marks if o is not m)]
    return sorted(marks, key=lambda m: (m["x"], m["y"]))


def _hover_once(page, chart: Chart, k: int) -> dict:
    """Hover chart *chart*'s marks the *k*-th time: onto a mark where it is
    drawn now, until Vega holds that mark under the pointer and, on a chart with
    tooltips, its tooltip names it; then off the chart until Vega holds no mark
    and the tooltip clears. Returns what the hover reached and the plot after
    it."""
    node_id = chart.node_id
    marktype = chart.hovered[k % len(chart.hovered)]
    record: dict = {"hover": k + 1, "mark": marktype}
    targets = _targets(_marks(page, node_id, marktype), marktype)
    if not targets:
        record["missed"] = f"no {marktype} to hover"
        record.update(_plot_after(page, node_id))
        return record
    target = targets[(k // len(chart.hovered)) % len(targets)]
    key = {field: target["datum"].get(field) for field in chart.keys[marktype]}
    names = chart.says(target, marktype) if chart.says else []
    record["target"] = names[0] if names else ", ".join(f"{field}: {value}" for field, value in key.items())
    landed = held = False
    # A rule is two pixels wide: if its middle misses by rounding, try beside it.
    for dx in (0, -0.6, 0.6, -1.2, 1.2):
        x, y = assert_in_view(page, target["x"] + dx, target["y"], f"{record['target']} in chart {node_id}")
        assert page.evaluate(_CANVAS_AT_JS, [node_id, x, y]), (
            f"something covers chart {node_id} at ({x:.0f}, {y:.0f}), where {record['target']} is drawn"
        )
        page.mouse.move(x, y)
        try:
            page.wait_for_function(_POINTER_ON_JS, arg=[node_id, marktype, key], timeout=2000)
            held = True
            if names:
                page.wait_for_function(_TOOLTIP_NAMES_JS, arg=[node_id, names], timeout=2000)
            landed = True
            break
        except PlaywrightTimeoutError:
            continue
    record["under"] = page.evaluate(_UNDER_POINTER_JS, node_id)
    record["tooltip"] = page.evaluate(_TOOLTIP_JS, node_id)
    if not landed:
        record["missed"] = (
            f"the tooltip never named {names}" if held
            else f"Vega never held the {marktype} {key} under the pointer: it held {record['under']}"
        )
    if marktype == "rule":
        record["select"] = page.evaluate(_HOVER_SELECT_JS, node_id)
        if landed and target["fips"] not in (record["select"] or ""):
            record["missed"] = f"the hover select holds {record['select']}, not {target['fips']}"
    off = page.evaluate(_OFF_CHART_JS, node_id)
    assert off, f"no point beside chart {node_id}'s canvas is in the window"
    page.mouse.move(*off)
    try:
        page.wait_for_function(_POINTER_OFF_JS, arg=node_id, timeout=5000)
    except PlaywrightTimeoutError:
        record["missed"] = (
            f"Vega still held {page.evaluate(_UNDER_POINTER_JS, node_id)} after the pointer left the chart"
        )
    try:
        page.wait_for_function(_TOOLTIP_CLEARED_JS, arg=node_id, timeout=5000)
    except PlaywrightTimeoutError:
        record["missed"] = f"the tooltip stayed after the pointer left: {page.evaluate(_TOOLTIP_JS, node_id)!r}"
    if marktype == "rule":
        left = page.evaluate(_HOVER_SELECT_JS, node_id)
        if target["fips"] in (left or ""):
            record["missed"] = f"the hover select still holds {left} after the pointer left"
    record.update(_plot_after(page, node_id))
    return record


def _resize_once(page, node_id: str, k: int) -> dict:
    """Resize the chart the *k*-th time, as its node's resize observer does:
    ``view.resize().runAsync()`` in the page. Returns the plot after it."""
    plot = page.evaluate(_PLOT_JS, [node_id, True, True])
    assert plot, f"chart {node_id} has no view or no canvas"
    return {"resize": k + 1, **plot}


def _brief(record: dict, what: str = "hover") -> str:
    plot, group = _size(record)
    return f"{record[what]}: plot {plot[0]}x{plot[1]}, group {group[0]}x{group[1]}, view {record['viewSize']}"


def _drawing(chart: Chart, legends, drawn: dict, clear: dict) -> str:
    """What the chart drew before the hovers, as the checks after the sizes read
    it: its legends, its marks of each type and the values they are colored
    by, and the marks clear enough to hover."""
    colored = {
        marktype: sorted({str(m["datum"].get(field)) for m in drawn[marktype]})
        for marktype, (field, _values) in chart.colored.items()
    }
    counts = {marktype: len(marks) for marktype, marks in drawn.items()}
    return f"legends {legends}, marks {json.dumps(counts)}, colored {json.dumps(colored)}, clear {json.dumps(clear)}"


def _measured(chart: Chart, before: dict, unsettled: list[dict], drawing: str,
              hovers: list[dict], resizes: list[dict]) -> str:
    """What the test measured, one line per chart for the CI log."""
    fields = ("plot", "group", "viewSize", "canvas", "mount")
    each_hover = [{k: h.get(k) for k in ("hover", "mark", "target") + fields + ("missed",)} for h in hovers]
    each_resize = [{k: r.get(k) for k in ("resize",) + fields} for r in resizes]
    return (
        f"[vega-fixed-size] {chart.slug}: spec {chart.fixed[0]}x{chart.fixed[1]}, autosize {before['autosize']}, "
        f"first draw plot {before['plot']} group {before['group']} view {before['viewSize']} "
        f"canvas {before['canvas']} mount {before['mount']} origin {before['origin']}"
        f"{' (still moving: ' + json.dumps([u['plot'] for u in unsettled]) + ')' if unsettled else ''}; "
        f"{drawing}; "
        f"after hover {HOVERS} plot {hovers[-1]['plot']} group {hovers[-1]['group']} view {hovers[-1]['viewSize']} "
        f"canvas {hovers[-1]['canvas']}; after resize {RESIZES} plot {resizes[-1]['plot']} "
        f"group {resizes[-1]['group']} view {resizes[-1]['viewSize']} canvas {resizes[-1]['canvas']}; "
        f"each hover: {json.dumps(each_hover)}; each resize: {json.dumps(each_resize)}"
    )


@pytest.mark.parametrize("chart", CHARTS, ids=[chart.slug for chart in CHARTS])
def test_a_chart_draws_its_plot_at_its_authors_size_through_hovers_and_resizes(
    app_frontend: "FrontendPage", current_server: str, page, capsys, chart: Chart,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    spec = _dataflow(chart)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Fixed Size Chart",
        username=f"vega_fixed_{chart.slug.replace('-', '_')}",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    run_all_and_wait(page, timeout_ms=180000)
    status = wait_for_node_settled(page, chart.node_id, node_type="vis-vega", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, chart.node_id)) if status == "error" else ""
    assert status == "done", f"{chart.title} did not draw: {detail}"
    assert_vega_canvas_rendered(page, chart.node_id)
    dismiss_toasts(page)
    frame_nodes(page, [chart.node_id])

    # The chart at its first draw: its plot, its legend, and a mark for every row.
    before, unsettled = _settled_plot(page, chart.node_id)
    legends = page.evaluate(_LEGENDS_JS, chart.node_id)
    drawn = {marktype: _marks(page, chart.node_id, marktype) for marktype in chart.marks}
    clear = {marktype: len(_targets(_marks(page, chart.node_id, marktype), marktype)) for marktype in chart.hovered}

    hovers = [_hover_once(page, chart, k) for k in range(HOVERS)]
    resizes = [_resize_once(page, chart.node_id, k) for k in range(RESIZES)]
    # Past pytest's capture, so a passing run's log holds the sizes too.
    with capsys.disabled():
        drawing = _drawing(chart, legends, drawn, clear)
        print("\n" + _measured(chart, before, unsettled, drawing, hovers, resizes), flush=True)

    width, height = chart.fixed
    authored = ((width, height), (width, height))
    assert _size(before) == authored, (
        f"{chart.title}, {width}x{height} in its spec, drew its plot at {before['plot'][0]}x{before['plot'][1]} "
        f"(group {before['group'][0]}x{before['group'][1]}), not {width}x{height}: view {before['viewSize']}, "
        f"canvas {before['canvas']}, origin {before['origin']}, autosize {before['autosize']}"
    )
    off_size = [h for h in hovers if _size(h) != authored]
    assert not off_size, (
        f"{chart.title}, {width}x{height} in its spec: after {len(off_size)} of {HOVERS} hovers its plot was not "
        f"{width}x{height}: " + "; ".join(_brief(h) for h in off_size)
    )
    off_size = [r for r in resizes if _size(r) != authored]
    assert not off_size, (
        f"{chart.title}, {width}x{height} in its spec: after {len(off_size)} of {RESIZES} resizes its plot was not "
        f"{width}x{height}: " + "; ".join(_brief(r, "resize") for r in off_size)
    )
    assert not unsettled, f"chart {chart.node_id}'s plot never settled before any hover: {unsettled}"

    # His chart as he drew it: its legend, and a mark for every row.
    assert all(isinstance(v, (int, float)) and v > 0 for v in before["plot"] + before["group"]), (
        f"{chart.title}'s view gives no plot size to hold: {before}"
    )
    if chart.legend:
        assert legends and legends >= 1, f"{chart.title} draws no legend: {legends}"
    else:
        assert legends == 0, f"{chart.title} draws {legends} legends, not none"
    for marktype, count in chart.marks.items():
        marks = drawn[marktype]
        assert len(marks) == count, f"{chart.title} draws {len(marks)} {marktype} marks, not {count}"
        if marktype in chart.colored:
            field, values = chart.colored[marktype]
            named = sorted({m["datum"].get(field) for m in marks})
            assert named == sorted(values), f"{chart.title}'s {marktype} marks name the {field} values {named}"
    for marktype in chart.hovered:
        assert clear[marktype] >= 4, f"{chart.title} draws fewer than four {marktype} marks clear enough to hover"

    changed = [h for h in hovers if _size(h) != _size(before)]
    assert not changed, (
        f"{chart.title}, fixed at {width}x{height}: the plot changed size under the pointer. "
        f"Before the hovers: plot {before['plot'][0]}x{before['plot'][1]}, group "
        f"{before['group'][0]}x{before['group'][1]}, view {before['viewSize']}, canvas {before['canvas']}, "
        f"autosize {before['autosize']}. After each hover: " + "; ".join(_brief(h) for h in hovers)
    )
    missed = [h for h in hovers if h.get("missed")]
    assert not missed, (
        f"{chart.title}: {len(missed)} of {HOVERS} hovers did not reach their mark: "
        + "; ".join(f"{h['hover']} ({h.get('target')}): {h['missed']}" for h in missed)
    )
