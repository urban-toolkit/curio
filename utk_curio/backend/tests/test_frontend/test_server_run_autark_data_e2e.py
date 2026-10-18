"""A run on the server runs an Autark node that only loads data: example 06's.

Playing example 06's loader saves the dataflow and starts a run the server
executes. Its data section is compiled with the browser's own compiler and
loaded in the sandbox, as the node's own run in the browser loads it, so the
page sends no ``/processJavaScriptCode`` for it. The run records the loader's
layer list, the node shows Done with the tables it loaded, and the Data Pool
below it, which reads the run's output, shows the five layers.

Nothing in this run draws: the loader and the pool need no WebGPU.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import expect

from .utils import (
    REPO_ROOT,
    _wait_for_reactflow_ready,
    api_json,
    node_locator,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

EXAMPLE = Path(REPO_ROOT) / "docs" / "examples" / "06-back-bay-road-sunlight.json"
DATA = "whatif-data"
POOL = "whatif-pool"
LAYERS = ["table_osm_surface", "table_osm_parks", "table_osm_water", "table_osm_roads", "table_osm_buildings"]


def _latest_run(backend: str, token: str, project_id: str) -> dict:
    runs = api_json(f"{backend}/api/projects/{project_id}/runs?limit=1", token)["runs"]
    assert runs, "playing the loader started no run on the server"
    return api_json(f"{backend}/api/runs/{runs[0]['id']}", token)


def _wait_for_run_to_end(backend: str, token: str, project_id: str, *, timeout_s: float = 180) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        run = _latest_run(backend, token, project_id)
        if run["status"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline, f"the run did not end within {timeout_s} s: {run['status']}"
        time.sleep(0.5)


def test_a_server_run_loads_example_06s_layers_and_its_pool_shows_them(
    app_frontend, current_server, page,
):
    require_project_page()
    require_user_auth()
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Example 06 loader",
        username="autark_server_load_e2e",
        project_name="Example 06 loader",
        project_spec=spec,
    )
    require_owner_view(page)
    token, project_id = session["token"], session["project"]["id"]
    _wait_for_reactflow_ready(page)
    for node_id in (DATA, POOL):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    # Every Autark data load the page itself sends while the loader runs, by
    # node id. The loader is the only node of this run.
    sent: list[str] = []

    def _request(request) -> None:
        if request.method != "POST" or not request.url.endswith("/processJavaScriptCode"):
            return
        try:
            sent.append(str(json.loads(request.post_data or "{}").get("nodeId")))
        except ValueError:
            sent.append("?")

    page.on("request", _request)
    try:
        play_node(page, DATA)
        wait_for_node_done(page, DATA, node_type="autk-grammar", timeout_ms=180000)
        run = _wait_for_run_to_end(current_server, token, project_id)
    finally:
        page.remove_listener("request", _request)

    # The server ran it, and kept its layer list as the node's output.
    steps = {s["nodeId"]: s for s in run["steps"]}
    loader = steps[DATA]
    assert (loader["role"], loader["status"], loader["outputType"]) == ("run", "ok", "list"), loader
    assert loader["outputPath"], loader
    assert run["status"] == "succeeded", run["status"]
    assert sent == [], f"the page sent Autark data loads itself, for {sent}"

    # Done, with the tables it loaded, as its own run in the browser says it.
    node = node_locator(page, DATA)
    node.locator('.nav-link[data-rr-ui-event-key="output"]').first.click()
    expect(node.locator('[data-curio-autk-summary="data"]')).to_have_text(
        "Loaded 5 tables: " + ", ".join(LAYERS), timeout=15000,
    )
    expect(node.locator("[data-curio-node-empty]")).to_have_count(0)

    # The pool below it reads the run's output: one tab per layer.
    expect(node_locator(page, POOL).locator('[data-testid="data-pool-tabs"] .nav-link')).to_have_text(
        LAYERS, timeout=60000,
    )

    # Recorded in the dataflow as a save records it: the scenarios' fixed context.
    saved = api_json(f"{current_server}/api/projects/{project_id}", token)
    assert DATA in {o["node_id"] for o in saved["outputs"]}, saved["outputs"]
