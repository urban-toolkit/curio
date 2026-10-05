"""SCOUT's high-rise shadow case on the canvas, compared as two scenarios (#662, step 19).

The shipped test dataflow ``ScoutShadows.json``: SCOUT's Chicago Loop buildings
(the Data Catalog dataset ``data.scout.loop-buildings``) and a season Parameter
node are the fixed context. In "Existing", Rasterize Buildings
(``scout.raster-conversion@1``) draws them into zoom-16 height tiles and
Accumulated Shadow (``scout.shadow@1``) runs SCOUT's Deep Umbra model (the
dataset ``data.scout.deep-umbra``) on them, in the season both scenarios share.
"Towers removed" first removes the 15 buildings SCOUT's second scenario removes.
Two Compare Scenarios nodes read the scenarios' outcomes: one charts the mean
accumulated shadow, the other maps its change through Autark.

Run All in the browser runs the whole dataflow:

1. The chart's stacked table holds one row per scenario, in summer, with SCOUT's
   mean accumulated shadow for each (128.64 and 106.73 minutes in SCOUT's
   metrics files) within 0.05 minutes, and its bars draw in both scenarios'
   colors.
2. The difference is a raster on the shadow mosaics' grid, 512 by 512 cells in
   EPSG:3395, in minutes: towers removed minus existing, which takes shadow away
   on the whole, and the map draws it.

The packages are in every account's store and their libraries are installed
because the stack starts with ``--with-examples`` and this dataflow declares the
packages.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_shadow_e2e.py -v
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .test_compare_difference_e2e import _OUTPUT_ARTIFACT_JS, _assert_difference_mapped, _band
from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS
from .utils import (
    REPO_ROOT,
    api_json,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
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

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "ScoutShadows.json"
SHADOW_TYPE = "scout.shadow/accumulated-shadow"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
PACKAGES = ("scout.raster-conversion@1", "scout.shadow@1")
#: SCOUT's A_shadows_metric.csv and B_shadows_metric.csv.
SCOUT_MEANS = {"existing": 128.63593, "towers-removed": 106.73111}


def _assert_chart_drew(page, node_id: str, colors: list[str]) -> None:
    """The bar chart compiled with no problem, and its canvas holds both scenarios' colors."""
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, "bar"])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"the bar chart's compile ended {state!r}: {problem}"
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both scenarios' colors {colors}: pixels {counts}")


def _saved_output(page, node_id: str) -> dict:
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    return load_artifact_as_dict(artifact)


def test_two_building_sets_are_shadowed_charted_and_mapped(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    record_property,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    shadows = [n for n, node in nodes.items() if node["type"] == SHADOW_TYPE]
    (chart,) = [n for n, node in nodes.items() if node["type"] == COMPARE_TYPE
                and node["metadata"]["compareScenarios"]["mode"] == "chart"]
    (difference,) = [n for n, node in nodes.items() if node["type"] == COMPARE_TYPE
                     and node["metadata"]["compareScenarios"]["mode"] == "difference"]
    colors = [scenario["color"] for scenario in dataflow["scenarios"]]

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scout Shadows",
        username="scout_shadows_e2e",
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
    for node_id in [*shadows, chart, difference]:
        status = wait_for_node_settled(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=180000)
        assert status == "done", (
            f"{nodes[node_id]['type']} {node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )

    # 1. One row per scenario, SCOUT's means, bars in both scenarios' colors.
    stacked = _saved_output(page, chart)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    assert list(table) == ["scenario", "scenario_name", "season", "mean_minutes", "median_minutes"], list(table)
    assert table["scenario"] == ["existing", "towers-removed"], table["scenario"]
    assert table["scenario_name"] == ["Existing", "Towers removed"], table["scenario_name"]
    assert table["season"] == ["summer", "summer"], table["season"]
    means = dict(zip(table["scenario"], table["mean_minutes"]))
    record_property("mean accumulated shadow (minutes)", json.dumps({"ours": means, "scout": SCOUT_MEANS}))
    assert all(abs(means[key] - SCOUT_MEANS[key]) <= 0.05 for key in SCOUT_MEANS), (
        f"mean accumulated shadow, ours {means}, SCOUT's {SCOUT_MEANS}"
    )
    frame_nodes(page, [chart])
    _assert_chart_drew(page, chart, colors)

    # 2. Towers removed minus existing, on the mosaics' grid, mapped.
    stored = _saved_output(page, difference)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", stored.get("dataType")
    grid = envelope["data"]["grid"]
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:3395", 512, 512), grid
    cells = _band(envelope)
    assert len(cells) == 512 * 512
    assert not any(math.isnan(v) for v in cells), "the difference has nodata where both mosaics have shadow"
    mean_change = sum(cells) / len(cells)
    record_property("difference (minutes)", json.dumps({"min": min(cells), "max": max(cells), "mean": mean_change}))
    assert min(cells) < -100 and mean_change < 0, (min(cells), max(cells), mean_change)
    assert -720 <= min(cells) and max(cells) <= 720, (min(cells), max(cells))
    frame_nodes(page, [difference])
    _assert_difference_mapped(page, difference, "the change in accumulated shadow when the towers are removed")
