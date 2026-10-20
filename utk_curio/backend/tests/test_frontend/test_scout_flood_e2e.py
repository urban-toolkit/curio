"""SCOUT's flood example on SCOUT's whole grid, in two scenarios from Curio's own nodes and SCOUT Rasters' Raster Calculator, each on an Autark map, compared on an absolute difference and a chart, and weighed against CDC's Social Vulnerability Index on the riverside tracts (#662, step 18; #819; #914).

The shipped test dataflow ``quad-cities-flood-vulnerability.json``: Parameter nodes for the
period and the region's corners, at SCOUT's flood example's, which take every
cell of SCOUT's 2592 by 2064 cell grid; three Data Loading nodes reading the
region's window of SCOUT's rasters, which the Data Catalog holds whole; and two
scenarios, "No NbS" and "NbS" (its copy), each holding a Raster Calculator
(``scout.rasters@1``) that
chooses the depth by nature-based solution (NbS) class, with its choice of NbS,
a second that takes the depth's statistics, and an Autark map of the depth.
One Compare Scenarios node, in Difference, takes the size of NbS minus No NbS,
which an Autark map after it draws on a sequential scale; the other charts
each scenario's median flood depth (#720). Run All drives the whole path:

1. The loaders read SCOUT's rasters by id, for the region and the period
   (2020 - 2050, which SCOUT labels 2020 - 2040) the Parameter nodes hold,
   and the four calculators and the three maps run.
2. Each scenario's map draws its depth, its legend titled "Flood depth (m)"
   and labelled 0 to 11, the color range both maps share.
3. The difference is a 2592 by 2064 cell raster in EPSG:4326 on SCOUT's grid,
   whose cells are the size of SCOUT's depths with NbS minus SCOUT's depths
   without, as autk-db reads both (float32): 267,494 cells changed, 842,515
   the same and 4,239,879 with no depth on one side or both, the counts
   SCOUT's rasters give. The node draws no map of it; the Autark map after it
   does, its legend titled "Absolute flood depth change (m)".
4. The chart draws both scenarios in their colors from the stacked table,
   whose medians and means are SCOUT's for its whole grid: a median flood depth
   of 7.164 m without NbS and 4.900 m with every NbS (``test_scout_flood.py``).
5. What differs lists two levers, the Raster Calculator that chooses and
   Average depth by period, and in each one widget, the NbS choice; no code
   line differs, the calculators of statistics, the maps and Tract depth are
   the same, and nothing is warned.
6. Two more Data Loading nodes read CDC's SVI census tracts and USGS's
   waterways from the Data Catalog, a Data Transformation keeps the 28 tracts
   NHD's rivers touch, and an Autark map draws their SVI percentile, its
   legend titled "Social vulnerability (SVI percentile)" and labelled 0 to 1.
7. In each scenario Tract depth averages the depth over each tract's land.
   The Compare Scenarios node that subtracts them, joined on FIPS, draws no
   map; the Autark map after it does, its legend titled "Absolute change in
   mean flood depth (m)": 23 of the 28 tracts change, by up to 1.603 m.
8. A scatter charts each tract's SVI percentile against its mean depth in both
   scenarios' colors.
9. Grouped bars chart each scenario's Average depth by period over the
   riverside land: 1.988, 1.923 and 2.237 m without NbS in SCOUT's three
   periods, and 1.337, 1.691 and 1.872 m with every NbS.

No request leaves the stack: the page asks no host but the stack's for
anything. The close-ups of the five maps and the three charts are the frames.
Nothing is pinned to the dashboard: a difference of the whole grid is over a
dashboard page's 25 MB.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_flood_e2e.py -v
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import numpy as np
import pytest
from playwright.sync_api import expect

from .test_compare_difference_e2e import _assert_difference_mapped, _assert_legend_reads, _assert_legend_title
from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS, _OUTPUT_ARTIFACT_JS
from .utils import (
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
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
CALCULATOR_TYPE = "scout.rasters/raster-calculator"
RASTERS_PACKAGE = "scout.rasters@1"
MAP_TYPE = "curio.builtin/autk-grammar"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
TRANSFORMATION_TYPE = "curio.builtin/data-transformation"
COLORS = {"no-nbs": "#e76f51", "nbs": "#2a9d8f"}
#: The legend title of the Autark map after the Compare Scenarios node in Difference.
DIFFERENCE_TITLE = "Absolute flood depth change (m)"
#: The legend titles of the riverside tracts' vulnerability map, and of the map
#: after the Compare Scenarios node that subtracts the tracts' mean depths.
VULNERABILITY_TITLE = "Social vulnerability (SVI percentile)"
TRACT_CHANGE_TITLE = "Absolute change in mean flood depth (m)"
#: An SVI percentile's whole range, the vulnerability map's ``colorMapRange``.
SVI_RANGE = (0, 1)
RIVERSIDE_TRACTS = 28
PERIODS = ["2020 - 2050", "2050 - 2080", "2080 - 2100"]
#: The mean depth over the riverside tracts' land in each period, in metres
#: (``PERIOD_DEPTHS`` in ``test_packages/test_scout_flood.py``).
PERIOD_DEPTHS = {"No NbS": [1.988, 1.923, 2.237], "NbS": [1.337, 1.691, 1.872]}
#: The color range both scenarios' depth maps share, in metres
#: (``colorMapRange``): both legends read its ends.
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


def _nodes_of(spec: dict, node_type: str) -> list[str]:
    return [node["id"] for node in spec["dataflow"]["nodes"] if node["type"] == node_type]


def _part(node: dict) -> str:
    """What a scenario's node is: the Raster Calculator that chooses the depth,
    the one of statistics, Tract depth or Average depth by period (the Data
    Transformation with the NbS widget)."""
    if node["type"] == CALCULATOR_TYPE:
        return "statistics" if "\nreturn curio_raster_statistics(" in node["content"] else "depth"
    assert node["type"] == TRANSFORMATION_TYPE, node["type"]
    return "by period" if node["metadata"].get("widgets") else "tract depth"


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


def _compare_nodes(spec: dict) -> dict:
    """Each Compare Scenarios node, by the part of the scenarios that feeds both
    its circles and by its mode: ``("depth", "difference")`` subtracts the depths."""
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    found = {}
    for node in nodes.values():
        if node["type"] != COMPARE_TYPE:
            continue
        (part,) = {_part(nodes[e["source"]]) for e in spec["dataflow"]["edges"] if e["target"] == node["id"]}
        found[(part, node["metadata"]["compareScenarios"]["mode"])] = node["id"]
    assert sorted(found) == sorted([
        ("depth", "difference"), ("statistics", "chart"),
        ("tract depth", "difference"), ("tract depth", "chart"), ("by period", "chart"),
    ]), found
    return found


def _riverside(spec: dict) -> str:
    """The Data Transformation in no scenario: the riverside tracts."""
    members = {node_id for scenario in spec["dataflow"]["scenarios"] for node_id in scenario["nodes"]}
    (riverside,) = [node["id"] for node in spec["dataflow"]["nodes"]
                    if node["type"] == TRANSFORMATION_TYPE and node["id"] not in members]
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


def _maps_by_scenario(spec: dict) -> dict:
    """Each scenario's Autark map, by the scenario's id."""
    maps = set(_nodes_of(spec, MAP_TYPE))
    found = {}
    for scenario in spec["dataflow"]["scenarios"]:
        (map_id,) = [node_id for node_id in scenario["nodes"] if node_id in maps]
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


def _assert_chart_drew(page, node_id: str, preset: str = "bar", opacity: float = 1.0) -> None:
    """The chart of *preset* compiled with no problem, and its canvas holds
    both scenarios' colors, as its marks draw them at *opacity*."""
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, preset])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"the {preset} chart's compile ended {state!r}: {problem}"
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


def _band(envelope: dict) -> np.ndarray:
    """The envelope's one band (utils/raster/rasterWire.ts)."""
    raw = base64.b64decode(envelope["data"]["features"][0]["properties"]["band_1"]["float32le"])
    return np.frombuffer(raw, dtype="<f4")


def test_two_flood_scenarios_are_mapped_and_charted(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
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
    # The Raster Calculators are SCOUT Rasters' nodes: the account has the
    # package because the stack starts --with-examples and the dataflow
    # declares it.
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    assert RASTERS_PACKAGE in store, f"{RASTERS_PACKAGE} is not in the account's store {store}: start the stack --with-examples"
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    compares = _compare_nodes(spec)
    maps = _maps_by_scenario(spec)
    difference = compares[("depth", "difference")]
    median_chart = compares[("statistics", "chart")]
    difference_map = _map_after(spec, difference)
    steps = [(node["id"], node["type"]) for node in spec["dataflow"]["nodes"]
             if node["type"] in (CALCULATOR_TYPE, MAP_TYPE, TRANSFORMATION_TYPE)]
    assert len(steps) == 14, steps
    # Two of the four Raster Calculators take the depth's statistics.
    statistics = [node["id"] for node in spec["dataflow"]["nodes"] if node["type"] == CALCULATOR_TYPE
                  and "\nreturn curio_raster_statistics(" in node["content"]]
    assert len(statistics) == 2, statistics

    # 1. Run All: both scenarios read SCOUT's rasters for the shared region and period.
    run_all_and_wait(page, timeout_ms=600000)
    for node_id, node_type in steps:
        status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=240000)
        assert status == "done", f"{node_type} did not run: {read_node_error_text(node_locator(page, node_id))}"
    for node_id in compares.values():
        status = wait_for_node_settled(page, node_id, node_type=COMPARE_TYPE, timeout_ms=240000)
        assert status == "done", f"Compare Scenarios did not compare: {read_node_error_text(node_locator(page, node_id))}"

    # 2. Each scenario's map draws its depth, under the grammar's title, on the
    # color range both maps share, so a color is the same depth on both.
    for scenario, map_id in maps.items():
        frame_nodes(page, [map_id])
        assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"the {scenario} flood depth map")
        _assert_legend_title(page, map_id, "Flood depth (m)")
        _assert_legend_reads(page, map_id, DEPTH_RANGE)
        save_node_closeup(page, f"scout-flood-depth-map-{scenario}", map_id, test_name=TEST_NAME, sweep_toasts=True)

    # 3. The difference, the size of NbS minus No NbS, on SCOUT's grid: the
    # node draws no map of it, and the Autark map after it does.
    frame_nodes(page, [difference, difference_map])
    _assert_difference_mapped(page, difference, difference_map,
                              "the size of NbS minus No NbS flood depth", legend=DIFFERENCE_TITLE)
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, difference)
    assert artifact, "Compare Scenarios shows no saved difference"
    stored = load_artifact_as_dict(artifact)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", stored.get("dataType")
    grid = envelope["data"]["grid"]
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:4326", WIDTH, HEIGHT), grid
    assert (grid["originX"], grid["originY"]) == pytest.approx(ORIGIN, abs=1e-9), grid
    assert (grid["resX"], grid["resY"]) == pytest.approx((CELL, -CELL), rel=1e-9), grid
    cells = _band(envelope)
    assert cells.size == WIDTH * HEIGHT
    finite = cells[~np.isnan(cells)]
    counts = (
        int((finite < 0).sum()), int((finite > 0).sum()),
        int((finite == 0).sum()), int(cells.size - finite.size),
    )
    assert counts == (0, 267494, 842515, 4239879), counts
    assert float(finite.max()) == pytest.approx(10.645233154296875, abs=1e-5)

    # 4. The chart of the median flood depth, from SCOUT's numbers.
    frame_nodes(page, [median_chart])
    _assert_chart_drew(page, median_chart)
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, median_chart)
    assert artifact, "Compare Scenarios shows no saved table"
    stacked = load_artifact_as_dict(artifact)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    # The stored table's columns come back by name, not in their order.
    assert sorted(table) == ["count", "max", "mean", "median", "min", "scenario", "scenario_name"], list(table)
    assert table["scenario"] == ["no-nbs", "nbs"] and table["scenario_name"] == ["No NbS", "NbS"]
    assert table["median"] == pytest.approx(MEDIANS, rel=1e-12)
    assert table["mean"] == pytest.approx(MEANS, rel=1e-12)
    assert table["count"] == COUNTS

    # 5. What differs: the NbS choice, in the Raster Calculator that chooses and
    # in Average depth by period, and nothing else. Each lever is listed under
    # its No NbS node.
    compare = node_locator(page, median_chart)
    compare.get_by_role("tab", name="What differs", exact=True).click()
    levers = compare.locator("[data-compare-lever]")
    levers.first.wait_for(state="visible", timeout=10000)
    no_nbs = _scenario_parts(spec)["no-nbs"]
    assert sorted(levers.nth(i).get_attribute("data-compare-lever") for i in range(levers.count())) == sorted(
        [no_nbs["depth"], no_nbs["by period"]]
    )
    for lever_id in (no_nbs["depth"], no_nbs["by period"]):
        lever = compare.locator(f'[data-compare-lever="{lever_id}"]')
        assert lever.locator("[data-compare-widget]").count() == 1, lever_id
        widget = lever.locator('[data-compare-widget="use_NBS_classes"]')
        assert widget.locator('[data-compare-value="no-nbs"]').inner_text().endswith("No NbS: []"), lever_id
        assert '"Constructed wetlands"' in widget.locator('[data-compare-value="nbs"]').inner_text(), lever_id
    assert compare.locator("[data-compare-code-added]").count() == 0
    assert compare.locator("[data-compare-code-removed]").count() == 0
    # The calculators of statistics, the maps and Tract depth are the same in both scenarios.
    assert compare.locator("[data-compare-same]").get_attribute("data-compare-same") == "3"
    assert compare.locator("[data-compare-warning]").count() == 0
    compare.get_by_role("tab", name="Chart", exact=True).click()

    frame_nodes(page, [difference, difference_map])
    _assert_difference_mapped(page, difference, difference_map,
                              "the flood depth change before its close-up", legend=DIFFERENCE_TITLE)
    save_node_closeup(page, "scout-flood-depth-change-map", difference_map, test_name=TEST_NAME, sweep_toasts=True)
    frame_nodes(page, [median_chart])
    _assert_chart_drew(page, median_chart)
    save_node_closeup(page, "scout-flood-median-depth", median_chart, test_name=TEST_NAME, sweep_toasts=True)

    # 6. The riverside tracts, CDC's tracts the rivers touch, on a map of their
    # SVI percentile over the whole range a percentile takes.
    vulnerability_map = _map_after(spec, _riverside(spec))
    frame_nodes(page, [vulnerability_map])
    assert_autark_map_drawn(page, vulnerability_map, timeout=60000, attach_as="the riverside tracts' vulnerability")
    _assert_legend_title(page, vulnerability_map, VULNERABILITY_TITLE)
    _assert_legend_reads(page, vulnerability_map, SVI_RANGE)
    save_node_closeup(page, "scout-flood-vulnerability-map", vulnerability_map, test_name=TEST_NAME, sweep_toasts=True)

    # 7. The size of each tract's change in mean depth, joined on FIPS: the node
    # draws no map of it, and the Autark map after it does.
    tract_change = compares[("tract depth", "difference")]
    tract_change_map = _map_after(spec, tract_change)
    frame_nodes(page, [tract_change, tract_change_map])
    _assert_difference_mapped(page, tract_change, tract_change_map,
                              "the size of each tract's change in mean depth", legend=TRACT_CHANGE_TITLE)
    expect(node_locator(page, tract_change).locator('select[aria-label="Key"]')).to_have_value("FIPS", timeout=15000)
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, tract_change)
    assert artifact, "Compare Scenarios shows no saved difference of the tracts"
    stored = load_artifact_as_dict(artifact)
    assert stored["dataType"] == "geodataframe", stored["dataType"]
    rows = [feature["properties"] for feature in stored["data"]["features"]]
    assert len({row["FIPS"] for row in rows}) == len(rows) == RIVERSIDE_TRACTS
    sizes = [row["mean_depth_m"] for row in rows]
    assert min(sizes) == 0 and max(sizes) == pytest.approx(1.603), sizes
    assert [row["change"] for row in rows].count("changed") == 23
    save_node_closeup(page, "scout-flood-depth-change-per-tract-map", tract_change_map,
                      test_name=TEST_NAME, sweep_toasts=True)

    # 8. Each tract's SVI percentile against its mean depth, in both scenarios.
    scatter = compares[("tract depth", "chart")]
    frame_nodes(page, [scatter])
    _assert_chart_drew(page, scatter, "scatter", opacity=POINT_OPACITY)
    stacked = load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, scatter))
    assert stacked["dataType"] == "geodataframe", stacked["dataType"]
    rows = [feature["properties"] for feature in stacked["data"]["features"]]
    assert [row["scenario_name"] for row in rows] == ["No NbS"] * RIVERSIDE_TRACTS + ["NbS"] * RIVERSIDE_TRACTS
    assert all(0 <= row["RPL_THEMES"] <= 1 and row["mean_depth_m"] >= 0 for row in rows), rows
    save_node_closeup(page, "scout-flood-vulnerability-against-depth", scatter, test_name=TEST_NAME, sweep_toasts=True)

    # 9. The mean depth over the riverside land in each period, in both scenarios.
    period_chart = compares[("by period", "chart")]
    frame_nodes(page, [period_chart])
    _assert_chart_drew(page, period_chart, "grouped-bar")
    stacked = load_artifact_as_dict(page.evaluate(_OUTPUT_ARTIFACT_JS, period_chart))
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    assert table["scenario_name"] == ["No NbS"] * 3 + ["NbS"] * 3, table["scenario_name"]
    assert table["period"] == PERIODS * 2, table["period"]
    assert table["mean_depth_m"] == PERIOD_DEPTHS["No NbS"] + PERIOD_DEPTHS["NbS"], table["mean_depth_m"]
    save_node_closeup(page, "scout-flood-depth-by-period", period_chart, test_name=TEST_NAME, sweep_toasts=True)

    assert outside == [], f"the page asked hosts outside the stack: {sorted(set(outside))[:10]}"
