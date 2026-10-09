"""Playwright E2E: a selection named by key columns lights the right rows of a chart over other rows.

A chart over six units is joined by a direct interaction edge, with no Data
Pool, to a chart over three readings per unit. The readings were taken in
rounds of a shuffled order, so the reading at a unit's row position belongs
to another unit: only a selection that names the units by their ``unit_id``
lights the right readings. A Vega-Lite point select over fields sends those
values (#847), and so does an Autark map or plot whose spec names
``selectFields``.

One test per pair of chart kinds. Each first asserts, from the fixture, that
the readings at the picked units' row positions belong to other units, then
that exactly the picked units' readings light up:

* Vega-Lite to Vega-Lite (guard): a click on unit 103's bar turns its three
  readings red in the readings chart.
* Vega-Lite to Autark (guard): the same click lights its three bars in an
  Autark bar plot of the readings.
* Autark to Vega-Lite (repro): a double click on unit 103's square, in the
  middle of a keyed Autark map, turns its three readings red.
* Autark to Autark (repro): a brush across the bars of units 103 and 105,
  side by side in a keyed Autark bar plot of the units, lights the bars of
  their six readings in the readings plot. 103 and 105 are not consecutive,
  so a brush sent as a range over unit_id would light 104's too.

The Autark tests skip without a WebGPU adapter unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_keyed_selection_between_charts_e2e.py -v
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

import pytest

from .test_selection_tags_e2e import _UNSCROLL_JS, _bars_by_tooltip
from .utils import (
    assert_autark_map_drawn,
    assert_in_view,
    bar_boxes,
    brush_area,
    dismiss_toasts,
    frame_node,
    lit_labels,
    mark_point,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

UNITS_ID = "keyed-units"
READINGS_ID = "keyed-readings"
SENDER_ID = "keyed-sender"
RECEIVER_ID = "keyed-receiver"

#: The units in input order, which is the order an Autark plot draws their bars
#: in: the bars of 103 and 105 sit side by side.
UNITS = [101, 102, 103, 105, 104, 106]
NAMES = {101: "Alpha", 102: "Bravo", 103: "Charlie", 104: "Delta", 105: "Echo", 106: "Foxtrot"}
HEIGHTS = {101: 30, 102: 24, 103: 18, 104: 12, 105: 9, 106: 18}
#: Each unit's square, in grid cells: 103 in the middle of the map's extent.
CELLS = {103: (0, 0), 101: (-1, -1), 102: (1, -1), 104: (-1, 1), 105: (1, 1), 106: (0, 1)}
#: The order of each round of readings.
READING_ROUND = [104, 101, 106, 102, 105, 103]
#: The readings, in the order they were taken.
READINGS = [f"{unit}-{t}" for t in (1, 2, 3) for unit in READING_ROUND]

UNITS_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "\n"
    f"units = {json.dumps(UNITS)}\n"
    f"names = {json.dumps({str(k): v for k, v in NAMES.items()})}\n"
    f"heights = {json.dumps({str(k): v for k, v in HEIGHTS.items()})}\n"
    f"cells = {json.dumps({str(k): list(v) for k, v in CELLS.items()})}\n"
    "size = 0.002\n"
    "\n"
    "def square(unit):\n"
    "    x, y = cells[str(unit)]\n"
    "    cx, cy = -87.63 + x * size, 41.88 + y * size\n"
    "    return box(cx - 0.4 * size, cy - 0.4 * size, cx + 0.4 * size, cy + 0.4 * size)\n"
    "\n"
    "return gpd.GeoDataFrame(\n"
    "    {\n"
    '        "unit_id": units,\n'
    '        "label": [str(u) for u in units],\n'
    '        "name": [names[str(u)] for u in units],\n'
    '        "height": [heights[str(u)] for u in units],\n'
    "    },\n"
    "    geometry=[square(u) for u in units],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
)

READINGS_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "# Three readings per unit, taken in rounds of a shuffled order.\n"
    f"order = {json.dumps(READING_ROUND)}\n"
    "rows = [(f\"{unit}-{t}\", unit, unit % 7 + t) for t in (1, 2, 3) for unit in order]\n"
    "return gpd.GeoDataFrame(\n"
    "    {\n"
    '        "reading": [r[0] for r in rows],\n'
    '        "label": [r[0] for r in rows],\n'
    '        "unit_id": [r[1] for r in rows],\n'
    '        "level": [r[2] for r in rows],\n'
    "    },\n"
    "    geometry=[Point(-87.64 + i * 0.0005, 41.86) for i in range(len(rows))],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
)

# A bar per unit, picked by a point select over unit_id.
VEGA_UNITS = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "params": [{"name": "pick", "select": {"type": "point", "fields": ["unit_id"]}}],
    "mark": {"type": "bar", "cursor": "pointer"},
    "encoding": {
        "x": {"field": "unit_id", "type": "ordinal"},
        "y": {"field": "height", "type": "quantitative"},
        "fillOpacity": {"condition": {"param": "pick", "value": 1}, "value": 0.3},
        "tooltip": [{"field": "unit_id"}, {"field": "name"}],
    },
}, indent=2)

# A bar per reading, in the order they were taken, red where a selection marks it.
VEGA_READINGS = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": {"type": "bar"},
    "encoding": {
        "x": {"field": "reading", "type": "ordinal", "sort": None},
        "y": {"field": "level", "type": "quantitative"},
        "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"},
    },
}, indent=2)

# The units' squares on an Autark map, picked by their unit_id.
AUTARK_UNITS_MAP = json.dumps({"map": {"layerRefs": [{
    "dataRef": "input_0", "getFnv": "height", "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateViridis", "isPick": True, "selectFields": ["unit_id"],
}]}}, indent=2)

# A bar per unit in an Autark plot, brushed across and named by unit_id.
AUTARK_UNITS_PLOT = json.dumps({"plot": {
    "dataRef": "input_0", "mark": "bar", "axis": ["label", "height"],
    "events": ["brushX"], "selectFields": ["unit_id"],
}}, indent=2)

# A bar per reading in an Autark plot.
AUTARK_READINGS_PLOT = json.dumps({"plot": {"dataRef": "input_0", "mark": "bar", "axis": ["label", "level"]}}, indent=2)

VEGA = "curio.builtin/vis-vega"
AUTARK = "curio.builtin/autk-grammar"


def _readings_of(*units: int) -> list[str]:
    return sorted(r for r in READINGS if int(r.split("-")[0]) in units)


def _assert_positions_name_other_units(*picked: int) -> None:
    """The readings at the picked units' row positions belong to other units,
    so a selection read by row position lights other readings."""
    at_positions = [READINGS[UNITS.index(unit)] for unit in picked]
    assert all(int(r.split("-")[0]) not in picked for r in at_positions), (
        f"the readings at units {picked}'s row positions are {at_positions}: the fixture no longer "
        "tells a selection by position from one by value"
    )


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target}


def _interaction(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}in/out-{target}in/out", "type": "Interaction",
        "source": source, "target": target, "sourceHandle": "in/out", "targetHandle": "in/out",
    }


def _spec(name: str, sender: tuple[str, str], receiver: tuple[str, str]) -> dict:
    return {"dataflow": {
        "name": name, "task": "", "timestamp": 1789193389280, "provenance_id": name,
        "nodes": [
            _node(UNITS_ID, "curio.builtin/data-loading", 0, 0, UNITS_CODE),
            _node(READINGS_ID, "curio.builtin/data-loading", 0, 600, READINGS_CODE),
            _node(SENDER_ID, sender[0], 650, 0, sender[1]),
            _node(RECEIVER_ID, receiver[0], 650, 600, receiver[1]),
        ],
        "edges": [
            _edge(UNITS_ID, SENDER_ID),
            _edge(READINGS_ID, RECEIVER_ID),
            _interaction(SENDER_ID, RECEIVER_ID),
        ],
    }}


def _open(page, app_frontend, current_server, *, username: str, spec: dict, autark: bool) -> None:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=spec["dataflow"]["name"],
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    if autark:
        has_adapter = bool(page.evaluate("async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"))
        if not has_adapter:
            if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
                pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
            pytest.skip("drawing an Autark map or plot needs a WebGPU adapter; this browser has none")
    run_all_and_wait(page, timeout_ms=180000)
    dismiss_toasts(page)


# The bars of the Vega-Lite readings chart, left to right, read along the
# lowest canvas row that crosses all of them: whether each is red.
_RED_BARS_JS = """([id, count]) => {
    const c = document.querySelector('#vega' + id + ' canvas');
    if (!c || !c.width || !c.height) return null;
    const w = c.width, h = c.height;
    const px = c.getContext('2d').getImageData(0, 0, w, h).data;
    const kind = (x, y) => {
        const i = (y * w + x) * 4;
        if (px[i + 3] < 200) return null;
        if (px[i] > 200 && px[i + 1] < 60 && px[i + 2] < 60) return 'red';
        if (px[i + 2] > 200 && px[i] < 60 && px[i + 1] < 60) return 'blue';
        return null;
    };
    for (let y = h - 1; y >= 4; y--) {
        const runs = [];
        let run = null;
        for (let x = 0; x < w; x++) {
            const k = kind(x, y);
            if (k && run && run.kind === k) { run.x1 = x; continue; }
            run = k ? { kind: k, x0: x, x1: x } : null;
            if (run) runs.push(run);
        }
        const bars = runs.filter((r) => r.x1 - r.x0 >= 2);
        if (bars.length === count) return bars.map((r) => r.kind === 'red');
    }
    return null;
}"""


def _vega_lit(page) -> list[str] | None:
    """The readings the Vega-Lite readings chart shows red, sorted."""
    red = page.evaluate(_RED_BARS_JS, [RECEIVER_ID, len(READINGS)])
    return None if red is None else sorted(r for r, lit in zip(READINGS, red) if lit)


def _autark_lit(page) -> list[str] | None:
    """The readings the Autark readings plot lights, sorted."""
    return lit_labels(page, f"#autk-grammar-plot-{RECEIVER_ID}")


def _wait_for_lit(page, read, expected: list[str], what: str, *, timeout_ms: int = 30000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    lit = read(page)
    while lit != sorted(expected) and time.monotonic() < deadline:
        page.wait_for_timeout(250)
        lit = read(page)
    assert lit == sorted(expected), f"{what}: the readings chart lights {lit!r}, not {sorted(expected)!r}"


def _click_unit_bar(page, unit: int) -> None:
    """Click unit *unit*'s bar in the Vega-Lite units chart."""
    bars = _bars_by_tooltip(page, SENDER_ID, "unit_id", {str(unit)})
    page.mouse.click(*bars[str(unit)])


def _wait_for_autark_plot(page, node_id: str, count: int) -> str:
    selector = f"#autk-grammar-plot-{node_id}"
    page.wait_for_function(
        "([selector, count]) => document.querySelectorAll(selector + ' .autkMark').length === count",
        arg=[selector, count], timeout=60000,
    )
    return selector


def test_a_vega_lite_point_select_lights_the_readings_of_a_vega_lite_chart(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Guard: a direct edge between two Vega-Lite charts over different rows."""
    _assert_positions_name_other_units(103)
    spec = _spec("Keyed selection Vega-Lite to Vega-Lite", (VEGA, VEGA_UNITS), (VEGA, VEGA_READINGS))
    _open(page, app_frontend, current_server, username="keyed_vega_vega", spec=spec, autark=False)
    page.locator(f"#vega{RECEIVER_ID} canvas").first.wait_for(state="attached", timeout=60000)
    _wait_for_lit(page, _vega_lit, [], "Before any click")

    _click_unit_bar(page, 103)

    _wait_for_lit(page, _vega_lit, _readings_of(103), "After a click on unit 103's bar")


def test_a_vega_lite_point_select_lights_the_readings_of_an_autark_plot(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Guard: a Vega-Lite chart's values reach an Autark plot over other rows."""
    _assert_positions_name_other_units(103)
    spec = _spec("Keyed selection Vega-Lite to Autark", (VEGA, VEGA_UNITS), (AUTARK, AUTARK_READINGS_PLOT))
    _open(page, app_frontend, current_server, username="keyed_vega_autark", spec=spec, autark=True)
    _wait_for_autark_plot(page, RECEIVER_ID, len(READINGS))
    _wait_for_lit(page, _autark_lit, [], "Before any click")

    _click_unit_bar(page, 103)

    _wait_for_lit(page, _autark_lit, _readings_of(103), "After a click on unit 103's bar")


def test_a_pick_on_a_keyed_autark_map_lights_the_readings_of_a_vega_lite_chart(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Repro: an Autark pick sent the row position, which lit unit 106's reading."""
    _assert_positions_name_other_units(103)
    spec = _spec("Keyed selection Autark to Vega-Lite", (AUTARK, AUTARK_UNITS_MAP), (VEGA, VEGA_READINGS))
    _open(page, app_frontend, current_server, username="keyed_autark_vega", spec=spec, autark=True)
    page.locator(f"#vega{RECEIVER_ID} canvas").first.wait_for(state="attached", timeout=60000)
    assert_autark_map_drawn(page, SENDER_ID, timeout=60000)
    _wait_for_lit(page, _vega_lit, [], "Before any pick")

    # Unit 103's square is in the middle of the map, which fits the layer.
    page.evaluate(_UNSCROLL_JS, SENDER_ID)
    frame_node(page, SENDER_ID)
    canvas = f"#autk-grammar-map-{SENDER_ID}"
    point = mark_point(page, canvas, (0.5, 0.5))
    assert point, "the units map shows no square"
    x, y = assert_in_view(page, point["x"], point["y"], "unit 103's square")
    assert page.evaluate(
        "([selector, x, y]) => document.elementFromPoint(x, y) === document.querySelector(selector)",
        [canvas, x, y],
    ), f"something covers the middle of the units map at ({x:.0f}, {y:.0f})"
    page.mouse.dblclick(x, y)

    _wait_for_lit(page, _vega_lit, _readings_of(103), "After a double click on unit 103's square")


def test_a_brush_on_a_keyed_autark_plot_lights_the_readings_of_an_autark_plot(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Repro: an Autark brush sent row positions, which lit 106-1 and 102-1."""
    _assert_positions_name_other_units(103, 105)
    # Not consecutive: a brush sent as a range over unit_id would take 104 in.
    assert min(103, 105) < 104 < max(103, 105)
    spec = _spec("Keyed selection Autark to Autark", (AUTARK, AUTARK_UNITS_PLOT), (AUTARK, AUTARK_READINGS_PLOT))
    _open(page, app_frontend, current_server, username="keyed_autark_autark", spec=spec, autark=True)
    _wait_for_autark_plot(page, RECEIVER_ID, len(READINGS))
    _wait_for_lit(page, _autark_lit, [], "Before any brush")

    page.evaluate(_UNSCROLL_JS, SENDER_ID)
    frame_node(page, SENDER_ID)
    units = _wait_for_autark_plot(page, SENDER_ID, len(UNITS))
    bars = bar_boxes(page, units)
    labels = [bar["label"] for bar in bars]
    assert labels == [str(unit) for unit in UNITS], f"the units plot draws its bars as {labels}"
    first, second = bars[labels.index("103")], bars[labels.index("105")]
    area = brush_area(page, units)
    assert area, "the units plot has no brush to drag"
    y = area["y"] + 0.5 * area["height"]
    page.mouse.move(*assert_in_view(page, (first["left"] + first["right"]) / 2, y, "unit 103's bar"))
    page.mouse.down()
    page.mouse.move(*assert_in_view(page, (second["left"] + second["right"]) / 2, y, "unit 105's bar"), steps=8)
    page.mouse.up()

    _wait_for_lit(page, _autark_lit, _readings_of(103, 105), "After a brush across the bars of units 103 and 105")
