"""Playwright E2E: a Vega-Lite chart whose author fixed its size keeps its plot through hovers.

komar41, reviewing what main took from his #914, reported that a chart whose
author fixed both its width and its height shrinks: on his layered charts with
a legend, the plot gave way to the axes and the legend, one hover at a time.

Main sizes a Vega-Lite spec in ``utils/vegaSpecSizing.ts``, which ``useVega``'s
``compileGrammar`` calls. A width or a height the author left out follows the
node, and a spec that sets no ``autosize`` gets ``{"type": "fit", "contains":
"padding", "resize": true}``, even when its author fixed both sizes. ``fit``
fits the whole chart, axes and legend included, into the given size, and
``resize: true`` has Vega lay the view out again on every update. A hover is an
update.

The two charts are his, from the FloodRisk dataflow on his #914, typed again
here: their titles and subtitles, fixed sizes, layers, tooltips, the ``hover``
select and the scenario legend, in nodes of the sizes he gave them.

* Average flood depth, with and without NbS: 440x280, a bar per period and
  scenario with a label above, colored by scenario.
* Social vulnerability against average flood depth: 520x320, a rule per tract
  from its No NbS depth to its All NbS depth, which the pointer darkens, under
  a circle per tract and scenario.

The second chart reads ``inputs``, his #914's stacked dataset (each input's
rows, with ``__input__``), which main does not have. Here its one input holds
those stacked rows, ``__input__`` included, and main hands them to the spec as
its data, so the spec stays his.

Each chart is hovered 20 times. The pointer moves onto one of its marks, found
where the view's scene graph draws it now, and stays until the tooltip Vega
writes on the chart's element names that mark (on a rule, the ``hover`` select
holds its tract too). Then it leaves the chart and the tooltip clears. After
every hover the plot, the view's ``width`` and ``height`` and its root group's
box, must keep the size it had before the first one.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_vega_fixed_size_e2e.py -v
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
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

#: How many times each chart is hovered.
HOVERS = 20
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

TRACT_DEPTH = (
    "import pandas as pd\n"
    "\n"
    "# Each tract's average depth, No NbS then All NbS, stacked as his #914 stacks\n"
    "# a node's inputs: each input's rows, with __input__.\n"
    f"tracts = {json.dumps(TRACTS)}\n"
    "return pd.DataFrame([\n"
    '    {"tract_fips": fips, "tract": name, "svi": svi, "mean_depth_m": depths[k], "__input__": k}\n'
    "    for k in (0, 1)\n"
    "    for fips, name, svi, depths in tracts\n"
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


@dataclass(frozen=True)
class Chart:
    slug: str
    title: str
    loader_id: str
    loader: str
    node_id: str
    spec: dict
    #: The node's box, as he sized it.
    box: tuple[int, int]
    #: The scene graph's mark types hovered in turn: a bar is a ``rect``, a
    #: circle a ``symbol``.
    hovered: tuple[str, ...]
    #: How many marks of each type his chart draws from these rows.
    marks: dict

    @property
    def fixed(self) -> tuple[int, int]:
        return self.spec["width"], self.spec["height"]


CHARTS = [
    Chart(
        slug="depth-by-period",
        title="Average flood depth, with and without NbS",
        loader_id="fixed-size-depth-loader",
        loader=DEPTH_BY_PERIOD,
        node_id="fixed-size-depth-chart",
        spec=DEPTH_CHART,
        box=(754, 432),
        hovered=("rect",),
        marks={"rect": len(PERIOD_DEPTHS)},
    ),
    Chart(
        slug="svi-against-depth",
        title="Social vulnerability against average flood depth",
        loader_id="fixed-size-svi-loader",
        loader=TRACT_DEPTH,
        node_id="fixed-size-svi-chart",
        spec=SVI_CHART,
        box=(748, 476),
        hovered=("rule", "symbol"),
        marks={"rule": len(TRACTS), "symbol": 2 * len(TRACTS)},
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
# size, the origin, and the autosize the view runs with. With *settle*, the
# view runs twice first: with resize: true each run asks for another layout,
# which the next update does.
_PLOT_JS = """async ([id, settle]) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!view || !canvas) return null;
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
        origin: view.origin(),
        autosize: view.autosize(),
    };
}"""

# The marks of one type the chart draws, where the page shows each one's
# middle, from the view's scene graph as it is now: an item's bounds are in its
# group's coordinates, and the canvas draws the root group at the view's origin
# plus its padding, scaled as the canvas is (the canvas zooms with the dataflow).
_MARKS_JS = """([id, marktype]) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!view || !canvas || !canvas.offsetWidth || !canvas.offsetHeight) return null;
    const box = canvas.getBoundingClientRect();
    const sx = box.width / canvas.offsetWidth, sy = box.height / canvas.offsetHeight;
    const pad = view.padding(), origin = view.origin();
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

# Vega's own tooltip, which it writes as the title of the element the chart
# draws in: the hovered mark's fields, one "Title: value" per line.
_TOOLTIP_JS = """(id) => {
    const el = document.getElementById("vega" + id);
    return el ? (el.getAttribute("title") || "") : null;
}"""
_TOOLTIP_NAMES_JS = """([id, parts]) => {
    const el = document.getElementById("vega" + id);
    const title = el && el.getAttribute("title");
    return !!title && parts.every((part) => title.includes(part));
}"""
_TOOLTIP_CLEARED_JS = """(id) => {
    const el = document.getElementById("vega" + id);
    return !!el && !el.getAttribute("title");
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
    def node(node_id: str, node_type: str, x: int, content: str, **box) -> dict:
        return {
            "id": node_id, "type": node_type, "x": x, "y": 0, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []}, **box,
        }

    name = f"{chart.title}, fixed size"
    return {"dataflow": {
        "name": name,
        "task": "",
        "timestamp": 1789193389280,
        "provenance_id": name,
        "nodes": [
            node(chart.loader_id, "curio.builtin/data-loading", 0, chart.loader),
            node(chart.node_id, "curio.builtin/vis-vega", 620, json.dumps(chart.spec, indent=2),
                 title=chart.title, width=chart.box[0], height=chart.box[1]),
        ],
        "edges": [{
            "id": f"reactflow__edge-{chart.loader_id}out-{chart.node_id}in",
            "source": chart.loader_id, "target": chart.node_id, "sourceHandle": "out", "targetHandle": "in",
        }],
    }}


def _size(plot: dict) -> tuple:
    """What the test holds the chart to: the plot's size, and its group's box."""
    return tuple(plot["plot"]), tuple(plot["group"])


def _settled_plot(page, node_id: str, *, reads: int = 5, timeout_s: float = 30) -> dict:
    """The chart's plot once it has stopped moving: the same in *reads* reads in
    a row, 200 ms apart, read without running the view. A drawn chart is
    resized once more after its first draw, and again by its mount's resize
    observer."""
    def drawn(plot: dict) -> tuple:
        return _size(plot) + (tuple(plot["canvas"]),)

    seen: list[dict] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        plot = page.evaluate(_PLOT_JS, [node_id, False])
        if plot:
            seen.append(plot)
            last = seen[-reads:]
            if len(last) == reads and all(drawn(p) == drawn(plot) for p in last):
                return plot
        page.wait_for_timeout(200)
    raise AssertionError(f"chart {node_id}'s plot never settled before any hover: {seen[-reads:]}")


def _plot_after(page, node_id: str) -> dict:
    """The chart's plot once the view has run the layouts it asked for."""
    plot = page.evaluate(_PLOT_JS, [node_id, True])
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


def _names(mark: dict, marktype: str) -> list[str]:
    """What the tooltip of *mark* says about it."""
    if marktype == "rect":
        return [f"Period: {mark['period']}", f"Scenario: {mark['scenario']}"]
    if marktype == "rule":
        return [f"Tract: {mark['tract']}", "Lowered by NbS (m): "]
    return [f"Tract: {mark['tract']}", f"Scenario: {mark['scenario']}"]


def _hover_once(page, chart: Chart, k: int) -> dict:
    """Hover chart *chart*'s marks the *k*-th time: onto a mark where it is
    drawn now, until its tooltip names it, then off the chart until the tooltip
    clears. Returns what the hover reached and the plot after it."""
    node_id = chart.node_id
    marktype = chart.hovered[k % len(chart.hovered)]
    record: dict = {"hover": k + 1, "mark": marktype}
    targets = _targets(_marks(page, node_id, marktype), marktype)
    if not targets:
        record["missed"] = f"no {marktype} to hover"
        record.update(_plot_after(page, node_id))
        return record
    target = targets[(k // len(chart.hovered)) % len(targets)]
    names = _names(target, marktype)
    record["target"] = names[0]
    landed = False
    # A rule is two pixels wide: if its middle misses by rounding, try beside it.
    for dx in (0, -0.6, 0.6, -1.2, 1.2):
        x, y = assert_in_view(page, target["x"] + dx, target["y"], f"{names[0]} in chart {node_id}")
        assert page.evaluate(_CANVAS_AT_JS, [node_id, x, y]), (
            f"something covers chart {node_id} at ({x:.0f}, {y:.0f}), where {names[0]} is drawn"
        )
        page.mouse.move(x, y)
        try:
            page.wait_for_function(_TOOLTIP_NAMES_JS, arg=[node_id, names], timeout=2000)
            landed = True
            break
        except PlaywrightTimeoutError:
            continue
    record["tooltip"] = page.evaluate(_TOOLTIP_JS, node_id)
    if not landed:
        record["missed"] = f"the tooltip never named {names}"
    if marktype == "rule":
        record["select"] = page.evaluate(_HOVER_SELECT_JS, node_id)
        if landed and target["fips"] not in (record["select"] or ""):
            record["missed"] = f"the hover select holds {record['select']}, not {target['fips']}"
    off = page.evaluate(_OFF_CHART_JS, node_id)
    assert off, f"no point beside chart {node_id}'s canvas is in the window"
    page.mouse.move(*off)
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


def _brief(record: dict) -> str:
    plot, group = _size(record)
    return f"{record['hover']}: plot {plot[0]}x{plot[1]}, group {group[0]}x{group[1]}, view {record['viewSize']}"


def _measured(chart: Chart, before: dict, hovers: list[dict]) -> str:
    """What the test measured, one line per chart for the CI log."""
    series = [{k: h.get(k) for k in ("hover", "mark", "target", "plot", "group", "viewSize", "canvas", "missed")}
              for h in hovers]
    return (
        f"[vega-fixed-size] {chart.slug}: fixed {chart.fixed[0]}x{chart.fixed[1]}, autosize {before['autosize']}, "
        f"before the hovers plot {before['plot']} group {before['group']} view {before['viewSize']} "
        f"canvas {before['canvas']} origin {before['origin']}; after hover {HOVERS} plot {hovers[-1]['plot']} "
        f"group {hovers[-1]['group']} view {hovers[-1]['viewSize']} canvas {hovers[-1]['canvas']}; "
        f"each hover: {json.dumps(series)}"
    )


@pytest.mark.parametrize("chart", CHARTS, ids=[chart.slug for chart in CHARTS])
def test_a_chart_of_fixed_size_keeps_its_plot_through_twenty_hovers(
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

    # His chart as he drew it: its legend, and a mark for every row.
    before = _settled_plot(page, chart.node_id)
    assert all(isinstance(v, (int, float)) and v > 0 for v in before["plot"] + before["group"]), (
        f"{chart.title}'s view gives no plot size to hold: {before}"
    )
    legends = page.evaluate(_LEGENDS_JS, chart.node_id)
    assert legends and legends >= 1, f"{chart.title} draws no legend: {legends}"
    for marktype, count in chart.marks.items():
        marks = _marks(page, chart.node_id, marktype)
        assert len(marks) == count, f"{chart.title} draws {len(marks)} {marktype} marks, not {count}"
        if marktype in ("rect", "symbol"):
            assert sorted({m["scenario"] for m in marks}) == sorted(SCENARIOS), (
                f"{chart.title}'s {marktype} marks name the scenarios {sorted({m['scenario'] for m in marks})}"
            )
    for marktype in chart.hovered:
        assert len(_targets(_marks(page, chart.node_id, marktype), marktype)) >= 4, (
            f"{chart.title} draws fewer than four {marktype} marks clear enough to hover"
        )

    hovers = [_hover_once(page, chart, k) for k in range(HOVERS)]
    # Past pytest's capture, so a passing run's log holds the sizes too.
    with capsys.disabled():
        print("\n" + _measured(chart, before, hovers), flush=True)

    width, height = chart.fixed
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
