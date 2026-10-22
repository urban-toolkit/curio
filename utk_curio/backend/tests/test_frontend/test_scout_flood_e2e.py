"""SCOUT's flood example on SCOUT's whole grid, in two scenarios from Curio's own nodes and Scout's Raster Calculator, each on an Autark map, compared on an absolute difference and a chart, and weighed against CDC's Social Vulnerability Index on the riverside tracts (#662, step 18; #819; #914).

The shipped test dataflow ``quad-cities-flood-vulnerability.json``: Parameter nodes for the
period and the region's corners, at SCOUT's flood example's, which take every
cell of SCOUT's 2592 by 2064 cell grid; three Data Loading nodes reading the
region's window of SCOUT's rasters, which the Data Catalog holds whole; and two
scenarios, "No NbS" and "NbS" (its copy), each holding a Raster Calculator
(``curio.scout@1``) that
chooses the depth by nature-based solution (NbS) class, with its choice of NbS,
a second that takes the depth's statistics, and an Autark map of the depth.
Another Raster Calculator takes the size of NbS minus No NbS, which an Autark
map after it draws on a sequential scale, and Scout's Bars charts each
scenario's median flood depth (#720).

Run All drives the whole path:

1. The loaders read SCOUT's rasters by id, for the region and the period
   (2020 - 2050, which SCOUT labels 2020 - 2040) the Parameter nodes hold,
   and the seven calculators and the seven maps run.
2. Each scenario's map draws its depth, its legend titled "Flood depth (m)"
   and labelled 0 to 11, the color range both maps share.
3. The change is a 2592 by 2064 cell raster in EPSG:4326 on SCOUT's grid,
   whose cells are the size of SCOUT's depths with NbS minus SCOUT's depths
   without: 267,494 cells changed, 842,515 the same and 4,239,879 with no
   depth on one side or both, the counts SCOUT's rasters give, cell for cell
   the size of the two depth rasters' difference. The Autark map after the
   Raster Calculator draws it, its legend titled "Absolute flood depth change
   (m)".
4. The Bars chart draws both scenarios in their colors from its rows, each
   scenario's statistics: the medians and means are SCOUT's for its whole
   grid, a median flood depth of 7.164 m without NbS and 4.900 m with every
   NbS (``test_scout_flood.py``).
5. Two more Data Loading nodes read CDC's SVI census tracts and USGS's
   waterways from the Data Catalog, a Data Transformation keeps the 28 tracts
   NHD's rivers touch, and an Autark map draws their SVI percentile, its
   legend titled "Social vulnerability (SVI percentile)" and labelled 0 to 1.
6. In each scenario Tract depth averages the depth over each tract's land,
   and an Autark map in the scenario draws it, its legend titled "Mean flood
   depth (m)" and labelled 0 to 11, the depth maps' range (issue 9 of that
   plan). The Python node that subtracts them, joined on FIPS, writes the
   size of each tract's change, column for column from the two Tract depth
   outputs, which the Autark map after it draws, its legend titled "Absolute
   change in mean flood depth (m)": 23 of the 28 tracts change, by up to
   1.603 m.
7. Scout's Points charts each tract's SVI percentile against its mean depth
   in both scenarios' colors, from its rows: the 28 tracts in each scenario,
   the two Tract depth outputs stacked under their boxes, row for row.
8. Scout's Grouped bars chart each scenario's Average depth by period over
   the riverside land, a row a bar: 1.988, 1.923 and 2.237 m without NbS in
   SCOUT's three periods, and 1.337, 1.691 and 1.872 m with every NbS.

No request leaves the stack: the page asks no host but the stack's for
anything. The close-ups of the seven maps and the three charts are the
frames. Nothing is pinned to the dashboard: a difference of the whole grid is
over a dashboard page's 25 MB.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_flood_e2e.py -v
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import numpy as np
import pytest

from .utils import (
    REPO_ROOT,
    _COLOR_PIXELS_JS,
    _OUTPUT_ARTIFACT_JS,
    _assert_legend_reads,
    _assert_legend_title,
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

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "quad-cities-flood-vulnerability.json"
TEST_NAME = "test_two_flood_scenarios_are_mapped_and_charted"
CALCULATOR_TYPE = "curio.scout/raster-calculator"
RASTERS_PACKAGE = "curio.scout@1"
MAP_TYPE = "curio.builtin/autk-grammar"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
TRANSFORMATION_TYPE = "curio.builtin/data-transformation"
PYTHON_TYPE = "curio.builtin/computation-analysis"
BARS_TYPE, POINTS_TYPE, GROUPED_BARS_TYPE = "curio.scout/bars", "curio.scout/points", "curio.scout/grouped-bars"
CHART_TYPES = (BARS_TYPE, POINTS_TYPE, GROUPED_BARS_TYPE)
COLORS = {"no-nbs": "#e76f51", "nbs": "#2a9d8f"}
#: The legend title of the Autark map after the Depth change.
DIFFERENCE_TITLE = "Absolute flood depth change (m)"
#: The legend titles of the riverside tracts' vulnerability map, of each
#: scenario's map of its tracts' mean depth, and of the map after the Python
#: node that subtracts the tracts' mean depths.
VULNERABILITY_TITLE = "Social vulnerability (SVI percentile)"
TRACT_DEPTH_TITLE = "Mean flood depth (m)"
TRACT_CHANGE_TITLE = "Absolute change in mean flood depth (m)"
#: An SVI percentile's whole range, the vulnerability map's ``colorMapRange``.
SVI_RANGE = (0, 1)
RIVERSIDE_TRACTS = 28
PERIODS = ["2020 - 2050", "2050 - 2080", "2080 - 2100"]
#: The mean depth over the riverside tracts' land in each period, in metres
#: (``PERIOD_DEPTHS`` in ``test_packages/test_scout_flood.py``).
PERIOD_DEPTHS = {"No NbS": [1.988, 1.923, 2.237], "NbS": [1.337, 1.691, 1.872]}
#: The color range both scenarios' depth maps share, in metres
#: (``colorMapRange``): both legends read its ends, and the tract maps' too.
DEPTH_RANGE = (0, 11)
CELL = 0.00010133941049058334
#: SCOUT's grid: its size, width by height, and its north-west corner.
WIDTH, HEIGHT = 2592, 2064
ORIGIN = (-90.6879323, 41.6242105)

#: SCOUT's median and mean flood depth for its whole grid in 2020 - 2050,
#: without NbS and with every NbS, and how many cells hold a depth
#: (``PINS`` in ``test_packages/test_scout_flood.py``).
MEDIANS = [7.163970947265625, 4.900075276692708]
MEANS = [6.346452299531106, 5.312285760833436]
COUNTS = [1160305, 1115187]
#: The columns of each row the median chart reads, past the ones the stacking
#: keeps for itself (``__input__``): its scenario's box, then the scenario's
#: statistics, a table of one row.
STATISTICS_ROW = ["count", "max", "mean", "median", "min", "scenario", "scenario_name"]
#: The size of the change in depth: how many cells grow, change, stay and hold
#: no value, and its largest cell, SCOUT's rasters' (float32, as autk-db reads them).
CHANGE_COUNTS = (0, 267494, 842515, 4239879)
CHANGE_MAX = 10.645233154296875

#: The dataflow's nodes that compare the scenarios, by the part of the
#: scenarios both their inputs are and their mode: the change in depth, the
#: chart of the statistics, the change in each tract's mean depth, the scatter
#: of the tracts and the chart of the depth by period.
_COMPARISONS = (
    ("depth", "difference"),
    ("statistics", "chart"),
    ("tract depth", "difference"),
    ("tract depth", "chart"),
    ("by period", "chart"),
)


def _nodes_of(spec: dict, node_type: str) -> list[str]:
    return [node["id"] for node in spec["dataflow"]["nodes"] if node["type"] == node_type]


def _part(node: dict) -> str:
    """What a scenario's node is: the Raster Calculator that chooses the depth,
    the one of statistics, the one averaging the depth by period (its code
    returns its own table), or Tract depth (the Data Transformation)."""
    if node["type"] == CALCULATOR_TYPE:
        if "\nreturn raster_statistics(" in node["content"]:
            return "statistics"
        return "by period" if "\nreturn pd.DataFrame(" in node["content"] else "depth"
    assert node["type"] == TRANSFORMATION_TYPE, node["type"]
    assert not node["metadata"].get("widgets"), node["id"]
    return "tract depth"


def _scenario_parts(spec: dict) -> dict:
    """Each scenario's Raster Calculators and Data Transformations, by part."""
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    return {
        scenario["id"]: {
            _part(nodes[node_id]): node_id for node_id in scenario["nodes"]
            if nodes[node_id]["type"] in (CALCULATOR_TYPE, TRANSFORMATION_TYPE)
        }
        for scenario in spec["dataflow"]["scenarios"]
    }


def _members(spec: dict) -> set:
    return {node_id for scenario in spec["dataflow"]["scenarios"] for node_id in scenario["nodes"]}


def _by_part_and_mode(spec: dict, types: tuple, mode_of) -> dict:
    """The nodes of *types* in no scenario, by the part of the scenarios that
    feeds both their circles and by *mode_of* the node."""
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    members = _members(spec)
    found = {}
    for node in nodes.values():
        if node["type"] not in types or node["id"] in members:
            continue
        (part,) = {_part(nodes[e["source"]]) for e in spec["dataflow"]["edges"] if e["target"] == node["id"]}
        found[(part, mode_of(node))] = node["id"]
    assert sorted(found) == sorted(_COMPARISONS), found
    return found


def _comparisons(spec: dict) -> dict:
    """The dataflow's nodes that compare the scenarios, keyed by the part of
    the scenarios that feeds them and their mode: ``("depth", "difference")``,
    the Raster Calculator that subtracts the depths, ``("tract depth",
    "difference")`` the Python node, and the three charts by their parts."""
    return _by_part_and_mode(spec, (CALCULATOR_TYPE, PYTHON_TYPE, *CHART_TYPES),
                             lambda node: "chart" if node["type"] in CHART_TYPES else "difference")


def _riverside(spec: dict) -> str:
    """The Data Transformation in no scenario: the riverside tracts."""
    (riverside,) = [node["id"] for node in spec["dataflow"]["nodes"]
                    if node["type"] == TRANSFORMATION_TYPE and node["id"] not in _members(spec)]
    return riverside


def _record_outside_requests(page, *urls: str) -> list:
    """Every request the page makes from now on to a host that is not the
    stack's (the hosts of *urls*, or a loopback name)."""
    stack = {urlparse(url).hostname for url in urls} | {"localhost", "127.0.0.1", "::1"}
    outside: list = []

    def seen(request) -> None:
        address = urlparse(request.url)
        if address.scheme in ("http", "https", "ws", "wss") and address.hostname not in stack:
            outside.append(request.url)

    page.on("request", seen)
    return outside


def _maps_by_scenario(spec: dict, part: str) -> dict:
    """Each scenario's Autark map of its *part*, by the scenario's id: of its
    depth (``"depth"``) or of its tracts' mean depth (``"tract depth"``)."""
    maps = set(_nodes_of(spec, MAP_TYPE))
    parts = _scenario_parts(spec)
    found = {}
    for scenario in spec["dataflow"]["scenarios"]:
        drawn = parts[scenario["id"]][part]
        (map_id,) = [e["target"] for e in spec["dataflow"]["edges"]
                     if e["source"] == drawn and e["target"] in maps and e["target"] in scenario["nodes"]]
        found[scenario["id"]] = map_id
    return found


def _map_after(spec: dict, node_id: str) -> str:
    """The Autark map *node_id* feeds."""
    maps = set(_nodes_of(spec, MAP_TYPE))
    found = [edge["target"] for edge in spec["dataflow"]["edges"]
             if edge["source"] == node_id and edge["target"] in maps]
    assert len(found) == 1, f"{node_id} feeds the Autark maps {found}, not one"
    return found[0]


#: The opacity Vega-Lite draws points with when their values are not
#: aggregated (``DEFAULT_REDUCED_OPACITY``, vega-lite's compile/mark/init.ts):
#: the scatter's points are its scenario colors at 0.7 over the chart's white.
POINT_OPACITY = 0.7


def _over_white(color: str, opacity: float) -> str:
    """*color* as a mark drawn at *opacity* shows it over Vega-Lite's default
    white background."""
    channels = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(opacity * channel + (1 - opacity) * 255):02x}" for channel in channels)


def _assert_chart_drew(page, node_id: str, opacity: float = 1.0) -> None:
    """The chart drew, and its canvas holds both scenarios' colors, as its
    marks draw them at *opacity*."""
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    colors = [_over_white(COLORS["no-nbs"], opacity), _over_white(COLORS["nbs"], opacity)]
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both scenarios' colors {colors}: pixels {counts}")


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


def _saved_artifact(page, node_id: str, what: str) -> str:
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved {what}"
    return artifact


def _features(stored: dict) -> list[dict]:
    """The rows of a stored layer, each its properties."""
    assert stored["dataType"] == "geodataframe", stored["dataType"]
    return [feature["properties"] for feature in stored["data"]["features"]]


def _feeds_of(spec: dict, node_id: str) -> dict:
    """The nodes on *node_id*'s two circles, No NbS's on input_0 and NbS's on
    input_1, as its code reads them."""
    box_of = {member: box["id"] for box in spec["dataflow"]["scenarios"] for member in box["nodes"]}
    feeds = {edge["targetHandle"]: edge["source"] for edge in spec["dataflow"]["edges"] if edge["target"] == node_id}
    assert sorted(feeds) == ["in", "in_1"], (node_id, feeds)
    assert (box_of.get(feeds["in"]), box_of.get(feeds["in_1"])) == ("no-nbs", "nbs"), (node_id, feeds)
    return feeds


def _tract_depths(page, spec: dict, node_id: str) -> list:
    """``(scenario id, its name, its rows)`` of the two Tract depth nodes on
    *node_id*'s circles, in circle order, the rows a table of the layer's
    properties as the page reads them."""
    import pandas as pd

    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    names = {box["id"]: box["name"] for box in spec["dataflow"]["scenarios"]}
    feeds = _feeds_of(spec, node_id)
    found = []
    for handle, scenario in (("in", "no-nbs"), ("in_1", "nbs")):
        assert _part(nodes[feeds[handle]]) == "tract depth", (node_id, feeds[handle])
        rows = _features(load_artifact_as_dict(_saved_artifact(page, feeds[handle], "tract depth")))
        found.append((scenario, names[scenario], pd.DataFrame(rows)))
    return found


def _change_counts(cells: np.ndarray) -> tuple:
    finite = cells[~np.isnan(cells)]
    return (int((finite < 0).sum()), int((finite > 0).sum()), int((finite == 0).sum()),
            int(cells.size - finite.size)), float(finite.max())


def test_two_flood_scenarios_are_mapped_and_charted(
    app_frontend: "FrontendPage", current_server: str, page,
):
    import pandas as pd

    from utk_curio.backend.tests._support.scenario_changes import (
        assert_rows_match,
        keyed_change,
        records_of,
        stacked_rows,
    )

    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    assert not _nodes_of(spec, COMPARE_TYPE), "the dataflow still holds a Compare node"
    outside = _record_outside_requests(page, app_frontend.base_url, current_server)
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Flood Scenarios",
        username="scout_flood_scenarios",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    # The Raster Calculators and the charts are Scout's nodes: the account has
    # the package because the stack starts --with-examples and the dataflow
    # declares it.
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    assert RASTERS_PACKAGE in store, f"{RASTERS_PACKAGE} is not in the account's store {store}: start the stack --with-examples"
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    comparisons = _comparisons(spec)
    maps = _maps_by_scenario(spec, "depth")
    tract_maps = _maps_by_scenario(spec, "tract depth")
    difference = comparisons[("depth", "difference")]
    median_chart = comparisons[("statistics", "chart")]
    difference_map = _map_after(spec, difference)
    types = {node["id"]: node["type"] for node in spec["dataflow"]["nodes"]}
    steps = [(node_id, node_type) for node_id, node_type in types.items()
             if node_type in (CALCULATOR_TYPE, MAP_TYPE, TRANSFORMATION_TYPE)]
    assert len(steps) == 17, steps
    # Two of the seven Raster Calculators take the depth's statistics.
    statistics = [node["id"] for node in spec["dataflow"]["nodes"] if node["type"] == CALCULATOR_TYPE
                  and "\nreturn raster_statistics(" in node["content"]]
    assert len(statistics) == 2, statistics

    # 1. Run All: both scenarios read SCOUT's rasters for the shared region and period.
    run_all_and_wait(page, timeout_ms=600000)
    for node_id, node_type in steps:
        status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=240000)
        assert status == "done", f"{node_type} did not run: {read_node_error_text(node_locator(page, node_id))}"
    for node_id in comparisons.values():
        status = wait_for_node_settled(page, node_id, node_type=types[node_id], timeout_ms=240000)
        assert status == "done", f"{types[node_id]} did not compare: {read_node_error_text(node_locator(page, node_id))}"

    # 2. Each scenario's map draws its depth, under the grammar's title, on the
    # color range both maps share, so a color is the same depth on both.
    for scenario, map_id in maps.items():
        frame_nodes(page, [map_id])
        assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"the {scenario} flood depth map")
        _assert_legend_title(page, map_id, "Flood depth (m)")
        _assert_legend_reads(page, map_id, DEPTH_RANGE)
        save_node_closeup(page, f"scout-flood-depth-map-{scenario}", map_id, test_name=TEST_NAME, sweep_toasts=True)

    # 3. The change, the size of NbS minus No NbS, on SCOUT's grid: the Raster
    # Calculator's raster, and the Autark map after it draws it.
    grid, bands = load_raster_cells(_saved_artifact(page, difference, "change in depth"))
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:4326", WIDTH, HEIGHT), grid
    assert (grid["originX"], grid["originY"]) == pytest.approx(ORIGIN, abs=1e-9), grid
    assert (grid["resX"], grid["resY"]) == pytest.approx((CELL, -CELL), rel=1e-9), grid
    (cells,) = bands
    assert cells.size == WIDTH * HEIGHT
    counts, largest = _change_counts(cells)
    assert counts == CHANGE_COUNTS, counts
    assert largest == pytest.approx(CHANGE_MAX, abs=1e-5)
    # Cell for cell, the size of NbS's depth minus No NbS's, the two rasters
    # the Raster Calculators that choose saved, on the change's grid.
    feeds = _feeds_of(spec, difference)
    depths = []
    for handle in ("in", "in_1"):
        depth_grid, (depth,) = load_raster_cells(_saved_artifact(page, feeds[handle], "flood depth"))
        assert (depth_grid["crs"], depth_grid["width"], depth_grid["height"]) == (
            grid["crs"], grid["width"], grid["height"]), (depth_grid, grid)
        assert [depth_grid[k] for k in ("originX", "originY", "resX", "resY")] == pytest.approx(
            [grid[k] for k in ("originX", "originY", "resX", "resY")], rel=1e-12), (depth_grid, grid)
        depths.append(depth)
    took = np.abs(depths[1].astype("float64") - depths[0].astype("float64")).astype("float32")
    assert np.array_equal(np.isnan(cells), np.isnan(took))
    assert np.allclose(cells, took, rtol=0, atol=1e-5, equal_nan=True), (
        f"the Raster Calculator's change differs from the size of NbS minus No NbS by up to "
        f"{float(np.nanmax(np.abs(cells - took)))}"
    )
    frame_nodes(page, [difference, difference_map])
    assert_autark_map_drawn(page, difference_map, timeout=60000, attach_as="the size of NbS minus No NbS flood depth")
    _assert_legend_title(page, difference_map, DIFFERENCE_TITLE)

    # 4. The chart of the median flood depth, from SCOUT's numbers: the rows the
    # Bars chart reads.
    rows = _chart_rows(page, median_chart, 2)
    assert [row["__input__"] for row in rows] == [0, 1], rows
    assert [sorted(name for name in row if not name.startswith("_")) for row in rows] == [STATISTICS_ROW] * 2, rows
    read = {name: [row.get(name) for row in rows] for name in ("scenario", "scenario_name", "median", "mean", "count")}
    where = "the rows the Bars chart reads"
    assert read["scenario"] == ["no-nbs", "nbs"] and read["scenario_name"] == ["No NbS", "NbS"], where
    assert read["median"] == pytest.approx(MEDIANS, rel=1e-12), where
    assert read["mean"] == pytest.approx(MEANS, rel=1e-12), where
    assert read["count"] == COUNTS, where
    frame_nodes(page, [median_chart])
    _assert_chart_drew(page, median_chart)

    frame_nodes(page, [difference, difference_map])
    assert_autark_map_drawn(page, difference_map, timeout=60000, attach_as="the flood depth change before its close-up")
    _assert_legend_title(page, difference_map, DIFFERENCE_TITLE)
    save_node_closeup(page, "scout-flood-depth-change-map", difference_map, test_name=TEST_NAME, sweep_toasts=True)
    frame_nodes(page, [median_chart])
    _assert_chart_drew(page, median_chart)
    save_node_closeup(page, "scout-flood-median-depth", median_chart, test_name=TEST_NAME, sweep_toasts=True)

    # 5. The riverside tracts, CDC's tracts the rivers touch, on a map of their
    # SVI percentile over the whole range a percentile takes.
    vulnerability_map = _map_after(spec, _riverside(spec))
    frame_nodes(page, [vulnerability_map])
    assert_autark_map_drawn(page, vulnerability_map, timeout=60000, attach_as="the riverside tracts' vulnerability")
    _assert_legend_title(page, vulnerability_map, VULNERABILITY_TITLE)
    _assert_legend_reads(page, vulnerability_map, SVI_RANGE)
    save_node_closeup(page, "scout-flood-vulnerability-map", vulnerability_map, test_name=TEST_NAME, sweep_toasts=True)

    # 6. Each scenario's tracts by their mean depth, on the depth maps' range;
    # then the size of each tract's change in mean depth, joined on FIPS: the
    # Python node's rows, which the Autark map after it draws.
    for scenario, map_id in tract_maps.items():
        frame_nodes(page, [map_id])
        assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"the {scenario} tract depth map")
        _assert_legend_title(page, map_id, TRACT_DEPTH_TITLE)
        _assert_legend_reads(page, map_id, DEPTH_RANGE)
        save_node_closeup(page, f"scout-flood-tract-depth-map-{scenario}", map_id, test_name=TEST_NAME,
                          sweep_toasts=True)
    tract_change = comparisons[("tract depth", "difference")]
    tract_change_map = _map_after(spec, tract_change)
    rows = _features(load_artifact_as_dict(_saved_artifact(page, tract_change, "difference of the tracts")))
    where = "the Python node's"
    assert len({row["FIPS"] for row in rows}) == len(rows) == RIVERSIDE_TRACTS, where
    sizes = [row["mean_depth_m"] for row in rows]
    assert min(sizes) == 0 and max(sizes) == pytest.approx(1.603), (where, sizes)
    assert [row["change"] for row in rows].count("changed") == 23, where
    # Column for column, the size of NbS's mean depth minus No NbS's, joined on
    # FIPS, from the two Tract depth nodes' rows (keyed_change, which the
    # fixture of Compare's own output holds to it). A page reads rows whose keys
    # the sandbox sorts, so their order is not compared.
    tracts = _tract_depths(page, spec, tract_change)
    assert_rows_match(rows, records_of(keyed_change(tracts[0][2], tracts[1][2], "FIPS", absolute=True)), rel=1e-12,
                      what="the Depth change per tract", key_order=False)
    frame_nodes(page, [tract_change, tract_change_map])
    assert_autark_map_drawn(page, tract_change_map, timeout=60000,
                            attach_as="the size of each tract's change in mean depth")
    _assert_legend_title(page, tract_change_map, TRACT_CHANGE_TITLE)
    save_node_closeup(page, "scout-flood-depth-change-per-tract-map", tract_change_map,
                      test_name=TEST_NAME, sweep_toasts=True)

    # 7. Each tract's SVI percentile against its mean depth, in both scenarios:
    # the rows Scout's Points reads.
    scatter = comparisons[("tract depth", "chart")]
    rows = _chart_rows(page, scatter, 2 * RIVERSIDE_TRACTS)
    where = "the rows Scout's Points reads"
    assert [row["scenario_name"] for row in rows] == ["No NbS"] * RIVERSIDE_TRACTS + ["NbS"] * RIVERSIDE_TRACTS, where
    assert all(0 <= row["RPL_THEMES"] <= 1 and row["mean_depth_m"] >= 0 for row in rows), (where, rows)
    # Row for row, the two Tract depth nodes' rows stacked under their boxes.
    stacked = records_of(pd.DataFrame(stacked_rows(_tract_depths(page, spec, scatter))))
    assert_rows_match([{k: v for k, v in row.items() if not k.startswith("_")} for row in rows], stacked, rel=1e-12,
                      what=where, key_order=False)
    frame_nodes(page, [scatter])
    _assert_chart_drew(page, scatter, opacity=POINT_OPACITY)
    save_node_closeup(page, "scout-flood-vulnerability-against-depth", scatter, test_name=TEST_NAME, sweep_toasts=True)

    # 8. The mean depth over the riverside land in each period, in both
    # scenarios, a row a bar: the rows Scout's Grouped bars reads.
    period_chart = comparisons[("by period", "chart")]
    rows = _chart_rows(page, period_chart, 6)
    read = {name: [row.get(name) for row in rows] for name in ("scenario_name", "period", "mean_depth_m")}
    where = "the rows Scout's Grouped bars reads"
    assert read["scenario_name"] == ["No NbS"] * 3 + ["NbS"] * 3, (where, read["scenario_name"])
    assert read["period"] == PERIODS * 2, (where, read["period"])
    assert read["mean_depth_m"] == PERIOD_DEPTHS["No NbS"] + PERIOD_DEPTHS["NbS"], (where, read["mean_depth_m"])
    assert len({(row["scenario"], row["period"]) for row in rows}) == len(rows), rows
    frame_nodes(page, [period_chart])
    _assert_chart_drew(page, period_chart)
    save_node_closeup(page, "scout-flood-depth-by-period", period_chart, test_name=TEST_NAME, sweep_toasts=True)

    assert outside == [], f"the page asked hosts outside the stack: {sorted(set(outside))[:10]}"
