"""Lower Manhattan's parks in the shadow of their towers, on the canvas, as
three scenarios (step 18 of the #914 plan: komar41's ShadowsAnywhere, re-made
on Curio's nodes).

The shipped test dataflow ``lower-manhattan-park-shade.json``: an Autark data
node reads OpenStreetMap's parks of a box, the Financial District to City
Hall, and the buildings of a box about 300 m larger on every side, up to the
extract's edge, from ``lower_mnt.osm.pbf``, which the backend serves, so the
run needs no network. Building heights, Open-air parks and Buildings around
parks are the context, with the Season, Distance from a park and Tall
building height Parameters. In
Existing, Towers removed and Height cap (whose Interaction nodes remove or cut
down the building parts Buildings around parks marks), Rasterize Buildings
(``curio.scout@1``) and Accumulated Shadow
(``model.scout.deep-umbra@1``) give the shadow, Shade per park measures it in
each park, and Autark maps draw the buildings in 3D and the shadow. Scout's
Dots with a range charts each park's minutes of shadow in the three
scenarios, and for each what-if a Raster Calculator takes the change in shadow
cell by cell and a Python node park by park, which Autark maps after them
draw.

The test adds the five Compare Scenarios nodes the dataflow held until they
went, over the same inputs, on which steps 2 and 3 read what they read on the
dataflow's own until then (step 6.4 of the plan answering komar41's review
removes them with the node). Run All in the browser runs the whole dataflow:

1. Open-air parks hands on the 29 parks; Buildings around parks marks 527
   building parts; Towers removed hands on every other part, and Height cap
   every part, the marked ones 60 m tall.
2. The rows the chart reads, and the Compare chart's stacked table, hold each
   park's mean minutes of shadow in each scenario: on average over the parks
   within half a minute of the run ``test_lower_manhattan_park_shade.py``
   pins, and in every park the least with the towers removed and the most as
   they are. Both charts draw in the three scenarios' colors.
3. Each what-if's change in shadow is a raster on the shadows' grid, 1024 by
   1280 cells in EPSG:3395, that takes shadow away on the whole, cell for cell
   what the Compare node in Difference takes, and each park's change in shade,
   row for row what the Compare node keyed on the park writes, takes shadow
   away in every park. The Compare nodes draw no map; the Autark map after
   each change does.
4. Each scenario's buildings and shadow draw.

Every map's legend is titled as its layer is, and labels the color range it
shares with the maps of its kind: 0 to 550 m for the buildings, 0 to 720
minutes for the shadow, and -720 to 720 minutes, centered on no change, for
a change. The close-ups of the ten maps are the frames.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_lower_manhattan_park_shade_e2e.py -v
"""
from __future__ import annotations

import copy
import json
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

from .test_compare_difference_e2e import (
    _OUTPUT_ARTIFACT_JS,
    _assert_compare_draws_no_map,
    _assert_legend_reads,
    _assert_legend_title,
    _band,
)
from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS
from .utils import (
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
    load_raster_cells,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "lower-manhattan-park-shade.json"
TEST_NAME = "test_three_scenarios_of_lower_manhattans_park_shade_are_charted_and_mapped"
PACKAGES = ("curio.scout@1", "model.scout.deep-umbra@1")
#: The scenarios, in the order the chart reads them, and the key of their nodes.
SCENARIOS = (("existing", "Existing", "existing"), ("towers-removed", "Towers removed", "removed"),
             ("height-cap", "Height cap", "capped"))
PARKS = 29
BUILDING_ROWS = 2688
MARKED_ROWS = 527
TALL_HEIGHT_M = 60
GRID = (1024, 1280)
#: Each scenario's mean over the parks of their mean minutes of shadow in
#: summer, from the run test_lower_manhattan_park_shade.py pins.
MEAN_OVER_PARKS = {"existing": 272.06, "towers-removed": 143.09, "height-cap": 219.03}
MINUTES = 0.5
#: The diverging schemes the maps of a change use: a legend labels their middle too.
DIVERGING = {"interpolateRdBu", "interpolateRdYlBu"}
COMPARE_TYPE = "curio.builtin/compare-scenarios"
DOTS_TYPE = "curio.scout/dots-with-a-range"
CALCULATOR_TYPE = "curio.scout/raster-calculator"
PYTHON_TYPE = "curio.builtin/computation-analysis"
#: The chart, which keeps the id of the Compare Scenarios node it replaced, as
#: each change does.
CHART = "park-shade-chart"

#: The code a Compare Scenarios node writes for its inputs (compareCode.ts).
_STACK_NOTE = (
    "# Compare Scenarios writes this code from its inputs: each input, under the\n"
    "# id and the name of its scenario. It is written again when they change.\n"
)
_DIFFERENCE_NOTE = (
    "# Compare Scenarios writes this code from its inputs: input_1 minus input_0,\n"
    "# each under the id and the name of its scenario. It is written again when\n"
    "# they change.\n"
)


def _compare_code(scenarios: list[tuple[str, str]], key: str = "") -> str:
    """The code a Compare node writes over *scenarios*: a stack of the three,
    or the difference of two, keyed on *key* when it names one."""
    entries = "".join(f'    ("{scenario}", "{name}", [!! input_{k} !!]),\n' for k, (scenario, name) in enumerate(scenarios))
    if len(scenarios) == 3:
        return _STACK_NOTE + "return curio_stack_scenarios([\n" + entries + "])\n"
    return _DIFFERENCE_NOTE + "return curio_difference_scenarios([\n" + entries + f"]{f', key={json.dumps(key)}' if key else ''})\n"


def _test_compare(key: str, what: str) -> str:
    """The id of a Compare node the test adds: ``chart``, or a what-if's
    ``change`` or ``park-change``."""
    return "test-compare-chart" if what == "chart" else f"test-compare-{key}-{what}"


def _with_compare_nodes(spec: dict) -> dict:
    """*spec* with the five Compare Scenarios nodes the dataflow held until
    Compare went, below the rest: the grouped bars on the chart's three
    inputs, and each what-if's two Differences on its changes' inputs, on the
    same circles. Each holds its labels and the code it writes for its inputs,
    so a load writes nothing again."""
    spec = copy.deepcopy(spec)
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    assert COMPARE_TYPE not in {node["type"] for node in nodes.values()}, "the dataflow still holds a Compare node"
    labels = {s["id"]: {"scenario": s["id"], "name": s["name"], "color": s["color"]} for s in dataflow["scenarios"]}
    names = [(scenario, name) for scenario, name, _key in SCENARIOS]
    added = [(_test_compare("", "chart"), CHART, DOTS_TYPE, names, {
        "chart": {"preset": "grouped-bar", "x": "park", "y": "mean_min", "aggregate": "none"}, "mode": "chart",
    }, {"width": 1000, "height": 600})]
    for scenario, name, key in SCENARIOS[1:]:
        pair = [names[0], (scenario, name)]
        added += [
            (_test_compare(key, "change"), f"park-shade-{key}-change", CALCULATOR_TYPE, pair,
             {"mode": "difference"}, {}),
            (_test_compare(key, "park-change"), f"park-shade-{key}-park-change", PYTHON_TYPE, pair,
             {"mode": "difference", "difference": {"key": "park"}}, {}),
        ]
    bottom = max(node["y"] + node.get("height", 450) for node in dataflow["nodes"])
    for k, (node_id, beside, beside_type, scenarios, settings, size) in enumerate(added):
        assert nodes[beside]["type"] == beside_type, (beside, nodes[beside]["type"])
        key = (settings.get("difference") or {}).get("key", "")
        dataflow["nodes"].append({
            "id": node_id, "type": COMPARE_TYPE, "x": 1100 * k, "y": bottom + 200, **size,
            "title": f"{nodes[beside]['title']}: Compare", "content": _compare_code(scenarios, key),
            "out": "DEFAULT", "in": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], "compareScenarios": {
                "inputs": [labels[scenario] for scenario, _name in scenarios], **settings,
            }},
        })
        dataflow["edges"] += [
            {**edge, "id": f"{edge['id']}-{node_id}", "target": node_id}
            for edge in dataflow["edges"] if edge["target"] == beside
        ]
    return spec


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

# The rows a chart's last view reads as its ``inputs`` dataset, as plain JSON.
_INPUTS_ROWS_JS = """(id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    if (!view) return null;
    try {
        return JSON.parse(JSON.stringify(view.data("inputs")));
    } catch (error) {
        return null;
    }
}"""


def _chart_rows(page, chart: str, count: int) -> list[dict]:
    """The *count* rows the chart reads, once its view holds them."""
    rows = None
    deadline = time.time() + 30
    while time.time() < deadline:
        rows = page.evaluate(_INPUTS_ROWS_JS, chart)
        if rows and len(rows) == count:
            return rows
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart {chart} reads the rows {rows}, not {count}")


def _saved_output(page, node_id: str) -> dict:
    return load_artifact_as_dict(_saved_artifact(page, node_id))


def _saved_artifact(page, node_id: str) -> str:
    """The artifact *node_id*'s output is saved to."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    return artifact


def _rows(page, node_id: str) -> list[dict]:
    """The rows of the layer *node_id* handed on, each its properties."""
    stored = _saved_output(page, node_id)
    assert stored["dataType"] == "geodataframe", f"{node_id} handed on {stored['dataType']}"
    return [feature["properties"] for feature in stored["data"]["features"]]


def _raster(page, node_id: str) -> dict:
    """The raster envelope *node_id* handed on."""
    stored = _saved_output(page, node_id)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", f"{node_id} handed on {stored.get('dataType')}"
    return envelope


def _assert_compare_chart_drew(page, node_id: str, colors: list[str]) -> None:
    """The Compare node's grouped bars compiled with no problem, and the canvas
    holds the three scenarios' colors."""
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, "grouped-bar"])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"the grouped bars' compile ended {state!r}: {problem}"
    _assert_chart_drew(page, node_id, colors)


def _assert_chart_drew(page, node_id: str, colors: list[str]) -> None:
    """The chart drew, and its canvas holds the three scenarios' colors."""
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw the three scenarios' colors {colors}: pixels {counts}")


def _layer(dataflow: dict, node_id: str) -> dict:
    """The one layer the map *node_id* draws, as its document writes it."""
    (layer,) = json.loads(next(n for n in dataflow["nodes"] if n["id"] == node_id)["content"])["map"]["layerRefs"]
    return layer


def _assert_legend_shows_its_range(page, dataflow: dict, map_id: str) -> None:
    """The map's legend is titled as its layer is, and labels the color range
    the maps beside it share: its ends, and on a diverging scheme its middle."""
    layer = _layer(dataflow, map_id)
    _assert_legend_title(page, map_id, layer["title"])
    low, high = layer["colorMapRange"]
    middle = layer.get("colorMapCenter", (low + high) / 2)
    diverging = layer["colorMapInterpolator"] in DIVERGING
    _assert_legend_reads(page, map_id, (low, middle, high) if diverging else (low, high))


def test_three_scenarios_of_lower_manhattans_park_shade_are_charted_and_mapped(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    record_property,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    spec = _with_compare_nodes(json.loads(DATAFLOW.read_text(encoding="utf-8")))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    colors = [scenario["color"] for scenario in dataflow["scenarios"]]
    assert [scenario["id"] for scenario in dataflow["scenarios"]] == [s[0] for s in SCENARIOS]
    assert nodes[CHART]["type"] == DOTS_TYPE
    maps = [n for n, node in nodes.items()
            if node["type"] == "curio.builtin/autk-grammar" and n != "park-shade-layers"]
    assert len(maps) == 10, maps

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Park Shade",
        username="park_shade_e2e",
        project_name=dataflow["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)

    run_all_and_wait(page, timeout_ms=600000)
    for node_id, node in nodes.items():
        if node["type"] == "curio.builtin/parameter":
            continue
        status = wait_for_node_settled(page, node_id, node_type=node["type"], timeout_ms=180000)
        assert status == "done", (
            f"{node['type']} {node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )

    # 1. The parks, the marked parts and the levers.
    assert len(_rows(page, "park-shade-parks")) == PARKS
    marked = _rows(page, "park-shade-around")
    assert len(marked) == BUILDING_ROWS and sum(1 for row in marked if row["around_park"]) == MARKED_ROWS
    removed = _rows(page, "park-shade-removed-lever")
    assert len(removed) == BUILDING_ROWS - MARKED_ROWS and not any(row["around_park"] for row in removed)
    capped = _rows(page, "park-shade-capped-lever")
    assert len(capped) == BUILDING_ROWS
    assert all(row["height"] == TALL_HEIGHT_M for row in capped if row["around_park"]), "Height cap left a part uncut"

    # 2. Each park's minutes in each scenario, and the charts in their colors:
    # in the rows the chart reads, and in the Compare chart's stacked table.
    rows = _chart_rows(page, CHART, 3 * PARKS)
    assert [row["__input__"] for row in rows] == [circle for circle in range(3) for _park in range(PARKS)], rows
    stacked = _rows(page, _test_compare("", "chart"))
    for table, where in ((stacked, "the Compare chart's stacked table"), (rows, "the rows the chart reads")):
        means: dict = {}
        for row in table:
            means.setdefault(row["scenario"], {})[row["park"]] = row["mean_min"]
        assert sorted(means) == sorted(s[0] for s in SCENARIOS) and all(len(m) == PARKS for m in means.values()), (
            where, means,
        )
        over_parks = {scenario: sum(m.values()) / len(m) for scenario, m in means.items()}
        record_property(f"mean over the parks (minutes) in {where}",
                        json.dumps({"ours": over_parks, "pinned": MEAN_OVER_PARKS}))
        assert all(abs(over_parks[key] - MEAN_OVER_PARKS[key]) <= MINUTES for key in MEAN_OVER_PARKS), (
            f"mean over the parks in {where}, ours {over_parks}, pinned {MEAN_OVER_PARKS}"
        )
        for park, existing in means["existing"].items():
            assert means["towers-removed"][park] < means["height-cap"][park] < existing, (where, park)
    assert [(row["scenario"], row["scenario_name"], row["park"]) for row in rows] == [
        (row["scenario"], row["scenario_name"], row["park"]) for row in stacked
    ]
    assert [row["mean_min"] for row in rows] == pytest.approx([row["mean_min"] for row in stacked], rel=1e-12)
    frame_nodes(page, [CHART])
    _assert_chart_drew(page, CHART, colors)
    frame_nodes(page, [_test_compare("", "chart")])
    _assert_compare_chart_drew(page, _test_compare("", "chart"), colors)

    # 3. Each what-if's change, in shadow and in each park, mapped after it:
    # the Raster Calculator's raster, cell for cell what the Compare node takes,
    # and the Python node's parks, row for row what the Compare node writes.
    for scenario, name, key in SCENARIOS[1:]:
        change, change_map = f"park-shade-{key}-change", f"park-shade-{key}-change-map"
        grid, bands = load_raster_cells(_saved_artifact(page, change))
        assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:3395", *GRID), grid
        (raster,) = bands
        finite = raster[~np.isnan(raster)]
        record_property(f"change in shadow, {name} (minutes)", json.dumps({
            "min": float(finite.min()), "max": float(finite.max()), "mean": float(finite.mean()),
        }))
        assert finite.min() < -100 and finite.mean() < 0, (name, finite.min(), finite.mean())
        assert -720 <= finite.min() and finite.max() <= 720, (name, finite.min(), finite.max())
        envelope = _raster(page, _test_compare(key, "change"))
        took_grid = envelope["data"]["grid"]
        assert (took_grid["crs"], took_grid["width"], took_grid["height"]) == ("EPSG:3395", *GRID), took_grid
        assert [took_grid[k] for k in ("originX", "originY", "resX", "resY")] == pytest.approx(
            [grid[k] for k in ("originX", "originY", "resX", "resY")], rel=1e-12)
        cells = [v for v in _band(envelope) if not math.isnan(v)]
        mean_change = sum(cells) / len(cells)
        assert min(cells) < -100 and mean_change < 0, (name, min(cells), mean_change)
        assert -720 <= min(cells) and max(cells) <= 720, (name, min(cells), max(cells))
        # The envelope's rows run from south to north (utils/raster/rasterWire.ts);
        # Compare rounds a float64 difference to float32, the Raster Calculator
        # subtracts in float32: they may part by a unit in the last place.
        took = np.asarray(_band(envelope), dtype="float32").reshape(GRID[1], GRID[0])[::-1]
        assert np.array_equal(np.isnan(raster), np.isnan(took)), name
        assert np.allclose(raster, took, rtol=0, atol=1e-3, equal_nan=True), (
            f"{name}: the Raster Calculator's change differs from Compare's by up to "
            f"{float(np.nanmax(np.abs(raster - took)))}"
        )
        frame_nodes(page, [change, change_map])
        assert_autark_map_drawn(page, change_map, timeout=60000, attach_as=f"the change in shadow under {name}")
        _assert_legend_shows_its_range(page, dataflow, change_map)
        save_node_closeup(page, f"park-shade-change-map-{scenario}", change_map, test_name=TEST_NAME, sweep_toasts=True)
        frame_nodes(page, [_test_compare(key, "change")])
        _assert_compare_draws_no_map(page, _test_compare(key, "change"))

        park_change, park_map = f"park-shade-{key}-park-change", f"park-shade-{key}-park-change-map"
        rows = _rows(page, park_change)
        assert len(rows) == PARKS and all(row["change"] == "changed" and row["mean_min"] < 0 for row in rows), (
            name, [(row["park"], row["change"], row["mean_min"]) for row in rows]
        )
        compared = _rows(page, _test_compare(key, "park-change"))
        assert [list(row) for row in rows] == [list(row) for row in compared], (name, list(rows[0]), list(compared[0]))
        assert [(row["park"], row["change"]) for row in rows] == [(row["park"], row["change"]) for row in compared]
        for column in [c for c in rows[0] if isinstance(rows[0][c], (int, float)) and not isinstance(rows[0][c], bool)]:
            assert [row[column] for row in rows] == pytest.approx([row[column] for row in compared], rel=1e-12), (
                name, column,
            )
        frame_nodes(page, [park_change, park_map])
        assert_autark_map_drawn(page, park_map, timeout=60000, attach_as=f"each park's change in shade under {name}")
        _assert_legend_shows_its_range(page, dataflow, park_map)
        save_node_closeup(page, f"park-shade-park-change-map-{scenario}", park_map, test_name=TEST_NAME,
                          sweep_toasts=True)
        frame_nodes(page, [_test_compare(key, "park-change")])
        _assert_compare_draws_no_map(page, _test_compare(key, "park-change"))

    # 4. Each scenario's buildings and shadow.
    for scenario, _name, key in SCENARIOS:
        for what in ("buildings-map", "shadow-map"):
            map_id = f"park-shade-{key}-{what}"
            frame_nodes(page, [map_id])
            assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"the {scenario} {what}")
            _assert_legend_shows_its_range(page, dataflow, map_id)
            save_node_closeup(page, f"park-shade-{what}-{scenario}", map_id, test_name=TEST_NAME, sweep_toasts=True)
