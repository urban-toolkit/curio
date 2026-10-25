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
Existing, Towers removed and Height cap (whose Map Editor nodes remove or cut
down the building parts Buildings around parks marks, each linked to the map
of the buildings it feeds), Rasterize Buildings
(``curio.scout@1``) and Accumulated Shadow
(``model.scout.deep-umbra@1``) give the shadow, Shade per park measures it in
each park, and Autark maps draw the buildings in 3D and the shadow. Scout's
Dots with a range charts each park's minutes of shadow in the three
scenarios, and for each what-if a Raster Calculator takes the change in shadow
cell by cell and a Python node park by park, which Autark maps after them
draw.

Run All in the browser runs the whole dataflow:

1. Open-air parks hands on the 29 parks; Buildings around parks marks 527
   building parts; Towers removed hands on every other part, and Height cap
   every part, the marked ones 60 m tall.
2. The rows the chart reads hold each park's mean minutes of shadow in each
   scenario, each circle's the parks its Shade per park node hands on, in
   their order, under its scenario box: on average over the parks within
   half a minute of the run
   ``test_lower_manhattan_park_shade.py`` pins, and in every park the least
   with the towers removed and the most as they are. The chart draws in the
   three scenarios' colors.
3. Each what-if's change in shadow is a raster on the shadows' grid, 1024 by
   1280 cells in EPSG:3395, cell for cell the what-if's shadow minus
   Existing's, that takes shadow away on the whole, and each park's change in
   shade, column for column the what-if's Shade per park minus Existing's,
   matched by the park's name, takes shadow away in every park. The Autark map
   after each change draws it.
4. Each scenario's buildings and shadow draw, and each what-if's Map Editor
   node edits on the map of its buildings.

Every map's legend is titled as its layer is, and labels the color range it
shares with the maps of its kind: 0 to 550 m for the buildings, 0 to 720
minutes for the shadow, and -720 to 720 minutes, centered on no change, for
a change. The close-ups of the ten maps are the frames.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_lower_manhattan_park_shade_e2e.py -v
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
from playwright.sync_api import expect

from .test_map_edits_e2e import _assert_linked
from .test_widget_tags_e2e import _open_tab
from .utils import (
    REPO_ROOT,
    _COLOR_PIXELS_JS,
    _OUTPUT_ARTIFACT_JS,
    _assert_legend_reads,
    _assert_legend_title,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    assert_vega_charts_fit,
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
MAP_EDITS_TYPE = "curio.builtin/edit-features"
#: The chart, which keeps the id of the Compare Scenarios node it replaced, as
#: each change does.
CHART = "park-shade-chart"


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
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    assert COMPARE_TYPE not in {node["type"] for node in nodes.values()}, "the dataflow still holds a Compare node"
    colors = [scenario["color"] for scenario in dataflow["scenarios"]]
    assert [scenario["id"] for scenario in dataflow["scenarios"]] == [s[0] for s in SCENARIOS]
    assert nodes[CHART]["type"] == DOTS_TYPE
    for _scenario, _name, key in SCENARIOS[1:]:
        assert nodes[f"park-shade-{key}-change"]["type"] == CALCULATOR_TYPE, key
        assert nodes[f"park-shade-{key}-park-change"]["type"] == PYTHON_TYPE, key
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

    # 2. Each park's minutes in each scenario, in the rows the chart reads, and
    # the chart in the scenarios' colors.
    rows = _chart_rows(page, CHART, 3 * PARKS)
    assert [row["__input__"] for row in rows] == [circle for circle in range(3) for _park in range(PARKS)], rows
    # Each circle's rows are its Shade per park node's parks, in that node's
    # order and with its minutes, under the circle's scenario box.
    wired = sorted(
        (0 if edge.get("targetHandle") in (None, "in") else int(edge["targetHandle"].split("_")[1]), edge["source"])
        for edge in dataflow["edges"] if edge["target"] == CHART
    )
    assert [circle for circle, _source in wired] == [0, 1, 2], wired
    for (circle, source), (scenario, name, _key) in zip(wired, SCENARIOS):
        drawn = [row for row in rows if row["__input__"] == circle]
        shade = _rows(page, source)
        assert [(row["scenario"], row["scenario_name"], row["park"]) for row in drawn] == [
            (scenario, name, row["park"]) for row in shade
        ], (circle, source)
        assert [row["mean_min"] for row in drawn] == pytest.approx([row["mean_min"] for row in shade], rel=1e-12), (
            circle, source,
        )
    where = "the rows the chart reads"
    means: dict = {}
    for row in rows:
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
    frame_nodes(page, [CHART])
    _assert_chart_drew(page, CHART, colors)
    # The chart shows whole in its node, its axes and legend included (#1097).
    assert_vega_charts_fit(page, DATAFLOW.name, [CHART])

    # 3. Each what-if's change, in shadow and in each park, mapped after it:
    # the Raster Calculator's raster and the Python node's parks.
    import pandas as pd

    from utk_curio.backend.tests._support.scenario_changes import assert_rows_match, keyed_change, records_of

    scenario_of = {node_id: box["id"] for box in dataflow["scenarios"] for node_id in box["nodes"]}

    def feeds_of(node_id: str) -> dict:
        """The nodes on *node_id*'s circles, Existing's on input_0 and the
        what-if's on input_1, as its code reads them."""
        feeds = {edge["targetHandle"]: edge["source"] for edge in dataflow["edges"] if edge["target"] == node_id}
        assert sorted(feeds) == ["in", "in_1"], (node_id, feeds)
        assert scenario_of.get(feeds["in"]) == "existing", (node_id, feeds)
        return feeds

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
        # Cell for cell, the what-if's shadow minus Existing's, the two rasters
        # Deep Umbra saved, on the change's grid. The Raster Calculator
        # subtracts in float32, so the two may part by a unit in the last place.
        feeds = feeds_of(change)
        assert scenario_of.get(feeds["in_1"]) == scenario, (change, feeds)
        shadows = []
        for handle in ("in", "in_1"):
            shadow_grid, (shadow,) = load_raster_cells(_saved_artifact(page, feeds[handle]))
            assert (shadow_grid["crs"], shadow_grid["width"], shadow_grid["height"]) == (
                grid["crs"], grid["width"], grid["height"]), (name, shadow_grid, grid)
            assert [shadow_grid[k] for k in ("originX", "originY", "resX", "resY")] == pytest.approx(
                [grid[k] for k in ("originX", "originY", "resX", "resY")], rel=1e-12), (name, shadow_grid, grid)
            shadows.append(shadow)
        existing_shadow, what_if_shadow = shadows
        took = (what_if_shadow.astype("float64") - existing_shadow.astype("float64")).astype("float32")
        assert np.array_equal(np.isnan(raster), np.isnan(took)), name
        assert np.allclose(raster, took, rtol=0, atol=1e-3, equal_nan=True), (
            f"{name}: the Raster Calculator's change differs from the what-if's shadow minus Existing's by up to "
            f"{float(np.nanmax(np.abs(raster - took)))}"
        )
        frame_nodes(page, [change, change_map])
        assert_autark_map_drawn(page, change_map, timeout=60000, attach_as=f"the change in shadow under {name}")
        _assert_legend_shows_its_range(page, dataflow, change_map)
        save_node_closeup(page, f"park-shade-change-map-{scenario}", change_map, test_name=TEST_NAME, sweep_toasts=True)

        park_change, park_map = f"park-shade-{key}-park-change", f"park-shade-{key}-park-change-map"
        rows = _rows(page, park_change)
        assert len(rows) == PARKS and all(row["change"] == "changed" and row["mean_min"] < 0 for row in rows), (
            name, [(row["park"], row["change"], row["mean_min"]) for row in rows]
        )
        # Each park's change, column for column, is what the rule writes from
        # the two Shade per park nodes' rows step 2 read: the what-if's minus
        # Existing's, matched by the park's name (keyed_change, which the
        # fixture of Compare's own output holds to it).
        feeds = feeds_of(park_change)
        assert scenario_of.get(feeds["in_1"]) == scenario, (park_change, feeds)
        # A page reads rows whose keys the sandbox sorts, so their order is not compared.
        before, after = (pd.DataFrame(_rows(page, feeds[handle])) for handle in ("in", "in_1"))
        assert_rows_match(rows, records_of(keyed_change(before, after, "park")), rel=1e-12,
                          what=f"{name}'s park change", key_order=False)
        frame_nodes(page, [park_change, park_map])
        assert_autark_map_drawn(page, park_map, timeout=60000, attach_as=f"each park's change in shade under {name}")
        _assert_legend_shows_its_range(page, dataflow, park_map)
        save_node_closeup(page, f"park-shade-park-change-map-{scenario}", park_map, test_name=TEST_NAME,
                          sweep_toasts=True)

    # 4. Each scenario's buildings and shadow. A what-if's buildings map is
    # the one its Map Editor lever feeds and is linked to: the lever names it
    # and lists the layer it edits there.
    for scenario, _name, key in SCENARIOS:
        for what in ("buildings-map", "shadow-map"):
            map_id = f"park-shade-{key}-{what}"
            lever = f"park-shade-{key}-lever"
            if what == "buildings-map" and lever in nodes:
                assert nodes[lever]["type"] == MAP_EDITS_TYPE, nodes[lever]["type"]
                frame_nodes(page, [lever, map_id])
                _open_tab(page, lever, "output")
                _assert_linked(page, lever, map_id, nodes[map_id]["title"])
                expect(node_locator(page, lever).get_by_test_id("interaction-layer-input_0")).to_be_attached()
            frame_nodes(page, [map_id])
            assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"the {scenario} {what}")
            _assert_legend_shows_its_range(page, dataflow, map_id)
            save_node_closeup(page, f"park-shade-{what}-{scenario}", map_id, test_name=TEST_NAME, sweep_toasts=True)
    assert sorted(n for n, node in nodes.items() if node["type"] == MAP_EDITS_TYPE) == [
        "park-shade-capped-lever", "park-shade-removed-lever",
    ], "the what-ifs' levers are not the dataflow's Map Editor nodes"
