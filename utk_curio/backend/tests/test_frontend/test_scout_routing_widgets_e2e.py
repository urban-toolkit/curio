"""Playwright E2E: Weather Routing's origin, moved in the Widgets tab, moves the route, and stays moved.

The shipped test dataflow ``WeatherRouting.json``, SCOUT's weather routing
example: the node that loads the roads of SCOUT's box from its OpenStreetMap
extract, the Weather Routing node of the model package
``model.scout.weather-gnn@1``, set as SCOUT's example sets it, and the Fastest
route scenario's node that keeps the fastest route. This drives the origin
widget as a user does:

1. Run the Fastest route's node. The roads load and Weather Routing runs: the
   route starts at the road node nearest SCOUT's origin.
2. Move the origin in Weather Routing's Widgets tab, typing its latitude and
   longitude. Weather Routing is stale (its Executed mark goes), and running
   the route's node again runs it again: the route starts at the road node
   nearest the new origin.
3. Save and reopen: the origin reads the new place.

The package is in every account's store and its libraries are installed
because the stack starts with ``--with-examples`` and the dataflow declares the
package.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_routing_widgets_e2e.py -v
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_widget_tags_e2e import _open_tab, _panel
from .utils import (
    REPO_ROOT,
    api_json,
    load_artifact_as_dict,
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_dataflow,
    stub_login_and_enter_workflow,
    wait_for_node_run_to_end,
    wait_for_run_guard_released,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "WeatherRouting.json"
PACKAGE_DIR = "model.scout.weather-gnn@1"
ROUTING_TYPE = "model.scout.weather-gnn/weather-routing"
PYTHON_TYPE = "curio.builtin/computation-analysis"
#: Where the origin moves: State and Jackson in the Loop, inside SCOUT's box,
#: about 2.9 km south-east of SCOUT's origin.
MOVED_ORIGIN = {"lat": 41.8781, "lon": -87.6278}
#: A route starts at the road node nearest its origin, a few metres off.
NEAR_M = 60
#: The first run loads the roads and runs Weather Routing; a rerun only routes.
FIRST_RUN_MS = 300000
RERUN_MS = 240000

#: The artifact a node's last run saved, from what its output pane says.
_OUTPUT_ARTIFACT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const content = node && node.data && node.data.output && node.data.output.content;
    const match = typeof content === "string" ? content.match(/Saved to file: (\\S+)/) : null;
    return match ? match[1] : null;
}"""


def _metres(a: dict, b: dict) -> float:
    """The distance on the Earth between two ``{lat, lon}`` points."""
    phi_a, phi_b = math.radians(a["lat"]), math.radians(b["lat"])
    dphi, dlam = phi_b - phi_a, math.radians(b["lon"] - a["lon"])
    h = math.sin(dphi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(dlam / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def _route_start(page, node_id: str) -> dict:
    """Where the route the node keeps starts: the first point of its line."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, "the route's node shows no saved output"
    stored = load_artifact_as_dict(artifact)
    assert stored["dataType"] == "geodataframe", stored["dataType"]
    (feature,) = stored["data"]["features"]
    lon, lat = feature["geometry"]["coordinates"][0][:2]
    return {"lat": lat, "lon": lon}


def _executed(page, node_id: str):
    return node_locator(page, node_id).locator('span[title="Executed"]')


def test_moving_weather_routings_origin_moves_the_route_and_survives_a_reopen(
    app_frontend: "FrontendPage", current_server: str, page,
):
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    routings = [node for node in dataflow["nodes"] if node["type"] == ROUTING_TYPE]
    assert len(routings) == 1, f"WeatherRouting.json has {len(routings)} Weather Routing nodes, not one"
    (routing_node,) = routings
    routing = routing_node["id"]
    widgets = {w["name"]: w for w in routing_node["metadata"]["widgets"]}
    origin = widgets["origin"].get("value", widgets["origin"]["default"])
    (fastest,) = [scenario for scenario in dataflow["scenarios"] if scenario["id"] == "fastest"]
    (route,) = [node_id for node_id in fastest["nodes"] if "input_0[0]" in nodes[node_id]["content"]]
    assert [e["source"] for e in dataflow["edges"] if e["target"] == route] == [routing]
    assert _metres(origin, MOVED_ORIGIN) > 1000, (origin, MOVED_ORIGIN)

    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Weather Routing Widgets",
        username="scout_routing_widgets_e2e",
        project_name="Routing widgets",
        project_spec={**spec, "dataflow": {**dataflow, "name": "Routing widgets"}},
    )
    require_owner_view(page)
    project_id = session["project"]["id"]
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    assert PACKAGE_DIR in store, f"{PACKAGE_DIR} is not in the account's store {store}: start the stack --with-examples"
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)

    # 1. The route from SCOUT's origin.
    run_node_and_wait(page, route, node_type=PYTHON_TYPE, timeout_ms=FIRST_RUN_MS)
    wait_for_run_guard_released(page, timeout_ms=FIRST_RUN_MS)
    expect(_executed(page, routing)).to_have_count(1, timeout=30000)
    start = _route_start(page, route)
    assert _metres(start, origin) < NEAR_M, f"the route starts at {start}, not at SCOUT's origin {origin}"

    # 2. The origin moves: Weather Routing is stale, and the next run routes
    # from the new origin.
    _open_tab(page, routing, "widgets")
    row = _panel(page, routing).locator('[data-widget-row="origin"]')
    row.get_by_label("Origin latitude").fill(str(MOVED_ORIGIN["lat"]))
    row.get_by_label("Origin longitude").fill(str(MOVED_ORIGIN["lon"]))
    expect(_executed(page, routing)).to_have_count(0, timeout=10000)
    watch_node_run(page, routing)
    watch_node_run(page, route)
    play_node(page, route)
    for node_id, node_type in ((routing, ROUTING_TYPE), (route, PYTHON_TYPE)):
        status = wait_for_node_run_to_end(page, node_id, node_type=node_type, timeout_ms=RERUN_MS)
        assert status == "done", f"{node_type} ran again and ended {status}: {read_node_error_text(node_locator(page, node_id))}"
    wait_for_run_guard_released(page, timeout_ms=RERUN_MS)
    moved = _route_start(page, route)
    assert _metres(moved, MOVED_ORIGIN) < NEAR_M, f"the route starts at {moved}, not at the moved origin {MOVED_ORIGIN}"
    assert _metres(moved, start) > 1000, (start, moved)

    # 3. Saved, then back after a reopen.
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    (saved_routing,) = [node for node in saved["dataflow"]["nodes"] if node["id"] == routing]
    saved_origin = next(w for w in saved_routing["metadata"]["widgets"] if w["name"] == "origin")
    assert saved_origin.get("value") == MOVED_ORIGIN, saved_origin

    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    node_locator(page, routing).wait_for(state="visible", timeout=45000)
    _open_tab(page, routing, "widgets")
    row = _panel(page, routing).locator('[data-widget-row="origin"]')
    latitude = row.get_by_label("Origin latitude")
    latitude.wait_for(state="visible", timeout=15000)
    reopened = {"lat": float(latitude.input_value()), "lon": float(row.get_by_label("Origin longitude").input_value())}
    assert reopened == MOVED_ORIGIN, reopened
