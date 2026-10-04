"""Playwright E2E: a reopened chart or Autark map draws from its saved input (#711).

A grammar node draws from a restored input with no Play (``UniversalNode``,
"Drawing from a restored input"). On a reopen the node's editor briefly holds
``{}`` while Monaco loads, and the restored input arrives in that window, so
the node took it for an author wiring an empty node and never drew it. Here a
Python node feeds the node directly, its output saved; the dataflow runs, is
saved, left and reopened, and the node must draw with nobody pressing Play.

The map test runs the Autark node, which needs WebGPU: without an adapter it
skips, unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails.

The same case, without a browser: ``universalNodeAutoRender.test.tsx``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_restored_input_draws_e2e.py -v
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from .utils import (
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

# A 10 x 10 grid of cells, each with its own value, so the map draws many
# colours (``assert_autark_map_drawn`` wants more than 8).
GRID_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "\n"
    "cells, pop = [], []\n"
    "for i in range(10):\n"
    "    for j in range(10):\n"
    "        x, y = -87.70 + 0.006 * i, 41.86 + 0.006 * j\n"
    "        cells.append(box(x, y, x + 0.005, y + 0.005))\n"
    "        pop.append(i * 10 + j)\n"
    'return gpd.GeoDataFrame({"pop": pop}, geometry=cells, crs="EPSG:4326")\n'
)
MAP_SPEC = json.dumps({"map": {"layerRefs": [{
    "dataRef": "input_0",
    "getFnv": "pop",
    "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateViridis",
}]}}, indent=2)

TABLE_CODE = (
    "import pandas as pd\n\n"
    "return pd.DataFrame({'category': ['a', 'b', 'c'], 'count': [3, 7, 5]})\n"
)
CHART_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": "bar",
    "encoding": {
        "x": {"field": "category", "type": "nominal"},
        "y": {"field": "count", "type": "quantitative"},
    },
}, indent=2)


def _spec(name: str, producer: tuple[str, str], drawer: tuple[str, str, str]) -> dict:
    """A Python node, its output saved, feeding one grammar node directly."""
    producer_id, producer_code = producer
    drawer_id, drawer_type, drawer_spec = drawer
    node = lambda node_id, node_type, x, content, **extra: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": 0, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []}, **extra,
    }
    return {"dataflow": {
        "name": name, "task": "", "timestamp": 1789193389280, "provenance_id": name,
        "nodes": [
            node(producer_id, "curio.builtin/data-loading", 0, producer_code, saveOutputDataset=True),
            node(drawer_id, drawer_type, 645, drawer_spec),
        ],
        "edges": [{
            "id": f"e-{producer_id}-{drawer_id}", "source": producer_id, "target": drawer_id,
            "sourceHandle": "out", "targetHandle": "in",
        }],
    }}


def _open(page, app_frontend, current_server, *, username: str, spec: dict) -> dict:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page, frontend_url=app_frontend.base_url, backend_url=current_server,
        name="Restored Input", username=username, project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    return session


def _run_save_and_reopen(page, app_frontend, session: dict, producer_id: str) -> None:
    """Run the dataflow, save it with the producer's output, leave and reopen it."""
    run_all_and_wait(page, timeout_ms=240000)
    saved = save_dataflow(page)
    outputs = [o.get("node_id") for o in (saved.get("outputs") or [])]
    assert producer_id in outputs, f"the save did not record {producer_id}'s output: {outputs}"
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{session['project']['id']}")
    node_locator(page, producer_id).wait_for(state="visible", timeout=45000)


def test_a_reopened_autark_map_draws_from_its_saved_input(
    app_frontend: "FrontendPage", current_server: str, page,
):
    producer, drawer = "reopen-grid", "reopen-map"
    session = _open(page, app_frontend, current_server, username="restored_input_map",
                    spec=_spec("Restored map", (producer, GRID_CODE),
                               (drawer, "curio.builtin/autk-grammar", MAP_SPEC)))
    has_adapter = bool(page.evaluate("async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"))
    if not has_adapter:
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("running an Autark node needs a WebGPU adapter; this browser has none")

    _run_save_and_reopen(page, app_frontend, session, producer)

    # Nobody presses Play: the restored input is enough.
    frame_nodes(page, [drawer])
    assert_autark_map_drawn(page, drawer, timeout=90000, attach_as="after the reopen")
    status = wait_for_node_settled(page, drawer, node_type="autk-grammar", timeout_ms=60000)
    detail = read_node_error_text(node_locator(page, drawer)) if status == "error" else ""
    assert status == "done", f"the reopened map ended {status}: {detail}"


def test_a_reopened_chart_draws_from_its_saved_input(
    app_frontend: "FrontendPage", current_server: str, page,
):
    producer, drawer = "reopen-table", "reopen-chart"
    session = _open(page, app_frontend, current_server, username="restored_input_chart",
                    spec=_spec("Restored chart", (producer, TABLE_CODE),
                               (drawer, "curio.builtin/vis-vega", CHART_SPEC)))

    _run_save_and_reopen(page, app_frontend, session, producer)

    frame_nodes(page, [drawer])
    assert_vega_canvas_rendered(page, drawer, timeout=90000)
