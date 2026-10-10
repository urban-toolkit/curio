"""SCOUT's high-rise shadow case on the canvas, compared as two scenarios (#662, step 19).

The shipped test dataflow ``WhatIfShadows.json``: SCOUT's Chicago Loop buildings
(the Data Catalog dataset ``data.scout.loop-buildings``) and a season Parameter
node are the fixed context. In "Existing", Rasterize Buildings
(``scout.raster-conversion@1``) draws them into a zoom-16 height mosaic,
Accumulated Shadow (``scout.shadow@1``) runs SCOUT's Deep Umbra model (the
Model Catalog model ``model.scout.deep-umbra``) on it, in the season both scenarios share,
and returns the shadow raster with SCOUT's mean and median over the ground, which
two Python Computation nodes take apart. "Towers removed" first removes the 15
buildings SCOUT's second scenario removes. A Vega-Lite node comparing the
scenarios draws SCOUT's mean accumulated shadow on a pie, one value per
scenario, and a Raster Calculator takes the size of its change, which an Autark
map draws.

Run All in the browser runs the whole dataflow:

1. Each scenario's metrics hold SCOUT's mean accumulated shadow (128.64 and
   106.73 minutes in SCOUT's metrics files, in summer) within 0.1 minutes, and
   the pie draws in both scenarios' colors.
2. The difference is a raster on the shadow mosaics' grid, 512 by 512 cells in
   EPSG:3395, in minutes: the size of towers removed minus existing
   (``absolute=True``), and the map draws it.

The packages are in every account's store and their libraries are installed
because the stack starts with ``--with-examples`` and this dataflow declares the
packages.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_shadow_e2e.py -v
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

from .utils import (
    OUTPUT_ARTIFACT_JS,
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_scenario_colors_drawn,
    assert_vega_canvas_rendered,
    fetch_raster,
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

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "WhatIfShadows.json"
SHADOW_TYPE = "scout.shadow/accumulated-shadow"
PICKER_TYPE = "curio.builtin/computation-analysis"
VEGA_TYPE = "curio.builtin/vis-vega"
CALCULATOR_TYPE = "curio.builtin/raster-calculator"
MAP_TYPE = "curio.builtin/autk-grammar"
PACKAGES = ("scout.raster-conversion@1", "scout.shadow@1")
#: SCOUT's A_shadows_metric.csv and B_shadows_metric.csv.
SCOUT_MEANS = {"existing": 128.63593, "towers-removed": 106.73111}


def _saved_output(page, node_id: str) -> dict:
    artifact = page.evaluate(OUTPUT_ARTIFACT_JS, node_id)
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
    # The two nodes that take SCOUT's metrics out of each Accumulated Shadow.
    metrics = [n for n, node in nodes.items() if node["type"] == PICKER_TYPE
               and node["content"].splitlines()[-1] == "return input_0[1]"]
    assert len(shadows) == len(metrics) == 2, (shadows, metrics)
    (chart,) = [n for n, node in nodes.items() if node["type"] == VEGA_TYPE]
    (difference,) = [n for n, node in nodes.items() if node["type"] == CALCULATOR_TYPE]
    (change_map,) = [e["target"] for e in dataflow["edges"] if e["source"] == difference]
    scenario_of = {n: scenario["id"] for scenario in dataflow["scenarios"] for n in scenario["nodes"]}
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
    for node_id in [*shadows, *metrics, chart, difference, change_map]:
        status = wait_for_node_settled(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=180000)
        assert status == "done", (
            f"{nodes[node_id]['type']} {node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )

    # 1. SCOUT's means, one per scenario, and the pie in both scenarios' colors.
    means = {}
    for node_id in metrics:
        stored = _saved_output(page, node_id)
        assert stored["dataType"] == "dataframe", stored["dataType"]
        (means[scenario_of[node_id]],) = stored["data"]["Mean Acc shadow"]
    record_property("mean accumulated shadow (minutes)", json.dumps({"ours": means, "scout": SCOUT_MEANS}))
    # The proof's tolerance (test_scout_shadow.py): Deep Umbra's output moves
    # with onnxruntime's thread count above 16.
    assert all(abs(means[key] - SCOUT_MEANS[key]) <= 0.1 for key in SCOUT_MEANS), (
        f"mean accumulated shadow, ours {means}, SCOUT's {SCOUT_MEANS}"
    )
    frame_nodes(page, [chart])
    assert_vega_canvas_rendered(page, chart, timeout=30000)
    assert_scenario_colors_drawn(page, chart, colors)

    # 2. The size of towers removed minus existing, on the mosaics' grid, mapped.
    artifact = page.evaluate(OUTPUT_ARTIFACT_JS, difference)
    assert artifact, "the Raster Calculator shows no saved raster"
    values, profile = fetch_raster(artifact)
    assert (str(profile["crs"]), profile["width"], profile["height"]) == ("EPSG:3395", 512, 512), profile
    cells = values[0].ravel().tolist()
    assert not any(math.isnan(v) for v in cells), "the difference has nodata where both mosaics have shadow"
    mean_change = sum(cells) / len(cells)
    record_property("difference (minutes)", json.dumps({"min": min(cells), "max": max(cells), "mean": mean_change}))
    assert 0 <= min(cells) and 100 < max(cells) <= 720, (min(cells), max(cells), mean_change)
    frame_nodes(page, [change_map])
    assert_autark_map_drawn(page, change_map, timeout=60000,
                            attach_as="the change in accumulated shadow when the towers are removed")
