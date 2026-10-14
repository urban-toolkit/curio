"""SCOUT's shadow model on a city SCOUT never shipped, with the minutes of shadow
in each park compared across three scenarios.

The shipped test dataflow ``ShadowsAnywhere.json``: Lower Manhattan's buildings
and parks (the Data Catalog bundle ``data.curio.lower-manhattan-shadows``,
Overture Maps' buildings and OpenStreetMap's parks as the Discovery Catalog
downloads them) and Parameter nodes are the fixed context. Building heights fills
each building's height, Open-air parks keeps the named parks in the open, and
Buildings around parks marks the buildings the what-ifs change, by one rule for
every park: 60 m or taller within 75 m of a park. In "Existing", in "Towers
removed", without the marked buildings, and in "Height cap", the marked buildings
cut down to 60 m, Rasterize Buildings (``scout.raster-conversion@1``) and
Accumulated Shadow (``scout.shadow@1``, Deep Umbra) give the shadow raster, and
Shade per park measures the minutes of shadow in each park. The comparison maps
each what-if's change cell by cell and the sun each park gains, and charts the
parks' shade on a Vega-Lite node comparing the scenarios.

Run All in the browser runs the whole dataflow:

1. Every node ends done.
2. The three scenarios' Shade per park hold the same parks. Most parks gain sun
   under each what-if, and removing the towers gives more than capping them.
3. The chart draws in the three scenarios' colors, and the four maps draw.

The packages are in every account's store and their libraries are installed
because the stack starts with ``--with-examples`` and this dataflow declares the
packages.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_shadows_anywhere_e2e.py -v --with-examples
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import TYPE_CHECKING

from .utils import (
    OUTPUT_ARTIFACT_JS,
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_scenario_colors_drawn,
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

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "ShadowsAnywhere.json"
VEGA_TYPE = "curio.builtin/vis-vega"
PACKAGES = ("scout.raster-conversion@1", "scout.shadow@1")
SCENARIOS = ("Existing", "Towers removed", "Height cap")
MAPS = ("Shadow change map - Towers removed", "Shadow change map - Height cap",
        "Sun gained per park map - Towers removed", "Sun gained per park map - Height cap")


def _saved_output(page, node_id: str) -> dict:
    artifact = page.evaluate(OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    return load_artifact_as_dict(artifact)


def _mean_minutes(stored: dict) -> dict[str, float]:
    """Each park's mean minutes of shadow, from a GeoDataFrame's features."""
    rows = [feature["properties"] for feature in stored["data"]["features"]]
    return {row["park"]: row["mean_min"] for row in rows}


def test_lower_manhattan_parks_shade_is_compared_across_three_scenarios(
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
    by_title = {node["title"]: node["id"] for node in dataflow["nodes"]}
    colors = [scenario["color"] for scenario in dataflow["scenarios"]]
    assert [scenario["name"] for scenario in dataflow["scenarios"]] == list(SCENARIOS)
    charts = [n for n, node in nodes.items() if node["type"] == VEGA_TYPE]
    maps = [by_title[title] for title in MAPS]

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Shadows Anywhere",
        username="shadows_anywhere_e2e",
        project_name=dataflow["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)

    # 1. Every node ends done.
    run_all_and_wait(page, timeout_ms=900000)
    for node_id, node in nodes.items():
        if node["type"] == "curio.builtin/parameter":
            continue
        status = wait_for_node_settled(page, node_id, node_type=node["type"], timeout_ms=180000)
        assert status == "done", (
            f"{node['title']} ({node['type']}) ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )

    # 2. The same parks in every scenario; most gain sun, and removing gives more than capping.
    means = {}
    for name in SCENARIOS:
        stored = _saved_output(page, by_title[f"Shade per park - {name}"])
        assert stored["dataType"] == "geodataframe", stored["dataType"]
        means[name] = _mean_minutes(stored)
    record_property("mean minutes of shadow per park", json.dumps(means))
    parks = set(means["Existing"])
    assert len(parks) >= 20 and all(set(means[name]) == parks for name in SCENARIOS), {
        name: sorted(means[name]) for name in SCENARIOS}
    gains = {name: [means["Existing"][p] - means[name][p] for p in parks] for name in SCENARIOS[1:]}
    for name, gained in gains.items():
        assert sum(g >= 1 for g in gained) >= 2 * len(parks) / 3, (name, sorted(gained))
    removed, capped = (statistics.median(gains[name]) for name in SCENARIOS[1:])
    assert removed >= capped > 0, (removed, capped)

    # 3. The charts and the maps draw.
    for node_id in charts:
        frame_nodes(page, [node_id])
        assert_vega_canvas_rendered(page, node_id, timeout=30000)
        assert_scenario_colors_drawn(page, node_id, colors)
    for node_id in maps:
        frame_nodes(page, [node_id])
        assert_autark_map_drawn(page, node_id, timeout=60000, attach_as=nodes[node_id]["title"])
